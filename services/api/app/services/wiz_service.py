"""Wiz CLI integration: authenticate and run IaC (cloud configuration) scans,
then map the resulting issues onto terraform resources.

Only IaC configuration issues are surfaced (not docker image vulnerabilities).
Each issue carries a title, severity and a link back to the Wiz report.
"""

import asyncio
import json
import os
import shutil
import tempfile

# Highest-to-lowest, used to pick a resource's dominant severity.
SEVERITY_RANK = {
    "CRITICAL": 5,
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "INFORMATIONAL": 1,
    "INFO": 1,
}


def wiz_available() -> bool:
    """True if the wizcli binary is on PATH."""
    return shutil.which("wizcli") is not None


async def _run(args: list[str], cwd: str | None = None, timeout: int = 300):
    proc = await asyncio.create_subprocess_exec(
        "wizcli",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("wizcli timed out")
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def authenticate(client_id: str, client_secret: str) -> None:
    if not client_id or not client_secret:
        raise RuntimeError("Wiz client_id/client_secret not configured")
    rc, out, err = await _run(
        ["auth", "--id", client_id, "--secret", client_secret], timeout=60
    )
    if rc != 0:
        raise RuntimeError((err or out or "wizcli auth failed").strip()[:500])


async def _iac_scan(project_dir: str) -> dict:
    """Run `wizcli iac scan` and return the parsed JSON result."""
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        # wizcli exits non-zero when issues are found (policy fail); that is not
        # an error for us — we parse the JSON output regardless of exit code.
        _rc, out, err = await _run(
            [
                "iac",
                "scan",
                "--path",
                project_dir,
                "--name",
                "inframate",
                "--format",
                "json",
                "--output",
                f"{out_path},json",
            ],
            cwd=project_dir,
        )
        data = _load_json(out_path) or _load_json_str(out)
        if data is None:
            raise RuntimeError(
                (err or out or "wizcli produced no JSON output").strip()[:500]
            )
        return data
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _load_json(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _load_json_str(s: str):
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_findings(data: dict) -> tuple[str, list[dict]]:
    """Flatten wizcli IaC scan JSON into a list of issue dicts.

    Tolerant of casing differences across wizcli versions.
    Returns (report_url, findings).
    """
    report_url = _first(data, "reportUrl", "ReportUrl", "reportUrlV2", default="") or ""
    result = _first(data, "result", "Result", default={}) or {}
    rule_matches = _first(result, "ruleMatches", "RuleMatches", default=[]) or []

    findings: list[dict] = []
    for rm in rule_matches:
        rule = _first(rm, "rule", "Rule", default={}) or {}
        title = (
            _first(rule, "name", "Name") or _first(rm, "name", "Name") or "Wiz issue"
        )
        rule_id = _first(rule, "id", "ID", "shortId") or ""
        severity = (
            _first(rm, "severity", "Severity")
            or _first(rule, "severity", "Severity")
            or "INFORMATIONAL"
        ).upper()
        url = _first(rule, "url", "URL") or report_url

        matches = _first(rm, "matches", "Matches", default=[]) or []
        if not matches:
            findings.append(
                {
                    "title": title,
                    "rule_id": rule_id,
                    "severity": severity,
                    "file": "",
                    "line": None,
                    "resource": "",
                    "url": url,
                }
            )
            continue
        for m in matches:
            findings.append(
                {
                    "title": title,
                    "rule_id": rule_id,
                    "severity": severity,
                    "file": _first(m, "fileName", "FileName", "file") or "",
                    "line": _first(m, "lineNumber", "LineNumber", "line"),
                    "resource": _first(
                        m, "resourceName", "ResourceName", "resource", "name"
                    )
                    or "",
                    "url": url,
                }
            )
    return report_url, findings


def _candidate_keys(row: dict) -> set[str]:
    """Identifiers a finding's resourceName might use for this row."""
    keys = set()
    addr = row.get("id") or ""
    rtype = row.get("resource_type") or ""
    rname = row.get("resource_name") or ""
    if addr:
        keys.add(addr)
    if rtype and rname:
        keys.add(f"{rtype}.{rname}")
    if rname:
        keys.add(rname)
    return {k for k in keys if k}


def map_findings_to_resources(
    findings: list[dict], rows: list[dict]
) -> dict[str, list[dict]]:
    """Group findings by terraform resource address (row 'id').

    Matches on address / type.name / name, with a tf_file fallback. Findings
    that match nothing are collected under the '__unmapped__' key.
    """
    by_key: dict[str, list[str]] = {}
    for r in rows:
        addr = r.get("id")
        if not addr:
            continue
        for k in _candidate_keys(r):
            by_key.setdefault(k, []).append(addr)

    file_index: dict[str, list[dict]] = {}
    for r in rows:
        f = r.get("tf_file")
        if f:
            file_index.setdefault(os.path.basename(f), []).append(r)

    mapped: dict[str, list[dict]] = {}
    for fnd in findings:
        res = (fnd.get("resource") or "").strip()
        target_addrs: list[str] = []
        if res and res in by_key:
            target_addrs = by_key[res]
        elif res:
            # last segment match (e.g. "module.x.aws_s3_bucket.data" -> "aws_s3_bucket.data")
            tail = ".".join(res.split(".")[-2:])
            if tail in by_key:
                target_addrs = by_key[tail]
        if not target_addrs and fnd.get("file"):
            base = os.path.basename(fnd["file"])
            for r in file_index.get(base, []):
                rname = r.get("resource_name") or ""
                if rname and rname in res:
                    target_addrs.append(r["id"])
        if not target_addrs:
            mapped.setdefault("__unmapped__", []).append(fnd)
            continue
        for addr in set(target_addrs):
            mapped.setdefault(addr, []).append(fnd)

    for addr in mapped:
        mapped[addr].sort(
            key=lambda f: SEVERITY_RANK.get((f.get("severity") or "").upper(), 0),
            reverse=True,
        )
    return mapped


async def run_scan(
    project_dir: str, client_id: str, client_secret: str, rows: list[dict]
) -> dict:
    """Authenticate, scan, and return findings mapped to resources."""
    if not wiz_available():
        return {
            "installed": False,
            "error": "wizcli is not installed. See https://www.wiz.io/lp/wiz-cli",
            "findings": {},
        }
    await authenticate(client_id, client_secret)
    data = await _iac_scan(project_dir)
    report_url, findings = parse_findings(data)
    mapped = map_findings_to_resources(findings, rows)

    counts: dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "INFORMATIONAL")
        counts[sev] = counts.get(sev, 0) + 1

    return {
        "installed": True,
        "error": None,
        "report_url": report_url,
        "findings": mapped,
        "total": len(findings),
        "counts": counts,
    }

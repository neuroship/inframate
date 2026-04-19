"""Detect cloud providers from .tf files and verify credentials."""

import glob
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import hcl2

from app import config


PROVIDER_CHECKS = {
    "aws": {
        "cmd": ["aws", "sts", "get-caller-identity"],
        "fix": "Run: aws configure  (or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)",
    },
    "google": {
        "cmd": ["gcloud", "auth", "print-access-token"],
        "fix": "Run: gcloud auth application-default login",
    },
    "azurerm": {
        "cmd": ["az", "account", "show"],
        "fix": "Run: az login",
    },
}

# Map backend types to the provider they need
BACKEND_PROVIDERS = {
    "s3": "aws",
    "gcs": "google",
    "azurerm": "azurerm",
}


def detect_providers(project_dir: str) -> set[str]:
    """Parse .tf files and return set of provider names (aws, google, azurerm, etc.)."""
    providers = set()

    for fname in os.listdir(project_dir):
        if not fname.endswith(".tf"):
            continue
        fpath = os.path.join(project_dir, fname)
        try:
            with open(fpath) as f:
                parsed = hcl2.load(f)
        except Exception:
            continue

        # Check provider blocks: [{"aws": {...}}, {"google": {...}}]
        for pblock in parsed.get("provider", []):
            if isinstance(pblock, dict):
                providers.update(pblock.keys())

        # Check terraform backend: [{"terraform": [{"backend": [{"s3": {...}}]}]}]
        for tblock in parsed.get("terraform", []):
            if isinstance(tblock, dict):
                for bblock in tblock.get("backend", []):
                    if isinstance(bblock, dict):
                        for backend_type in bblock.keys():
                            mapped = BACKEND_PROVIDERS.get(backend_type)
                            if mapped:
                                providers.add(mapped)

        # Check resource types: [{"aws_instance": {"web": {...}}}]
        for rblock in parsed.get("resource", []):
            if isinstance(rblock, dict):
                for rtype in rblock.keys():
                    if rtype.startswith("aws_"):
                        providers.add("aws")
                    elif rtype.startswith("google_"):
                        providers.add("google")
                    elif rtype.startswith("azurerm_"):
                        providers.add("azurerm")

    return providers


def _check_terraform_binary() -> str | None:
    """Check terraform binary exists and is runnable. Returns error string or None."""
    tf_bin = config.TERRAFORM_BINARY
    if not shutil.which(tf_bin):
        return f"terraform binary not found: '{tf_bin}'. Install terraform or set terraform_binary in config."
    try:
        result = subprocess.run(
            [tf_bin, "version"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"terraform binary failed: {result.stderr.decode().strip()}"
    except subprocess.TimeoutExpired:
        return "terraform version check timed out."
    return None


def _check_terraform_init(project_dir: str) -> str | None:
    """Check terraform has been initialized. Returns error string or None."""
    tf_dir = os.path.join(project_dir, ".terraform")
    if not os.path.isdir(tf_dir):
        return f"terraform not initialized. Run: cd {project_dir} && terraform init"
    return None


def check_backend(project_dir: str) -> tuple[bool, list[str]]:
    """Check terraform binary, init status, and provider credentials. Returns (ok, errors)."""
    errors = []

    # 1. Terraform binary
    tf_err = _check_terraform_binary()
    if tf_err:
        errors.append(tf_err)
        return (False, errors)

    # 2. Terraform init
    init_err = _check_terraform_init(project_dir)
    if init_err:
        errors.append(init_err)
        return (False, errors)

    # 3. Provider credentials
    providers = detect_providers(project_dir)

    for provider in sorted(providers):
        check = PROVIDER_CHECKS.get(provider)
        if not check:
            continue

        try:
            result = subprocess.run(
                check["cmd"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"{provider}: credentials not valid. {check['fix']}")
        except FileNotFoundError:
            errors.append(f"{provider}: CLI not found ({check['cmd'][0]}). Install it or configure credentials via env vars.")
        except subprocess.TimeoutExpired:
            errors.append(f"{provider}: credential check timed out.")

    return (len(errors) == 0, errors)


def _parse_expiry(s: str) -> datetime | None:
    """Parse ISO datetime string to timezone-aware datetime."""
    if not s:
        return None
    try:
        # Handle both "2026-04-09T16:46:02Z" and "2026-04-09T16:46:02+00:00"
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def get_credential_expiry() -> dict:
    """Detect AWS credential expiry from SSO and CLI cache files.

    Returns {"expires_at": ISO string or None, "type": "sso"|"session"|"static"}.
    """
    now = datetime.now(timezone.utc)
    best_expiry = None
    cred_type = "static"

    # 1. SSO cache — files with accessToken are actual session tokens
    sso_dir = os.path.expanduser("~/.aws/sso/cache")
    if os.path.isdir(sso_dir):
        for path in glob.glob(os.path.join(sso_dir, "*.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
                if "accessToken" not in data:
                    continue
                exp = _parse_expiry(data.get("expiresAt", ""))
                if exp and exp > now:
                    if best_expiry is None or exp < best_expiry:
                        best_expiry = exp
                        cred_type = "sso"
            except Exception:
                continue

    # 2. CLI cache — assumed role / SSO role credentials
    cli_dir = os.path.expanduser("~/.aws/cli/cache")
    if os.path.isdir(cli_dir):
        for path in glob.glob(os.path.join(cli_dir, "*.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
                creds = data.get("Credentials", {})
                exp = _parse_expiry(creds.get("Expiration", ""))
                if exp and exp > now:
                    if best_expiry is None or exp < best_expiry:
                        best_expiry = exp
                        cred_type = data.get("ProviderType", "session") or "session"
            except Exception:
                continue

    return {
        "expires_at": best_expiry.isoformat() if best_expiry else None,
        "type": cred_type,
    }


def format_time_remaining(expires_at_iso: str | None) -> str:
    """Format expiry as human-readable remaining time string."""
    if not expires_at_iso:
        return ""
    exp = _parse_expiry(expires_at_iso)
    if not exp:
        return ""
    delta = exp - datetime.now(timezone.utc)
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "expired"
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

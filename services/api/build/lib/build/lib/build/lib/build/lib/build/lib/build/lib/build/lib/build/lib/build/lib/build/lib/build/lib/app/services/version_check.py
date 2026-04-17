"""Check PyPI for newer version of inframate."""

import json
import os
import time
import threading
import urllib.request
from importlib.metadata import version as get_version
from pathlib import Path


CACHE_DIR = Path.home() / ".inframate"
CACHE_FILE = CACHE_DIR / "version-check.json"
CACHE_TTL = 86400  # 24 hours
PYPI_URL = "https://pypi.org/pypi/inframate/json"


def _get_current_version() -> str:
    try:
        return get_version("inframate")
    except Exception:
        return "0.0.0"


def _fetch_latest() -> str | None:
    try:
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("info", {}).get("version")
    except Exception:
        return None


def _read_cache() -> dict | None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _write_cache(latest: str):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"latest": latest, "timestamp": time.time()}))
    except Exception:
        pass


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0, 0, 0)


_result: dict | None = None


def _check():
    global _result
    current = _get_current_version()

    cached = _read_cache()
    if cached:
        latest = cached["latest"]
    else:
        latest = _fetch_latest()
        if latest:
            _write_cache(latest)

    if latest and _version_tuple(latest) > _version_tuple(current):
        _result = {"current": current, "latest": latest}


def start_check():
    """Start version check in background thread."""
    t = threading.Thread(target=_check, daemon=True)
    t.start()
    return t


def print_update_notice(thread: threading.Thread):
    """Print update notice if available. Call after command dispatch."""
    thread.join(timeout=2)
    if _result:
        print(f"\n  Update available: {_result['current']} → {_result['latest']}")
        print("  Run: uv tool upgrade inframate\n")

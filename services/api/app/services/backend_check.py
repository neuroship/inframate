"""Detect cloud providers from .tf files and verify credentials."""

import asyncio
import os
import subprocess

import hcl2


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


def check_backend(project_dir: str) -> tuple[bool, list[str]]:
    """Detect providers and verify credentials. Returns (ok, errors)."""
    providers = detect_providers(project_dir)
    errors = []

    for provider in sorted(providers):
        check = PROVIDER_CHECKS.get(provider)
        if not check:
            continue

        try:
            result = subprocess.run(
                check["cmd"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                errors.append(f"{provider}: credentials not valid. {check['fix']}")
        except FileNotFoundError:
            errors.append(f"{provider}: CLI not found ({check['cmd'][0]}). Install it or configure credentials via env vars.")
        except subprocess.TimeoutExpired:
            errors.append(f"{provider}: credential check timed out.")

    return (len(errors) == 0, errors)

import os

import yaml

# Set by load_config()
PROJECT_DIR: str = ""
TERRAFORM_BINARY: str = "terraform"

_config: dict = {}


def load_config(project_dir: str, overrides: dict | None = None):
    """Load config from .inframate.yml + env vars + overrides."""
    global PROJECT_DIR, TERRAFORM_BINARY, _config

    PROJECT_DIR = project_dir

    # Load YAML if present
    config_file = os.path.join(project_dir, ".inframate.yml")
    if os.path.isfile(config_file):
        with open(config_file) as f:
            _config = yaml.safe_load(f) or {}
    else:
        _config = {}

    # Apply overrides (from CLI args)
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                _config[k] = v

    TERRAFORM_BINARY = (
        _config.get("terraform_binary")
        or os.environ.get("TERRAFORM_BINARY")
        or "terraform"
    )


def get_ai_config() -> dict:
    ai = _config.get("ai", {})
    return {
        "endpoint": ai.get("endpoint") or os.environ.get("OPENAI_API_BASE", ""),
        "api_token": ai.get("api_token") or os.environ.get("OPENAI_API_KEY", ""),
        "model": ai.get("model") or os.environ.get("OPENAI_MODEL", "gpt-4o"),
    }


def get_port() -> int:
    return int(_config.get("port", 8000))

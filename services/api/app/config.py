import os
from pathlib import Path

import yaml

# Set by load_config()
PROJECT_DIR: str = ""
TERRAFORM_BINARY: str = "terraform"

CONFIG_DIR = Path.home() / ".inframate"

# Known provider defaults — endpoint only, user supplies token + model
PROVIDERS = {
    "openai": {"endpoint": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    "anthropic": {"endpoint": "https://api.anthropic.com/v1", "default_model": "claude-sonnet-4-20250514"},
    "ollama": {"endpoint": "http://localhost:11434/v1", "default_model": "llama3"},
    "groq": {"endpoint": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile"},
    "deepseek": {"endpoint": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
}

_config: dict = {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(project_dir: str, overrides: dict | None = None):
    """Load config: global ~/.inframate/config.yml + project .inframate/config.yml + env vars + overrides."""
    global PROJECT_DIR, TERRAFORM_BINARY, _config

    PROJECT_DIR = project_dir

    # 1. Global config
    global_config = {}
    global_file = CONFIG_DIR / "config.yml"
    if global_file.is_file():
        with open(global_file) as f:
            global_config = yaml.safe_load(f) or {}

    # 2. Project config (overrides global)
    project_config = {}
    project_file = os.path.join(project_dir, ".inframate", "config.yml")
    if os.path.isfile(project_file):
        with open(project_file) as f:
            project_config = yaml.safe_load(f) or {}

    _config = _deep_merge(global_config, project_config)

    # 3. CLI overrides
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
    ai = _config.get("ai") or {}

    # Resolve provider preset
    provider_name = ai.get("provider", "")
    preset = PROVIDERS.get(provider_name, {})

    endpoint = ai.get("endpoint") or os.environ.get("OPENAI_API_BASE") or preset.get("endpoint", "")
    api_token = ai.get("api_token") or os.environ.get("OPENAI_API_KEY", "")
    model = ai.get("model") or os.environ.get("OPENAI_MODEL") or preset.get("default_model", "gpt-4o")

    return {
        "endpoint": endpoint,
        "api_token": api_token,
        "model": model,
    }


def get_terraform_config() -> dict:
    tf = _config.get("terraform") or {}
    return {
        "var_file": tf.get("var_file"),
        "backend_config": tf.get("backend_config"),
        "data_dir": tf.get("data_dir"),
    }


def get_port() -> int:
    return int(_config.get("port", 8000))


def init_config_dir():
    """Create ~/.inframate/ with a default config.yml if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / "config.yml"
    if not config_file.exists():
        config_file.write_text(
            "# inframate configuration\n"
            "# See: https://github.com/nicholasgasior/inframate\n"
            "\n"
            "ai:\n"
            "  # provider: openai | anthropic | ollama | groq | deepseek\n"
            "  # provider: openai\n"
            "  # api_token: sk-...\n"
            "  # model: gpt-4o\n"
            "  #\n"
            "  # Or set a custom endpoint:\n"
            "  # endpoint: http://localhost:11434/v1\n"
            "  # api_token: ollama\n"
            "  # model: llama3\n"
        )

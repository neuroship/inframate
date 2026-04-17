import asyncio
import configparser
import os


AWS_CONFIG_PATH = os.path.expanduser("~/.aws/config")


def save_sso_profile(profile_name: str, config: dict) -> None:
    """Write an AWS SSO profile to ~/.aws/config."""
    os.makedirs(os.path.dirname(AWS_CONFIG_PATH), exist_ok=True)

    parser = configparser.ConfigParser()
    parser.read(AWS_CONFIG_PATH)

    section = f"profile {profile_name}"
    if not parser.has_section(section):
        parser.add_section(section)

    parser.set(section, "sso_start_url", config["sso_start_url"])
    parser.set(section, "sso_region", config["sso_region"])
    parser.set(section, "sso_account_id", config["sso_account_id"])
    parser.set(section, "sso_role_name", config["sso_role_name"])
    parser.set(section, "region", config["region"])

    with open(AWS_CONFIG_PATH, "w") as f:
        parser.write(f)


async def sso_login(profile_name: str):
    """Run aws sso login --no-browser and stream the output.

    Yields lines including the SSO authorization URL the user needs to visit.
    """
    proc = await asyncio.create_subprocess_exec(
        "aws", "sso", "login", "--profile", profile_name, "--no-browser",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async for line in proc.stdout:
        yield line.decode()

    await proc.wait()
    if proc.returncode != 0:
        yield f"\n[Exit code: {proc.returncode}]\n"


async def check_sso_session(profile_name: str) -> bool:
    """Check if the current SSO session is valid."""
    proc = await asyncio.create_subprocess_exec(
        "aws", "sts", "get-caller-identity", "--profile", profile_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await proc.communicate()
    return proc.returncode == 0


def get_sso_session_expiry(start_url: str) -> str:
    """Read SSO token expiry from the AWS SSO cache files."""
    import glob
    import hashlib
    import json

    cache_dir = os.path.expanduser("~/.aws/sso/cache")
    if not os.path.isdir(cache_dir):
        return ""

    # AWS CLI caches SSO tokens by SHA1 hash of the start URL
    expected_hash = hashlib.sha1(start_url.encode("utf-8")).hexdigest()
    target = os.path.join(cache_dir, f"{expected_hash}.json")
    if os.path.isfile(target):
        try:
            with open(target) as f:
                data = json.load(f)
            return data.get("expiresAt", "")
        except Exception:
            pass

    # Fallback: scan all cache files for matching startUrl
    for path in glob.glob(os.path.join(cache_dir, "*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("startUrl") == start_url and data.get("expiresAt"):
                return data["expiresAt"]
        except Exception:
            continue
    return ""


async def test_credentials(extra_env: dict[str, str]) -> dict:
    """Run sts get-caller-identity with given env vars. Returns identity or error."""
    import json as _json

    env = {**os.environ, **extra_env}
    # Remove AWS_PROFILE so explicit keys take precedence
    env.pop("AWS_PROFILE", None)

    proc = await asyncio.create_subprocess_exec(
        "aws", "sts", "get-caller-identity", "--output", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return {"ok": False, "error": stderr.decode().strip() or "Authentication failed"}

    try:
        identity = _json.loads(stdout.decode())
        return {
            "ok": True,
            "account": identity.get("Account", ""),
            "arn": identity.get("Arn", ""),
            "user_id": identity.get("UserId", ""),
        }
    except Exception:
        return {"ok": False, "error": "Failed to parse response"}


def list_profiles() -> list[str]:
    """List existing AWS profiles from ~/.aws/config."""
    parser = configparser.ConfigParser()
    parser.read(AWS_CONFIG_PATH)
    profiles = []
    for section in parser.sections():
        if section.startswith("profile "):
            profiles.append(section.removeprefix("profile "))
        elif section == "default":
            profiles.append("default")
    return profiles


def detect_env() -> dict:
    """Detect existing AWS configuration from environment variables."""
    return {
        "access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", ""),
        "secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "session_token": os.environ.get("AWS_SESSION_TOKEN", ""),
        "region": os.environ.get("AWS_DEFAULT_REGION", "")
        or os.environ.get("AWS_REGION", ""),
        "profile": os.environ.get("AWS_PROFILE", ""),
    }


def env_for_access_keys(config: dict) -> dict[str, str]:
    """Build env vars for access key auth."""
    env = {}
    if config.get("access_key_id"):
        env["AWS_ACCESS_KEY_ID"] = config["access_key_id"]
    if config.get("secret_access_key"):
        env["AWS_SECRET_ACCESS_KEY"] = config["secret_access_key"]
    if config.get("session_token"):
        env["AWS_SESSION_TOKEN"] = config["session_token"]
    if config.get("region"):
        env["AWS_DEFAULT_REGION"] = config["region"]
    return env


async def assume_role(
    role_arn: str,
    source_credentials: dict | None = None,
    mfa_serial: str | None = None,
    mfa_token: str | None = None,
    region: str = "us-east-1",
) -> dict:
    """Run aws sts assume-role using explicit base credentials."""
    cmd = [
        "aws", "sts", "assume-role",
        "--role-arn", role_arn,
        "--role-session-name", "inframate-session",
        "--output", "json",
    ]
    if mfa_serial and mfa_token:
        cmd.extend(["--serial-number", mfa_serial, "--token-code", mfa_token])

    env = {**os.environ, "AWS_DEFAULT_REGION": region}
    if source_credentials:
        if source_credentials.get("access_key_id"):
            env["AWS_ACCESS_KEY_ID"] = source_credentials["access_key_id"]
        if source_credentials.get("secret_access_key"):
            env["AWS_SECRET_ACCESS_KEY"] = source_credentials["secret_access_key"]
        env.pop("AWS_PROFILE", None)
        env.pop("AWS_SESSION_TOKEN", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return {"error": stderr.decode().strip() or stdout.decode().strip()}

    import json

    data = json.loads(stdout.decode())
    creds = data.get("Credentials", {})
    expiration = creds.get("Expiration", "")
    # Expiration is ISO string like "2026-04-16T12:00:00Z"
    return {
        "access_key_id": creds.get("AccessKeyId", ""),
        "secret_access_key": creds.get("SecretAccessKey", ""),
        "session_token": creds.get("SessionToken", ""),
        "expires_at": expiration,
    }

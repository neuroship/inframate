import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator

from app import config

logger = logging.getLogger(__name__)

_VAR_FILE_COMMANDS = {"plan", "apply", "destroy", "import"}


def _build_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return env


def _apply_config_defaults(cmd: list[str], args: list[str], var_file: str | None = None):
    """Apply var_file and backend_config from config to a terraform command."""
    tf_config = config.get_terraform_config()
    if not args:
        return

    command = args[0]

    # var_file: explicit param > config, only for relevant commands
    effective_var_file = var_file or tf_config.get("var_file")
    if effective_var_file and command in _VAR_FILE_COMMANDS and "-var-file" not in args:
        cmd.extend(["-var-file", effective_var_file])
        logger.debug("applied var_file=%s for command=%s", effective_var_file, command)
    elif command in _VAR_FILE_COMMANDS:
        logger.debug("no var_file configured for command=%s", command)

    # backend_config: only for init
    backend_config = tf_config.get("backend_config")
    if backend_config and command == "init" and not any(a.startswith("-backend-config") for a in args):
        cmd.append(f"-backend-config={backend_config}")
        logger.debug("applied backend_config=%s", backend_config)


async def stream_terraform(
    workspace_path: str,
    args: list[str],
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    cmd = [config.TERRAFORM_BINARY] + args
    _apply_config_defaults(cmd, args, var_file)

    # Auto-approve for apply/destroy
    if args and args[0] in ("apply", "destroy") and "-auto-approve" not in args:
        cmd.append("-auto-approve")

    cmd_with_no_color = cmd + ["-no-color"]

    process = await asyncio.create_subprocess_exec(
        *cmd_with_no_color,
        cwd=workspace_path,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_build_env(extra_env),
    )

    async for line in process.stdout:
        yield line.decode()

    await process.wait()
    if process.returncode != 0:
        yield f"\n[Exit code: {process.returncode}]\n"


async def run_terraform(
    workspace_path: str,
    args: list[str],
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, int]:
    cmd = [config.TERRAFORM_BINARY] + args
    _apply_config_defaults(cmd, args, var_file)
    logger.debug("run_terraform: %s (cwd=%s)", " ".join(cmd), workspace_path)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workspace_path,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_build_env(extra_env),
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()
    logger.debug("run_terraform: exit=%s output_len=%d", process.returncode, len(output))
    if process.returncode != 0:
        logger.warning("run_terraform failed: cmd=%s exit=%s output=%s", " ".join(cmd), process.returncode, output[:500])
    return output, process.returncode


async def get_plan_json(
    workspace_path: str,
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    inframate_dir = os.path.join(workspace_path, ".inframate")
    os.makedirs(inframate_dir, exist_ok=True)
    plan_file = os.path.join(inframate_dir, "plan.tfplan")
    args = ["plan", "-input=false", "-lock-timeout=30s", "-out", plan_file, "-no-color"]

    output, code = await run_terraform(workspace_path, args, var_file=var_file, extra_env=extra_env)
    if code != 0:
        # Trim to last 500 chars to keep the most useful part of the error
        err_msg = output.strip()[-500:] if output else "unknown error"
        return {"error": f"Plan failed: {err_msg}", "raw_output": output}

    output, _ = await run_terraform(
        workspace_path, ["show", "-json", plan_file], extra_env=extra_env
    )
    try:
        return json.loads(output)
    finally:
        if os.path.exists(plan_file):
            os.remove(plan_file)


async def stream_plan_with_output(
    workspace_path: str,
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
    on_line=None,
) -> dict:
    """Run terraform plan, call on_line(text) for each output line, return plan JSON."""
    inframate_dir = os.path.join(workspace_path, ".inframate")
    os.makedirs(inframate_dir, exist_ok=True)
    plan_file = os.path.join(inframate_dir, "plan.tfplan")
    args = ["plan", "-input=false", "-lock-timeout=30s", "-out", plan_file, "-no-color"]
    cmd = [config.TERRAFORM_BINARY] + args
    _apply_config_defaults(cmd, args, var_file)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workspace_path,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_build_env(extra_env),
    )

    plan_output_lines = []
    async for line in process.stdout:
        text = line.decode().rstrip()
        if text:
            plan_output_lines.append(text)
            if on_line:
                await on_line(text)

    await process.wait()
    if process.returncode != 0:
        raw = "\n".join(plan_output_lines)
        err_msg = raw.strip()[-500:] if raw else "unknown error"
        return {"error": f"Plan failed: {err_msg}", "raw_output": raw}

    output, _ = await run_terraform(
        workspace_path, ["show", "-json", plan_file], extra_env=extra_env
    )
    try:
        return json.loads(output)
    finally:
        if os.path.exists(plan_file):
            os.remove(plan_file)


async def get_state(
    workspace_path: str, extra_env: dict[str, str] | None = None
) -> dict | None:
    output, code = await run_terraform(
        workspace_path, ["show", "-json"], extra_env=extra_env
    )
    if code != 0:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


async def get_graph_dot(
    workspace_path: str, extra_env: dict[str, str] | None = None
) -> str:
    output, _ = await run_terraform(workspace_path, ["graph"], extra_env=extra_env)
    return output


async def get_providers(
    workspace_path: str, extra_env: dict[str, str] | None = None
) -> str:
    output, _ = await run_terraform(workspace_path, ["providers"], extra_env=extra_env)
    return output

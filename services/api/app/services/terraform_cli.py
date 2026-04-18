import asyncio
import json
import os
from collections.abc import AsyncGenerator

from app import config


def _build_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return env


async def stream_terraform(
    workspace_path: str,
    args: list[str],
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    cmd = [config.TERRAFORM_BINARY] + args
    if var_file:
        cmd.extend(["-var-file", var_file])

    # Auto-approve for apply/destroy
    if args and args[0] in ("apply", "destroy") and "-auto-approve" not in args:
        cmd.append("-auto-approve")

    cmd_with_no_color = cmd + ["-no-color"]

    process = await asyncio.create_subprocess_exec(
        *cmd_with_no_color,
        cwd=workspace_path,
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
    if var_file:
        cmd.extend(["-var-file", var_file])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_build_env(extra_env),
    )
    stdout, _ = await process.communicate()
    return stdout.decode(), process.returncode


async def get_plan_json(
    workspace_path: str,
    var_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    plan_file = os.path.join(workspace_path, ".inframate-plan.tfplan")
    args = ["plan", "-out", plan_file, "-no-color"]
    if var_file:
        args.extend(["-var-file", var_file])

    output, code = await run_terraform(workspace_path, args, extra_env=extra_env)
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
    plan_file = os.path.join(workspace_path, ".inframate-plan.tfplan")
    cmd = [config.TERRAFORM_BINARY, "plan", "-out", plan_file, "-no-color"]
    if var_file:
        cmd.extend(["-var-file", var_file])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_build_env(extra_env),
    )

    async for line in process.stdout:
        text = line.decode().rstrip()
        if text and on_line:
            await on_line(text)

    await process.wait()
    if process.returncode != 0:
        return {"error": "Plan failed"}

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

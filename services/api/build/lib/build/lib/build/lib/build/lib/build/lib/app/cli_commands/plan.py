import asyncio
import json
import re

from rich.text import Text
from rich.panel import Panel

from app.cli_commands.console import console
from app.services.terraform_cli import stream_terraform, get_plan_json


def run_plan(project_dir: str, var_file: str | None = None, json_output: bool = False, compact: bool = False):
    asyncio.run(_run(project_dir, var_file, json_output, compact))


def _style_plan_line(line: str) -> Text:
    """Apply terraform-style coloring to plan output lines."""
    text = Text(line)
    stripped = line.lstrip()
    if stripped.startswith("+") or "will be created" in line:
        text.stylize("green")
    elif stripped.startswith("-") or "will be destroyed" in line:
        text.stylize("red")
    elif stripped.startswith("~") or "will be updated" in line:
        text.stylize("yellow")
    elif stripped.startswith("#"):
        text.stylize("bold")
    elif "Plan:" in line:
        text.stylize("bold cyan")
    elif "No changes" in line:
        text.stylize("bold green")
    elif re.match(r"^\s*Error", line):
        text.stylize("bold red")
    return text


async def _run(project_dir: str, var_file: str | None, json_output: bool, compact: bool):
    if json_output:
        plan_data = await get_plan_json(project_dir, var_file)
        if compact and not plan_data.get("error"):
            changes = [
                rc for rc in plan_data.get("resource_changes", [])
                if rc.get("change", {}).get("actions", []) not in [["no-op"], ["read"]]
            ]
            plan_data = {"resource_changes": changes}
        print(json.dumps(plan_data, indent=2))
        return

    if compact:
        lines = []
        async for line in stream_terraform(project_dir, ["plan"], var_file):
            lines.append(line)
        output = "".join(lines)
        for line in output.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("+", "-", "~", "#")) or "Plan:" in line or "No changes" in line or "Error" in line:
                console.print(_style_plan_line(line))
        return

    async for line in stream_terraform(project_dir, ["plan"], var_file):
        for sub in line.splitlines(keepends=True):
            console.print(_style_plan_line(sub.rstrip("\n")))

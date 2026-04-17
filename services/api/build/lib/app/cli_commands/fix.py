import asyncio
import re
import sys

from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from app import config
from app.cli_commands.console import console


def run_fix(project_dir: str, auto: bool = False, dry_run: bool = False):
    ai_config = config.get_ai_config()
    if not ai_config.get("api_token"):
        console.print("[error]Error:[/] AI not configured. Set OPENAI_API_KEY or add ai.api_token to .inframate.yml")
        raise SystemExit(1)
    asyncio.run(_run(project_dir, ai_config, auto, dry_run))


async def _run(project_dir: str, ai_config: dict, auto: bool, dry_run: bool):
    from app.services.terraform_cli import run_terraform
    from app.services.terraform_parser import load_project_context, write_file
    from app.services.ai_service import diagnose_stream

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task("Running terraform plan...", total=None)
        output, code = await run_terraform(project_dir, ["plan", "-no-color"])

    console.print(Panel(output.strip(), title="Plan Output", border_style="red" if code != 0 else "green", expand=False))

    if code == 0:
        console.print("\n[success]Plan succeeded. Nothing to fix.[/]")
        return

    console.print("\n[warning]Plan failed.[/] Sending to AI for diagnosis...\n")

    context = load_project_context(project_dir)
    full_response = []

    async for chunk in diagnose_stream("terraform plan", output, context, ai_config):
        sys.stdout.write(chunk)
        sys.stdout.flush()
        full_response.append(chunk)
    print()

    response_text = "".join(full_response)
    changes = _parse_file_changes(response_text)

    if not changes:
        console.print("\n[muted]No file changes suggested by AI.[/]")
        return

    console.print(f"\n[bold]{len(changes)} file change(s) suggested:[/]")
    for filename, content in changes:
        console.print(f"  [cyan]{filename}[/]")
        console.print(Syntax(content.strip(), "hcl", theme="monokai", line_numbers=True, padding=1))

    if dry_run:
        console.print("\n[muted](dry-run) No changes applied.[/]")
        return

    if not auto:
        if not Confirm.ask("\nApply changes?", default=False, console=console):
            console.print("[muted]Skipped.[/]")
            return

    for filename, content in changes:
        if write_file(project_dir, filename, content):
            console.print(f"  [success]Updated {filename}[/]")
        else:
            console.print(f"  [error]Failed to write {filename}[/]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task("Re-running terraform plan...", total=None)
        output2, code2 = await run_terraform(project_dir, ["plan", "-no-color"])

    console.print(Panel(output2.strip(), title="Re-plan Output", border_style="green" if code2 == 0 else "red", expand=False))

    if code2 == 0:
        console.print("[success]Plan succeeded after fix.[/]")
    else:
        console.print("[warning]Plan still failing.[/] Run [bold]inframate fix[/] again or fix manually.")


FILE_PATTERN = re.compile(r'File:\s*(\S+)\s*\n```\w*\n(.*?)```', re.DOTALL)


def _parse_file_changes(response: str) -> list[tuple[str, str]]:
    """Parse AI response for file change suggestions."""
    return [(m.group(1), m.group(2)) for m in FILE_PATTERN.finditer(response)]

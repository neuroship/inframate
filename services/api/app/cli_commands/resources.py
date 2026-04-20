import asyncio
import json as json_mod
import os
import re
import sys

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

from app import config
from app.cli_commands.console import console


FILE_PATTERN = re.compile(r'File:\s*(\S+)\s*\n```\w*\n(.*?)```', re.DOTALL)
CMD_PATTERN = re.compile(r'```(?:bash|sh|shell)\n(.*?)```', re.DOTALL)


def _needs_reinit(plan_output: str) -> bool:
    """Check if plan error indicates terraform reinitialization is needed."""
    lower = plan_output.lower()
    return "reinitialization" in lower or ("terraform init" in lower and "backend" in lower)


async def _ensure_init(project_dir: str):
    """Run terraform init automatically if .terraform directory is missing."""
    tf_dir = os.path.join(project_dir, ".terraform")
    if os.path.isdir(tf_dir):
        return

    from app.services.terraform_cli import run_terraform

    console.print("[muted]  terraform: not initialized, running init...[/]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task("Running terraform init...", total=None)
        output, code = await run_terraform(project_dir, ["init", "-input=false", "-no-color"])

    if code == 0:
        console.print("[muted]  terraform: initialized ✓[/]")
    else:
        console.print(f"  [error]terraform init failed:[/] {output.strip()[-200:]}")


async def _handle_reinit(project_dir: str) -> bool:
    """Prompt user and run terraform init with -reconfigure or -migrate-state. Returns True on success."""
    from app.services.terraform_cli import run_terraform
    from app.services.plan_cache import invalidate_cache

    console.print()
    console.print("  [warning]Backend configuration changed — reinitialization required.[/]")
    choice = Prompt.ask(
        "  Init mode",
        choices=["reconfigure", "migrate-state", "skip"],
        default="reconfigure",
        console=console,
    )
    if choice == "skip":
        return False

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task(f"Running terraform init -{choice}...", total=None)
        output, code = await run_terraform(project_dir, ["init", "-input=false", f"-{choice}", "-no-color"])

    if code == 0:
        console.print(f"  [success]✓ Reinitialized successfully[/]")
        invalidate_cache(project_dir)
        return True
    else:
        console.print(f"  [error]terraform init failed:[/] {output.strip()[-200:]}")
        return False


def run_resources(
    project_dir: str,
    status: str | None = None,
    service: str | None = None,
    json_output: bool = False,
    no_cloud: bool = False,
    credential_expiry: dict | None = None,
):
    # Auto-init if .terraform is missing
    try:
        asyncio.run(_ensure_init(project_dir))
    except KeyboardInterrupt:
        console.print("\n[muted]Interrupted.[/]")
        return

    try:
        rows, warnings, plan_raw_output = asyncio.run(_load_data(project_dir, service, no_cloud))
    except KeyboardInterrupt:
        console.print("\n[muted]Interrupted.[/]")
        return

    if json_output:
        if status:
            rows = [r for r in rows if r.get("status") == status]
        print(json_mod.dumps(rows, indent=2))
        return

    # Handle reinit before falling to AI fix loop
    if plan_raw_output and _needs_reinit(plan_raw_output):
        try:
            if asyncio.run(_handle_reinit(project_dir)):
                rows, warnings, plan_raw_output = asyncio.run(_load_data(project_dir, service, no_cloud))
        except KeyboardInterrupt:
            pass

    # AI diagnosis flow if plan still failed
    if plan_raw_output:
        try:
            fixed = asyncio.run(_ai_fix_loop(project_dir, "plan", plan_raw_output, ["plan", "-no-color"]))
        except KeyboardInterrupt:
            fixed = False
        if fixed:
            try:
                rows, warnings, plan_raw_output = asyncio.run(_load_data(project_dir, service, no_cloud))
            except KeyboardInterrupt:
                console.print("\n[muted]Interrupted.[/]")
                return

    # Main TUI loop — re-enters after apply/destroy/costs
    show_costs = False
    while True:
        from app.cli_commands.resources_tui import ResourcesApp
        app = ResourcesApp(rows, warnings=warnings, show_costs=show_costs, credential_expiry=credential_expiry)
        result = app.run()

        if not isinstance(result, tuple):
            break

        action, resources = result

        try:
            if action == "refresh":
                rows, warnings, plan_raw_output = asyncio.run(_load_data(project_dir, service, no_cloud))
                show_costs = False
                continue
            elif action == "load_costs":
                rows = asyncio.run(_load_costs(project_dir, rows))
                show_costs = True
                continue
            elif action == "summarize":
                asyncio.run(_show_summary(rows))
                continue
            elif action == "apply":
                _handle_apply(project_dir, resources)
            elif action == "destroy":
                _handle_destroy(project_dir, resources)

            # Re-load data for next TUI iteration
            rows, warnings, plan_raw_output = asyncio.run(_load_data(project_dir, service, no_cloud))
            show_costs = False
        except KeyboardInterrupt:
            console.print("\n[muted]Interrupted. Returning to TUI...[/]")
            continue


# --- AI diagnosis ---


def _parse_commands(response: str) -> list[str]:
    """Extract runnable commands from bash/sh/shell code blocks (excluding file changes)."""
    file_spans = {(m.start(), m.end()) for m in FILE_PATTERN.finditer(response)}

    commands = []
    for m in CMD_PATTERN.finditer(response):
        # Skip if this code block overlaps with a file change
        if any(fs[0] <= m.start() <= fs[1] for fs in file_spans):
            continue
        block = m.group(1).strip()
        for line in block.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


async def _run_command(project_dir: str, command: str) -> tuple[str, int]:
    """Run a shell command in the project directory."""
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=project_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ},
    )
    stdout, _ = await process.communicate()
    return stdout.decode(), process.returncode


async def _ai_fix_loop(project_dir: str, command: str, error_output: str, rerun_args: list[str]) -> bool:
    """Chat-like AI diagnosis loop for plan/apply/destroy errors.
    Returns True if command succeeded after fix."""
    ai_config = config.get_ai_config()
    if not ai_config.get("api_token"):
        console.print()
        console.print("  [muted]Tip: configure AI to get fix suggestions. Add .inframate/config.yml:[/]")
        console.print("  [muted]  ai:[/]")
        console.print("  [muted]    provider: openai  # or: anthropic, ollama, groq, deepseek[/]")
        console.print("  [muted]    api_token: sk-...[/]")
        console.print("  [muted]Or set OPENAI_API_KEY environment variable.[/]")
        console.print()
        return False

    from app.services.terraform_cli import run_terraform
    from app.services.terraform_parser import load_project_context, write_file
    from app.services.ai_service import diagnose_stream
    from app.services.plan_cache import invalidate_cache

    context = load_project_context(project_dir)
    current_output = error_output

    while True:
        console.print()
        console.print(f"  [warning]{command.capitalize()} failed.[/] Diagnosing with AI...\n")

        # Stream AI response
        full_response = []
        console.print("  [bold cyan]--- AI Diagnosis ---[/]\n")
        async for chunk in diagnose_stream(command, current_output, context, ai_config):
            sys.stdout.write(chunk)
            sys.stdout.flush()
            full_response.append(chunk)
        sys.stdout.write("\n\n")

        response_text = "".join(full_response)
        changes = [(m.group(1), m.group(2)) for m in FILE_PATTERN.finditer(response_text)]
        commands = _parse_commands(response_text)

        if not changes and not commands:
            console.print("  [muted]No actionable suggestions from AI.[/]\n")
            return False

        applied_something = False

        # File changes
        if changes:
            console.print(f"  [bold]{len(changes)} file change(s) suggested:[/]\n")
            for filename, content in changes:
                console.print(f"  [cyan]{filename}[/]")
                console.print(Syntax(content.strip(), "hcl", theme="monokai", line_numbers=True, padding=1))
                console.print()

            if Confirm.ask("  Apply file changes?", default=True, console=console):
                for filename, content in changes:
                    if write_file(project_dir, filename, content):
                        console.print(f"    [success]✓ Updated {filename}[/]")
                    else:
                        console.print(f"    [error]✕ Failed to write {filename}[/]")
                applied_something = True

        # Commands
        if commands:
            console.print(f"\n  [bold]{len(commands)} command(s) suggested:[/]\n")
            for cmd in commands:
                console.print(f"    [cyan]$ {cmd}[/]")
            console.print()

            if Confirm.ask("  Run these commands?", default=True, console=console):
                for cmd in commands:
                    console.print(f"\n    [dim]$ {cmd}[/]")
                    cmd_output, code = await _run_command(project_dir, cmd)
                    if cmd_output.strip():
                        for line in cmd_output.strip().splitlines():
                            console.print(f"    {line}")
                    if code == 0:
                        console.print(f"    [success]✓ Done[/]")
                    else:
                        console.print(f"    [error]✕ Exit code {code}[/]")
                applied_something = True

        if not applied_something:
            console.print("  [muted]No changes applied.[/]\n")
            return False

        # Invalidate cache and re-run
        invalidate_cache(project_dir)

        console.print(f"\n  Re-running {command}...")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
            progress.add_task(f"Running terraform {command}...", total=None)
            output, code = await run_terraform(project_dir, rerun_args)

        if code == 0:
            console.print(f"  [success]✓ {command.capitalize()} succeeded![/]\n")
            return True

        # Still failing — offer another round
        current_output = output
        console.print(f"  [warning]{command.capitalize()} still failing.[/]")
        if not Confirm.ask("  Try AI diagnosis again?", default=True, console=console):
            return False

        context = load_project_context(project_dir)


# --- Plan summary ---


async def _show_summary(rows: list[dict]):
    """Stream AI plan summary to console."""
    ai_config = config.get_ai_config()
    if not ai_config.get("api_token"):
        console.print("\n  [muted]AI not configured. Add to .inframate/config.yml in your project (or set OPENAI_API_KEY):[/]")
        console.print("  [muted]  ai:[/]")
        console.print("  [muted]    provider: openai[/]")
        console.print("  [muted]    api_token: sk-...[/]\n")
        Prompt.ask("  [dim]Press Enter to return[/]", default="", console=console)
        return

    from app.services.ai_service import summarize_plan_stream

    console.print("\n  [bold cyan]--- Plan Summary ---[/]\n")
    try:
        async for chunk in summarize_plan_stream(rows, ai_config):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n\n")
    except Exception as e:
        console.print(f"\n  [error]Error: {e}[/]\n")
    Prompt.ask("  [dim]Press Enter to return[/]", default="", console=console)


# --- Apply flow ---


def _handle_apply(project_dir: str, resources: list[dict]):
    """Run terraform apply with confirmation and AI fix on failure."""
    if resources:
        console.print(f"\n[bold]Apply {len(resources)} resource(s)?[/]\n")
        for r in resources:
            name = r.get("resource_name", "")
            action = r.get("action", "")
            symbols = {"create": "+", "update": "~", "destroy": "-", "replace": "±"}
            colors = {"create": "blue", "update": "yellow", "destroy": "red", "replace": "magenta"}
            s = symbols.get(action, "?")
            c = colors.get(action, "dim")
            rtype = r.get("display_type", r.get("resource_type", ""))
            console.print(f"  [{c}]{s}[/] {rtype}: {name} [{c}]{action}[/]")
    else:
        console.print("\n[bold]Apply all planned changes?[/]")

    console.print()
    if not Confirm.ask("Proceed?", default=False, console=console):
        console.print("[muted]Cancelled.[/]")
        return

    asyncio.run(_run_apply(project_dir, resources))


async def _run_apply(project_dir: str, resources: list[dict]):
    """Stream terraform apply, then AI fix loop on failure."""
    args = ["apply"]
    if resources:
        args += [f"-target={r['id']}" for r in resources]

    console.print(f"\n[bold]Running terraform apply...[/]\n")
    output, code = await _stream_and_capture(project_dir, args)

    if code == 0:
        console.print("\n[success]✓ Apply succeeded![/]")
        return

    # Build re-run args for AI fix loop (run_terraform doesn't auto-add flags)
    rerun = ["apply", "-auto-approve", "-no-color"]
    if resources:
        rerun += [f"-target={r['id']}" for r in resources]

    await _ai_fix_loop(project_dir, "apply", output, rerun)


# --- Destroy flow ---


def _handle_destroy(project_dir: str, resources: list[dict]):
    """Run destroy with confirmation and AI fix on failure."""
    tf_resources = [r for r in resources if r.get("in_code") or r.get("in_state")]
    aws_only = [r for r in resources if r.get("status") == "unmanaged"]

    console.print(f"\n[bold red]Destroy {len(resources)} resource(s)?[/]\n")
    for r in resources:
        name = r.get("resource_name", "")
        rtype = r.get("display_type", r.get("resource_type", ""))
        method = "terraform" if (r.get("in_code") or r.get("in_state")) else "AWS API"
        console.print(f"  [red]✕[/] {rtype}: {name} [dim]({method})[/]")

    console.print()
    if not Confirm.ask("Proceed?", default=False, console=console):
        console.print("[muted]Cancelled.[/]")
        return

    asyncio.run(_run_destroy(project_dir, tf_resources, aws_only))


async def _run_destroy(project_dir: str, tf_resources: list[dict], aws_only: list[dict]):
    if tf_resources:
        targets = [f"-target={r['id']}" for r in tf_resources]
        args = ["destroy"] + targets

        console.print(f"\n[bold]Destroying {len(tf_resources)} terraform resource(s)...[/]\n")
        output, code = await _stream_and_capture(project_dir, args)

        if code != 0:
            rerun = ["destroy", "-auto-approve", "-no-color"] + targets
            await _ai_fix_loop(project_dir, "destroy", output, rerun)

    if aws_only:
        import aioboto3
        from app.services.aws_delete import delete_resource

        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
        session = aioboto3.Session(region_name=region)
        console.print(f"\n[bold]Deleting {len(aws_only)} AWS resource(s)...[/]\n")

        for r in aws_only:
            name = r.get("resource_name", r.get("cloud_id", ""))

            async def on_progress(msg):
                console.print(f"  [dim]{msg}[/]")

            result = await delete_resource(session, region, r, on_progress)
            if result["ok"]:
                console.print(f"  [green]✓[/] {name}: {result['message']}")
            else:
                console.print(f"  [red]✕[/] {name}: {result['message']}")

    console.print("\n[bold]Done.[/]")


# --- Costs ---


async def _load_costs(project_dir: str, rows: list[dict]) -> list[dict]:
    """Fetch AWS costs and merge into existing resource rows."""
    from app.services.aws_costs import get_costs_by_resource, get_costs_by_service, match_costs_to_resources

    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task("Fetching AWS costs...", total=None)
        resource_costs, service_costs = await asyncio.gather(
            get_costs_by_resource({}, region, [], 30),
            get_costs_by_service({}, 30),
        )

    if "_error" in resource_costs:
        console.print(f"[error]Error fetching costs:[/] {resource_costs['_error']}")
        return rows

    match_costs_to_resources(resource_costs, service_costs, rows)
    total = sum(r.get("cost_monthly") or 0 for r in rows)
    console.print(f"[muted]  costs: ${total:,.2f}/mo across {sum(1 for r in rows if r.get('cost_monthly'))} resources[/]")
    return rows


# --- Helpers ---


async def _stream_and_capture(project_dir: str, args: list[str]) -> tuple[str, int]:
    """Stream terraform output to console and return (output, exit_code)."""
    from app.services.terraform_cli import stream_terraform

    lines = []
    async for line in stream_terraform(project_dir, args):
        console.print(line, end="", highlight=False)
        lines.append(line)

    output = "".join(lines)
    # stream_terraform appends "[Exit code: N]\n" on non-zero exit
    failed = "[Exit code:" in output
    return output, 1 if failed else 0


# --- Data loading ---


async def _load_data(
    project_dir: str,
    service: str | None,
    no_cloud: bool,
) -> tuple[list[dict], list[str], str]:
    """Load terraform + cloud data. Returns (rows, warnings, plan_raw_output)."""
    from app.services.aws_inventory import scan_all
    from app.services.unified import merge_with_cloud

    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    from app.services.terraform_cli import get_plan_json, get_graph_dot, stream_plan_with_output
    from app.services.terraform_parser import parse_dot_graph, get_resource_locations
    from app.services.plan_cache import get_cached_plan, save_cached_plan
    from app.services.overview import parse_plan_resources, build_overview_rows, _rows_from_state, OverviewResult

    # Phase 1: Terraform
    result = OverviewResult([])

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        task = progress.add_task("Reading terraform graph...", total=None)

        dot = await get_graph_dot(project_dir)
        graph = parse_dot_graph(dot)
        result.graph_nodes = len(graph["nodes"])
        progress.update(task, description=f"Graph: {len(graph['nodes'])} nodes. Reading plan...")

        cached = get_cached_plan(project_dir)
        if cached and not cached["plan_data"].get("error"):
            plan_data = cached["plan_data"]
            progress.update(task, description=f"Graph: {len(graph['nodes'])} nodes. Plan loaded from cache.")
        else:
            n = len(graph['nodes'])

            async def on_plan_line(line):
                # Show last meaningful line from terraform in the spinner
                short = line.strip()[:70]
                if short:
                    progress.update(task, description=f"Planning... {short}")

            progress.update(task, description=f"Graph: {n} nodes. Running terraform plan...")
            plan_data = await stream_plan_with_output(project_dir, on_line=on_plan_line)
            if not plan_data.get("error"):
                save_cached_plan(project_dir, plan_data)
                progress.update(task, description=f"Graph: {n} nodes. Plan: {len(plan_data.get('resource_changes', []))} changes.")
            else:
                progress.update(task, description=f"Graph: {n} nodes. Plan failed, reading state...")

        if plan_data.get("error"):
            result.plan_error = plan_data["error"]
            result.plan_raw_output = plan_data.get("raw_output", "")
            result.warnings.append(plan_data["error"])

        plan_resources = parse_plan_resources(plan_data)
        result.plan_resources = len(plan_resources)
        locations = get_resource_locations(project_dir)
        rows = build_overview_rows(graph, plan_resources, locations)

        if not rows:
            progress.update(task, description="Graph+plan empty, reading state...")
            rows = await _rows_from_state(project_dir, locations)
            if rows:
                result.source = "state"
                result.warnings.append(f"using state fallback ({len(rows)} resources)")

        result.rows = rows

    overview = result
    console.print(f"[muted]  terraform: {len(overview)} resources (graph:{overview.graph_nodes}, plan:{overview.plan_resources}, source:{overview.source})[/]")
    for w in overview.warnings:
        console.print(f"  [warning]warning:[/] {w}")

    rows = list(overview.rows)

    # Phase 2: Cloud scan (optional)
    if not no_cloud:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=20),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        ) as progress:
            scan_task = progress.add_task("Scanning cloud resources...", total=22)

            def on_progress(done, total, label):
                progress.update(scan_task, total=total, completed=done, description=f"Scanning {label}...")

            aws_resources = await scan_all({}, region, on_progress=on_progress)

        console.print(f"[muted]  cloud: {len(aws_resources)} resources found[/]")
        rows = merge_with_cloud(rows, aws_resources, region)

    # Pre-filter by service
    if service:
        rows = [r for r in rows if service.lower() in (r.get("service", "") or "").lower()]

    return rows, overview.warnings, overview.plan_raw_output

import asyncio
import json as json_mod
import os

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from app.cli_commands.console import console


def run_resources(
    project_dir: str,
    status: str | None = None,
    service: str | None = None,
    json_output: bool = False,
    no_cloud: bool = False,
):
    rows, warnings = asyncio.run(_load_data(project_dir, service, no_cloud))

    if json_output:
        if status:
            rows = [r for r in rows if r.get("status") == status]
        print(json_mod.dumps(rows, indent=2))
        return

    from app.cli_commands.resources_tui import ResourcesApp
    app = ResourcesApp(rows, warnings=warnings)
    result = app.run()

    if isinstance(result, tuple) and result[0] == "destroy":
        _handle_destroy(project_dir, result[1])


def _handle_destroy(project_dir: str, resources: list[dict]):
    """Run destroy after TUI exits with selected resources."""
    from rich.prompt import Confirm

    tf_resources = [r for r in resources if r.get("in_code") or r.get("in_state")]
    aws_only = [r for r in resources if r.get("status") == "unmanaged"]

    console.print(f"\n[bold red]Destroy {len(resources)} resource(s)?[/]\n")
    for r in resources:
        status = r.get("status", "")
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
    from app.services.terraform_cli import stream_terraform

    if tf_resources:
        targets = [f"-target={r['id']}" for r in tf_resources]
        console.print(f"\n[bold]Destroying {len(tf_resources)} terraform resource(s)...[/]\n")
        async for line in stream_terraform(project_dir, ["destroy"] + targets):
            console.print(line, end="", highlight=False)

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


async def _load_data(
    project_dir: str,
    service: str | None,
    no_cloud: bool,
) -> tuple[list[dict], list[str]]:
    from app.services.overview import compute_overview
    from app.services.aws_inventory import scan_all
    from app.services.unified import merge_with_cloud

    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    from app.services.terraform_cli import get_graph_dot, get_plan_json, get_state
    from app.services.terraform_parser import parse_dot_graph, get_resource_locations
    from app.services.plan_cache import get_cached_plan, save_cached_plan
    from app.services.overview import parse_plan_resources, build_overview_rows, _rows_from_state, OverviewResult
    from app.services.unified import derive_status

    # Phase 1: Terraform — show progress per step
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
            plan_data = await get_plan_json(project_dir)
            if not plan_data.get("error"):
                save_cached_plan(project_dir, plan_data)
                progress.update(task, description=f"Graph: {len(graph['nodes'])} nodes. Plan: {len(plan_data.get('resource_changes', []))} changes.")
            else:
                progress.update(task, description=f"Graph: {len(graph['nodes'])} nodes. Plan failed, reading state...")

        if plan_data.get("error"):
            result.plan_error = plan_data["error"]
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

    return rows, overview.warnings

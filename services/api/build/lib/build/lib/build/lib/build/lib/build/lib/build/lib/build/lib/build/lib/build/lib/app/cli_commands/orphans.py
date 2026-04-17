import asyncio
import json as json_mod
import os

from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from app.cli_commands.console import console


def run_orphans(project_dir: str, service: str | None = None, resource_type: str | None = None, json_output: bool = False):
    asyncio.run(_run(project_dir, service, resource_type, json_output))


async def _run(project_dir: str, service: str | None, resource_type: str | None, json_output: bool):
    from app.services.overview import compute_overview
    from app.services.aws_inventory import scan_all, match_inventory_with_terraform

    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=20),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        scan_task = progress.add_task("Scanning AWS resources...", total=22)

        def on_progress(done, total, label):
            progress.update(scan_task, total=total, completed=done, description=f"Scanning {label}...")

        aws_resources = await scan_all({}, region, on_progress=on_progress)
        progress.update(scan_task, description=f"Found {len(aws_resources)} AWS resources", completed=22)

        progress.add_task("Reading terraform state...", total=None)
        tf_rows = await compute_overview(project_dir)

    console.print(f"[muted]Found {len(aws_resources)} AWS resources, {len(tf_rows)} terraform resources[/]")

    merged = match_inventory_with_terraform(aws_resources, tf_rows)
    orphans = [r for r in merged if r.get("source") == "aws_only"]

    if service:
        orphans = [r for r in orphans if service.lower() in (r.get("service", "") or "").lower()]
    if resource_type:
        orphans = [r for r in orphans if resource_type.lower() in (r.get("type", "") or "").lower()]

    if json_output:
        print(json_mod.dumps(orphans, indent=2))
        return

    if not orphans:
        console.print("\n[success]No orphaned resources found.[/] All AWS resources are managed by terraform.")
        return

    table = Table(
        title=f"{len(orphans)} Unmanaged Resources",
        title_style="bold yellow",
        border_style="dim",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("Service", style="cyan", min_width=12)
    table.add_column("Type", style="dim")
    table.add_column("Name", style="white", min_width=20, max_width=40)
    table.add_column("ID", style="dim", max_width=30)

    for r in orphans:
        table.add_row(
            r.get("service", ""),
            r.get("type", ""),
            r.get("name", ""),
            r.get("id", ""),
        )

    console.print()
    console.print(table)
    console.print(f"\n[muted]These resources exist in AWS but are not managed by Terraform.[/]")

import asyncio
import json as json_mod
import os

from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from app.cli_commands.console import console


def run_costs(project_dir: str, days: int = 30, service: str | None = None, sort_by: str = "cost", json_output: bool = False):
    asyncio.run(_run(project_dir, days, service, sort_by, json_output))


def _cost_style(cost: float) -> str:
    if cost > 100:
        return "cost.high"
    if cost > 10:
        return "cost.medium"
    return "cost.low"


def _cost_str(cost: float) -> str:
    return f"[{_cost_style(cost)}]${cost:>9.2f}[/]"


async def _run(project_dir: str, days: int, service: str | None, sort_by: str, json_output: bool):
    from app.services.overview import compute_overview
    from app.services.aws_costs import get_costs_by_resource, get_costs_by_service, match_costs_to_resources

    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Computing terraform overview...", total=None)
        rows = await compute_overview(project_dir)

        progress.tasks[0].description = f"Fetching AWS costs ({days} days)..."
        resource_costs, service_costs = await asyncio.gather(
            get_costs_by_resource({}, region, [], days),
            get_costs_by_service({}, days),
        )

    if "_error" in resource_costs:
        console.print(f"\n[error]Error fetching resource costs:[/] {resource_costs['_error']}")
        svc = {k: v for k, v in service_costs.items() if not k.startswith("_")}
        if service:
            svc = {k: v for k, v in svc.items() if service.lower() in k.lower()}
        if json_output:
            print(json_mod.dumps({"service_costs": svc, "error": resource_costs["_error"]}, indent=2))
        else:
            _print_service_table(svc, days)
        return

    enriched = match_costs_to_resources(resource_costs, service_costs, rows)

    if service:
        enriched = [r for r in enriched if service.lower() in (r.get("service", "") or "").lower()]

    costed = [r for r in enriched if r.get("cost_monthly")]

    if sort_by == "cost":
        costed.sort(key=lambda r: r.get("cost_monthly", 0), reverse=True)
    elif sort_by == "name":
        costed.sort(key=lambda r: r.get("resource_name", ""))
    elif sort_by == "service":
        costed.sort(key=lambda r: (r.get("service", ""), -(r.get("cost_monthly") or 0)))

    total = sum(r.get("cost_monthly") or 0 for r in costed)

    if json_output:
        svc = {k: v for k, v in service_costs.items() if not k.startswith("_")}
        if service:
            svc = {k: v for k, v in svc.items() if service.lower() in k.lower()}
        print(json_mod.dumps({
            "resources": costed,
            "service_costs": svc,
            "total_monthly": round(total, 2),
            "days": days,
        }, indent=2))
        return

    if costed:
        table = Table(
            title=f"Resource Costs ({days}-day lookback)",
            title_style="bold",
            border_style="dim",
            show_lines=False,
            pad_edge=True,
        )
        table.add_column("Resource", style="cyan", min_width=20, max_width=45)
        table.add_column("Type", style="dim")
        table.add_column("Monthly", justify="right", min_width=10)

        for r in costed:
            name = r.get("resource_name", r.get("id", ""))
            rtype = r.get("display_type", r.get("resource_type", ""))
            cost = r.get("cost_monthly", 0)
            table.add_row(name, rtype, _cost_str(cost))

        table.add_section()
        table.add_row("[bold]Total[/]", "", f"[bold]{_cost_str(total)}[/]")
        console.print()
        console.print(table)
    else:
        console.print("\n[muted]No resource-level costs found.[/]")

    svc = {k: v for k, v in service_costs.items() if not k.startswith("_")}
    if service:
        svc = {k: v for k, v in svc.items() if service.lower() in k.lower()}
    if svc:
        _print_service_table(svc, days)


def _print_service_table(service_costs: dict, days: int):
    def _cost(v):
        return v["total"] if isinstance(v, dict) else v

    items = sorted(service_costs.items(), key=lambda x: _cost(x[1]), reverse=True)
    total = sum(_cost(v) for _, v in items)

    table = Table(
        title=f"Costs by Service ({days}-day lookback)",
        title_style="bold",
        border_style="dim",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("Service", style="white", min_width=30)
    table.add_column("Monthly", justify="right", min_width=10)

    for svc, val in items:
        cost = _cost(val)
        table.add_row(svc, _cost_str(cost))

    table.add_section()
    table.add_row("[bold]Total[/]", f"[bold]{_cost_str(total)}[/]")
    console.print()
    console.print(table)

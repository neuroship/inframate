import argparse
import os


def _check_tf_files(project_dir: str):
    has_tf = any(f.endswith(".tf") for f in os.listdir(project_dir) if os.path.isfile(os.path.join(project_dir, f)))
    if not has_tf:
        print(f"No .tf files found in {project_dir}")
        print()
        print("To get started, create a terraform configuration or run:")
        print(f"  cd {project_dir} && terraform init")
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="inframate",
        description="Terraform infrastructure management tool",
    )
    parser.add_argument("--dir", type=str, default=".", help="Terraform project directory (default: cwd)")

    sub = parser.add_subparsers(dest="command")

    # ui
    ui_parser = sub.add_parser("ui", help="Start web UI")
    ui_parser.add_argument("--port", type=int, default=None, help="Port (default: from config or 8000)")
    ui_parser.add_argument("--no-browser", action="store_true", help="Don't open browser on startup")

    # plan
    plan_parser = sub.add_parser("plan", help="Run terraform plan")
    plan_parser.add_argument("--var-file", type=str, default=None, help="Path to .tfvars file")
    plan_parser.add_argument("--json", action="store_true", dest="json_output", help="Output plan as JSON")
    plan_parser.add_argument("--compact", action="store_true", help="Show only resources with changes")

    # costs
    costs_parser = sub.add_parser("costs", help="Show AWS costs breakdown")
    costs_parser.add_argument("--days", type=int, default=30, help="Lookback period in days (default: 30)")
    costs_parser.add_argument("--service", type=str, default=None, help="Filter by service name")
    costs_parser.add_argument("--sort", choices=["cost", "name", "service"], default="cost", help="Sort order (default: cost)")
    costs_parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")

    # resources
    res_parser = sub.add_parser("resources", help="Interactive resource browser (state / code / cloud)")
    res_parser.add_argument("--service", type=str, default=None, help="Filter by service name")
    res_parser.add_argument("--no-cloud", action="store_true", help="Skip cloud scan (faster, no drift/unmanaged detection)")
    res_parser.add_argument("--status", type=str, default=None, choices=["managed", "pending", "drift", "unmanaged", "orphaned"], help="Filter by status (for --json)")
    res_parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON (non-interactive)")

    # fix
    fix_parser = sub.add_parser("fix", help="AI-assisted error fixing")
    fix_parser.add_argument("--auto", action="store_true", help="Apply fixes without prompting")
    fix_parser.add_argument("--dry-run", action="store_true", help="Show AI suggestion without applying")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        raise SystemExit(0)

    project_dir = os.path.abspath(args.dir)
    if not os.path.isdir(project_dir):
        print(f"Error: {project_dir} is not a directory")
        raise SystemExit(1)

    # Version check (background)
    from app.services.version_check import start_check, print_update_notice
    version_thread = start_check()

    # Load config
    from app import config
    overrides = {}
    if hasattr(args, "port") and args.port is not None:
        overrides["port"] = args.port
    config.load_config(project_dir, overrides)

    _check_tf_files(project_dir)

    # Backend reachability check (skip for ui — let it show errors interactively)
    if args.command != "ui":
        from app.services.backend_check import check_backend
        ok, errors = check_backend(project_dir)
        if not ok:
            print("Backend authentication failed:\n")
            for err in errors:
                print(f"  - {err}")
            print()
            raise SystemExit(1)

    # Dispatch
    if args.command == "ui":
        from app.cli_commands.ui import run_ui
        run_ui(project_dir, config.get_port(), args.no_browser)
    elif args.command == "plan":
        from app.cli_commands.plan import run_plan
        run_plan(project_dir, var_file=args.var_file, json_output=args.json_output, compact=args.compact)
    elif args.command == "resources":
        from app.cli_commands.resources import run_resources
        run_resources(project_dir, status=args.status, service=args.service, json_output=args.json_output, no_cloud=args.no_cloud)
    elif args.command == "costs":
        from app.cli_commands.costs import run_costs
        run_costs(project_dir, days=args.days, service=args.service, sort_by=args.sort, json_output=args.json_output)
    elif args.command == "fix":
        from app.cli_commands.fix import run_fix
        run_fix(project_dir, auto=args.auto, dry_run=args.dry_run)

    # Show upgrade notice if available
    print_update_notice(version_thread)


if __name__ == "__main__":
    main()

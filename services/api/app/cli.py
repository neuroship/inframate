import argparse
import os
from importlib.metadata import version


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
        description="Terraform infrastructure management tool. Runs the interactive resource browser by default.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {version('inframate')}")
    parser.add_argument("--dir", type=str, default=".", help="Terraform project directory (default: cwd)")
    parser.add_argument("--service", type=str, default=None, help="Filter by service name")
    parser.add_argument("--no-cloud", action="store_true", help="Skip cloud scan (faster, no drift/unmanaged detection)")
    parser.add_argument("--status", type=str, default=None, choices=["managed", "pending", "drift", "unmanaged", "orphaned"], help="Filter by status (for --json)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON (non-interactive)")

    sub = parser.add_subparsers(dest="command")

    ui_parser = sub.add_parser("serve", help="Start web server with UI")
    ui_parser.add_argument("--port", type=int, default=None, help="Port (default: from config or 8000)")
    ui_parser.add_argument("--no-browser", action="store_true", help="Don't open browser on startup")

    args = parser.parse_args()

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
    config.init_config_dir()
    config.load_config(project_dir, overrides)

    _check_tf_files(project_dir)

    # Backend reachability check (skip for ui)
    credential_expiry = None
    if args.command != "serve":
        from app.services.backend_check import check_backend, get_credential_expiry
        ok, errors = check_backend(project_dir)
        if not ok:
            print("Backend authentication failed:\n")
            for err in errors:
                print(f"  - {err}")
            print()
            raise SystemExit(1)
        credential_expiry = get_credential_expiry()

    # Dispatch
    try:
        if args.command == "serve":
            from app.cli_commands.ui import run_ui
            run_ui(project_dir, config.get_port(), args.no_browser)
        else:
            from app.cli_commands.resources import run_resources
            run_resources(project_dir, status=args.status, service=args.service, json_output=args.json_output, no_cloud=args.no_cloud, credential_expiry=credential_expiry)
    except KeyboardInterrupt:
        print()

    print_update_notice(version_thread)


if __name__ == "__main__":
    main()

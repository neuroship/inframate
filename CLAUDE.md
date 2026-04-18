# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

inframate is a CLI tool for managing Terraform infrastructure. It serves a local web UI for browsing, editing, planning, and applying Terraform configurations, managing AWS resources (inventory, costs, deletion), and includes an AI chat assistant.

## Usage

```bash
# Install
inframate              # or: pipx install inframate, brew install inframate

# Run in a terraform project directory
cd my-terraform-project
inframate                        # starts at http://localhost:8000
inframate --port 9000            # custom port
inframate --dir /path/to/project # explicit directory
inframate --no-browser           # don't auto-open browser
```

## Commands

```bash
# Install all dependencies
task install

# Development (run in separate terminals)
task api:dev    # API server on port 8000
task ui:dev     # Vite dev server on port 5173 (proxies /api to :8000)

# Build
task ui:build   # Build UI into services/api/app/static/
task build      # Build full package (UI + Python wheel)

# Run packaged CLI
task run
```

## Architecture

Two services under `services/`:

**`services/api`** - Python 3.13 / FastAPI backend
- Entry point: `app/cli.py` - CLI with argparse, starts uvicorn
- App factory: `app/main.py` - creates FastAPI app, mounts routers + static files
- `app/config.py` - YAML config at `.inframate.yml` (AI settings, AWS config)
- `app/routers/` - API route handlers (terraform, aws, ai, settings)
- `app/services/` - business logic (terraform CLI/parser, AWS inventory/costs/delete, AI)
- Uses SSE for streaming operations (terraform plan/apply, AWS inventory, AI chat)
- Package manager: `uv` with `pyproject.toml`
- No database - settings stored in TOML config file

**`services/ui`** - Svelte 5 / Vite frontend
- Single-page app, no routing (always shows workspace view)
- `lib/api.js` - all API calls and SSE stream helpers
- Styling: TailwindCSS v4 + FlyonUI, icons via `@iconify-json/tabler`
- Build output goes to `services/api/app/static/` for bundling

## Key patterns

- All API routes prefixed with `/api`
- Streaming uses SSE with `data: ` prefix and `[DONE]` sentinel
- No auth - local CLI tool, single user
- Project directory set via CLI `--dir` flag, stored in `app.state.project_dir`
- AWS config stored in `app.state.aws_config` (runtime) + `~/.inframate/config.toml` (persistent)
- AI config stored in `~/.inframate/config.toml`

## API routes

```
/api/health                    GET   Health check
/api/settings/project          GET   Project directory info
/api/settings/ai               GET   AI config
/api/settings/ai               PUT   Save AI config
/api/terraform/{command}       POST  Run terraform command (SSE)
/api/terraform/files           GET   List .tf files
/api/terraform/files/{path}    GET/PUT  Read/write files
/api/terraform/overview        GET   Combined plan + graph
/api/terraform/overview-stream GET   SSE overview with progress
/api/terraform/costs           GET   AWS costs
/api/terraform/inventory       GET   AWS inventory scan (SSE)
/api/aws/configure             POST  Save AWS credentials
/api/aws/identity              GET   Current AWS identity
/api/aws/login                 POST  SSO login (SSE)
/api/aws/status                GET   Auth status
/api/ai/chat                   POST  Single message chat (SSE)
/api/ai/chat-session           POST  Multi-turn chat (SSE)
/api/ai/diagnose               POST  Diagnose terraform error (SSE)
```

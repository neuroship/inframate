# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

inframate is a CLI tool for managing Terraform infrastructure. It provides an interactive TUI for browsing, applying, and destroying resources, detecting drift, viewing costs, and AI-assisted error fixing. It also serves a web UI for browser-based management.

## Usage

```bash
cd my-terraform-project
inframate                # interactive TUI (default)
inframate --no-cloud     # skip cloud scan
inframate --json         # JSON output
inframate serve             # web UI at http://localhost:8000
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
- Entry point: `app/cli.py` - CLI with argparse, dispatches to TUI or web UI
- App factory: `app/main.py` - creates FastAPI app, mounts routers + static files
- `app/config.py` - YAML config: global `~/.inframate/config.yml` + project `.inframate/config.yml`
- `app/routers/` - API route handlers (terraform, aws, ai, settings)
- `app/services/` - business logic (terraform CLI/parser, AWS inventory/costs/delete, AI)
- `app/cli_commands/resources.py` - main CLI flow: load data, AI fix loop, TUI loop
- `app/cli_commands/resources_tui.py` - Textual TUI: tree view, search, apply, destroy, costs
- Uses SSE for streaming operations (terraform plan/apply, AWS inventory, AI chat)
- Package manager: `uv` with `pyproject.toml`
- No database - settings stored in YAML config files

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
- Config priority: env vars > project `.inframate/config.yml` > global `~/.inframate/config.yml` > defaults
- AI providers: openai, anthropic, ollama, groq, deepseek (all via OpenAI-compatible client)

## CLI flow (resources.py)

```
inframate
  ├── Load data (terraform graph + plan + cloud scan)
  ├── Plan error? → AI fix loop (diagnose → file changes + commands → re-plan)
  └── TUI loop:
      ├── Enter → Apply (confirm → stream apply → AI fix on failure)
      ├── x → Destroy (confirm → terraform destroy / AWS API → AI fix on failure)
      ├── $ → Load costs (fetch AWS billing → show in tree)
      ├── / → Search resources
      └── q → Quit
```

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

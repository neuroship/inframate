# inframate

A CLI tool for managing Terraform infrastructure. Browse resources, apply changes, detect drift, view costs, and fix errors with AI — all from your terminal.

## Install

```bash
# uv (recommended)
uv tool install inframate

# Homebrew
brew install inframate

# pip / pipx
pip install inframate
```

## Usage

```bash
cd my-terraform-project
inframate                # interactive resource browser (TUI)
inframate --no-cloud     # skip AWS cloud scan (faster)
inframate --service s3   # filter by service
inframate --json         # output as JSON
inframate serve             # start web UI at http://localhost:8000
```

Running `inframate` in a Terraform project directory will:

1. Read the Terraform graph and plan
2. Scan AWS resources for drift and unmanaged resources
3. Open an interactive TUI for browsing, applying, and destroying resources
4. If the plan fails and AI is configured, offer AI-assisted diagnosis and fixes

### Resource statuses

| Status | Meaning |
|--------|---------|
| **Managed** | In Terraform state and code, no pending changes |
| **Pending** | In code but not yet applied (create/update/destroy/replace planned) |
| **Drift** | Applied but actual cloud state differs from Terraform state |
| **Unmanaged** | Exists in AWS but not in any Terraform configuration |
| **Orphaned** | In Terraform state but the resource no longer exists in cloud |

Each resource also shows three indicators: **S** (in state), **C** (in code), **W** (in cloud).

### TUI keybindings

**Navigation & search**

| Key | Action |
|-----|--------|
| `Up/Down` | Navigate resources |
| `Left/Right` | Collapse/expand tree node |
| `/` | Search resources by name, type, or service |
| `Escape` | Clear search |
| `e` | Expand all tree nodes |
| `c` | Collapse all tree nodes |

**Filters**

| Key | Action |
|-----|--------|
| `a` | Show all resources |
| `m` | Filter: managed |
| `p` | Filter: pending |
| `d` | Filter: drift |
| `u` | Filter: unmanaged |
| `o` | Filter: orphaned |
| `1` | Filter action: create |
| `2` | Filter action: update |
| `3` | Filter action: destroy |
| `4` | Filter action: replace |
| `0` | Clear action filter |

**Actions**

| Key | Action |
|-----|--------|
| `Enter` | Show resource detail (attributes, changes, tags) |
| `Space` | Toggle resource selection |
| `r` | Force re-plan (invalidate cache, re-run terraform plan) |
| `R` | Apply (all planned changes, or selected only) |
| `X` | Destroy selected resources |
| `s` | AI plan summary (prioritized change overview) |
| `$` | Load and display AWS costs |
| `F5` | Refresh (re-read terraform + cloud data, may use cached plan) |
| `q` | Quit |

When apply or destroy fails, inframate streams AI diagnosis, suggests file changes and commands (e.g. `terraform import`, `terraform state rm`), and offers to apply fixes — in a loop until the issue is resolved.

### AI plan summary

Press `s` in the TUI (or click **Summarize** in the web UI) to get an AI-generated summary of all planned changes, ranked from most critical (destroys, replacements) to least (creates, minor updates). Requires AI to be configured.

## Configuration

Project config lives in `.inframate/config.yml` inside your Terraform project. Global defaults in `~/.inframate/config.yml` are merged underneath (project wins).

```yaml
# .inframate/config.yml
ai:
  provider: openai   # openai | anthropic | ollama | groq | deepseek
  api_token: sk-...
  # model: gpt-4o   # optional, defaults per provider

# Or use a custom endpoint:
# ai:
#   endpoint: http://localhost:11434/v1
#   api_token: ollama
#   model: llama3

# Custom var-file and backend config (applied automatically)
terraform:
  var_file: env/dev/terraform.tfvars         # used in plan, apply, destroy
  backend_config: env/dev/backend.hcl        # used in init
```

The `.inframate/` directory also stores plan cache and temporary plan files. You may want to add `.inframate/` to your `.gitignore`.

Provider defaults:

| Provider | Endpoint | Default model |
|----------|----------|---------------|
| `openai` | `api.openai.com/v1` | `gpt-4o` |
| `anthropic` | `api.anthropic.com/v1` | `claude-sonnet-4-20250514` |
| `ollama` | `localhost:11434/v1` | `llama3` |
| `groq` | `api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| `deepseek` | `api.deepseek.com/v1` | `deepseek-chat` |

Environment variables (`OPENAI_API_KEY`, `OPENAI_API_BASE`, `OPENAI_MODEL`) also work and take precedence over the config file.

## Web UI

```bash
inframate serve
inframate serve --port 9000
inframate serve --no-browser
```

The web UI provides a browser-based interface with file editing, AI chat sidebar, and interactive resource management.

## Development

### Prerequisites

- [go-task](https://taskfile.dev/)
- [Python 3.13+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/)
- [Node.js 22+](https://nodejs.org/)
- [Terraform](https://www.terraform.io/)

### Setup

```bash
task install       # install all dependencies
task api:dev       # start API server (terminal 1)
task ui:dev        # start UI dev server (terminal 2)
```

### Build

```bash
task build         # build UI + Python package
task run           # run the built CLI
```

## Project structure

```
services/
  api/    Python 3.13 / FastAPI backend
  ui/     Svelte 5 / TailwindCSS frontend
```

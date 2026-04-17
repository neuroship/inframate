# inframate

An all-in-one local interface for navigating, operating, and understanding your Terraform infrastructure.

## Features

- **Overview** — see Terraform resources at a glance with state and drift info
- **Inventory** — live-scan AWS resources across your account
- **Costs** — AWS cost breakdown by service and resource
- **File Editor** — browse and edit Terraform files in the browser
- **Variables** — view and manage Terraform variables
- **AI Assistant** — sidebar chat that understands your infrastructure context
- **AWS SSO** — SSO profile configuration and login

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
inframate                        # starts at http://localhost:8000
inframate --port 9000            # custom port
inframate --dir /path/to/project # explicit directory
inframate --no-browser           # don't auto-open browser
```

## Configuration

Settings are stored in `~/.inframate/config.toml`:

```toml
[ai]
endpoint = ""
api_token = "sk-..."
model = "gpt-4o"

[terraform]
binary = "terraform"
```

AWS credentials and AI settings can also be configured from the web UI.

## Development

### Prerequisites

- [go-task](https://taskfile.dev/)
- [Python 3.13+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/)
- [Node.js 22+](https://nodejs.org/)
- [Terraform](https://www.terraform.io/)

### Setup

```bash
# Install all dependencies
task install

# Start API (terminal 1)
task api:dev

# Start UI (terminal 2)
task ui:dev
```

The UI dev server runs at `http://localhost:5173` and proxies `/api` to `http://localhost:8000`.

### Build

```bash
# Build UI + Python package
task build

# Run the built CLI
task run
```

## Project Structure

```
services/
  api/         Python/FastAPI backend
  ui/          Svelte 5 frontend
```

## Tech Stack

- **Backend** — Python 3.13, FastAPI, aioboto3, OpenAI
- **Frontend** — Svelte 5, TailwindCSS v4, FlyonUI, ag-grid
- **Build** — go-task, uv, Vite

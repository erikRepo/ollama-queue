# Contributing / Developer Setup

## Prerequisites

- Python 3.11 or newer
- Git

## Quick start

```bash
# 1. Clone
git clone https://github.com/<you>/ollama-queue.git
cd ollama-queue

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install the project and dev dependencies
pip install -e ".[dev]"

# 4. Copy the example env file and edit as needed
cp .env.example .env
```

The server reads settings from `.env` automatically on startup (via `python-dotenv` — no export needed).

## Running the tests

```bash
# All tests
pytest

# Unit tests only (fast, no I/O)
pytest tests/unit/

# E2E tests only (spins up FastAPI + temp SQLite, mocks Ollama)
pytest tests/e2e/

# With verbose output
pytest -v
```

## Code quality

```bash
# Lint
ruff check .

# Format (writes files in place)
ruff format .

# Both in one shot (lint then format)
ruff check . && ruff format .
```

CI requires zero `ruff` warnings before merge.

## Project layout

```
server/       FastAPI app, config, models, DB, queue, worker, WoL
client/       Python client library (ollama_queue package)
tests/unit/   Fast tests — no filesystem, network, or real DB
tests/e2e/    Full-stack tests — temp SQLite, Ollama mocked at HTTP
```

## Configuration reference

All settings can be set via environment variables or in `.env`:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8080` | Bind port |
| `DATABASE_URL` | `sqlite:///./ollama_queue.db` | SQLite file path |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama base URL |
| `OLLAMA_TIMEOUT` | `300` | Seconds to wait for an Ollama response |
| `WORKER_POLL_INTERVAL` | `2.0` | Seconds between queue polls |
| `WORKER_MAX_RETRIES` | `3` | Retry limit per job |
| `WORKER_RETRY_DELAY` | `5.0` | Seconds between retries |
| `WOL_MAC_ADDRESS` | _(empty)_ | Target MAC — leave blank to disable WoL |
| `WOL_BROADCAST` | `255.255.255.255` | WoL broadcast address |
| `WOL_PORT` | `9` | WoL UDP port |

## Commit style

- Imperative mood, max 72 chars: `Add POST /api/queue endpoint`
- One logical change per commit
- Never commit `.env` or secrets

# CLAUDE.md — ollama-queue development guidelines

## Implementation checklist

Each item below is one session. After completing an item, in this exact order:

1. Show the result and **wait for user approval**
2. Bump the version in `pyproject.toml` (patch = bug fix / small addition, minor = new feature, major = breaking change)
3. Add an entry to `CHANGELOG.md` describing what changed
4. Mark the completed item as done (`[x]`) in this checklist
5. `git commit` + `git push`

### Server
- [x] 1. Project scaffolding — `pyproject.toml` (version starts at `0.1.0`), `CHANGELOG.md`, `.env.example`, directory skeleton, `ruff` config
- [x] 2. `config.py` — load all settings from env/`.env` with defaults and validation
- [x] 3. `database.py` — SQLite connection, schema creation, migration on startup
- [x] 4. `models.py` — Pydantic request/response models and job status enum
- [x] 5. `queue.py` — Job CRUD: insert, get by id, list pending, update status
- [x] 6. `POST /api/queue` endpoint + unit tests
- [x] 7. `GET /api/status/:id` endpoint + unit tests
- [ ] 8. `wol.py` — Wake-on-LAN magic packet + unit tests
- [ ] 9. `worker.py` — background worker: poll queue, send WoL, call Ollama, update status, retry logic
- [ ] 10. E2E tests — full flow with temporary SQLite and mocked Ollama HTTP

### Client library
- [ ] 11. `client/ollama_queue/client.py` — `OllamaQueueClient.generate()` blocking implementation
- [ ] 12. Client unit tests + e2e test against a locally running server

---

## Implementation philosophy

- **Small pieces.** Implement one logical unit at a time (one endpoint, one worker behaviour, one DB operation). Do not combine multiple features in a single step.
- **Small files.** Split code into focused modules. No file should exceed ~200 lines. If it grows beyond that, split it before continuing.
- **No speculative code.** Only implement what the current task requires. No "we might need this later" abstractions.

## Project structure

```
ollama-queue/
├── server/
│   ├── main.py          # FastAPI app entry point, mounts routers
│   ├── config.py        # Settings loaded from env / .env
│   ├── models.py        # Pydantic request/response models
│   ├── database.py      # SQLite connection and schema setup
│   ├── queue.py         # Job CRUD operations
│   ├── worker.py        # Background worker: drain queue, call Ollama
│   └── wol.py           # Wake-on-LAN magic packet logic
├── client/
│   ├── ollama_queue/
│   │   ├── __init__.py
│   │   └── client.py    # OllamaQueueClient — blocking generate()
│   └── tests/
│       └── ...
├── tests/
│   ├── unit/            # Fast, no I/O
│   └── e2e/             # Full stack with a real SQLite DB and mocked Ollama
├── .env.example
├── CLAUDE.md
└── README.md
```

## Test-driven development

- **Write the test first**, then the implementation.
- Every public function and endpoint must have at least one test before the PR is considered done.
- Unit tests live in `tests/unit/` and must not touch the filesystem, network, or database.
- E2E tests live in `tests/e2e/` and spin up the full FastAPI app with a temporary SQLite database. Ollama is mocked at the HTTP level (e.g. `respx` or `responses`).
- Run tests with `pytest` before reporting a task as complete.

## Python environment

- All Python code must run inside a virtual environment — never use the system Python.
- Create the virtual environment with `python -m venv .venv` in the project root.
- Activate with `source .venv/bin/activate` before running any command.
- Install project and dev dependencies with `pip install -e ".[dev]"`.
- Never install packages globally; all dependencies go into `.venv/`.
- `.venv/` must be listed in `.gitignore`.
- Before running `pytest`, `ruff`, or the server, always verify the venv is active.

## Code quality

- **Docstrings on every public function and class.** One-line summary + param/return description where non-obvious. No novel-length blocks.
- **Type hints everywhere** — function signatures, local variables where the type is not obvious.
- **No dead code.** Remove unused imports, variables, and functions immediately.
- **No print statements** — use Python `logging` everywhere.
- **Logging levels:** `DEBUG` for internal state, `INFO` for job lifecycle events (queued, processing, completed, failed), `WARNING` for retries, `ERROR` for unrecoverable failures.
- **Log format:** timestamp + level + module + message. Configured once in `main.py`, inherited by all modules.
- **Every job state transition must be logged** at `INFO` level with the `job_id`.
- Linting: `ruff check .` must pass with zero warnings.
- Formatting: `ruff format .` (or `black`) applied before every commit.

## Protected files and dependencies

- **`README.md` and `CLAUDE.md` are frozen** — do not modify either file without explicit user approval. If a change seems needed, propose it and wait for a yes before touching the file.
- **No new dependencies without approval** — before adding any package to `pyproject.toml`, state what it is, why it is needed, and what the alternative would be. Wait for approval before installing or importing it.
- **Prefer stdlib over third-party** — if Python's standard library can do the job, use it.

## Commit discipline

- One logical change per commit.
- Commit message: imperative mood, max 72 chars, e.g. `Add POST /api/queue endpoint`.
- Do not commit `.env` files or secrets.

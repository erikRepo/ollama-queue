# Changelog

## [1.3.0] - 2026-05-14

### Added
- `client/ollama_queue/client.py`: `OllamaQueueClient` with a blocking `generate()` method
- Webhook-based return channel: `generate()` binds a temporary `HTTPServer` on a random local port, passes it as `callback_url`, and blocks with `threading.Event.wait(timeout)` until the server pushes the result back — no polling loop
- Local IP auto-detection via UDP connect trick so the callback URL is reachable from the server
- `client/pyproject.toml`: standalone packaging as `ollama-queue-client` with zero external dependencies (stdlib only)

## [1.2.0] - 2026-05-14

### Added
- Webhook delivery: when a job completes and `callback_url` is set, `worker.py` sends `POST callback_url` with the full `JobResponse` JSON body and marks the job `closed`; retries up to 3 times on transient HTTP errors (5xx / network); permanent errors (4xx) are abandoned and the job stays `ready` for polling
- `_deliver_webhook` and `_post_webhook_sync` in `server/worker.py`
- Unit tests: `TestDeliverWebhook` (success→closed, permanent 4xx stops retrying, transient retried until success, all retries exhausted→ready) and `TestPostWebhookSync` (2xx→True, 5xx→False, 4xx→None, network→False)
- E2E tests: webhook delivered and job closed, webhook failure leaves job ready for polling

## [1.1.0] - 2026-05-14

### Added
- `tests/e2e/test_full_flow.py`: 6 end-to-end tests that spin up the full FastAPI app with a real temporary SQLite database and mock Ollama at the HTTP layer (`urllib.request.urlopen`); covers low-priority batch flow, high-priority immediate wakeup, `ready→closed` status transition, multiple concurrent jobs, transient failure + retry, and permanent failure after max retries

## [1.0.0] - 2026-05-14

### Breaking Changes
- `JobRequest`: `prompt: str` replaced by `messages: list[Message]` (must contain at least one message); also added `format: str | None` and `callback_url: str | None`
- `JobResponse`: `prompt` removed; `messages`, `format`, `callback_url` added
- `JobStatus.COMPLETED` removed; replaced by `READY` (result stored, not yet delivered) and `CLOSED` (client received result)
- `GET /api/status/{id}`: when job is `READY`, returns it with `status="ready"` and atomically transitions DB record to `CLOSED`; subsequent polls return `status="closed"` with `response` still present
- Worker now calls `POST /api/chat` (not `/api/generate`); response parsed from `data["message"]["content"]`

### Added
- `Message` Pydantic model (`role`, `content`) in `server/models.py`
- DB migration v3: recreates `jobs` table replacing `prompt TEXT` with `messages TEXT` (JSON array), `format TEXT`, `callback_url TEXT`; migrates existing rows by wrapping `prompt` as `[{"role": "user", "content": prompt}]`
- `ollama_concurrency` setting (default 1, validated ≥ 1); `asyncio.Semaphore` enforcement planned for later
- New unit tests: `Message` model, empty-messages validation, `READY`/`CLOSED` statuses, `format`/`callback_url` round-trip, `/api/chat` payload shape, `format` included/omitted correctly, v3 migration, `ready→closed` GET transition

### Changed
- Worker sets `READY` (was `COMPLETED`) after successful Ollama call
- `README.md`: request body updated to `messages` format, response body to full job object, HTTP 202 → 201, lifecycle table updated, "SQLite (via SQLAlchemy)" → "SQLite (stdlib `sqlite3`)", `OLLAMA_CONCURRENCY` added to config reference, client `generate()` docstring updated

## [0.11.0] - 2026-05-14

### Changed
- `server/worker.py` rewritten with README-correct logic: `run_worker` now accepts an `asyncio.Event` and wakes immediately on high-priority jobs, falling back to the `WORKER_BATCH_INTERVAL` timer for low-priority batches
- WoL is sent once per batch (in `_drain`) rather than per job; after sending, `_wait_for_ollama` polls `GET /api/tags` with exponential backoff (2 s → 4 s → 8 s …) up to `WORKER_WOL_TIMEOUT`; if Ollama does not respond, `_apply_wol_failure` increments `retry_count` for all pending jobs (marking `failed` at `worker_max_retries`)
- `server/main.py`: creates `asyncio.Event` in lifespan, stores in `app.state`, passes to `run_worker`
- `server/router.py`: `POST /api/queue` is now async and sets the event when a `high`-priority job is enqueued

### Added
- `_check_ollama_sync`: health-poll helper (`GET /api/tags`)
- 23 unit tests covering `TestRunWorker` (event trigger, batch timer, cancellation), `TestWaitForOllama` (success, timeout, backoff), `TestDrain` (no-mac, WoL paths, timeout path), `TestApplyWolFailure` (pending/failed transitions)

## [0.10.0] - 2026-05-14

### Changed
- Renamed `WORKER_POLL_INTERVAL` → `WORKER_BATCH_INTERVAL` (low-priority batch window, seconds); updated `Settings` field, `.env.example`, worker, and all tests

### Added
- `WORKER_WOL_TIMEOUT` setting (max seconds to wait for Ollama after WoL, default 300); validated >= 0
- README ⚙️ Configuration section aligned to actual env var names (`WOL_MAC_ADDRESS`, `OLLAMA_HOST`, `WORKER_BATCH_INTERVAL`); removed stale `SERVER_IP`, `SERVER_MAC_ADDRESS`, `STORAGE_TYPE`, `CRON_INTERVAL`

## [0.9.0] - 2026-05-14

### Added
- `JobPriority` enum (`high`/`low`) in `server/models.py`
- `priority` field on `JobRequest` (default `low`) and `JobResponse`
- DB migration v2: `ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT 'low'` with index
- `queue.insert()` stores priority; `queue.list_pending()` orders high-priority jobs first, then by `created_at ASC`
- New unit tests: priority stored on insert, high/low ordering in `list_pending`, endpoint tests for priority field, invalid priority rejected with 422

## [0.8.0] - 2026-05-14

### Added
- `server/wol.py`: `build_magic_packet(mac)` — constructs a 102-byte WoL magic packet from a colon- or dash-separated MAC address; `send_wol(mac, broadcast, port)` — sends the packet via UDP broadcast, closing the socket in all cases
- `tests/unit/test_wol.py`: 11 unit tests covering packet structure, MAC format variants, invalid MAC rejection, socket options, target address, and socket cleanup on both success and error

## [0.7.0] - 2026-05-14

### Added
- `server/router.py`: `GET /api/status/{job_id}` endpoint — returns `JobResponse` with HTTP 200 if found, HTTP 404 with detail message if not
- `tests/unit/test_get_status.py`: 4 unit tests covering 200 response shape, field correctness, and 404 for unknown ID; uses in-memory SQLite via dependency override

## [0.6.0] - 2026-05-14

### Added
- `server/main.py`: FastAPI app entry point; configures logging, runs `init_db` in the lifespan, mounts router at `/api`
- `server/router.py`: `POST /api/queue` endpoint — validates request body via `JobRequest`, inserts a job, returns `JobResponse` with HTTP 201
- `server/database.py`: `get_db` FastAPI dependency (yields a per-request `sqlite3.Connection`); added `check_same_thread=False` to `get_connection` for threadpool compatibility
- `pyproject.toml`: added `fastapi>=0.110`, `uvicorn[standard]>=0.29` runtime deps; `httpx>=0.27` dev dep
- `tests/unit/test_post_queue.py`: 10 unit tests covering 201 response shape, field defaults, and 422 validation for blank/missing fields; uses in-memory SQLite via dependency override

## [0.5.0] - 2026-05-14

### Added
- `server/queue.py`: Job CRUD — `insert`, `get_by_id`, `list_pending`, `update_status`; all operations take a `sqlite3.Connection` directly and log every state transition at `INFO` level
- `tests/unit/test_queue.py`: 22 unit tests covering all four functions using in-memory SQLite
- `CONTRIBUTING.md`: developer setup guide (venv, install, running tests, ruff, config reference)

## [0.4.0] - 2026-05-14

### Added
- `server/models.py`: `JobStatus(StrEnum)` with four states (`pending`, `processing`, `completed`, `failed`); `JobRequest` Pydantic model (model + prompt, blank-rejection validation); `JobResponse` Pydantic model matching the full `jobs` table schema
- `pyproject.toml`: added `pydantic>=2` runtime dependency
- `tests/unit/test_models.py`: 13 unit tests covering enum values, string coercion, required fields, blank/whitespace rejection, and valid/invalid response construction

## [0.3.0] - 2026-05-14

### Added
- `server/database.py`: SQLite connection management (`get_connection`), URL parsing (`get_db_path`), and startup migrations (`init_db`) using `PRAGMA user_version` as version tracker; initial schema creates `jobs` table with status index
- `tests/unit/test_database.py`: 12 unit tests covering URL parsing, schema creation, column layout, index presence, column defaults, and idempotent migration runs

## [0.2.0] - 2026-05-14

### Added
- `server/config.py`: immutable `Settings` dataclass loaded from env variables and an optional `.env` file, with defaults and validation (port range, non-negative timeouts and retries)
- `tests/unit/test_config.py`: 25 unit tests covering defaults, env overrides, `.env` file loading, and validation errors
- `.env.example`: all supported settings documented with defaults

## [0.1.0] - 2026-05-14

### Added
- Project scaffolding: `pyproject.toml` (version 0.1.0), `ruff` config, `.env.example`, directory skeleton

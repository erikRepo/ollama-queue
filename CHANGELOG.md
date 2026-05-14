# Changelog

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

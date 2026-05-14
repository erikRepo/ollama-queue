# Changelog

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

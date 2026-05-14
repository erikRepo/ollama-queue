"""SQLite connection management, schema creation, and startup migrations."""

import logging
import sqlite3
from collections.abc import Generator
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_VERSION: int = 3


def get_db_path(database_url: str) -> Path:
    """Extract the filesystem path from a ``sqlite:///`` URL.

    Raises ValueError if the URL does not start with ``sqlite:///``.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"Unsupported database URL: {database_url!r}")
    return Path(database_url[len(prefix) :])


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL journal mode and Row factory."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create the database file (and parent dirs) then run pending migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations using ``PRAGMA user_version`` as version tracker."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    logger.debug("Database schema version on open: %d", version)

    if version < 1:
        _v1(conn)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        logger.info("Applied database migration to version 1")

    if version < 2:
        _v2(conn)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        logger.info("Applied database migration to version 2")

    if version < 3:
        _v3(conn)
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        logger.info("Applied database migration to version 3")


def _v1(conn: sqlite3.Connection) -> None:
    """Initial schema: jobs table and status index."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            status      TEXT NOT NULL DEFAULT 'pending',
            model       TEXT NOT NULL,
            prompt      TEXT NOT NULL,
            response    TEXT,
            error       TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")


def _v2(conn: sqlite3.Connection) -> None:
    """Migration v2: add priority column (default 'low') to jobs table."""
    conn.execute("ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT 'low'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs (priority)")


def _v3(conn: sqlite3.Connection) -> None:
    """Migration v3: replace prompt with messages JSON; add format and callback_url."""
    conn.execute(
        """
        CREATE TABLE jobs_new (
            id           TEXT PRIMARY KEY,
            status       TEXT NOT NULL DEFAULT 'pending',
            priority     TEXT NOT NULL DEFAULT 'low',
            model        TEXT NOT NULL,
            messages     TEXT NOT NULL DEFAULT '[]',
            format       TEXT,
            callback_url TEXT,
            response     TEXT,
            error        TEXT,
            retry_count  INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO jobs_new
            SELECT id, status, priority, model,
                   json_array(json_object('role', 'user', 'content', prompt)),
                   NULL, NULL, response, error, retry_count, created_at, updated_at
            FROM jobs
        """
    )
    conn.execute("DROP TABLE jobs")
    conn.execute("ALTER TABLE jobs_new RENAME TO jobs")
    conn.execute("CREATE INDEX idx_jobs_status   ON jobs (status)")
    conn.execute("CREATE INDEX idx_jobs_priority ON jobs (priority)")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency: open a per-request SQLite connection, close on exit."""
    from server.config import load_settings  # local import avoids circular reference

    settings = load_settings()
    conn = get_connection(get_db_path(settings.database_url))
    try:
        yield conn
    finally:
        conn.close()

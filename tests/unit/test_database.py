"""Unit tests for server.database — all use in-memory SQLite."""

import sqlite3
from pathlib import Path

import pytest

from server.database import CURRENT_VERSION, _migrate, get_db_path

# ---------------------------------------------------------------------------
# get_db_path
# ---------------------------------------------------------------------------


class TestGetDbPath:
    def test_relative_path(self) -> None:
        assert get_db_path("sqlite:///./data.db") == Path("./data.db")

    def test_absolute_path(self) -> None:
        assert get_db_path("sqlite:////var/db/data.db") == Path("/var/db/data.db")

    def test_default_url(self) -> None:
        assert get_db_path("sqlite:///./ollama_queue.db") == Path("./ollama_queue.db")

    def test_rejects_non_sqlite(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            get_db_path("postgres://localhost/db")

    def test_rejects_two_slash_url(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            get_db_path("sqlite://localhost/db")


# ---------------------------------------------------------------------------
# _migrate helpers
# ---------------------------------------------------------------------------


def _mem() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class TestMigrate:
    def test_creates_jobs_table(self) -> None:
        conn = _mem()
        _migrate(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_sets_user_version(self) -> None:
        conn = _mem()
        _migrate(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_VERSION
        conn.close()

    def test_is_idempotent(self) -> None:
        conn = _mem()
        _migrate(conn)
        _migrate(conn)  # second call must not raise
        conn.close()

    def test_jobs_table_columns(self) -> None:
        expected = {
            "id",
            "status",
            "model",
            "prompt",
            "response",
            "error",
            "retry_count",
            "created_at",
            "updated_at",
        }
        conn = _mem()
        _migrate(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        assert cols == expected
        conn.close()

    def test_status_index_exists(self) -> None:
        conn = _mem()
        _migrate(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='index' AND name='idx_jobs_status'"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_status_default_is_pending(self) -> None:
        conn = _mem()
        _migrate(conn)
        conn.execute(
            "INSERT INTO jobs (id, model, prompt, created_at, updated_at)"
            " VALUES ('1', 'llama3', 'hello', '2026-01-01', '2026-01-01')"
        )
        row = conn.execute("SELECT status FROM jobs WHERE id='1'").fetchone()
        assert row["status"] == "pending"
        conn.close()

    def test_retry_count_default_is_zero(self) -> None:
        conn = _mem()
        _migrate(conn)
        conn.execute(
            "INSERT INTO jobs (id, model, prompt, created_at, updated_at)"
            " VALUES ('2', 'llama3', 'hello', '2026-01-01', '2026-01-01')"
        )
        row = conn.execute("SELECT retry_count FROM jobs WHERE id='2'").fetchone()
        assert row["retry_count"] == 0
        conn.close()

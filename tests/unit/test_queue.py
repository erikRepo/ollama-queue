"""Unit tests for server.queue — all use in-memory SQLite."""

import sqlite3

from server.database import _migrate
from server.models import JobRequest, JobResponse, JobStatus
from server.queue import get_by_id, insert, list_pending, update_status


def _mem() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


_REQUEST = JobRequest(model="llama3", prompt="hello")


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------


class TestInsert:
    def test_returns_job_response(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert isinstance(job, JobResponse)
        conn.close()

    def test_status_is_pending(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.status == JobStatus.PENDING
        conn.close()

    def test_model_and_prompt_match_request(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.model == _REQUEST.model
        assert job.prompt == _REQUEST.prompt
        conn.close()

    def test_response_and_error_are_none(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.response is None
        assert job.error is None
        conn.close()

    def test_retry_count_is_zero(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.retry_count == 0
        conn.close()

    def test_id_is_unique(self) -> None:
        conn = _mem()
        a = insert(conn, _REQUEST)
        b = insert(conn, _REQUEST)
        assert a.id != b.id
        conn.close()

    def test_persisted_to_db(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job.id,)).fetchone()
        assert row is not None
        conn.close()


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    def test_returns_job_response(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        fetched = get_by_id(conn, job.id)
        assert isinstance(fetched, JobResponse)
        conn.close()

    def test_data_matches_insert(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        fetched = get_by_id(conn, job.id)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.model == job.model
        assert fetched.prompt == job.prompt
        conn.close()

    def test_returns_none_for_unknown_id(self) -> None:
        conn = _mem()
        assert get_by_id(conn, "nonexistent") is None
        conn.close()


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


class TestListPending:
    def test_returns_list(self) -> None:
        conn = _mem()
        result = list_pending(conn)
        assert isinstance(result, list)
        conn.close()

    def test_empty_when_no_jobs(self) -> None:
        conn = _mem()
        assert list_pending(conn) == []
        conn.close()

    def test_includes_pending_jobs(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        pending = list_pending(conn)
        assert any(j.id == job.id for j in pending)
        conn.close()

    def test_excludes_non_pending_jobs(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        update_status(conn, job.id, JobStatus.PROCESSING)
        assert list_pending(conn) == []
        conn.close()

    def test_ordered_by_created_at(self) -> None:
        conn = _mem()
        a = insert(conn, _REQUEST)
        b = insert(conn, _REQUEST)
        pending = list_pending(conn)
        ids = [j.id for j in pending]
        assert ids.index(a.id) < ids.index(b.id)
        conn.close()


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_returns_updated_job(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        updated = update_status(conn, job.id, JobStatus.PROCESSING)
        assert updated is not None
        assert updated.status == JobStatus.PROCESSING
        conn.close()

    def test_sets_response(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        updated = update_status(conn, job.id, JobStatus.COMPLETED, response="done")
        assert updated is not None
        assert updated.response == "done"
        conn.close()

    def test_sets_error(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        updated = update_status(conn, job.id, JobStatus.FAILED, error="oops")
        assert updated is not None
        assert updated.error == "oops"
        conn.close()

    def test_increments_retry_count(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        updated = update_status(conn, job.id, JobStatus.PENDING, retry_count=1)
        assert updated is not None
        assert updated.retry_count == 1
        conn.close()

    def test_updates_updated_at(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        updated = update_status(conn, job.id, JobStatus.PROCESSING)
        assert updated is not None
        assert updated.updated_at >= job.updated_at
        conn.close()

    def test_returns_none_for_unknown_id(self) -> None:
        conn = _mem()
        result = update_status(conn, "nonexistent", JobStatus.PROCESSING)
        assert result is None
        conn.close()

    def test_persisted_to_db(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        update_status(conn, job.id, JobStatus.COMPLETED, response="ok")
        fetched = get_by_id(conn, job.id)
        assert fetched is not None
        assert fetched.status == JobStatus.COMPLETED
        assert fetched.response == "ok"
        conn.close()

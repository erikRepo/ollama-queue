"""Unit tests for server.queue — all use in-memory SQLite."""

import sqlite3

from server.database import _migrate
from server.models import JobPriority, JobRequest, JobResponse, JobStatus, Message
from server.queue import get_by_id, insert, list_pending, update_status


def _mem() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


def _request(**overrides) -> JobRequest:
    base: dict = dict(
        model="llama3",
        messages=[{"role": "user", "content": "hello"}],
    )
    base.update(overrides)
    return JobRequest(**base)


_REQUEST = _request()
_HIGH = _request(priority=JobPriority.HIGH)
_LOW = _request(priority=JobPriority.LOW)


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

    def test_model_matches_request(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.model == _REQUEST.model
        conn.close()

    def test_messages_serialized_and_deserialized(self) -> None:
        conn = _mem()
        req = _request(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
        )
        job = insert(conn, req)
        assert len(job.messages) == 2
        assert isinstance(job.messages[0], Message)
        assert job.messages[0].role == "system"
        assert job.messages[1].content == "hi"
        conn.close()

    def test_format_stored(self) -> None:
        conn = _mem()
        req = _request(format="json")
        job = insert(conn, req)
        assert job.format == "json"
        conn.close()

    def test_callback_url_stored(self) -> None:
        conn = _mem()
        req = _request(callback_url="http://cb.example.com")
        job = insert(conn, req)
        assert job.callback_url == "http://cb.example.com"
        conn.close()

    def test_format_none_by_default(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.format is None
        conn.close()

    def test_callback_url_none_by_default(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.callback_url is None
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

    def test_default_priority_is_low(self) -> None:
        conn = _mem()
        job = insert(conn, _REQUEST)
        assert job.priority == JobPriority.LOW
        conn.close()

    def test_high_priority_stored(self) -> None:
        conn = _mem()
        job = insert(conn, _HIGH)
        assert job.priority == JobPriority.HIGH
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
        assert fetched.messages[0].content == job.messages[0].content
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

    def test_high_priority_before_low(self) -> None:
        conn = _mem()
        low = insert(conn, _LOW)
        high = insert(conn, _HIGH)
        pending = list_pending(conn)
        ids = [j.id for j in pending]
        assert ids.index(high.id) < ids.index(low.id)
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
        updated = update_status(conn, job.id, JobStatus.READY, response="done")
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
        update_status(conn, job.id, JobStatus.READY, response="ok")
        fetched = get_by_id(conn, job.id)
        assert fetched is not None
        assert fetched.status == JobStatus.READY
        assert fetched.response == "ok"
        conn.close()

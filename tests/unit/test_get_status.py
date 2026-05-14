"""Unit tests for GET /api/status/:id."""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.database import _migrate, get_db
from server.main import app
from server.models import JobRequest, JobStatus
from server.queue import insert, update_status

_MESSAGES = [{"role": "user", "content": "hi"}]


def _mem() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


@pytest.fixture()
def client_conn():
    """Yield (TestClient, conn) with an in-memory DB injected."""
    conn = _mem()

    def _override():
        yield conn

    app.dependency_overrides[get_db] = _override
    with patch("server.main.init_db"):
        with TestClient(app) as c:
            yield c, conn
    app.dependency_overrides.clear()
    conn.close()


@pytest.fixture()
def client(client_conn):
    """TestClient only (no conn access needed for most tests)."""
    c, _ = client_conn
    return c


class TestGetStatus:
    def test_returns_200_for_existing_job(self, client: TestClient) -> None:
        created = client.post(
            "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
        )
        job_id = created.json()["id"]
        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200

    def test_returns_job_fields(self, client: TestClient) -> None:
        created = client.post(
            "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
        )
        job_id = created.json()["id"]
        body = client.get(f"/api/status/{job_id}").json()
        assert body["id"] == job_id
        assert body["model"] == "llama3"
        assert body["messages"] == _MESSAGES
        assert body["status"] == "pending"
        assert body["priority"] == "low"
        assert body["retry_count"] == 0
        assert body["response"] is None
        assert body["error"] is None

    def test_returns_404_for_unknown_id(self, client: TestClient) -> None:
        resp = client.get("/api/status/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_404_body_has_detail(self, client: TestClient) -> None:
        resp = client.get("/api/status/00000000-0000-0000-0000-000000000000")
        assert "detail" in resp.json()

    def test_ready_job_returns_ready_status(self, client_conn) -> None:
        """GET on a READY job returns status 'ready' to the client."""
        c, conn = client_conn
        req = JobRequest(model="llama3", messages=_MESSAGES)
        job = insert(conn, req)
        update_status(conn, job.id, JobStatus.READY, response="AI response")

        body = c.get(f"/api/status/{job.id}").json()
        assert body["status"] == "ready"
        assert body["response"] == "AI response"

    def test_ready_job_transitions_to_closed_in_db(self, client_conn) -> None:
        """After GET on a READY job, the DB record is updated to 'closed'."""
        c, conn = client_conn
        req = JobRequest(model="llama3", messages=_MESSAGES)
        job = insert(conn, req)
        update_status(conn, job.id, JobStatus.READY, response="AI response")

        c.get(f"/api/status/{job.id}")

        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job.id,)).fetchone()
        assert row["status"] == "closed"

    def test_closed_job_still_returns_response(self, client_conn) -> None:
        """Subsequent GETs on a CLOSED job still return the response."""
        c, conn = client_conn
        req = JobRequest(model="llama3", messages=_MESSAGES)
        job = insert(conn, req)
        update_status(conn, job.id, JobStatus.READY, response="AI response")

        c.get(f"/api/status/{job.id}")  # transitions to closed
        body = c.get(f"/api/status/{job.id}").json()
        assert body["status"] == "closed"
        assert body["response"] == "AI response"

"""Unit tests for GET /api/status/:id."""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.database import _migrate, get_db
from server.main import app


def _mem() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


@pytest.fixture()
def client() -> TestClient:
    """TestClient with an in-memory DB injected and lifespan init_db skipped."""
    conn = _mem()

    def _override():
        yield conn

    app.dependency_overrides[get_db] = _override
    with patch("server.main.init_db"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()
    conn.close()


class TestGetStatus:
    def test_returns_200_for_existing_job(self, client: TestClient) -> None:
        created = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        job_id = created.json()["id"]
        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200

    def test_returns_job_fields(self, client: TestClient) -> None:
        created = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        job_id = created.json()["id"]
        body = client.get(f"/api/status/{job_id}").json()
        assert body["id"] == job_id
        assert body["model"] == "llama3"
        assert body["prompt"] == "hi"
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

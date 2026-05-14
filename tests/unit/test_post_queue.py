"""Unit tests for POST /api/queue."""

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


class TestPostQueue:
    def test_returns_201(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        assert resp.status_code == 201

    def test_response_has_pending_status(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        assert resp.json()["status"] == "pending"

    def test_response_echoes_model_and_prompt(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        body = resp.json()
        assert body["model"] == "llama3"
        assert body["prompt"] == "hi"

    def test_response_has_id_and_timestamps(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        body = resp.json()
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_response_defaults(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        body = resp.json()
        assert body["retry_count"] == 0
        assert body["response"] is None
        assert body["error"] is None
        assert body["priority"] == "low"

    def test_high_priority_accepted(self, client: TestClient) -> None:
        resp = client.post(
            "/api/queue", json={"model": "llama3", "prompt": "hi", "priority": "high"}
        )
        assert resp.status_code == 201
        assert resp.json()["priority"] == "high"

    def test_invalid_priority_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/queue", json={"model": "llama3", "prompt": "hi", "priority": "urgent"}
        )
        assert resp.status_code == 422

    def test_blank_model_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "  ", "prompt": "hi"})
        assert resp.status_code == 422

    def test_blank_prompt_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3", "prompt": ""})
        assert resp.status_code == 422

    def test_missing_model_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"prompt": "hi"})
        assert resp.status_code == 422

    def test_missing_prompt_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/queue", json={"model": "llama3"})
        assert resp.status_code == 422

    def test_each_post_creates_unique_id(self, client: TestClient) -> None:
        a = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        b = client.post("/api/queue", json={"model": "llama3", "prompt": "hi"})
        assert a.json()["id"] != b.json()["id"]

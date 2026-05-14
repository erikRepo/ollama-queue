"""
E2E tests for the complete server flow.

Infrastructure
--------------
Each test starts the full FastAPI app via its real lifespan hook (DB init +
background worker task). A fresh SQLite database is created in pytest's
tmp_path for every test. Ollama HTTP calls are intercepted by patching
``urllib.request.urlopen`` at the module level; because the worker runs in the
event loop thread (separate from the test thread), the patch is visible to it
as long as it is active before the job is enqueued.

WoL is disabled in all tests (``wol_mac_address=""``). The WoL + Ollama
health-check path is covered exhaustively in ``tests/unit/test_worker.py``.

Scenarios covered
-----------------
- Low-priority batch flow: POST → pending → worker picks up on timer → ready
- High-priority wakeup: POST high → asyncio.Event set → worker wakes immediately
- READY → CLOSED transition: first GET returns ready; subsequent GET returns
  closed (response preserved)
- Multiple jobs: two jobs enqueued in the same batch, both reach ready
- Transient retry: Ollama fails once; job is retried and reaches ready on the
  second attempt (retry_count verified)
- Permanent failure: Ollama always fails; job reaches failed after
  worker_max_retries (3) attempts
"""

import json
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server.config import Settings
from server.database import get_connection, get_db

_MESSAGES = [{"role": "user", "content": "hello"}]


def _settings(db_path: Path, **overrides) -> Settings:
    """Build a Settings instance pointing to *db_path* with fast worker timings."""
    base = dict(
        host="0.0.0.0",
        port=8080,
        database_url=f"sqlite:///{db_path}",
        ollama_host="http://ollama-mock:11434",
        ollama_timeout=5,
        ollama_concurrency=1,
        worker_batch_interval=0.05,
        worker_wol_timeout=0,
        worker_max_retries=3,
        worker_retry_delay=0.0,
        wol_mac_address="",
        wol_broadcast="255.255.255.255",
        wol_port=9,
    )
    base.update(overrides)
    return Settings(**base)


def _ok_mock(text: str = "AI answer") -> MagicMock:
    """Return a mock that urlopen can return for a successful /api/chat call."""
    body = json.dumps({"message": {"role": "assistant", "content": text}}).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = 200
    resp.__enter__ = lambda s: resp
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _poll(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    """Poll /api/status/:id until status reaches a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/status/{job_id}").json()
        if data["status"] in ("ready", "closed", "failed"):
            return data
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id!r} did not reach terminal state within {timeout}s")


@pytest.fixture()
def app_client(tmp_path: Path):
    """TestClient backed by a temp SQLite DB with the real worker running."""
    from server.main import app

    db_file = tmp_path / "e2e.db"
    settings = _settings(db_file)

    def _db():
        conn = get_connection(db_file)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _db
    with patch("server.main._settings", settings):
        with TestClient(app) as client:
            yield client
    app.dependency_overrides.clear()


class TestFullFlow:
    def test_low_priority_job_completes(self, app_client: TestClient) -> None:
        """Low-priority job is picked up on the batch timer and reaches READY."""
        with patch("urllib.request.urlopen", return_value=_ok_mock("the answer")):
            resp = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            )
            assert resp.status_code == 201
            assert resp.json()["status"] == "pending"

            data = _poll(app_client, resp.json()["id"])

        assert data["status"] == "ready"
        assert data["response"] == "the answer"

    def test_high_priority_job_completes(self, app_client: TestClient) -> None:
        """High-priority job sets the asyncio.Event and reaches READY."""
        with patch("urllib.request.urlopen", return_value=_ok_mock("urgent reply")):
            resp = app_client.post(
                "/api/queue",
                json={"model": "llama3", "messages": _MESSAGES, "priority": "high"},
            )
            assert resp.status_code == 201

            data = _poll(app_client, resp.json()["id"])

        assert data["status"] == "ready"
        assert data["response"] == "urgent reply"

    def test_ready_then_closed_on_second_poll(self, app_client: TestClient) -> None:
        """First GET when READY returns ready; second GET returns closed."""
        with patch("urllib.request.urlopen", return_value=_ok_mock()):
            resp = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            )
            job_id = resp.json()["id"]
            first = _poll(app_client, job_id)

        second = app_client.get(f"/api/status/{job_id}").json()

        assert first["status"] == "ready"
        assert second["status"] == "closed"
        assert second["response"] == first["response"]

    def test_multiple_jobs_all_complete(self, app_client: TestClient) -> None:
        """Two queued jobs are both processed and reach READY."""
        with patch("urllib.request.urlopen", return_value=_ok_mock()):
            id_a = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            ).json()["id"]
            id_b = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            ).json()["id"]

            data_a = _poll(app_client, id_a)
            data_b = _poll(app_client, id_b)

        assert data_a["status"] == "ready"
        assert data_b["status"] == "ready"

    def test_job_retries_on_transient_failure(self, app_client: TestClient) -> None:
        """A job that fails once is retried and eventually reaches READY."""
        call_count = [0]

        def _side_effect(req, timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.URLError("connection refused")
            return _ok_mock("retry succeeded")

        with patch("urllib.request.urlopen", side_effect=_side_effect):
            resp = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            )
            job_id = resp.json()["id"]
            data = _poll(app_client, job_id)

        assert data["status"] == "ready"
        assert data["response"] == "retry succeeded"
        assert call_count[0] == 2

    def test_job_fails_permanently_after_max_retries(
        self, app_client: TestClient
    ) -> None:
        """A job that always fails reaches FAILED after worker_max_retries attempts."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("always fails"),
        ):
            resp = app_client.post(
                "/api/queue", json={"model": "llama3", "messages": _MESSAGES}
            )
            job_id = resp.json()["id"]
            data = _poll(app_client, job_id, timeout=10.0)

        assert data["status"] == "failed"

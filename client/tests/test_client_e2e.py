"""E2E test: OllamaQueueClient against a real running ollama-queue server.

Infrastructure
--------------
The server is started via ``uvicorn.Server`` in a daemon thread, binding to a
random localhost port. Ollama HTTP calls are intercepted by patching
``urllib.request.urlopen`` with a smart side-effect that mocks only requests
to the configured Ollama host and passes all other calls (server API calls,
webhook delivery) through to the real implementation.

WoL is disabled (``wol_mac_address=""``). Worker timings are set as fast as
possible so tests finish quickly.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import uvicorn
from ollama_queue import OllamaQueueClient

from server.config import Settings
from server.database import get_connection, get_db

_MESSAGES = [{"role": "user", "content": "hello"}]
_OLLAMA_HOST = "ollama-mock-e2e"


def _settings(db_path: Path) -> Settings:
    """Build Settings pointing to *db_path* with fast worker timings."""
    return Settings(
        host="127.0.0.1",
        port=0,
        database_url=f"sqlite:///{db_path}",
        ollama_host=f"http://{_OLLAMA_HOST}:11434",
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


def _free_port() -> int:
    """Return a free local TCP port (released before the caller binds it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(base_url: str, timeout: float = 5.0) -> None:
    """Block until the server responds to a probe request or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/api/status/probe", timeout=0.5)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return  # Server is up and routing
        except Exception:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"Server at {base_url} did not become ready within {timeout}s")


def _ollama_ok_mock(text: str) -> MagicMock:
    """Return a context-manager mock for a successful Ollama /api/chat response."""
    body = json.dumps({"message": {"role": "assistant", "content": text}}).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = 200
    resp.__enter__ = lambda s: resp
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture()
def server_url(tmp_path: Path):
    """Start the full ollama-queue server on a random localhost port.

    Yields the base URL (``http://127.0.0.1:{port}``) and shuts the server
    down after the test completes.
    """
    from server.main import app

    db_file = tmp_path / "client_e2e.db"
    settings = _settings(db_file)
    port = _free_port()

    def _db():
        conn = get_connection(db_file)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _db

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)

    with patch("server.main._settings", settings):
        t.start()
        _wait_for_server(f"http://127.0.0.1:{port}")
        yield f"http://127.0.0.1:{port}"
        server.should_exit = True
        t.join(timeout=5)

    app.dependency_overrides.clear()


class TestClientE2E:
    def test_generate_returns_ollama_response(self, server_url: str) -> None:
        """Client blocks, server processes the job, webhook delivers the result."""
        original_urlopen = urllib.request.urlopen

        def _side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if _OLLAMA_HOST in url:
                return _ollama_ok_mock("e2e answer")
            return original_urlopen(req, timeout=timeout)

        client = OllamaQueueClient(server_url)
        with patch("urllib.request.urlopen", side_effect=_side_effect):
            result = client.generate(
                model="llama3",
                messages=_MESSAGES,
                priority="low",
                timeout=15.0,
            )

        assert result == "e2e answer"

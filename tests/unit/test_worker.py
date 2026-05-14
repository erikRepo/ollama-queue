"""Unit tests for worker.py."""

import asyncio
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from server import worker
from server.config import Settings
from server.models import JobResponse, JobStatus


def _settings(**overrides) -> Settings:
    base = dict(
        host="0.0.0.0",
        port=8080,
        database_url="sqlite:///./test.db",
        ollama_host="http://localhost:11434",
        ollama_timeout=30,
        worker_batch_interval=2.0,
        worker_wol_timeout=300,
        worker_max_retries=3,
        worker_retry_delay=0.0,
        wol_mac_address="",
        wol_broadcast="255.255.255.255",
        wol_port=9,
    )
    base.update(overrides)
    return Settings(**base)


def _job(**overrides) -> JobResponse:
    base = dict(
        id="test-job-1",
        status=JobStatus.PENDING,
        priority="low",
        model="llama3",
        prompt="Hello, world!",
        response=None,
        error=None,
        retry_count=0,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return JobResponse(**base)


class TestProcessJob:
    def test_success_completes_job(self) -> None:
        settings = _settings()
        conn = MagicMock()
        job = _job()

        ollama_mock = AsyncMock(return_value="AI response")
        with (
            patch("server.worker.queue.update_status") as mock_update,
            patch("server.worker._call_ollama", new=ollama_mock),
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        calls = mock_update.call_args_list
        assert calls[0] == call(conn, job.id, JobStatus.PROCESSING)
        assert calls[1] == call(
            conn, job.id, JobStatus.COMPLETED, response="AI response"
        )

    def test_failure_within_retries_requeues_with_incremented_count(self) -> None:
        settings = _settings(worker_max_retries=3)
        conn = MagicMock()
        job = _job(retry_count=0)

        ollama_mock = AsyncMock(side_effect=RuntimeError("timeout"))
        with (
            patch("server.worker.queue.update_status") as mock_update,
            patch("server.worker._call_ollama", new=ollama_mock),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        calls = mock_update.call_args_list
        assert calls[0] == call(conn, job.id, JobStatus.PROCESSING)
        assert calls[1].args[2] == JobStatus.PENDING
        assert calls[1].kwargs["retry_count"] == 1
        assert "error" in calls[1].kwargs

    def test_failure_at_max_retries_marks_failed(self) -> None:
        settings = _settings(worker_max_retries=3)
        conn = MagicMock()
        job = _job(retry_count=2)  # next failure is the 3rd attempt → permanent fail

        ollama_mock = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("server.worker.queue.update_status") as mock_update,
            patch("server.worker._call_ollama", new=ollama_mock),
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        calls = mock_update.call_args_list
        assert calls[0] == call(conn, job.id, JobStatus.PROCESSING)
        assert calls[1].args[2] == JobStatus.FAILED
        assert calls[1].kwargs["retry_count"] == 3

    def test_wol_sent_on_first_attempt(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job(retry_count=0)

        with (
            patch("server.worker.queue.update_status"),
            patch("server.worker._call_ollama", new=AsyncMock(return_value="ok")),
            patch("server.worker.send_wol") as mock_wol,
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        mock_wol.assert_called_once_with(
            "AA:BB:CC:DD:EE:FF", settings.wol_broadcast, settings.wol_port
        )

    def test_wol_not_sent_on_retry(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job(retry_count=1)

        with (
            patch("server.worker.queue.update_status"),
            patch("server.worker._call_ollama", new=AsyncMock(return_value="ok")),
            patch("server.worker.send_wol") as mock_wol,
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        mock_wol.assert_not_called()

    def test_wol_not_sent_when_no_mac_configured(self) -> None:
        settings = _settings(wol_mac_address="")
        conn = MagicMock()
        job = _job(retry_count=0)

        with (
            patch("server.worker.queue.update_status"),
            patch("server.worker._call_ollama", new=AsyncMock(return_value="ok")),
            patch("server.worker.send_wol") as mock_wol,
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        mock_wol.assert_not_called()

    def test_wol_failure_does_not_abort_job(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job(retry_count=0)

        with (
            patch("server.worker.queue.update_status") as mock_update,
            patch("server.worker._call_ollama", new=AsyncMock(return_value="ok")),
            patch("server.worker.send_wol", side_effect=OSError("network error")),
        ):
            asyncio.run(worker._process_job(settings, conn, job))

        # Job should still complete despite WoL failure
        last_call = mock_update.call_args_list[-1]
        assert last_call.args[2] == JobStatus.COMPLETED


class TestCallOllamaSync:
    def test_success_returns_response_text(self) -> None:
        settings = _settings()
        body = json.dumps({"response": "AI text here"}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = body

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_resp
            mock_open.return_value.__exit__.return_value = False

            result = worker._call_ollama_sync(settings, "llama3", "hello")

        assert result == "AI text here"

    def test_http_error_raises_runtime_error(self) -> None:
        settings = _settings()

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="http://x",
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=None,
            ),
        ):
            with pytest.raises(RuntimeError, match="Ollama HTTP 500"):
                worker._call_ollama_sync(settings, "llama3", "hello")

    def test_url_error_raises_runtime_error(self) -> None:
        settings = _settings()

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="Ollama unreachable"):
                worker._call_ollama_sync(settings, "llama3", "hello")

    def test_request_sends_correct_payload(self) -> None:
        settings = _settings(ollama_host="http://ollama:11434")
        body = json.dumps({"response": "ok"}).encode()

        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req)
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            worker._call_ollama_sync(settings, "llama3", "hi there")

        assert len(captured) == 1
        req = captured[0]
        assert req.full_url == "http://ollama:11434/api/generate"
        payload = json.loads(req.data.decode())
        assert payload == {"model": "llama3", "prompt": "hi there", "stream": False}

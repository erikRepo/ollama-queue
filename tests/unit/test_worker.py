"""Unit tests for worker.py."""

import asyncio
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from server import worker
from server.config import Settings
from server.models import JobPriority, JobResponse, JobStatus, Message


def _settings(**overrides) -> Settings:
    base = dict(
        host="0.0.0.0",
        port=8080,
        database_url="sqlite:///./test.db",
        ollama_host="http://localhost:11434",
        ollama_timeout=30,
        ollama_concurrency=1,
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
        priority=JobPriority.LOW,
        model="llama3",
        messages=[Message(role="user", content="Hello, world!")],
        format=None,
        callback_url=None,
        response=None,
        error=None,
        retry_count=0,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return JobResponse(**base)


class TestRunWorker:
    def test_high_priority_event_triggers_drain_immediately(self) -> None:
        """Pre-set event bypasses the batch-interval wait."""
        settings = _settings(worker_batch_interval=999.0)
        conn = MagicMock()
        drain_calls: list[int] = []

        async def fake_drain(s, c):
            drain_calls.append(1)
            raise asyncio.CancelledError()

        async def run():
            event = asyncio.Event()
            event.set()
            with patch("server.worker._drain", new=fake_drain):
                await worker.run_worker(settings, conn, event)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())

        assert len(drain_calls) == 1

    def test_batch_interval_triggers_drain(self) -> None:
        """Batch interval timeout fires drain without the event being set."""
        settings = _settings(worker_batch_interval=0.01)
        conn = MagicMock()
        drain_calls: list[int] = []

        async def fake_drain(s, c):
            drain_calls.append(1)
            raise asyncio.CancelledError()

        async def run():
            event = asyncio.Event()  # not set
            with patch("server.worker._drain", new=fake_drain):
                await worker.run_worker(settings, conn, event)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())

        assert len(drain_calls) == 1

    def test_event_is_cleared_after_trigger(self) -> None:
        """The high-priority event is cleared before _drain runs."""
        settings = _settings(worker_batch_interval=999.0)
        conn = MagicMock()
        event_state_during_drain: list[bool] = []

        async def fake_drain(s, c):
            event_state_during_drain.append(False)  # event should be cleared
            raise asyncio.CancelledError()

        async def run():
            event = asyncio.Event()
            event.set()
            with patch("server.worker._drain", new=fake_drain):
                await worker.run_worker(settings, conn, event)
            return event

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())

        assert len(event_state_during_drain) == 1

    def test_cancellation_stops_cleanly(self) -> None:
        """Cancelling the worker task raises CancelledError without side-effects."""
        settings = _settings(worker_batch_interval=999.0)
        conn = MagicMock()

        async def run():
            event = asyncio.Event()
            task = asyncio.create_task(worker.run_worker(settings, conn, event))
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())  # must not raise


class TestWaitForOllama:
    def test_returns_true_when_ollama_responds(self) -> None:
        settings = _settings(worker_wol_timeout=60)

        with (
            patch("server.worker._check_ollama_sync", return_value=True),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = asyncio.run(worker._wait_for_ollama(settings))

        assert result is True

    def test_returns_false_when_timeout_is_zero(self) -> None:
        """wol_timeout=0 means deadline is immediately past — loop never executes."""
        settings = _settings(worker_wol_timeout=0)

        check_patch = patch("server.worker._check_ollama_sync", return_value=False)
        with check_patch as mock_check:
            result = asyncio.run(worker._wait_for_ollama(settings))

        assert result is False
        mock_check.assert_not_called()

    def test_initial_sleep_is_two_seconds(self) -> None:
        """First sleep delay must be exactly 2 s (start of exponential backoff)."""
        settings = _settings(worker_wol_timeout=60)
        sleep_calls: list[float] = []

        async def mock_sleep(d: float) -> None:
            sleep_calls.append(d)

        with (
            patch("server.worker._check_ollama_sync", return_value=True),
            patch("asyncio.sleep", new=mock_sleep),
        ):
            asyncio.run(worker._wait_for_ollama(settings))

        assert sleep_calls[0] == 2.0

    def test_delay_doubles_on_each_retry(self) -> None:
        """Sleep delays follow the 2→4→8 exponential sequence."""
        settings = _settings(worker_wol_timeout=60)
        sleep_calls: list[float] = []
        check_count = [0]

        async def mock_sleep(d: float) -> None:
            sleep_calls.append(d)

        def mock_check(s):
            check_count[0] += 1
            return check_count[0] >= 3  # succeed on 3rd attempt

        with (
            patch("server.worker._check_ollama_sync", side_effect=mock_check),
            patch("asyncio.sleep", new=mock_sleep),
        ):
            result = asyncio.run(worker._wait_for_ollama(settings))

        assert result is True
        assert sleep_calls[:3] == [2.0, 4.0, 8.0]


class TestDrain:
    def test_no_pending_jobs_skips_wol_and_processing(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()

        with (
            patch("server.worker.queue.list_pending", return_value=[]),
            patch("server.worker.send_wol") as mock_wol,
            patch("server.worker._process_job", new=AsyncMock()) as mock_proc,
        ):
            asyncio.run(worker._drain(settings, conn))

        mock_wol.assert_not_called()
        mock_proc.assert_not_called()

    def test_processes_jobs_directly_when_no_mac(self) -> None:
        settings = _settings(wol_mac_address="")
        conn = MagicMock()
        job = _job()

        with (
            patch("server.worker.queue.list_pending", return_value=[job]),
            patch("server.worker.send_wol") as mock_wol,
            patch("server.worker._process_job", new=AsyncMock()) as mock_proc,
        ):
            asyncio.run(worker._drain(settings, conn))

        mock_wol.assert_not_called()
        mock_proc.assert_called_once_with(settings, conn, job)

    def test_sends_wol_waits_for_ollama_then_processes(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job()

        with (
            patch("server.worker.queue.list_pending", return_value=[job]),
            patch("server.worker.send_wol") as mock_wol,
            patch("server.worker._wait_for_ollama", new=AsyncMock(return_value=True)),
            patch("server.worker._process_job", new=AsyncMock()) as mock_proc,
        ):
            asyncio.run(worker._drain(settings, conn))

        mock_wol.assert_called_once_with(
            "AA:BB:CC:DD:EE:FF", settings.wol_broadcast, settings.wol_port
        )
        mock_proc.assert_called_once_with(settings, conn, job)

    def test_wol_send_failure_still_continues_to_check_ollama(self) -> None:
        """A WoL send error is logged but does not abort the drain."""
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job()

        with (
            patch("server.worker.queue.list_pending", return_value=[job]),
            patch("server.worker.send_wol", side_effect=OSError("network error")),
            patch("server.worker._wait_for_ollama", new=AsyncMock(return_value=True)),
            patch("server.worker._process_job", new=AsyncMock()) as mock_proc,
        ):
            asyncio.run(worker._drain(settings, conn))

        mock_proc.assert_called_once()

    def test_wol_timeout_applies_failure_and_skips_processing(self) -> None:
        settings = _settings(wol_mac_address="AA:BB:CC:DD:EE:FF")
        conn = MagicMock()
        job = _job()

        with (
            patch("server.worker.queue.list_pending", return_value=[job]),
            patch("server.worker.send_wol"),
            patch("server.worker._wait_for_ollama", new=AsyncMock(return_value=False)),
            patch("server.worker._apply_wol_failure") as mock_apply,
            patch("server.worker._process_job", new=AsyncMock()) as mock_proc,
        ):
            asyncio.run(worker._drain(settings, conn))

        mock_apply.assert_called_once_with(settings, conn, [job])
        mock_proc.assert_not_called()


class TestApplyWolFailure:
    def test_keeps_job_pending_within_retry_limit(self) -> None:
        settings = _settings(worker_max_retries=3)
        conn = MagicMock()
        job = _job(retry_count=0)

        with patch("server.worker.queue.update_status") as mock_update:
            worker._apply_wol_failure(settings, conn, [job])

        mock_update.assert_called_once_with(
            conn,
            job.id,
            JobStatus.PENDING,
            error="WoL: Ollama did not respond within timeout",
            retry_count=1,
        )

    def test_marks_job_failed_at_max_retries(self) -> None:
        settings = _settings(worker_max_retries=3)
        conn = MagicMock()
        job = _job(retry_count=2)  # next failure is 3rd → permanent fail

        with patch("server.worker.queue.update_status") as mock_update:
            worker._apply_wol_failure(settings, conn, [job])

        mock_update.assert_called_once_with(
            conn,
            job.id,
            JobStatus.FAILED,
            error="WoL: Ollama did not respond within timeout",
            retry_count=3,
        )

    def test_handles_multiple_jobs(self) -> None:
        settings = _settings(worker_max_retries=3)
        conn = MagicMock()
        jobs = [_job(id="job-1", retry_count=0), _job(id="job-2", retry_count=0)]

        with patch("server.worker.queue.update_status") as mock_update:
            worker._apply_wol_failure(settings, conn, jobs)

        assert mock_update.call_count == 2


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
        assert calls[1] == call(conn, job.id, JobStatus.READY, response="AI response")

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


class TestCallOllamaSync:
    def test_success_returns_response_text(self) -> None:
        settings = _settings()
        body = json.dumps(
            {"message": {"role": "assistant", "content": "AI text here"}}
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = body

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_resp
            mock_open.return_value.__exit__.return_value = False

            result = worker._call_ollama_sync(settings, _job())

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
                worker._call_ollama_sync(settings, _job())

    def test_url_error_raises_runtime_error(self) -> None:
        settings = _settings()

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="Ollama unreachable"):
                worker._call_ollama_sync(settings, _job())

    def test_request_sends_correct_payload(self) -> None:
        settings = _settings(ollama_host="http://ollama:11434")
        body = json.dumps({"message": {"role": "assistant", "content": "ok"}}).encode()

        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req)
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        job = _job(messages=[Message(role="user", content="hi there")])
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            worker._call_ollama_sync(settings, job)

        assert len(captured) == 1
        req = captured[0]
        assert req.full_url == "http://ollama:11434/api/chat"
        payload = json.loads(req.data.decode())
        assert payload["model"] == "llama3"
        assert payload["messages"] == [{"role": "user", "content": "hi there"}]
        assert payload["stream"] is False

    def test_format_included_in_payload_when_set(self) -> None:
        settings = _settings(ollama_host="http://ollama:11434")
        body = json.dumps({"message": {"role": "assistant", "content": "ok"}}).encode()

        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req)
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        job = _job(format="json")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            worker._call_ollama_sync(settings, job)

        payload = json.loads(captured[0].data.decode())
        assert payload.get("format") == "json"

    def test_format_omitted_when_none(self) -> None:
        settings = _settings(ollama_host="http://ollama:11434")
        body = json.dumps({"message": {"role": "assistant", "content": "ok"}}).encode()

        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req)
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        job = _job(format=None)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            worker._call_ollama_sync(settings, job)

        payload = json.loads(captured[0].data.decode())
        assert "format" not in payload

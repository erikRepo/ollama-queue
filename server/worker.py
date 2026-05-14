"""Background worker: drain queue, call Ollama, update job status."""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from sqlite3 import Connection

from server import queue
from server.config import Settings
from server.models import JobResponse, JobStatus
from server.wol import send_wol

logger = logging.getLogger(__name__)


async def run_worker(
    settings: Settings, conn: Connection, high_priority_event: asyncio.Event
) -> None:
    """Main worker loop: drain queue on high-priority event or batch interval.

    Runs until the asyncio task is cancelled.

    Args:
        settings: Application settings (batch interval, retry limits, etc.).
        conn: Dedicated SQLite connection for the worker.
        high_priority_event: Set by the API when a high-priority job is enqueued.
    """
    logger.info("Worker started (batch_interval=%.1fs)", settings.worker_batch_interval)
    try:
        while True:
            await _wait_for_trigger(high_priority_event, settings.worker_batch_interval)
            high_priority_event.clear()
            await _drain(settings, conn)
    except asyncio.CancelledError:
        logger.info("Worker stopped")
        raise


async def _wait_for_trigger(event: asyncio.Event, timeout: float) -> None:
    """Wait until *event* is set or *timeout* seconds elapse."""
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        pass


async def _drain(settings: Settings, conn: Connection) -> None:
    """Fetch pending jobs, optionally send WoL and wait for Ollama, then process.

    If WoL is configured and Ollama does not become ready within the timeout,
    each pending job counts one failure toward its retry limit.
    """
    jobs = queue.list_pending(conn)
    if not jobs:
        return

    if settings.wol_mac_address:
        try:
            send_wol(
                settings.wol_mac_address, settings.wol_broadcast, settings.wol_port
            )
        except Exception as exc:
            logger.warning("WoL send failed: %s", exc)

        ready = await _wait_for_ollama(settings)
        if not ready:
            logger.error(
                "Ollama did not respond within %ds; counting as one retry failure",
                settings.worker_wol_timeout,
            )
            _apply_wol_failure(settings, conn, jobs)
            return

    for job in jobs:
        await _process_job(settings, conn, job)


def _apply_wol_failure(
    settings: Settings, conn: Connection, jobs: list[JobResponse]
) -> None:
    """Increment retry_count for each pending job after a WoL/Ollama-readiness timeout.
    """
    for job in jobs:
        new_retry = job.retry_count + 1
        if new_retry >= settings.worker_max_retries:
            logger.error("Job %s failed permanently after WoL timeout", job.id)
            queue.update_status(
                conn,
                job.id,
                JobStatus.FAILED,
                error="WoL: Ollama did not respond within timeout",
                retry_count=new_retry,
            )
        else:
            logger.warning(
                "Job %s WoL timeout (attempt %d/%d)",
                job.id,
                new_retry,
                settings.worker_max_retries,
            )
            queue.update_status(
                conn,
                job.id,
                JobStatus.PENDING,
                error="WoL: Ollama did not respond within timeout",
                retry_count=new_retry,
            )


async def _wait_for_ollama(settings: Settings) -> bool:
    """Poll GET /api/tags with exponential backoff (2 s → 4 s → 8 s …) until ready.

    Returns True when Ollama responds with HTTP 200, False if the timeout expired.
    """
    delay = 2.0
    deadline = time.monotonic() + settings.worker_wol_timeout
    loop = asyncio.get_running_loop()

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        await asyncio.sleep(min(delay, remaining))
        ok = await loop.run_in_executor(None, _check_ollama_sync, settings)
        if ok:
            logger.info("Ollama is ready after WoL")
            return True
        logger.debug("Ollama not yet ready; next check in %.0fs", delay * 2)
        delay *= 2

    return False


async def _process_job(settings: Settings, conn: Connection, job: JobResponse) -> None:
    """Mark job PROCESSING, call Ollama, then set COMPLETED or requeue/fail."""
    queue.update_status(conn, job.id, JobStatus.PROCESSING)
    try:
        response_text = await _call_ollama(settings, job.model, job.prompt)
        queue.update_status(conn, job.id, JobStatus.COMPLETED, response=response_text)
    except Exception as exc:
        new_retry = job.retry_count + 1
        if new_retry >= settings.worker_max_retries:
            logger.error(
                "Job %s failed permanently after %d attempt(s): %s",
                job.id,
                new_retry,
                exc,
            )
            queue.update_status(
                conn, job.id, JobStatus.FAILED, error=str(exc), retry_count=new_retry
            )
        else:
            logger.warning(
                "Job %s failed (attempt %d/%d): %s — retrying after %.1fs",
                job.id,
                new_retry,
                settings.worker_max_retries,
                exc,
                settings.worker_retry_delay,
            )
            await asyncio.sleep(settings.worker_retry_delay)
            queue.update_status(
                conn, job.id, JobStatus.PENDING, error=str(exc), retry_count=new_retry
            )


async def _call_ollama(settings: Settings, model: str, prompt: str) -> str:
    """Call Ollama /api/generate (non-streaming) in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call_ollama_sync, settings, model, prompt)


def _call_ollama_sync(settings: Settings, model: str, prompt: str) -> str:
    """Blocking Ollama /api/generate call; raises RuntimeError on HTTP/network failure.
    """
    url = f"{settings.ollama_host}/api/generate"
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.ollama_timeout) as resp:
            data = json.loads(resp.read().decode())
            return data["response"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama unreachable: {exc.reason}") from exc


def _check_ollama_sync(settings: Settings) -> bool:
    """Return True if GET /api/tags responds with HTTP 200."""
    url = f"{settings.ollama_host}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False

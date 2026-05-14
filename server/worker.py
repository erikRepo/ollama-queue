"""Background worker: poll queue, send WoL, call Ollama, update job status."""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from sqlite3 import Connection

from server import queue
from server.config import Settings
from server.models import JobResponse, JobStatus
from server.wol import send_wol

logger = logging.getLogger(__name__)


async def run_worker(settings: Settings, conn: Connection) -> None:
    """Poll the queue forever, processing pending jobs each tick.

    Runs until the asyncio task is cancelled.

    Args:
        settings: Application settings (poll interval, retry limits, etc.).
        conn: Dedicated SQLite connection for the worker.
    """
    logger.info("Worker started (poll_interval=%.1fs)", settings.worker_poll_interval)
    try:
        while True:
            await _process_pending(settings, conn)
            await asyncio.sleep(settings.worker_poll_interval)
    except asyncio.CancelledError:
        logger.info("Worker stopped")
        raise


async def _process_pending(settings: Settings, conn: Connection) -> None:
    """Fetch and process all currently pending jobs.

    Args:
        settings: Application settings.
        conn: SQLite connection.
    """
    jobs = queue.list_pending(conn)
    for job in jobs:
        await _process_job(settings, conn, job)


async def _process_job(settings: Settings, conn: Connection, job: JobResponse) -> None:
    """Process one job: WoL → Ollama call → update status.

    Args:
        settings: Application settings.
        conn: SQLite connection.
        job: The pending job to process.
    """
    queue.update_status(conn, job.id, JobStatus.PROCESSING)

    if settings.wol_mac_address and job.retry_count == 0:
        try:
            send_wol(
                settings.wol_mac_address, settings.wol_broadcast, settings.wol_port
            )
        except Exception as exc:
            logger.warning("WoL failed for job %s: %s", job.id, exc)

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
    """Call Ollama /api/generate (non-streaming) in a thread executor.

    Args:
        settings: Application settings (host, timeout).
        model: Ollama model name.
        prompt: User prompt string.

    Returns:
        The response text from Ollama.

    Raises:
        RuntimeError: On HTTP error or network failure.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call_ollama_sync, settings, model, prompt)


def _call_ollama_sync(settings: Settings, model: str, prompt: str) -> str:
    """Blocking Ollama HTTP call, intended to run in a thread executor.

    Args:
        settings: Application settings.
        model: Ollama model name.
        prompt: User prompt string.

    Returns:
        Response text from the Ollama API.

    Raises:
        RuntimeError: On HTTP error or network failure.
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

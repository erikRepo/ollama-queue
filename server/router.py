"""API route handlers."""

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

import server.queue as queue_ops
from server.database import get_db
from server.models import JobPriority, JobRequest, JobResponse, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/queue", response_model=JobResponse, status_code=201)
async def post_queue(
    request: Request,
    body: JobRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> JobResponse:
    """Enqueue a new inference job and return it with status PENDING.

    High-priority jobs immediately wake the background worker via an asyncio.Event.
    """
    job = queue_ops.insert(conn, body)
    if job.priority == JobPriority.HIGH:
        request.app.state.high_priority_event.set()
    return job


@router.get("/status/{job_id}", response_model=JobResponse)
def get_status(
    job_id: str,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> JobResponse:
    """Return the current state of a job by its ID.

    When the job is READY, marks it CLOSED in the DB but returns it with the
    original READY status so the client sees "your result is available".

    Args:
        job_id: UUID of the target job.
        conn: Active SQLite connection.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = queue_ops.get_by_id(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if job.status == JobStatus.READY:
        queue_ops.update_status(conn, job_id, JobStatus.CLOSED)
    return job

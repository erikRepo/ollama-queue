"""API route handlers."""

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

import server.queue as queue_ops
from server.database import get_db
from server.models import JobRequest, JobResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/queue", response_model=JobResponse, status_code=201)
def post_queue(
    body: JobRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> JobResponse:
    """Enqueue a new inference job and return it with status PENDING."""
    return queue_ops.insert(conn, body)


@router.get("/status/{job_id}", response_model=JobResponse)
def get_status(
    job_id: str,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> JobResponse:
    """Return the current state of a job by its ID.

    Args:
        job_id: UUID of the target job.
        conn: Active SQLite connection.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = queue_ops.get_by_id(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job

"""API route handlers."""

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

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

"""Job CRUD operations against the SQLite jobs table."""

import logging
import sqlite3
import uuid
from datetime import UTC, datetime

from server.models import JobRequest, JobResponse, JobStatus

logger = logging.getLogger(__name__)


def _now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _row_to_job(row: sqlite3.Row) -> JobResponse:
    """Convert a sqlite3.Row from the jobs table into a JobResponse."""
    return JobResponse(
        id=row["id"],
        status=JobStatus(row["status"]),
        model=row["model"],
        prompt=row["prompt"],
        response=row["response"],
        error=row["error"],
        retry_count=row["retry_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def insert(conn: sqlite3.Connection, request: JobRequest) -> JobResponse:
    """Insert a new pending job and return the persisted record.

    Args:
        conn: Active SQLite connection with the jobs schema applied.
        request: Validated job request containing model and prompt.

    Returns:
        The newly created JobResponse with status PENDING.
    """
    job_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """
        INSERT INTO jobs (id, status, model, prompt, response, error, retry_count,
                          created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, NULL, 0, ?, ?)
        """,
        (job_id, JobStatus.PENDING, request.model, request.prompt, now, now),
    )
    conn.commit()
    logger.info("Job queued: %s model=%s", job_id, request.model)
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def get_by_id(conn: sqlite3.Connection, job_id: str) -> JobResponse | None:
    """Fetch a single job by its ID.

    Args:
        conn: Active SQLite connection.
        job_id: UUID string of the target job.

    Returns:
        JobResponse if found, None otherwise.
    """
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_pending(conn: sqlite3.Connection) -> list[JobResponse]:
    """Return all jobs with status PENDING, ordered by creation time ascending.

    Args:
        conn: Active SQLite connection.

    Returns:
        List of pending JobResponse objects, oldest first.
    """
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
        (JobStatus.PENDING,),
    ).fetchall()
    return [_row_to_job(row) for row in rows]


def update_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: JobStatus,
    *,
    response: str | None = None,
    error: str | None = None,
    retry_count: int | None = None,
) -> JobResponse | None:
    """Update a job's status and optional fields, returning the updated record.

    Args:
        conn: Active SQLite connection.
        job_id: UUID string of the target job.
        status: New JobStatus value.
        response: Ollama response text to store (COMPLETED jobs).
        error: Error message to store (FAILED jobs).
        retry_count: New retry count (overrides existing value when provided).

    Returns:
        Updated JobResponse, or None if the job_id does not exist.
    """
    now = _now()
    fields = ["status = ?", "updated_at = ?"]
    values: list = [status, now]

    if response is not None:
        fields.append("response = ?")
        values.append(response)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if retry_count is not None:
        fields.append("retry_count = ?")
        values.append(retry_count)

    values.append(job_id)
    conn.execute(
        f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
        values,
    )
    conn.commit()

    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        return None

    logger.info("Job %s status → %s", job_id, status)
    return get_by_id(conn, job_id)

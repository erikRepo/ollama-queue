"""Pydantic request/response models and job status enum."""

from enum import StrEnum

from pydantic import BaseModel, field_validator


class JobStatus(StrEnum):
    """Possible lifecycle states of a queued job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRequest(BaseModel):
    """Body for POST /api/queue."""

    model: str
    prompt: str

    @field_validator("model", "prompt")
    @classmethod
    def not_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only strings."""
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class JobResponse(BaseModel):
    """Full job record returned by the API."""

    id: str
    status: JobStatus
    model: str
    prompt: str
    response: str | None
    error: str | None
    retry_count: int
    created_at: str
    updated_at: str

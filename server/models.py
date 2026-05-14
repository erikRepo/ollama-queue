"""Pydantic request/response models and job status enum."""

from enum import StrEnum

from pydantic import BaseModel, field_validator


class JobStatus(StrEnum):
    """Possible lifecycle states of a queued job."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    CLOSED = "closed"
    FAILED = "failed"


class JobPriority(StrEnum):
    """Job scheduling priority."""

    HIGH = "high"
    LOW = "low"


class Message(BaseModel):
    """A single chat message sent to Ollama."""

    role: str
    content: str


class JobRequest(BaseModel):
    """Body for POST /api/queue."""

    model: str
    messages: list[Message]
    priority: JobPriority = JobPriority.LOW
    format: str | None = None
    callback_url: str | None = None

    @field_validator("model")
    @classmethod
    def model_not_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only model name."""
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("messages")
    @classmethod
    def messages_not_empty(cls, v: list[Message]) -> list[Message]:
        """Require at least one message."""
        if not v:
            raise ValueError("must contain at least one message")
        return v


class JobResponse(BaseModel):
    """Full job record returned by the API."""

    id: str
    status: JobStatus
    priority: JobPriority
    model: str
    messages: list[Message]
    format: str | None
    callback_url: str | None
    response: str | None
    error: str | None
    retry_count: int
    created_at: str
    updated_at: str

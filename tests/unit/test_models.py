"""Unit tests for Pydantic models and JobStatus enum."""

import pytest
from pydantic import ValidationError

from server.models import JobRequest, JobResponse, JobStatus, Message


class TestJobStatus:
    def test_all_values_present(self) -> None:
        assert {s.value for s in JobStatus} == {
            "pending",
            "processing",
            "ready",
            "closed",
            "failed",
        }

    def test_string_coercion(self) -> None:
        assert JobStatus("pending") is JobStatus.PENDING
        assert JobStatus("failed") is JobStatus.FAILED
        assert JobStatus("ready") is JobStatus.READY
        assert JobStatus("closed") is JobStatus.CLOSED


class TestMessage:
    def test_valid(self) -> None:
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_system_role(self) -> None:
        msg = Message(role="system", content="Be helpful.")
        assert msg.role == "system"

    def test_assistant_role(self) -> None:
        msg = Message(role="assistant", content="Sure!")
        assert msg.role == "assistant"


_MESSAGES = [{"role": "user", "content": "Hello"}]


class TestJobRequest:
    def test_valid(self) -> None:
        req = JobRequest(model="llama3", messages=_MESSAGES)
        assert req.model == "llama3"
        assert req.messages[0].content == "Hello"

    def test_missing_model(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(messages=_MESSAGES)  # type: ignore[call-arg]

    def test_missing_messages(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="llama3")  # type: ignore[call-arg]

    def test_empty_messages_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="llama3", messages=[])

    def test_empty_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="", messages=_MESSAGES)

    def test_whitespace_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="   ", messages=_MESSAGES)

    def test_default_priority_is_low(self) -> None:
        req = JobRequest(model="llama3", messages=_MESSAGES)
        assert req.priority.value == "low"

    def test_format_default_is_none(self) -> None:
        req = JobRequest(model="llama3", messages=_MESSAGES)
        assert req.format is None

    def test_callback_url_default_is_none(self) -> None:
        req = JobRequest(model="llama3", messages=_MESSAGES)
        assert req.callback_url is None

    def test_format_stored(self) -> None:
        req = JobRequest(model="llama3", messages=_MESSAGES, format="json")
        assert req.format == "json"

    def test_callback_url_stored(self) -> None:
        req = JobRequest(
            model="llama3", messages=_MESSAGES, callback_url="http://cb.example.com"
        )
        assert req.callback_url == "http://cb.example.com"


class TestJobResponse:
    _BASE: dict = {
        "id": "abc-123",
        "status": "pending",
        "priority": "low",
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello"}],
        "format": None,
        "callback_url": None,
        "response": None,
        "error": None,
        "retry_count": 0,
        "created_at": "2026-05-14T12:00:00",
        "updated_at": "2026-05-14T12:00:00",
    }

    def test_valid_pending(self) -> None:
        job = JobResponse(**self._BASE)
        assert job.id == "abc-123"
        assert job.status is JobStatus.PENDING
        assert job.response is None

    def test_ready_with_response(self) -> None:
        data = {**self._BASE, "status": "ready", "response": "Hi there"}
        job = JobResponse(**data)
        assert job.status is JobStatus.READY
        assert job.response == "Hi there"

    def test_closed_with_response(self) -> None:
        data = {**self._BASE, "status": "closed", "response": "Hi there"}
        job = JobResponse(**data)
        assert job.status is JobStatus.CLOSED
        assert job.response == "Hi there"

    def test_failed_with_error(self) -> None:
        data = {**self._BASE, "status": "failed", "error": "timeout"}
        job = JobResponse(**data)
        assert job.status is JobStatus.FAILED
        assert job.error == "timeout"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobResponse(**{**self._BASE, "status": "unknown"})

    def test_messages_deserialized(self) -> None:
        job = JobResponse(**self._BASE)
        assert isinstance(job.messages[0], Message)
        assert job.messages[0].role == "user"

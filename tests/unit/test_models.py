"""Unit tests for Pydantic models and JobStatus enum."""

import pytest
from pydantic import ValidationError

from server.models import JobRequest, JobResponse, JobStatus


class TestJobStatus:
    def test_all_values_present(self) -> None:
        assert {s.value for s in JobStatus} == {
            "pending",
            "processing",
            "completed",
            "failed",
        }

    def test_string_coercion(self) -> None:
        assert JobStatus("pending") is JobStatus.PENDING
        assert JobStatus("failed") is JobStatus.FAILED


class TestJobRequest:
    def test_valid(self) -> None:
        req = JobRequest(model="llama3", prompt="Hello")
        assert req.model == "llama3"
        assert req.prompt == "Hello"

    def test_missing_model(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(prompt="Hello")  # type: ignore[call-arg]

    def test_missing_prompt(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="llama3")  # type: ignore[call-arg]

    def test_empty_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="", prompt="Hello")

    def test_empty_prompt_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="llama3", prompt="")

    def test_whitespace_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="   ", prompt="Hello")

    def test_whitespace_prompt_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobRequest(model="llama3", prompt="   ")


class TestJobResponse:
    _BASE = {
        "id": "abc-123",
        "status": "pending",
        "priority": "low",
        "model": "llama3",
        "prompt": "Hello",
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

    def test_completed_with_response(self) -> None:
        data = {**self._BASE, "status": "completed", "response": "Hi there"}
        job = JobResponse(**data)
        assert job.status is JobStatus.COMPLETED
        assert job.response == "Hi there"

    def test_failed_with_error(self) -> None:
        data = {**self._BASE, "status": "failed", "error": "timeout"}
        job = JobResponse(**data)
        assert job.status is JobStatus.FAILED
        assert job.error == "timeout"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JobResponse(**{**self._BASE, "status": "unknown"})

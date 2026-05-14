"""Unit tests for OllamaQueueClient and its helpers."""

import io
import json
import threading
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from ollama_queue.client import OllamaQueueClient, _local_ip_for, _make_handler


class TestLocalIpFor:
    def test_connects_to_parsed_hostname(self) -> None:
        """Uses the hostname from the URL as the UDP probe target."""
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.getsockname.return_value = ("192.168.1.5", 12345)

        with patch("socket.socket", return_value=mock_sock):
            ip = _local_ip_for("http://myserver:11430")

        mock_sock.connect.assert_called_once_with(("myserver", 80))
        assert ip == "192.168.1.5"

    def test_falls_back_to_default_when_no_hostname(self) -> None:
        """Falls back to 8.8.8.8 when the URL cannot be parsed for a hostname."""
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: mock_sock
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.getsockname.return_value = ("10.0.0.1", 0)

        with patch("socket.socket", return_value=mock_sock):
            ip = _local_ip_for("not-a-url-at-all")

        mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))
        assert ip == "10.0.0.1"


class TestMakeHandler:
    def _make_instance(self, event: threading.Event, result: dict):
        """Instantiate the handler without going through HTTPServer."""
        Handler = _make_handler(event, result)
        handler = object.__new__(Handler)
        return handler

    def test_stores_response_and_fires_event(self) -> None:
        """do_POST reads the JSON body, stores response, and sets the event."""
        event = threading.Event()
        result: dict = {}
        handler = self._make_instance(event, result)

        body = json.dumps({"response": "hello from ollama"}).encode()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.send_response = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_POST()

        assert event.is_set()
        assert result["response"] == "hello from ollama"
        handler.send_response.assert_called_once_with(200)
        handler.end_headers.assert_called_once()

    def test_log_message_is_suppressed(self) -> None:
        """log_message() does nothing — no error, no output."""
        event = threading.Event()
        result: dict = {}
        handler = self._make_instance(event, result)
        handler.log_message("irrelevant %s", "arg")  # must not raise


class TestGenerate:
    def test_returns_response_when_webhook_arrives(self) -> None:
        """generate() returns the string from the webhook callback body."""
        client = OllamaQueueClient("http://fake-server:11430")

        def _fake_enqueue(model, messages, priority, fmt, callback_url):
            def _fire():
                import time

                time.sleep(0.05)
                body = json.dumps({"response": "the answer"}).encode()
                req = urllib.request.Request(
                    callback_url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req)

            threading.Thread(target=_fire, daemon=True).start()
            return "fake-job-id"

        with (
            patch("ollama_queue.client._local_ip_for", return_value="127.0.0.1"),
            patch.object(client, "_enqueue", side_effect=_fake_enqueue),
        ):
            response = client.generate(
                model="llama3",
                messages=[{"role": "user", "content": "hi"}],
                timeout=5.0,
            )

        assert response == "the answer"

    def test_raises_timeout_when_no_webhook_arrives(self) -> None:
        """generate() raises TimeoutError if no callback arrives before timeout."""
        client = OllamaQueueClient("http://fake-server:11430")

        with (
            patch("ollama_queue.client._local_ip_for", return_value="127.0.0.1"),
            patch.object(client, "_enqueue", return_value="fake-id"),
        ):
            with pytest.raises(TimeoutError):
                client.generate(
                    model="llama3",
                    messages=[{"role": "user", "content": "hi"}],
                    timeout=0.05,
                )


class TestEnqueue:
    def _ok_response(self, job_id: str = "abc-123") -> MagicMock:
        body = json.dumps({"id": job_id}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_posts_required_fields(self) -> None:
        """_enqueue POSTs model, messages, priority, and callback_url."""
        client = OllamaQueueClient("http://my-server:11430")
        captured: list[urllib.request.Request] = []

        def _urlopen(req, **_):
            captured.append(req)
            return self._ok_response()

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            job_id = client._enqueue(
                "llama3",
                [{"role": "user", "content": "hello"}],
                "low",
                None,
                "http://127.0.0.1:9999",
            )

        assert job_id == "abc-123"
        assert len(captured) == 1
        req = captured[0]
        assert req.full_url == "http://my-server:11430/api/queue"
        payload = json.loads(req.data.decode())
        assert payload["model"] == "llama3"
        assert payload["priority"] == "low"
        assert payload["callback_url"] == "http://127.0.0.1:9999"
        assert "format" not in payload

    def test_includes_format_when_specified(self) -> None:
        """_enqueue adds 'format' to the payload only when explicitly given."""
        client = OllamaQueueClient("http://my-server:11430")
        captured: list[urllib.request.Request] = []

        def _urlopen(req, **_):
            captured.append(req)
            return self._ok_response()

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            client._enqueue(
                "llama3",
                [{"role": "user", "content": "hello"}],
                "high",
                "json",
                "http://127.0.0.1:9999",
            )

        payload = json.loads(captured[0].data.decode())
        assert payload["format"] == "json"

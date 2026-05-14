"""Blocking HTTP client for the ollama-queue server."""

import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse


def _local_ip_for(server_url: str) -> str:
    """Return the local IP address that can reach the given server URL."""
    host = urlparse(server_url).hostname or "8.8.8.8"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 80))
        return s.getsockname()[0]


def _make_handler(
    event: threading.Event, result: dict[str, Any]
) -> type[BaseHTTPRequestHandler]:
    """Return a one-shot webhook handler class bound to shared state."""

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            result["response"] = body.get("response")
            event.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass  # suppress default stderr access log

    return _Handler


class OllamaQueueClient:
    """Blocking client for the ollama-queue server.

    Starts a local webhook listener on a random port, submits the job with
    that URL as callback_url, and waits for the server to push the result back.
    """

    def __init__(self, base_url: str) -> None:
        """Initialize with the server base URL, e.g. 'http://raspberrypi:11430'."""
        self._base_url = base_url.rstrip("/")

    def generate(
        self,
        model: str,
        messages: list[dict[str, str]],
        priority: str = "low",
        format: str | None = None,
        timeout: float = 600,
    ) -> str:
        """Submit a job and block until the server delivers the result via webhook.

        Binds a temporary HTTP listener on a random local port and passes it as
        callback_url when enqueuing. Blocks until the webhook arrives or timeout
        expires.

        Args:
            model: Ollama model name.
            messages: List of {"role": ..., "content": ...} dicts.
            priority: "high" or "low".
            format: Optional Ollama format option (e.g. "json").
            timeout: Maximum seconds to wait before raising TimeoutError.

        Returns:
            The LLM response as a string.

        Raises:
            TimeoutError: If no webhook callback arrives within `timeout` seconds.
        """
        event: threading.Event = threading.Event()
        result: dict[str, Any] = {}

        server = HTTPServer(("", 0), _make_handler(event, result))
        port = server.server_address[1]
        callback_url = f"http://{_local_ip_for(self._base_url)}:{port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self._enqueue(model, messages, priority, format, callback_url)
            if not event.wait(timeout=timeout):
                raise TimeoutError(
                    f"No webhook callback received within {timeout} seconds"
                )
        finally:
            server.shutdown()

        return result["response"]

    def _enqueue(
        self,
        model: str,
        messages: list[dict[str, str]],
        priority: str,
        format: str | None,
        callback_url: str,
    ) -> str:
        """POST /api/queue and return the job ID."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "priority": priority,
            "callback_url": callback_url,
        }
        if format is not None:
            payload["format"] = format

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/queue",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["id"]

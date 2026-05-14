"""Unit tests for server/config.py."""

import os
from pathlib import Path

import pytest

from server.config import load_settings


class TestDefaults:
    def test_default_host(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.host == "0.0.0.0"

    def test_default_port(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.port == 8080

    def test_default_database_url(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.database_url == "sqlite:///./ollama_queue.db"

    def test_default_ollama_host(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.ollama_host == "http://localhost:11434"

    def test_default_ollama_timeout(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.ollama_timeout == 300

    def test_default_worker_batch_interval(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.worker_batch_interval == 2.0

    def test_default_worker_wol_timeout(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.worker_wol_timeout == 300

    def test_default_worker_max_retries(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.worker_max_retries == 3

    def test_default_worker_retry_delay(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.worker_retry_delay == 5.0

    def test_default_wol_mac_address(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.wol_mac_address == ""

    def test_default_wol_broadcast(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.wol_broadcast == "255.255.255.255"

    def test_default_wol_port(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        assert s.wol_port == 9


class TestEnvOverrides:
    def test_port_from_env(self, clean_env: None) -> None:
        os.environ["PORT"] = "9090"
        s = load_settings(env_file=None)
        assert s.port == 9090

    def test_ollama_host_from_env(self, clean_env: None) -> None:
        os.environ["OLLAMA_HOST"] = "http://192.168.1.5:11434"
        s = load_settings(env_file=None)
        assert s.ollama_host == "http://192.168.1.5:11434"

    def test_wol_mac_from_env(self, clean_env: None) -> None:
        os.environ["WOL_MAC_ADDRESS"] = "AA:BB:CC:DD:EE:FF"
        s = load_settings(env_file=None)
        assert s.wol_mac_address == "AA:BB:CC:DD:EE:FF"

    def test_worker_batch_interval_from_env(self, clean_env: None) -> None:
        os.environ["WORKER_BATCH_INTERVAL"] = "0.5"
        s = load_settings(env_file=None)
        assert s.worker_batch_interval == 0.5

    def test_worker_wol_timeout_from_env(self, clean_env: None) -> None:
        os.environ["WORKER_WOL_TIMEOUT"] = "120"
        s = load_settings(env_file=None)
        assert s.worker_wol_timeout == 120


class TestDotEnvFile:
    def test_loads_from_file(self, tmp_path: Path, clean_env: None) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=7777\nOLLAMA_HOST=http://gpu-box:11434\n")
        s = load_settings(env_file=env_file)
        assert s.port == 7777
        assert s.ollama_host == "http://gpu-box:11434"

    def test_env_var_takes_precedence_over_file(
        self, tmp_path: Path, clean_env: None
    ) -> None:
        """Environment variable set before load_settings wins over .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=7777\n")
        os.environ["PORT"] = "9999"
        s = load_settings(env_file=env_file)
        assert s.port == 9999

    def test_missing_file_uses_defaults(self, tmp_path: Path, clean_env: None) -> None:
        s = load_settings(env_file=tmp_path / "nonexistent.env")
        assert s.port == 8080

    def test_ignores_blank_lines_and_comments(
        self, tmp_path: Path, clean_env: None
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nPORT=6666\n")
        s = load_settings(env_file=env_file)
        assert s.port == 6666


class TestValidation:
    def test_invalid_port_raises(self, clean_env: None) -> None:
        os.environ["PORT"] = "99999"
        with pytest.raises(ValueError, match="PORT"):
            load_settings(env_file=None)

    def test_port_zero_raises(self, clean_env: None) -> None:
        os.environ["PORT"] = "0"
        with pytest.raises(ValueError, match="PORT"):
            load_settings(env_file=None)

    def test_non_integer_port_raises(self, clean_env: None) -> None:
        os.environ["PORT"] = "abc"
        with pytest.raises(ValueError):
            load_settings(env_file=None)

    def test_negative_timeout_raises(self, clean_env: None) -> None:
        os.environ["OLLAMA_TIMEOUT"] = "-1"
        with pytest.raises(ValueError, match="OLLAMA_TIMEOUT"):
            load_settings(env_file=None)

    def test_negative_max_retries_raises(self, clean_env: None) -> None:
        os.environ["WORKER_MAX_RETRIES"] = "-1"
        with pytest.raises(ValueError, match="WORKER_MAX_RETRIES"):
            load_settings(env_file=None)

    def test_negative_wol_timeout_raises(self, clean_env: None) -> None:
        os.environ["WORKER_WOL_TIMEOUT"] = "-1"
        with pytest.raises(ValueError, match="WORKER_WOL_TIMEOUT"):
            load_settings(env_file=None)

    def test_settings_is_immutable(self, clean_env: None) -> None:
        s = load_settings(env_file=None)
        with pytest.raises((AttributeError, TypeError)):
            s.port = 1234  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CONFIG_KEYS = [
    "HOST",
    "PORT",
    "DATABASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_TIMEOUT",
    "WORKER_BATCH_INTERVAL",
    "WORKER_WOL_TIMEOUT",
    "WORKER_MAX_RETRIES",
    "WORKER_RETRY_DELAY",
    "WOL_MAC_ADDRESS",
    "WOL_BROADCAST",
    "WOL_PORT",
]


@pytest.fixture()
def clean_env() -> None:
    """Remove all config-related env vars, restore after the test."""
    saved = {k: os.environ.pop(k, None) for k in _CONFIG_KEYS}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

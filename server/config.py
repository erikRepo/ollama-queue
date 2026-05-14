"""Settings loader: reads env variables and an optional .env file."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Populate os.environ from a .env file without overwriting existing vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _int_env(name: str, default: int) -> int:
    """Return env var as int; raises ValueError with var name on bad input."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid integer") from None


def _float_env(name: str, default: float) -> float:
    """Return env var as float; raises ValueError with var name on bad input."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid number") from None


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    host: str
    port: int
    database_url: str
    ollama_host: str
    ollama_timeout: int
    worker_poll_interval: float
    worker_max_retries: int
    worker_retry_delay: float
    wol_mac_address: str
    wol_broadcast: str
    wol_port: int


def _validate(s: Settings) -> Settings:
    """Raise ValueError for logically invalid setting values."""
    if not (1 <= s.port <= 65535):
        raise ValueError(f"PORT={s.port} must be between 1 and 65535")
    if s.ollama_timeout < 0:
        raise ValueError(f"OLLAMA_TIMEOUT={s.ollama_timeout} must be >= 0")
    if s.worker_max_retries < 0:
        raise ValueError(f"WORKER_MAX_RETRIES={s.worker_max_retries} must be >= 0")
    return s


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Load settings from environment variables, optionally seeding from *env_file*.

    Variables already present in the environment take precedence over the file.
    """
    if env_file is not None:
        _load_env_file(env_file)

    return _validate(
        Settings(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=_int_env("PORT", 8080),
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./ollama_queue.db"),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_timeout=_int_env("OLLAMA_TIMEOUT", 300),
            worker_poll_interval=_float_env("WORKER_POLL_INTERVAL", 2.0),
            worker_max_retries=_int_env("WORKER_MAX_RETRIES", 3),
            worker_retry_delay=_float_env("WORKER_RETRY_DELAY", 5.0),
            wol_mac_address=os.environ.get("WOL_MAC_ADDRESS", ""),
            wol_broadcast=os.environ.get("WOL_BROADCAST", "255.255.255.255"),
            wol_port=_int_env("WOL_PORT", 9),
        )
    )

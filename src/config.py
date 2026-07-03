from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    polling_interval_seconds: int
    database_path: Path
    alert_dedupe_minutes: int
    watchlist_path: Path
    log_level: str


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def load_config(env_path: str | Path = ".env") -> AppConfig:
    load_dotenv(env_path)
    return AppConfig(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        polling_interval_seconds=_int_env("POLLING_INTERVAL_SECONDS", 30),
        database_path=Path(os.getenv("DATABASE_PATH", "data/polymarket_ai_release_pinger.sqlite3")),
        alert_dedupe_minutes=_int_env("ALERT_DEDUPE_MINUTES", 15),
        watchlist_path=Path(os.getenv("WATCHLIST_PATH", "watchlists/ai_model_releases.yml")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

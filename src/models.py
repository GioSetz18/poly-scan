from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class AlertRules:
    price_move_1m_pp: float | None = None
    price_move_5m_pp: float | None = None
    price_move_15m_pp: float | None = None
    min_absolute_volume_15m_usd: float | None = None
    dead_market_volume_15m_usd: float | None = None


@dataclass(frozen=True)
class MarketConfig:
    id: str
    name: str
    url: str
    category: str
    company: str | None
    model_family: str | None
    event_type: str | None
    deadline: date | None
    tags: list[str]
    liquidity_tier: str
    enabled: bool
    alert_rules: AlertRules


@dataclass(frozen=True)
class MarketSnapshot:
    market_id: str
    timestamp: datetime
    yes_price: float | None
    no_price: float | None
    volume: float | None
    liquidity: float | None
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertCandidate:
    market_id: str
    alert_type: str
    severity: str
    message: str
    yes_price_before: float | None
    yes_price_after: float | None
    price_move_pp: float | None
    volume_window: float | None
    raw_context: dict[str, Any]

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import AlertRules, MarketConfig


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_watchlist(path: str | Path) -> list[MarketConfig]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    markets: list[MarketConfig] = []
    for item in payload.get("markets", []):
        rules = item.get("alert_rules", {}) or {}
        markets.append(
            MarketConfig(
                id=str(item["id"]),
                name=str(item["name"]),
                url=str(item["url"]),
                category=str(item.get("category", "")),
                company=item.get("company"),
                model_family=item.get("model_family"),
                event_type=item.get("event_type"),
                deadline=_parse_date(item.get("deadline")),
                tags=[str(tag) for tag in item.get("tags", [])],
                liquidity_tier=str(item.get("liquidity_tier", "medium")),
                enabled=bool(item.get("enabled", True)),
                alert_rules=AlertRules(
                    price_move_1m_pp=_optional_float(rules.get("price_move_1m_pp")),
                    price_move_5m_pp=_optional_float(rules.get("price_move_5m_pp")),
                    price_move_15m_pp=_optional_float(rules.get("price_move_15m_pp")),
                    min_absolute_volume_15m_usd=_optional_float(rules.get("min_absolute_volume_15m_usd")),
                    dead_market_volume_15m_usd=_optional_float(rules.get("dead_market_volume_15m_usd")),
                ),
            )
        )
    return markets


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)

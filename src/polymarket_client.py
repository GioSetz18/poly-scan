from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from .models import MarketConfig, MarketSnapshot

LOGGER = logging.getLogger(__name__)


class PolymarketClient:
    """Small public-data client.

    Polymarket has multiple public surfaces. For MVP use, this client first tries
    Gamma event/market endpoints from a market URL slug and normalizes whichever
    shape it receives. If a market cannot be resolved, the caller logs and keeps
    processing the rest of the watchlist.
    """

    def __init__(self, timeout_seconds: int = 12) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polymarket-ai-release-pinger/0.1"})

    def fetch_market_snapshot(self, market: MarketConfig) -> MarketSnapshot:
        slug = self._slug_from_url(market.url)
        if not slug or "PASTE_MARKET_URL_HERE" in market.url:
            raise ValueError(f"Market {market.id} needs a real Polymarket URL")

        raw = self._fetch_by_slug(slug)
        normalized = self._normalize(raw)
        return MarketSnapshot(
            market_id=market.id,
            timestamp=datetime.now(timezone.utc),
            yes_price=normalized.get("yes_price"),
            no_price=normalized.get("no_price"),
            volume=normalized.get("volume"),
            liquidity=normalized.get("liquidity"),
            status=normalized.get("status"),
            outcome=normalized.get("outcome"),
            resolved_at=normalized.get("resolved_at"),
            raw_json=raw,
        )

    def _fetch_by_slug(self, slug: str) -> dict[str, Any]:
        candidates = [
            ("event", "https://gamma-api.polymarket.com/events", {"slug": slug}),
            ("market", "https://gamma-api.polymarket.com/markets", {"slug": slug}),
        ]
        last_error: Exception | None = None
        for kind, url, params in candidates:
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                item = self._first_item(payload)
                if item:
                    return {"source": kind, "payload": item}
            except (requests.RequestException, json.JSONDecodeError) as exc:
                last_error = exc
                LOGGER.debug("Polymarket %s lookup failed for slug %s: %s", kind, slug, exc)

        if last_error:
            raise RuntimeError(f"Could not fetch Polymarket data for slug {slug}: {last_error}") from last_error
        raise RuntimeError(f"No Polymarket data found for slug {slug}")

    @staticmethod
    def _slug_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None
        if path_parts[0] in {"event", "market"} and len(path_parts) > 1:
            return path_parts[1]
        return path_parts[-1]

    @staticmethod
    def _first_item(payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, list):
            return payload[0] if payload and isinstance(payload[0], dict) else None
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data:
                return data[0]
            return payload
        return None

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        payload = raw.get("payload", raw)
        market = self._pick_market(payload)
        yes_price = self._extract_yes_price(market)
        no_price = None if yes_price is None else max(0.0, min(1.0, 1.0 - yes_price))
        return {
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": self._number(market.get("volume") or market.get("volumeNum") or payload.get("volume")),
            "liquidity": self._number(market.get("liquidity") or market.get("liquidityNum") or payload.get("liquidity")),
            "status": self._extract_status(market, payload),
            "outcome": self._extract_outcome(market),
            "resolved_at": self._parse_datetime(
                market.get("resolvedAt")
                or market.get("resolutionTime")
                or market.get("closedTime")
                or payload.get("resolvedAt")
            ),
        }

    @staticmethod
    def _pick_market(payload: dict[str, Any]) -> dict[str, Any]:
        markets = payload.get("markets")
        if isinstance(markets, list) and markets:
            # Prefer a binary market with YES/NO outcomes when an event has many markets.
            for market in markets:
                outcomes = str(market.get("outcomes", "")).lower()
                if isinstance(market, dict) and "yes" in outcomes and "no" in outcomes:
                    return market
            if isinstance(markets[0], dict):
                return markets[0]
        return payload

    def _extract_yes_price(self, market: dict[str, Any]) -> float | None:
        for key in ("bestAsk", "lastTradePrice", "price", "yesPrice"):
            value = self._number(market.get(key))
            if value is not None:
                return self._normalize_price(value)

        outcome_prices = market.get("outcomePrices")
        outcomes = market.get("outcomes")
        price = self._price_from_outcomes(outcomes, outcome_prices)
        return self._normalize_price(price) if price is not None else None

    def _extract_status(self, market: dict[str, Any], payload: dict[str, Any]) -> str:
        for key in ("status", "marketStatus"):
            value = market.get(key) or payload.get(key)
            if value:
                return str(value).lower()
        if self._bool_value(market.get("resolved") or payload.get("resolved")):
            return "resolved"
        if self._bool_value(market.get("closed") or payload.get("closed")):
            return "closed"
        return "open"

    def _extract_outcome(self, market: dict[str, Any]) -> str | None:
        for key in ("winningOutcome", "winner", "resolution", "resolvedOutcome"):
            value = market.get(key)
            if value:
                return str(value)

        yes_price = self._extract_yes_price(market)
        if not self._bool_value(market.get("resolved") or market.get("closed")) or yes_price is None:
            return None
        if yes_price >= 0.99:
            return "YES"
        if yes_price <= 0.01:
            return "NO"
        return None

    def _price_from_outcomes(self, outcomes: Any, prices: Any) -> float | None:
        parsed_outcomes = self._maybe_json_list(outcomes)
        parsed_prices = self._maybe_json_list(prices)
        if not parsed_prices:
            return None
        if parsed_outcomes:
            for outcome, price in zip(parsed_outcomes, parsed_prices, strict=False):
                if str(outcome).lower() == "yes":
                    return self._number(price)
        return self._number(parsed_prices[0])

    @staticmethod
    def _maybe_json_list(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else None
            except json.JSONDecodeError:
                return re.findall(r"[^,\[\]\"]+", value)
        return None

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_price(value: float) -> float:
        return value / 100.0 if value > 1.0 else value

    @staticmethod
    def _bool_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "resolved", "closed"}
        return bool(value)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

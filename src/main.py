from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from .config import load_config
from .market_loader import load_watchlist
from .models import MarketConfig, MarketSnapshot
from .polymarket_client import PolymarketClient
from .signal_engine import dedupe_since, evaluate_market, should_send_alert
from .storage import (
    connect,
    ensure_tables,
    get_last_alert,
    get_recent_snapshots,
    insert_alert,
    insert_snapshot,
    upsert_market,
)
from .telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket AI release alert pinger")
    parser.add_argument("--dry-run", action="store_true", help="Use mock data and print alerts instead of Telegram")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    parser.add_argument("--watchlist", help="Override WATCHLIST_PATH")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config()
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    watchlist_path = args.watchlist or config.watchlist_path
    markets = [market for market in load_watchlist(watchlist_path) if market.enabled]
    conn = connect(":memory:" if args.dry_run else config.database_path)
    ensure_tables(conn)
    for market in markets:
        upsert_market(conn, market)

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id, dry_run=args.dry_run)
    client = PolymarketClient()

    if args.dry_run:
        run_dry_demo(conn, markets, notifier, config.alert_dedupe_minutes)
        return

    LOGGER.info("Watching %s enabled markets", len(markets))
    while True:
        run_poll_cycle(conn, markets, client, notifier, config.alert_dedupe_minutes)
        if args.once:
            return
        time.sleep(config.polling_interval_seconds)


def run_poll_cycle(
    conn,
    markets: list[MarketConfig],
    client: PolymarketClient,
    notifier: TelegramNotifier,
    dedupe_minutes: int,
) -> None:
    for market in markets:
        try:
            snapshot = client.fetch_market_snapshot(market)
            process_snapshot(conn, market, snapshot, notifier, dedupe_minutes)
        except Exception:
            LOGGER.exception("Failed to process market %s", market.id)


def process_snapshot(conn, market: MarketConfig, snapshot: MarketSnapshot, notifier: TelegramNotifier, dedupe_minutes: int) -> None:
    insert_snapshot(conn, snapshot)
    recent = get_recent_snapshots(conn, market.id, minutes=30)
    candidates = evaluate_market(market, snapshot, recent)
    for candidate in candidates:
        last = get_last_alert(conn, candidate.market_id, candidate.alert_type, dedupe_since(dedupe_minutes))
        if not should_send_alert(last, candidate):
            LOGGER.info("Deduped %s alert for %s", candidate.alert_type, candidate.market_id)
            continue
        notifier.send(candidate.message)
        insert_alert(conn, candidate)


def run_dry_demo(conn, markets: list[MarketConfig], notifier: TelegramNotifier, dedupe_minutes: int) -> None:
    if not markets:
        raise RuntimeError("No enabled markets found in watchlist")
    market = markets[0]
    now = datetime.now(timezone.utc)
    baseline = MarketSnapshot(
        market_id=market.id,
        timestamp=now - timedelta(minutes=5),
        yes_price=0.085,
        no_price=0.915,
        volume=100.0,
        liquidity=300.0,
        raw_json={"dry_run": True, "phase": "baseline"},
    )
    moved = MarketSnapshot(
        market_id=market.id,
        timestamp=now,
        yes_price=0.241,
        no_price=0.759,
        volume=2500.0,
        liquidity=900.0,
        raw_json={"dry_run": True, "phase": "moved"},
    )
    insert_snapshot(conn, baseline)
    process_snapshot(conn, market, moved, notifier, dedupe_minutes)
    LOGGER.info("Dry-run complete")


if __name__ == "__main__":
    main()

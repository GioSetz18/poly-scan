from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from .config import load_config
from .market_loader import load_watchlist
from .models import EventLogEntry, MarketConfig, MarketSnapshot
from .polymarket_client import PolymarketClient
from .signal_engine import dedupe_since, evaluate_market, should_send_alert
from .storage import (
    connect,
    ensure_tables,
    get_last_alert,
    get_event_log,
    get_market_state,
    get_recent_snapshots,
    insert_alert,
    insert_event_log,
    insert_snapshot,
    update_market_state_from_snapshot,
    upsert_market,
)
from .telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket AI release alert pinger")
    parser.add_argument("--dry-run", action="store_true", help="Use mock data and print alerts instead of Telegram")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
    parser.add_argument("--watchlist", help="Override WATCHLIST_PATH")
    parser.add_argument("--log-event", action="store_true", help="Add a manual event-log entry and exit")
    parser.add_argument("--event-market-id", help="Market id for --log-event")
    parser.add_argument("--event-type", default="manual_note", help="Event type, e.g. official_announcement or review_note")
    parser.add_argument("--event-title", help="Short title for --log-event")
    parser.add_argument("--event-source", default="manual", help="Source for --log-event")
    parser.add_argument("--event-url", help="Optional source URL for --log-event")
    parser.add_argument("--event-notes", help="Optional notes for --log-event")
    parser.add_argument("--show-events", action="store_true", help="Print recent event-log rows and exit")
    parser.add_argument("--limit", type=int, default=20, help="Row limit for --show-events")
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

    if args.log_event:
        add_manual_event(conn, args)
        return

    if args.show_events:
        print_event_log(conn, args.event_market_id, args.limit)
        return

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
    previous_state = get_market_state(conn, market.id)
    insert_snapshot(conn, snapshot)
    update_market_state_from_snapshot(conn, snapshot)
    maybe_log_outcome_change(conn, market, snapshot, previous_state)
    recent = get_recent_snapshots(conn, market.id, minutes=30)
    candidates = evaluate_market(market, snapshot, recent)
    for candidate in candidates:
        last = get_last_alert(conn, candidate.market_id, candidate.alert_type, dedupe_since(dedupe_minutes))
        if not should_send_alert(last, candidate):
            LOGGER.info("Deduped %s alert for %s", candidate.alert_type, candidate.market_id)
            continue
        notifier.send(candidate.message)
        alert_id = insert_alert(conn, candidate)
        insert_event_log(
            conn,
            EventLogEntry(
                market_id=market.id,
                event_type="alert_sent",
                source="bot",
                title=f"{candidate.alert_type} alert ({candidate.severity})",
                timestamp=datetime.now(timezone.utc),
                alert_id=alert_id,
                yes_price=snapshot.yes_price,
                no_price=snapshot.no_price,
                volume=snapshot.volume,
                outcome=snapshot.outcome,
                raw_context={
                    "alert_type": candidate.alert_type,
                    "severity": candidate.severity,
                    "price_move_pp": candidate.price_move_pp,
                    "volume_window": candidate.volume_window,
                },
            ),
        )


def maybe_log_outcome_change(
    conn,
    market: MarketConfig,
    snapshot: MarketSnapshot,
    previous_state: dict[str, str] | None,
) -> None:
    if not snapshot.outcome and snapshot.status not in {"resolved", "closed"}:
        return

    previous_outcome = previous_state.get("outcome") if previous_state else None
    previous_status = previous_state.get("status") if previous_state else None
    if previous_outcome == snapshot.outcome and previous_status == snapshot.status:
        return

    insert_event_log(
        conn,
        EventLogEntry(
            market_id=market.id,
            event_type="market_outcome_observed",
            source="polymarket",
            title=f"Market outcome observed: {snapshot.outcome or snapshot.status}",
            timestamp=snapshot.resolved_at or snapshot.timestamp,
            yes_price=snapshot.yes_price,
            no_price=snapshot.no_price,
            volume=snapshot.volume,
            outcome=snapshot.outcome,
            raw_context={
                "status": snapshot.status,
                "previous_status": previous_status,
                "previous_outcome": previous_outcome,
            },
        ),
    )


def add_manual_event(conn, args) -> None:
    if not args.event_market_id or not args.event_title:
        raise SystemExit("--event-market-id and --event-title are required with --log-event")
    entry_id = insert_event_log(
        conn,
        EventLogEntry(
            market_id=args.event_market_id,
            event_type=args.event_type,
            source=args.event_source,
            title=args.event_title,
            timestamp=datetime.now(timezone.utc),
            details_url=args.event_url,
            notes=args.event_notes,
        ),
    )
    LOGGER.info("Inserted event_log row %s", entry_id)


def print_event_log(conn, market_id: str | None, limit: int) -> None:
    rows = get_event_log(conn, market_id=market_id, limit=limit)
    for row in rows:
        print(
            f"{row['timestamp']} | {row['market_id']} | {row['event_type']} | "
            f"{row['source']} | {row['title']}"
        )


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
    insert_event_log(
        conn,
        EventLogEntry(
            market_id=market.id,
            event_type="official_announcement",
            source="manual",
            title="Dry-run example official announcement",
            timestamp=now + timedelta(minutes=92),
            details_url="https://example.com/official-announcement",
            notes="Example row showing how to audit alert timing against later public confirmation.",
            yes_price=0.90,
            outcome="YES",
            raw_context={"dry_run": True},
        ),
    )
    print("\nEvent log:")
    print_event_log(conn, market.id, limit=10)
    LOGGER.info("Dry-run complete")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import AlertCandidate, EventLogEntry, MarketConfig, MarketSnapshot


def connect(database_path: str | Path) -> sqlite3.Connection:
    if str(database_path) == ":memory:":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS markets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            company TEXT,
            model_family TEXT,
            event_type TEXT,
            deadline TEXT,
            liquidity_tier TEXT,
            enabled INTEGER NOT NULL,
            status TEXT,
            outcome TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            yes_price REAL,
            no_price REAL,
            volume REAL,
            liquidity REAL,
            status TEXT,
            outcome TEXT,
            resolved_at TEXT,
            raw_json TEXT NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
            ON market_snapshots (market_id, timestamp);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            yes_price_before REAL,
            yes_price_after REAL,
            price_move_pp REAL,
            volume_window REAL,
            raw_context_json TEXT NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id)
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_market_type_time
            ON alerts (market_id, alert_type, timestamp);

        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            details_url TEXT,
            notes TEXT,
            alert_id INTEGER,
            yes_price REAL,
            no_price REAL,
            volume REAL,
            outcome TEXT,
            raw_context_json TEXT NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id),
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        );

        CREATE INDEX IF NOT EXISTS idx_event_log_market_time
            ON event_log (market_id, timestamp);

        CREATE INDEX IF NOT EXISTS idx_event_log_type_time
            ON event_log (event_type, timestamp);
        """
    )
    _ensure_column(conn, "markets", "status", "TEXT")
    _ensure_column(conn, "markets", "outcome", "TEXT")
    _ensure_column(conn, "markets", "resolved_at", "TEXT")
    _ensure_column(conn, "market_snapshots", "status", "TEXT")
    _ensure_column(conn, "market_snapshots", "outcome", "TEXT")
    _ensure_column(conn, "market_snapshots", "resolved_at", "TEXT")
    conn.commit()


def upsert_market(conn: sqlite3.Connection, market: MarketConfig) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO markets (
            id, name, url, category, company, model_family, event_type, deadline,
            liquidity_tier, enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            url=excluded.url,
            category=excluded.category,
            company=excluded.company,
            model_family=excluded.model_family,
            event_type=excluded.event_type,
            deadline=excluded.deadline,
            liquidity_tier=excluded.liquidity_tier,
            enabled=excluded.enabled,
            updated_at=excluded.updated_at
        """,
        (
            market.id,
            market.name,
            market.url,
            market.category,
            market.company,
            market.model_family,
            market.event_type,
            market.deadline.isoformat() if market.deadline else None,
            market.liquidity_tier,
            1 if market.enabled else 0,
            now,
            now,
        ),
    )
    conn.commit()


def insert_snapshot(conn: sqlite3.Connection, snapshot: MarketSnapshot) -> None:
    conn.execute(
        """
        INSERT INTO market_snapshots (
            market_id, timestamp, yes_price, no_price, volume, liquidity,
            status, outcome, resolved_at, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.market_id,
            snapshot.timestamp.isoformat(),
            snapshot.yes_price,
            snapshot.no_price,
            snapshot.volume,
            snapshot.liquidity,
            snapshot.status,
            snapshot.outcome,
            snapshot.resolved_at.isoformat() if snapshot.resolved_at else None,
            json.dumps(snapshot.raw_json, sort_keys=True),
        ),
    )
    conn.commit()


def get_market_state(conn: sqlite3.Connection, market_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT status, outcome, resolved_at FROM markets WHERE id = ?",
        (market_id,),
    ).fetchone()
    return dict(row) if row else None


def update_market_state_from_snapshot(conn: sqlite3.Connection, snapshot: MarketSnapshot) -> None:
    conn.execute(
        """
        UPDATE markets
        SET status = COALESCE(?, status),
            outcome = COALESCE(?, outcome),
            resolved_at = COALESCE(?, resolved_at),
            updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot.status,
            snapshot.outcome,
            snapshot.resolved_at.isoformat() if snapshot.resolved_at else None,
            datetime.now(timezone.utc).isoformat(),
            snapshot.market_id,
        ),
    )
    conn.commit()


def get_recent_snapshots(conn: sqlite3.Connection, market_id: str, minutes: int = 30) -> list[MarketSnapshot]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = conn.execute(
        """
        SELECT market_id, timestamp, yes_price, no_price, volume, liquidity,
               status, outcome, resolved_at, raw_json
        FROM market_snapshots
        WHERE market_id = ? AND timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (market_id, cutoff.isoformat()),
    ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def get_last_alert(
    conn: sqlite3.Connection,
    market_id: str,
    alert_type: str,
    since: datetime,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT timestamp, severity
        FROM alerts
        WHERE market_id = ? AND alert_type = ? AND timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (market_id, alert_type, since.isoformat()),
    ).fetchone()
    return dict(row) if row else None


def insert_alert(conn: sqlite3.Connection, alert: AlertCandidate) -> int:
    cursor = conn.execute(
        """
        INSERT INTO alerts (
            market_id, timestamp, alert_type, severity, message,
            yes_price_before, yes_price_after, price_move_pp, volume_window,
            raw_context_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.market_id,
            datetime.now(timezone.utc).isoformat(),
            alert.alert_type,
            alert.severity,
            alert.message,
            alert.yes_price_before,
            alert.yes_price_after,
            alert.price_move_pp,
            alert.volume_window,
            json.dumps(alert.raw_context, sort_keys=True),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def insert_event_log(conn: sqlite3.Connection, entry: EventLogEntry) -> int:
    cursor = conn.execute(
        """
        INSERT INTO event_log (
            market_id, timestamp, event_type, source, title, details_url, notes,
            alert_id, yes_price, no_price, volume, outcome, raw_context_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.market_id,
            entry.timestamp.isoformat(),
            entry.event_type,
            entry.source,
            entry.title,
            entry.details_url,
            entry.notes,
            entry.alert_id,
            entry.yes_price,
            entry.no_price,
            entry.volume,
            entry.outcome,
            json.dumps(entry.raw_context, sort_keys=True),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_event_log(conn: sqlite3.Connection, market_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if market_id:
        rows = conn.execute(
            """
            SELECT *
            FROM event_log
            WHERE market_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (market_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM event_log
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _snapshot_from_row(row: sqlite3.Row) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=row["market_id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        yes_price=row["yes_price"],
        no_price=row["no_price"],
        volume=row["volume"],
        liquidity=row["liquidity"],
        status=row["status"] if "status" in row.keys() else None,
        outcome=row["outcome"] if "outcome" in row.keys() else None,
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if "resolved_at" in row.keys() and row["resolved_at"] else None,
        raw_json=json.loads(row["raw_json"]),
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

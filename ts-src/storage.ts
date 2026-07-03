import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

import type { AlertCandidate, EventLogEntry, MarketConfig, MarketSnapshot } from "./models.js";

type Row = Record<string, unknown>;

export function connect(databasePath: string): DatabaseSync {
  if (databasePath !== ":memory:") {
    mkdirSync(dirname(databasePath), { recursive: true });
  }
  return new DatabaseSync(databasePath);
}

export function ensureTables(db: DatabaseSync): void {
  db.exec(`
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
  `);
  ensureColumn(db, "markets", "status", "TEXT");
  ensureColumn(db, "markets", "outcome", "TEXT");
  ensureColumn(db, "markets", "resolved_at", "TEXT");
  ensureColumn(db, "market_snapshots", "status", "TEXT");
  ensureColumn(db, "market_snapshots", "outcome", "TEXT");
  ensureColumn(db, "market_snapshots", "resolved_at", "TEXT");
}

export function upsertMarket(db: DatabaseSync, market: MarketConfig): void {
  const now = new Date().toISOString();
  db.prepare(`
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
  `).run(
    market.id,
    market.name,
    market.url,
    market.category,
    market.company ?? null,
    market.modelFamily ?? null,
    market.eventType ?? null,
    market.deadline ?? null,
    market.liquidityTier,
    market.enabled ? 1 : 0,
    now,
    now
  );
}

export function insertSnapshot(db: DatabaseSync, snapshot: MarketSnapshot): void {
  db.prepare(`
    INSERT INTO market_snapshots (
      market_id, timestamp, yes_price, no_price, volume, liquidity,
      status, outcome, resolved_at, raw_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    snapshot.marketId,
    snapshot.timestamp.toISOString(),
    snapshot.yesPrice,
    snapshot.noPrice,
    snapshot.volume,
    snapshot.liquidity,
    snapshot.status ?? null,
    snapshot.outcome ?? null,
    snapshot.resolvedAt?.toISOString() ?? null,
    JSON.stringify(snapshot.rawJson)
  );
}

export function getRecentSnapshots(db: DatabaseSync, marketId: string, minutes = 30): MarketSnapshot[] {
  const cutoff = new Date(Date.now() - minutes * 60_000).toISOString();
  const rows = db.prepare(`
    SELECT market_id, timestamp, yes_price, no_price, volume, liquidity,
           status, outcome, resolved_at, raw_json
    FROM market_snapshots
    WHERE market_id = ? AND timestamp >= ?
    ORDER BY timestamp ASC
  `).all(marketId, cutoff) as Row[];
  return rows.map(snapshotFromRow);
}

export function getMarketState(db: DatabaseSync, marketId: string): Row | null {
  return db.prepare("SELECT status, outcome, resolved_at FROM markets WHERE id = ?").get(marketId) as Row | undefined ?? null;
}

export function updateMarketStateFromSnapshot(db: DatabaseSync, snapshot: MarketSnapshot): void {
  db.prepare(`
    UPDATE markets
    SET status = COALESCE(?, status),
        outcome = COALESCE(?, outcome),
        resolved_at = COALESCE(?, resolved_at),
        updated_at = ?
    WHERE id = ?
  `).run(
    snapshot.status ?? null,
    snapshot.outcome ?? null,
    snapshot.resolvedAt?.toISOString() ?? null,
    new Date().toISOString(),
    snapshot.marketId
  );
}

export function getLastAlert(db: DatabaseSync, marketId: string, alertType: string, since: Date): Row | null {
  return db.prepare(`
    SELECT timestamp, severity
    FROM alerts
    WHERE market_id = ? AND alert_type = ? AND timestamp >= ?
    ORDER BY timestamp DESC
    LIMIT 1
  `).get(marketId, alertType, since.toISOString()) as Row | undefined ?? null;
}

export function insertAlert(db: DatabaseSync, alert: AlertCandidate): number {
  const result = db.prepare(`
    INSERT INTO alerts (
      market_id, timestamp, alert_type, severity, message,
      yes_price_before, yes_price_after, price_move_pp, volume_window,
      raw_context_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    alert.marketId,
    new Date().toISOString(),
    alert.alertType,
    alert.severity,
    alert.message,
    alert.yesPriceBefore,
    alert.yesPriceAfter,
    alert.priceMovePp,
    alert.volumeWindow,
    JSON.stringify(alert.rawContext)
  );
  return Number(result.lastInsertRowid);
}

export function insertEventLog(db: DatabaseSync, entry: EventLogEntry): number {
  const result = db.prepare(`
    INSERT INTO event_log (
      market_id, timestamp, event_type, source, title, details_url, notes,
      alert_id, yes_price, no_price, volume, outcome, raw_context_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    entry.marketId,
    entry.timestamp.toISOString(),
    entry.eventType,
    entry.source,
    entry.title,
    entry.detailsUrl ?? null,
    entry.notes ?? null,
    entry.alertId ?? null,
    entry.yesPrice ?? null,
    entry.noPrice ?? null,
    entry.volume ?? null,
    entry.outcome ?? null,
    JSON.stringify(entry.rawContext ?? {})
  );
  return Number(result.lastInsertRowid);
}

export function getEventLog(db: DatabaseSync, marketId?: string, limit = 50): Row[] {
  if (marketId) {
    return db.prepare(`
      SELECT *
      FROM event_log
      WHERE market_id = ?
      ORDER BY timestamp DESC, id DESC
      LIMIT ?
    `).all(marketId, limit) as Row[];
  }
  return db.prepare(`
    SELECT *
    FROM event_log
    ORDER BY timestamp DESC, id DESC
    LIMIT ?
  `).all(limit) as Row[];
}

function snapshotFromRow(row: Row): MarketSnapshot {
  return {
    marketId: String(row.market_id),
    timestamp: new Date(String(row.timestamp)),
    yesPrice: nullableNumber(row.yes_price),
    noPrice: nullableNumber(row.no_price),
    volume: nullableNumber(row.volume),
    liquidity: nullableNumber(row.liquidity),
    status: nullableString(row.status),
    outcome: nullableString(row.outcome),
    resolvedAt: row.resolved_at ? new Date(String(row.resolved_at)) : null,
    rawJson: JSON.parse(String(row.raw_json)) as Record<string, unknown>
  };
}

function ensureColumn(db: DatabaseSync, table: string, column: string, definition: string): void {
  const rows = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
  if (!rows.some((row) => row.name === column)) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
  }
}

function nullableNumber(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}

function nullableString(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}

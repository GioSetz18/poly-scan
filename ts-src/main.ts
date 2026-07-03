import type { DatabaseSync } from "node:sqlite";

import { loadConfig } from "./config.js";
import { loadWatchlist } from "./market-loader.js";
import type { EventLogEntry, MarketConfig, MarketSnapshot } from "./models.js";
import { PolymarketClient } from "./polymarket-client.js";
import { dedupeSince, evaluateMarket, shouldSendAlert } from "./signal-engine.js";
import {
  connect,
  ensureTables,
  getEventLog,
  getLastAlert,
  getMarketState,
  getRecentSnapshots,
  insertAlert,
  insertEventLog,
  insertSnapshot,
  updateMarketStateFromSnapshot,
  upsertMarket
} from "./storage.js";
import { TelegramNotifier } from "./telegram-notifier.js";

interface Args {
  dryRun: boolean;
  once: boolean;
  watchlist?: string;
  logEvent: boolean;
  eventMarketId?: string;
  eventType: string;
  eventTitle?: string;
  eventSource: string;
  eventUrl?: string;
  eventNotes?: string;
  showEvents: boolean;
  limit: number;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const config = loadConfig();
  const watchlistPath = args.watchlist || config.watchlistPath;
  const markets = loadWatchlist(watchlistPath).filter((market) => market.enabled);
  const db = connect(args.dryRun ? ":memory:" : config.databasePath);
  ensureTables(db);
  for (const market of markets) upsertMarket(db, market);

  if (args.logEvent) {
    addManualEvent(db, args);
    return;
  }

  if (args.showEvents) {
    printEventLog(db, args.eventMarketId, args.limit);
    return;
  }

  const notifier = new TelegramNotifier(config.telegramBotToken, config.telegramChatId, args.dryRun);
  const client = new PolymarketClient();

  if (args.dryRun) {
    await runDryDemo(db, markets, notifier, config.alertDedupeMinutes);
    return;
  }

  console.info(`Watching ${markets.length} enabled markets`);
  while (true) {
    await runPollCycle(db, markets, client, notifier, config.alertDedupeMinutes);
    if (args.once) return;
    await sleep(config.pollingIntervalSeconds * 1000);
  }
}

async function runPollCycle(
  db: DatabaseSync,
  markets: MarketConfig[],
  client: PolymarketClient,
  notifier: TelegramNotifier,
  dedupeMinutes: number
): Promise<void> {
  for (const market of markets) {
    try {
      const snapshot = await client.fetchMarketSnapshot(market);
      await processSnapshot(db, market, snapshot, notifier, dedupeMinutes);
    } catch (error) {
      console.error(`Failed to process market ${market.id}`, error);
    }
  }
}

async function processSnapshot(
  db: DatabaseSync,
  market: MarketConfig,
  snapshot: MarketSnapshot,
  notifier: TelegramNotifier,
  dedupeMinutes: number
): Promise<void> {
  const previousState = getMarketState(db, market.id);
  insertSnapshot(db, snapshot);
  updateMarketStateFromSnapshot(db, snapshot);
  maybeLogOutcomeChange(db, market, snapshot, previousState);

  const recent = getRecentSnapshots(db, market.id, 30);
  const candidates = evaluateMarket(market, snapshot, recent);
  for (const candidate of candidates) {
    const last = getLastAlert(db, candidate.marketId, candidate.alertType, dedupeSince(dedupeMinutes));
    if (!shouldSendAlert(last, candidate)) {
      console.info(`Deduped ${candidate.alertType} alert for ${candidate.marketId}`);
      continue;
    }
    await notifier.send(candidate.message);
    const alertId = insertAlert(db, candidate);
    insertEventLog(db, {
      marketId: market.id,
      eventType: "alert_sent",
      source: "bot",
      title: `${candidate.alertType} alert (${candidate.severity})`,
      timestamp: new Date(),
      alertId,
      yesPrice: snapshot.yesPrice,
      noPrice: snapshot.noPrice,
      volume: snapshot.volume,
      outcome: snapshot.outcome,
      rawContext: {
        alertType: candidate.alertType,
        severity: candidate.severity,
        priceMovePp: candidate.priceMovePp,
        volumeWindow: candidate.volumeWindow
      }
    });
  }
}

function maybeLogOutcomeChange(
  db: DatabaseSync,
  market: MarketConfig,
  snapshot: MarketSnapshot,
  previousState: Record<string, unknown> | null
): void {
  if (!snapshot.outcome && snapshot.status !== "resolved" && snapshot.status !== "closed") return;

  const previousOutcome = previousState?.outcome ? String(previousState.outcome) : null;
  const previousStatus = previousState?.status ? String(previousState.status) : null;
  if (previousOutcome === snapshot.outcome && previousStatus === snapshot.status) return;

  insertEventLog(db, {
    marketId: market.id,
    eventType: "market_outcome_observed",
    source: "polymarket",
    title: `Market outcome observed: ${snapshot.outcome || snapshot.status}`,
    timestamp: snapshot.resolvedAt || snapshot.timestamp,
    yesPrice: snapshot.yesPrice,
    noPrice: snapshot.noPrice,
    volume: snapshot.volume,
    outcome: snapshot.outcome,
    rawContext: {
      status: snapshot.status,
      previousStatus,
      previousOutcome
    }
  });
}

function addManualEvent(db: DatabaseSync, args: Args): void {
  if (!args.eventMarketId || !args.eventTitle) {
    throw new Error("--event-market-id and --event-title are required with --log-event");
  }
  const entry: EventLogEntry = {
    marketId: args.eventMarketId,
    eventType: args.eventType,
    source: args.eventSource,
    title: args.eventTitle,
    timestamp: new Date(),
    detailsUrl: args.eventUrl,
    notes: args.eventNotes
  };
  const id = insertEventLog(db, entry);
  console.info(`Inserted event_log row ${id}`);
}

function printEventLog(db: DatabaseSync, marketId: string | undefined, limit: number): void {
  for (const row of getEventLog(db, marketId, limit)) {
    console.log(`${row.timestamp} | ${row.market_id} | ${row.event_type} | ${row.source} | ${row.title}`);
  }
}

async function runDryDemo(
  db: DatabaseSync,
  markets: MarketConfig[],
  notifier: TelegramNotifier,
  dedupeMinutes: number
): Promise<void> {
  if (markets.length === 0) throw new Error("No enabled markets found in watchlist");
  const market = markets[0];
  const now = new Date();
  const baseline: MarketSnapshot = {
    marketId: market.id,
    timestamp: new Date(now.getTime() - 5 * 60_000),
    yesPrice: 0.085,
    noPrice: 0.915,
    volume: 100,
    liquidity: 300,
    rawJson: { dryRun: true, phase: "baseline" }
  };
  const moved: MarketSnapshot = {
    marketId: market.id,
    timestamp: now,
    yesPrice: 0.241,
    noPrice: 0.759,
    volume: 2500,
    liquidity: 900,
    rawJson: { dryRun: true, phase: "moved" }
  };

  insertSnapshot(db, baseline);
  await processSnapshot(db, market, moved, notifier, dedupeMinutes);
  insertEventLog(db, {
    marketId: market.id,
    eventType: "official_announcement",
    source: "manual",
    title: "Dry-run example official announcement",
    timestamp: new Date(now.getTime() + 92 * 60_000),
    detailsUrl: "https://example.com/official-announcement",
    notes: "Example row showing how to audit alert timing against later public confirmation.",
    yesPrice: 0.9,
    outcome: "YES",
    rawContext: { dryRun: true }
  });
  console.log("\nEvent log:");
  printEventLog(db, market.id, 10);
  console.info("Dry-run complete");
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    dryRun: false,
    once: false,
    logEvent: false,
    eventType: "manual_note",
    eventSource: "manual",
    showEvents: false,
    limit: 20
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = (): string => {
      const value = argv[index + 1];
      if (!value) throw new Error(`${arg} requires a value`);
      index += 1;
      return value;
    };
    if (arg === "--dry-run") args.dryRun = true;
    else if (arg === "--once") args.once = true;
    else if (arg === "--watchlist") args.watchlist = next();
    else if (arg === "--log-event") args.logEvent = true;
    else if (arg === "--event-market-id") args.eventMarketId = next();
    else if (arg === "--event-type") args.eventType = next();
    else if (arg === "--event-title") args.eventTitle = next();
    else if (arg === "--event-source") args.eventSource = next();
    else if (arg === "--event-url") args.eventUrl = next();
    else if (arg === "--event-notes") args.eventNotes = next();
    else if (arg === "--show-events") args.showEvents = true;
    else if (arg === "--limit") args.limit = Number.parseInt(next(), 10);
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});

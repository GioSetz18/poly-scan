import "dotenv/config";

export interface AppConfig {
  telegramBotToken?: string;
  telegramChatId?: string;
  pollingIntervalSeconds: number;
  databasePath: string;
  alertDedupeMinutes: number;
  watchlistPath: string;
  logLevel: string;
}

function intEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) {
    throw new Error(`${name} must be an integer, got ${raw}`);
  }
  return parsed;
}

export function loadConfig(): AppConfig {
  return {
    telegramBotToken: process.env.TELEGRAM_BOT_TOKEN || undefined,
    telegramChatId: process.env.TELEGRAM_CHAT_ID || undefined,
    pollingIntervalSeconds: intEnv("POLLING_INTERVAL_SECONDS", 30),
    databasePath: process.env.DATABASE_PATH || "data/polymarket_ai_release_pinger.sqlite3",
    alertDedupeMinutes: intEnv("ALERT_DEDUPE_MINUTES", 15),
    watchlistPath: process.env.WATCHLIST_PATH || "watchlists/ai_model_releases.yml",
    logLevel: (process.env.LOG_LEVEL || "INFO").toUpperCase()
  };
}

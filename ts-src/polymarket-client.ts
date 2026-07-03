import type { MarketConfig, MarketSnapshot } from "./models.js";

type UnknownRecord = Record<string, unknown>;

export class PolymarketClient {
  constructor(private readonly timeoutMs = 12_000) {}

  async fetchMarketSnapshot(market: MarketConfig): Promise<MarketSnapshot> {
    const slug = slugFromUrl(market.url);
    if (!slug || market.url.includes("PASTE_MARKET_URL_HERE")) {
      throw new Error(`Market ${market.id} needs a real Polymarket URL`);
    }

    const raw = await this.fetchBySlug(slug);
    const normalized = normalize(raw);
    return {
      marketId: market.id,
      timestamp: new Date(),
      yesPrice: normalized.yesPrice,
      noPrice: normalized.noPrice,
      volume: normalized.volume,
      liquidity: normalized.liquidity,
      status: normalized.status,
      outcome: normalized.outcome,
      resolvedAt: normalized.resolvedAt,
      rawJson: raw
    };
  }

  private async fetchBySlug(slug: string): Promise<UnknownRecord> {
    const candidates: Array<[string, string]> = [
      ["event", `https://gamma-api.polymarket.com/events?slug=${encodeURIComponent(slug)}`],
      ["market", `https://gamma-api.polymarket.com/markets?slug=${encodeURIComponent(slug)}`]
    ];

    let lastError: unknown;
    for (const [source, url] of candidates) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
        const response = await fetch(url, {
          signal: controller.signal,
          headers: { "user-agent": "polymarket-ai-release-pinger-ts/0.1" }
        });
        clearTimeout(timeout);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as unknown;
        const item = firstItem(payload);
        if (item) return { source, payload: item };
      } catch (error) {
        lastError = error;
      }
    }

    throw new Error(`Could not fetch Polymarket data for slug ${slug}: ${String(lastError)}`);
  }
}

function slugFromUrl(url: string): string | null {
  const parsed = new URL(url);
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length === 0) return null;
  if ((parts[0] === "event" || parts[0] === "market") && parts.length > 1) return parts[1] ?? null;
  return parts.at(-1) ?? null;
}

function firstItem(payload: unknown): UnknownRecord | null {
  if (Array.isArray(payload)) return isRecord(payload[0]) ? payload[0] : null;
  if (isRecord(payload)) {
    const data = payload.data;
    if (Array.isArray(data) && isRecord(data[0])) return data[0];
    return payload;
  }
  return null;
}

function normalize(raw: UnknownRecord): {
  yesPrice: number | null;
  noPrice: number | null;
  volume: number | null;
  liquidity: number | null;
  status: string;
  outcome: string | null;
  resolvedAt: Date | null;
} {
  const payload = isRecord(raw.payload) ? raw.payload : raw;
  const market = pickMarket(payload);
  const yesPrice = extractYesPrice(market);
  return {
    yesPrice,
    noPrice: yesPrice === null ? null : Math.max(0, Math.min(1, 1 - yesPrice)),
    volume: numberValue(market.volume ?? market.volumeNum ?? payload.volume),
    liquidity: numberValue(market.liquidity ?? market.liquidityNum ?? payload.liquidity),
    status: extractStatus(market, payload),
    outcome: extractOutcome(market),
    resolvedAt: parseDate(market.resolvedAt ?? market.resolutionTime ?? market.closedTime ?? payload.resolvedAt)
  };
}

function pickMarket(payload: UnknownRecord): UnknownRecord {
  if (Array.isArray(payload.markets) && payload.markets.length > 0) {
    for (const item of payload.markets) {
      if (isRecord(item) && String(item.outcomes || "").toLowerCase().includes("yes")) return item;
    }
    if (isRecord(payload.markets[0])) return payload.markets[0];
  }
  return payload;
}

function extractYesPrice(market: UnknownRecord): number | null {
  for (const key of ["bestAsk", "lastTradePrice", "price", "yesPrice"]) {
    const value = numberValue(market[key]);
    if (value !== null) return normalizePrice(value);
  }
  const price = priceFromOutcomes(market.outcomes, market.outcomePrices);
  return price === null ? null : normalizePrice(price);
}

function priceFromOutcomes(outcomes: unknown, prices: unknown): number | null {
  const parsedOutcomes = maybeList(outcomes);
  const parsedPrices = maybeList(prices);
  if (!parsedPrices?.length) return null;
  if (parsedOutcomes?.length) {
    for (let index = 0; index < parsedOutcomes.length; index += 1) {
      if (String(parsedOutcomes[index]).toLowerCase() === "yes") {
        return numberValue(parsedPrices[index]);
      }
    }
  }
  return numberValue(parsedPrices[0]);
}

function extractStatus(market: UnknownRecord, payload: UnknownRecord): string {
  const explicit = market.status ?? market.marketStatus ?? payload.status ?? payload.marketStatus;
  if (explicit) return String(explicit).toLowerCase();
  if (boolValue(market.resolved ?? payload.resolved)) return "resolved";
  if (boolValue(market.closed ?? payload.closed)) return "closed";
  return "open";
}

function extractOutcome(market: UnknownRecord): string | null {
  for (const key of ["winningOutcome", "winner", "resolution", "resolvedOutcome"]) {
    if (market[key]) return String(market[key]);
  }
  const yesPrice = extractYesPrice(market);
  if (!boolValue(market.resolved ?? market.closed) || yesPrice === null) return null;
  if (yesPrice >= 0.99) return "YES";
  if (yesPrice <= 0.01) return "NO";
  return null;
}

function maybeList(value: unknown): unknown[] | null {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value) as unknown;
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return value.replace(/[[\]"]/g, "").split(",").map((item) => item.trim()).filter(Boolean);
    }
  }
  return null;
}

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizePrice(value: number): number {
  return value > 1 ? value / 100 : value;
}

function boolValue(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return ["true", "1", "yes", "resolved", "closed"].includes(value.toLowerCase());
  return Boolean(value);
}

function parseDate(value: unknown): Date | null {
  if (!value) return null;
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

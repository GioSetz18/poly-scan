import { readFileSync } from "node:fs";
import YAML from "yaml";

import type { AlertRules, MarketConfig } from "./models.js";

interface RawMarket {
  id: string;
  name: string;
  url: string;
  category?: string;
  company?: string;
  model_family?: string;
  event_type?: string;
  deadline?: string | null;
  tags?: string[];
  liquidity_tier?: string;
  enabled?: boolean;
  alert_rules?: Record<string, unknown>;
}

export function loadWatchlist(path: string): MarketConfig[] {
  const payload = YAML.parse(readFileSync(path, "utf8")) as { markets?: RawMarket[] } | null;
  return (payload?.markets || []).map((item) => ({
    id: String(item.id),
    name: String(item.name),
    url: String(item.url),
    category: String(item.category || ""),
    company: item.company,
    modelFamily: item.model_family,
    eventType: item.event_type,
    deadline: item.deadline ?? null,
    tags: (item.tags || []).map(String),
    liquidityTier: String(item.liquidity_tier || "medium"),
    enabled: item.enabled ?? true,
    alertRules: parseRules(item.alert_rules || {})
  }));
}

function parseRules(raw: Record<string, unknown>): AlertRules {
  return {
    priceMove1mPp: optionalNumber(raw.price_move_1m_pp),
    priceMove5mPp: optionalNumber(raw.price_move_5m_pp),
    priceMove15mPp: optionalNumber(raw.price_move_15m_pp),
    minAbsoluteVolume15mUsd: optionalNumber(raw.min_absolute_volume_15m_usd),
    deadMarketVolume15mUsd: optionalNumber(raw.dead_market_volume_15m_usd)
  };
}

function optionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return undefined;
  return parsed;
}

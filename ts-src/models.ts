export type Severity = "watch" | "interesting" | "urgent";

export interface AlertRules {
  priceMove1mPp?: number;
  priceMove5mPp?: number;
  priceMove15mPp?: number;
  minAbsoluteVolume15mUsd?: number;
  deadMarketVolume15mUsd?: number;
}

export interface MarketConfig {
  id: string;
  name: string;
  url: string;
  category: string;
  company?: string;
  modelFamily?: string;
  eventType?: string;
  deadline?: string | null;
  tags: string[];
  liquidityTier: string;
  enabled: boolean;
  alertRules: AlertRules;
}

export interface MarketSnapshot {
  marketId: string;
  timestamp: Date;
  yesPrice: number | null;
  noPrice: number | null;
  volume: number | null;
  liquidity: number | null;
  status?: string | null;
  outcome?: string | null;
  resolvedAt?: Date | null;
  rawJson: Record<string, unknown>;
}

export interface AlertCandidate {
  marketId: string;
  alertType: string;
  severity: Severity;
  message: string;
  yesPriceBefore: number | null;
  yesPriceAfter: number | null;
  priceMovePp: number | null;
  volumeWindow: number | null;
  rawContext: Record<string, unknown>;
}

export interface EventLogEntry {
  marketId: string;
  eventType: string;
  source: string;
  title: string;
  timestamp: Date;
  detailsUrl?: string | null;
  notes?: string | null;
  alertId?: number | null;
  yesPrice?: number | null;
  noPrice?: number | null;
  volume?: number | null;
  outcome?: string | null;
  rawContext?: Record<string, unknown>;
}

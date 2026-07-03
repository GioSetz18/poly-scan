import type { AlertCandidate, MarketConfig, MarketSnapshot, Severity } from "./models.js";

const severityRank: Record<Severity, number> = { watch: 1, interesting: 2, urgent: 3 };

export function evaluateMarket(
  market: MarketConfig,
  current: MarketSnapshot,
  recentSnapshots: MarketSnapshot[]
): AlertCandidate[] {
  if (current.yesPrice === null) return [];

  const alerts: AlertCandidate[] = [];
  for (const rule of [
    { minutes: 5, threshold: market.alertRules.priceMove5mPp, type: "price_move_5m" },
    { minutes: 15, threshold: market.alertRules.priceMove15mPp, type: "price_move_15m" }
  ]) {
    if (rule.threshold === undefined) continue;
    const previous = closestSnapshotAround(recentSnapshots, new Date(current.timestamp.getTime() - rule.minutes * 60_000));
    if (!previous || previous.yesPrice === null) continue;
    const movePp = (current.yesPrice - previous.yesPrice) * 100;
    if (Math.abs(movePp) >= rule.threshold) {
      alerts.push(buildPriceAlert(market, rule.type, rule.minutes, previous, current, movePp, rule.threshold));
    }
  }

  const previous15m = closestSnapshotAround(recentSnapshots, new Date(current.timestamp.getTime() - 15 * 60_000));
  const volumeWindow = volumeChange(previous15m, current);
  const volumeThreshold = market.alertRules.minAbsoluteVolume15mUsd;
  if (volumeThreshold !== undefined && volumeWindow !== null && volumeWindow >= volumeThreshold) {
    alerts.push(buildVolumeAlert(market, "volume_burst_15m", current, previous15m, volumeWindow, volumeThreshold));
  }

  const deadThreshold = market.alertRules.deadMarketVolume15mUsd ?? volumeThreshold;
  const priorLiquidity = previous15m?.liquidity ?? 0;
  const priorVolume = previous15m?.volume ?? 0;
  if (deadThreshold !== undefined && volumeWindow !== null && volumeWindow >= deadThreshold && priorLiquidity < 500 && priorVolume < 500) {
    alerts.push(buildVolumeAlert(market, "dead_market_wakes_up", current, previous15m, volumeWindow, deadThreshold));
  }

  return alerts;
}

export function shouldSendAlert(lastAlert: Record<string, unknown> | null, candidate: AlertCandidate): boolean {
  if (!lastAlert) return true;
  const previous = String(lastAlert.severity || "watch") as Severity;
  return severityRank[candidate.severity] > (severityRank[previous] ?? 1);
}

export function dedupeSince(minutes: number): Date {
  return new Date(Date.now() - minutes * 60_000);
}

function closestSnapshotAround(snapshots: MarketSnapshot[], target: Date, toleranceMs = 2 * 60_000): MarketSnapshot | null {
  const candidates = snapshots.filter((snapshot) => snapshot.timestamp.getTime() <= target.getTime() + toleranceMs);
  if (candidates.length === 0) return null;
  const closest = candidates.reduce((best, item) => {
    const bestDelta = Math.abs(best.timestamp.getTime() - target.getTime());
    const itemDelta = Math.abs(item.timestamp.getTime() - target.getTime());
    return itemDelta < bestDelta ? item : best;
  });
  return Math.abs(closest.timestamp.getTime() - target.getTime()) > toleranceMs ? null : closest;
}

function volumeChange(before: MarketSnapshot | null, after: MarketSnapshot): number | null {
  if (!before || before.volume === null || after.volume === null) return null;
  return Math.max(0, after.volume - before.volume);
}

function buildPriceAlert(
  market: MarketConfig,
  alertType: string,
  minutes: number,
  before: MarketSnapshot,
  current: MarketSnapshot,
  movePp: number,
  thresholdPp: number
): AlertCandidate {
  const volumeWindow = volumeChange(before, current);
  const severity = priceSeverity(Math.abs(movePp), thresholdPp, volumeWindow);
  return {
    marketId: market.id,
    alertType,
    severity,
    message: formatAlertMessage(market, alertType, severity, before.yesPrice, current.yesPrice, movePp, minutes, volumeWindow),
    yesPriceBefore: before.yesPrice,
    yesPriceAfter: current.yesPrice,
    priceMovePp: movePp,
    volumeWindow,
    rawContext: { thresholdPp, liquidityTier: market.liquidityTier }
  };
}

function buildVolumeAlert(
  market: MarketConfig,
  alertType: string,
  current: MarketSnapshot,
  previous: MarketSnapshot | null,
  volumeWindow: number,
  threshold: number
): AlertCandidate {
  const movePp = previous?.yesPrice !== null && previous?.yesPrice !== undefined && current.yesPrice !== null
    ? (current.yesPrice - previous.yesPrice) * 100
    : null;
  const severity = volumeSeverity(volumeWindow, threshold);
  return {
    marketId: market.id,
    alertType,
    severity,
    message: formatAlertMessage(market, alertType, severity, previous?.yesPrice ?? null, current.yesPrice, movePp, 15, volumeWindow),
    yesPriceBefore: previous?.yesPrice ?? null,
    yesPriceAfter: current.yesPrice,
    priceMovePp: movePp,
    volumeWindow,
    rawContext: { volumeThreshold: threshold, liquidityTier: market.liquidityTier }
  };
}

function priceSeverity(absMovePp: number, thresholdPp: number, volumeWindow: number | null): Severity {
  const volumeConfirmed = volumeWindow !== null && volumeWindow > 0;
  if (absMovePp >= thresholdPp * 2 || (absMovePp >= thresholdPp * 1.5 && volumeConfirmed)) return "urgent";
  if (absMovePp >= thresholdPp * 1.25 || volumeConfirmed) return "interesting";
  return "watch";
}

function volumeSeverity(volumeWindow: number, threshold: number): Severity {
  if (volumeWindow >= threshold * 3) return "urgent";
  if (volumeWindow >= threshold * 1.5) return "interesting";
  return "watch";
}

function formatAlertMessage(
  market: MarketConfig,
  alertType: string,
  severity: Severity,
  beforePrice: number | null,
  afterPrice: number | null,
  movePp: number | null,
  minutes: number,
  volumeWindow: number | null
): string {
  return [
    "🚨 Polymarket AI Release Alert",
    "",
    `Market: ${market.name}`,
    `Company: ${market.company || "n/a"}`,
    `Model family: ${market.modelFamily || "n/a"}`,
    `Type: ${alertType}`,
    `Severity: ${severity}`,
    "",
    `YES moved: ${formatPrice(beforePrice)} -> ${formatPrice(afterPrice)}`,
    `Move: ${movePp === null ? "n/a" : `${movePp >= 0 ? "+" : ""}${movePp.toFixed(1)} percentage points`} in ~${minutes} minutes`,
    `Liquidity tier: ${market.liquidityTier}`,
    `15m volume change: ${volumeWindow === null ? "n/a" : `+$${volumeWindow.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}`,
    "",
    "Why this matters:",
    "This is a high-specificity AI model release market. Sudden movement may indicate new public information, informed speculation, a leak, or thin-market manipulation. Check official sources before acting.",
    "",
    "Market:",
    market.url
  ].join("\n");
}

function formatPrice(value: number | null): string {
  return value === null ? "n/a" : `${(value * 100).toFixed(1)}%`;
}

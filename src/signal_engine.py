from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import AlertCandidate, MarketConfig, MarketSnapshot

SEVERITY_RANK = {"watch": 1, "interesting": 2, "urgent": 3}


def evaluate_market(
    market: MarketConfig,
    current: MarketSnapshot,
    recent_snapshots: list[MarketSnapshot],
) -> list[AlertCandidate]:
    if current.yes_price is None:
        return []

    alerts: list[AlertCandidate] = []
    for minutes, rule_value, alert_type in (
        (5, market.alert_rules.price_move_5m_pp, "price_move_5m"),
        (15, market.alert_rules.price_move_15m_pp, "price_move_15m"),
    ):
        if rule_value is None:
            continue
        previous = closest_snapshot_around(recent_snapshots, current.timestamp - timedelta(minutes=minutes))
        if previous and previous.yes_price is not None:
            move_pp = (current.yes_price - previous.yes_price) * 100.0
            if abs(move_pp) >= rule_value:
                volume_window = volume_change(previous, current)
                alerts.append(
                    build_price_alert(
                        market=market,
                        alert_type=alert_type,
                        minutes=minutes,
                        before=previous,
                        current=current,
                        move_pp=move_pp,
                        threshold_pp=rule_value,
                        volume_window=volume_window,
                    )
                )

    volume_threshold = market.alert_rules.min_absolute_volume_15m_usd
    if volume_threshold is not None:
        previous_15m = closest_snapshot_around(recent_snapshots, current.timestamp - timedelta(minutes=15))
        vol_window = volume_change(previous_15m, current) if previous_15m else None
        if vol_window is not None and vol_window >= volume_threshold:
            alerts.append(
                build_volume_alert(
                    market=market,
                    alert_type="volume_burst_15m",
                    current=current,
                    previous=previous_15m,
                    volume_window=vol_window,
                    threshold=volume_threshold,
                )
            )

    dead_threshold = market.alert_rules.dead_market_volume_15m_usd or volume_threshold
    previous_15m = closest_snapshot_around(recent_snapshots, current.timestamp - timedelta(minutes=15))
    if dead_threshold is not None and previous_15m:
        vol_window = volume_change(previous_15m, current)
        prior_liquidity = previous_15m.liquidity or 0.0
        prior_volume = previous_15m.volume or 0.0
        if vol_window is not None and vol_window >= dead_threshold and prior_liquidity < 500 and prior_volume < 500:
            alerts.append(
                build_volume_alert(
                    market=market,
                    alert_type="dead_market_wakes_up",
                    current=current,
                    previous=previous_15m,
                    volume_window=vol_window,
                    threshold=dead_threshold,
                )
            )

    return alerts


def closest_snapshot_around(
    snapshots: list[MarketSnapshot],
    target: datetime,
    tolerance: timedelta = timedelta(minutes=2),
) -> MarketSnapshot | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.timestamp <= target + tolerance]
    if not candidates:
        return None
    closest = min(candidates, key=lambda snapshot: abs(snapshot.timestamp - target))
    if abs(closest.timestamp - target) > tolerance:
        return None
    return closest


def volume_change(before: MarketSnapshot | None, after: MarketSnapshot) -> float | None:
    if before is None or before.volume is None or after.volume is None:
        return None
    return max(0.0, after.volume - before.volume)


def build_price_alert(
    market: MarketConfig,
    alert_type: str,
    minutes: int,
    before: MarketSnapshot,
    current: MarketSnapshot,
    move_pp: float,
    threshold_pp: float,
    volume_window: float | None,
) -> AlertCandidate:
    severity = price_severity(abs(move_pp), threshold_pp, volume_window)
    direction = "+" if move_pp >= 0 else ""
    message = format_alert_message(
        market=market,
        alert_type=alert_type,
        severity=severity,
        before_price=before.yes_price,
        after_price=current.yes_price,
        move_pp=move_pp,
        minutes=minutes,
        volume_window=volume_window,
    )
    return AlertCandidate(
        market_id=market.id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        yes_price_before=before.yes_price,
        yes_price_after=current.yes_price,
        price_move_pp=move_pp,
        volume_window=volume_window,
        raw_context={
            "threshold_pp": threshold_pp,
            "direction": direction,
            "liquidity_tier": market.liquidity_tier,
        },
    )


def build_volume_alert(
    market: MarketConfig,
    alert_type: str,
    current: MarketSnapshot,
    previous: MarketSnapshot | None,
    volume_window: float,
    threshold: float,
) -> AlertCandidate:
    severity = volume_severity(volume_window, threshold)
    message = format_alert_message(
        market=market,
        alert_type=alert_type,
        severity=severity,
        before_price=previous.yes_price if previous else None,
        after_price=current.yes_price,
        move_pp=None if previous is None or previous.yes_price is None or current.yes_price is None else (current.yes_price - previous.yes_price) * 100.0,
        minutes=15,
        volume_window=volume_window,
    )
    return AlertCandidate(
        market_id=market.id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        yes_price_before=previous.yes_price if previous else None,
        yes_price_after=current.yes_price,
        price_move_pp=None if previous is None or previous.yes_price is None or current.yes_price is None else (current.yes_price - previous.yes_price) * 100.0,
        volume_window=volume_window,
        raw_context={"volume_threshold": threshold, "liquidity_tier": market.liquidity_tier},
    )


def price_severity(abs_move_pp: float, threshold_pp: float, volume_window: float | None) -> str:
    volume_confirmed = volume_window is not None and volume_window > 0
    if abs_move_pp >= threshold_pp * 2 or (abs_move_pp >= threshold_pp * 1.5 and volume_confirmed):
        return "urgent"
    if abs_move_pp >= threshold_pp * 1.25 or volume_confirmed:
        return "interesting"
    return "watch"


def volume_severity(volume_window: float, threshold: float) -> str:
    if volume_window >= threshold * 3:
        return "urgent"
    if volume_window >= threshold * 1.5:
        return "interesting"
    return "watch"


def should_send_alert(last_alert: dict[str, str] | None, candidate: AlertCandidate) -> bool:
    if last_alert is None:
        return True
    return SEVERITY_RANK[candidate.severity] > SEVERITY_RANK.get(last_alert.get("severity", "watch"), 1)


def dedupe_since(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def format_alert_message(
    market: MarketConfig,
    alert_type: str,
    severity: str,
    before_price: float | None,
    after_price: float | None,
    move_pp: float | None,
    minutes: int,
    volume_window: float | None,
) -> str:
    before = _format_price(before_price)
    after = _format_price(after_price)
    move = "n/a" if move_pp is None else f"{move_pp:+.1f} percentage points"
    volume = "n/a" if volume_window is None else f"+${volume_window:,.0f}"
    return (
        "🚨 Polymarket AI Release Alert\n\n"
        f"Market: {market.name}\n"
        f"Company: {market.company or 'n/a'}\n"
        f"Model family: {market.model_family or 'n/a'}\n"
        f"Type: {alert_type}\n"
        f"Severity: {severity}\n\n"
        f"YES moved: {before} → {after}\n"
        f"Move: {move} in ~{minutes} minutes\n"
        f"Liquidity tier: {market.liquidity_tier}\n"
        f"15m volume change: {volume}\n\n"
        "Why this matters:\n"
        "This is a high-specificity AI model release market. Sudden movement may indicate new public "
        "information, informed speculation, a leak, or thin-market manipulation. Check official sources "
        "before acting.\n\n"
        f"Market:\n{market.url}"
    )


def _format_price(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"

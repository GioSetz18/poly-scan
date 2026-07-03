# polymarket-ai-release-pinger

A lightweight local-first Python bot that watches manually selected Polymarket markets related to AI model releases and sends Telegram alerts when abnormal market movement occurs.

This is a research and signal-detection tool. It does not trade, place orders, manage wallets, hold private keys, or tell you to buy or sell.

## What It Watches

The MVP is built for niche markets such as:

- Google Gemini model release markets
- Anthropic Claude model release markets
- OpenAI GPT or o-series release markets
- Meta Llama release markets
- xAI Grok release markets

These markets can move before official announcements because of public information, speculation, leaks, API sightings, press preparation, or thin-market manipulation. Alerts intentionally say "abnormal market move detected" rather than making legal or insider-trading claims.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:replace-with-your-token
TELEGRAM_CHAT_ID=123456789
POLLING_INTERVAL_SECONDS=30
DATABASE_PATH=data/polymarket_ai_release_pinger.sqlite3
ALERT_DEDUPE_MINUTES=15
WATCHLIST_PATH=watchlists/ai_model_releases.yml
```

## Create A Telegram Bot

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Copy the bot token into `TELEGRAM_BOT_TOKEN`.
4. Send a message to your new bot.
5. Find your chat id by visiting:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

Copy the chat id into `TELEGRAM_CHAT_ID`.

## Add Markets

Edit `watchlists/ai_model_releases.yml`.

```yaml
markets:
  - id: "gemini-pro-release-july-2026"
    name: "Next Google Gemini Pro model released before deadline"
    url: "https://polymarket.com/event/..."
    category: "ai_model_release"
    company: "Google"
    model_family: "Gemini"
    event_type: "release"
    deadline: "2026-07-15"
    tags:
      - "google"
      - "gemini"
      - "model-release"
    liquidity_tier: "tiny"
    enabled: true
    alert_rules:
      price_move_5m_pp: 8
      price_move_15m_pp: 12
      min_absolute_volume_15m_usd: 1000
```

Keep placeholder URLs disabled until you replace them with real Polymarket market URLs.

## Run

Run continuously:

```bash
.venv/bin/python -m src.main
```

Run one real polling cycle:

```bash
.venv/bin/python -m src.main --once
```

Run dry-run mode:

```bash
.venv/bin/python -m src.main --dry-run
```

Dry-run mode loads the watchlist, creates mock snapshots with a move from 8.5% to 24.1%, and prints the alert instead of sending Telegram.

## Alert Rules

Implemented alert types:

- `price_move_5m`
- `price_move_15m`
- `volume_burst_15m`
- `dead_market_wakes_up`

Severity levels:

- `watch`: threshold barely crossed
- `interesting`: stronger move or volume confirmation
- `urgent`: very strong move, or a strong move with volume confirmation

Alerts are deduplicated by market and alert type. By default, the bot will not send the same alert type for the same market again within 15 minutes unless severity increases.

## Percentage Points

Price movement uses percentage points, not relative percentage change.

Example:

- 8% to 23% is a +15 percentage point move.
- 5% to 10% is a +5 percentage point move, even though it doubled in relative terms.

## Storage

SQLite tables are created automatically:

- `markets`
- `market_snapshots`
- `alerts`
- `event_log`

Raw Polymarket responses are stored in `market_snapshots.raw_json` to make debugging easier. The bot also stores market `status`, observed `outcome`, and `resolved_at` when those fields are available from Polymarket.

## Event Log And Edge Audit

Telegram pings are only the real-time layer. The `event_log` table is the audit layer for answering questions later:

- When did the alert fire?
- When did an official announcement happen?
- Did YES continue moving after the alert?
- Did the market resolve YES or NO?
- Was there already public news?
- Was the alert useful or a false positive?

Automatic event rows:

- `alert_sent`: written whenever a Telegram or dry-run alert is emitted
- `market_outcome_observed`: written when a watched market appears closed/resolved or exposes an outcome

Add a manual official announcement or review note:

```bash
.venv/bin/python -m src.main --log-event \
  --event-market-id gemini-pro-release-july-2026 \
  --event-type official_announcement \
  --event-title "Google announces Gemini model update" \
  --event-url "https://example.com/source" \
  --event-notes "Compare this timestamp with the alert timestamp."
```

Show recent audit events:

```bash
.venv/bin/python -m src.main --show-events --limit 20
```

Show events for one market:

```bash
.venv/bin/python -m src.main --show-events --event-market-id gemini-pro-release-july-2026
```

After 30-50 alerts, this event log becomes a personal edge audit: you can compare alert timing, later price movement, public news timing, and final outcomes.

## Polymarket Data

`src/polymarket_client.py` is intentionally small and isolated. It resolves slugs from Polymarket URLs, tries public Gamma API event and market lookups, and normalizes YES price, NO price, volume, liquidity, and raw JSON.

If Polymarket changes endpoint behavior, update this module without touching storage, alerting, or signal logic.

## Non-Goals

- No auto-trading
- No private key handling
- No wallet intelligence
- No dashboard
- No X/Twitter scraping
- No automatic market discovery
- No AI summary layer
- No portfolio tracking
- No betting recommendations
- No legal claims about insider trading

## Future Extensions

The modules are separated so later versions can add:

- Automatic discovery of AI-related Polymarket markets
- Correlation clusters across related markets
- Wallet tracking
- News/RSS/official-source checks
- Social signal scanning
- Daily alert performance review
- Other categories such as sports injuries, awards, politics, product launches, and Google Trends markets

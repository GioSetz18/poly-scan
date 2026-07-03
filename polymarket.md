# Polymarket Quickguide

Source: https://docs.polymarket.com/quickstart

Last checked: 2026-07-03

This is a local reference for `polymarket-ai-release-pinger`. The bot is read-only: it fetches public market data, stores snapshots, detects abnormal movement, and sends alerts. It must not place trades, manage wallets, or handle private keys.

## Public Market Data

Polymarket market data endpoints are public and do not require an API key for basic reads.

Fetch active, open markets:

```bash
curl "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=1"
```

Useful fields from Gamma market responses commonly include:

- `question`
- `slug`
- `conditionId`
- `clobTokenIds`
- `outcomes`
- `outcomePrices`
- `volume`
- `liquidity`
- `active`
- `closed`
- `resolved`

For binary markets, `clobTokenIds` normally maps to:

```text
[YES token id, NO token id]
```

For this project, the most important fields are the market URL/slug, YES price, NO price, volume, liquidity, market status, and final outcome if available.

## Fetching By URL Slug

Polymarket URLs often contain a slug:

```text
https://polymarket.com/event/<event-or-market-slug>
```

The current bot extracts that slug and tries Gamma lookups like:

```text
https://gamma-api.polymarket.com/events?slug=<slug>
https://gamma-api.polymarket.com/markets?slug=<slug>
```

If the response is an event with multiple markets, the bot picks a binary YES/NO market where possible.

## Price Handling

Use percentage points for movement calculations.

Examples:

- `0.085 -> 0.241` is `+15.6 percentage points`
- `0.05 -> 0.10` is `+5.0 percentage points`, not `+100%`

Alert rules in this repo are named with `_pp` to make this explicit.

## Orderbook / CLOB Context

Polymarket also exposes CLOB tooling and SDKs for trading-oriented use cases. The official quickstart shows SDK setup and order placement, but this repo intentionally does not implement that part.

For a read-only alert bot:

- OK: fetch market metadata
- OK: fetch prices, volume, liquidity, status, outcomes
- OK: store snapshots and raw JSON
- OK: detect abnormal movement
- OK: send Telegram alerts
- Not OK: place orders
- Not OK: sign transactions
- Not OK: store private keys
- Not OK: provide buy/sell recommendations

## TypeScript Fetch Example

```ts
const response = await fetch(
  "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=1"
);
const markets = await response.json();
const market = markets[0];

console.log(market.question);
console.log(market.clobTokenIds);
```

## Python Fetch Example

```py
import requests

response = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={"active": "true", "closed": "false", "limit": 1},
)
markets = response.json()
market = markets[0]

print(market["question"])
print(market["clobTokenIds"])
```

## Bot Integration Notes

For this project, keep Polymarket-specific API details isolated in:

- Python: `src/polymarket_client.py`
- TypeScript: `ts-src/polymarket-client.ts`

Everything else should consume normalized snapshots:

```text
market_id
timestamp
yes_price
no_price
volume
liquidity
status
outcome
resolved_at
raw_json
```

This keeps the signal engine, SQLite storage, Telegram notifier, and event log independent from Polymarket endpoint changes.

## Edge Audit Fields

The most useful long-term research dataset comes from comparing alerts to later events.

Track:

- alert timestamp
- YES price at alert
- NO price at alert
- volume/liquidity at alert
- market URL
- official announcement timestamp
- source URL for public news
- later price movement
- final market outcome
- manual review note
- false positive / useful signal assessment

Relevant SQLite tables:

- `market_snapshots`
- `alerts`
- `event_log`

## Reference Links

- Polymarket Quickstart: https://docs.polymarket.com/quickstart
- Polymarket Documentation: https://docs.polymarket.com/
- Gamma markets endpoint example: https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=1

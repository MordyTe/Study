# Vendor Baseline — Bybit V5 Public Market API

**Baseline recorded:** 2026-07-25
**Base URL:** `https://api.bybit.com`
**Authentication:** none. Every endpoint used here is public and requires no API key.

Bybit V5 public market data is the sole exchange source of truth for this release.

## Official documentation consulted

| Topic | URL |
|---|---|
| Integration guide | https://bybit-exchange.github.io/docs/v5/guide |
| Instruments | https://bybit-exchange.github.io/docs/v5/market/instrument |
| Server time | https://bybit-exchange.github.io/docs/v5/market/time |
| Tickers | https://bybit-exchange.github.io/docs/v5/market/tickers |
| Historical klines | https://bybit-exchange.github.io/docs/v5/market/kline |
| Mark-price klines | https://bybit-exchange.github.io/docs/v5/market/mark-kline |
| Index-price klines | https://bybit-exchange.github.io/docs/v5/market/index-kline |
| Order book | https://bybit-exchange.github.io/docs/v5/market/orderbook |
| Open interest | https://bybit-exchange.github.io/docs/v5/market/open-interest |
| Funding history | https://bybit-exchange.github.io/docs/v5/market/history-fund-rate |
| Rate limits | https://bybit-exchange.github.io/docs/v5/rate-limit |

## Endpoints used

| Path | Purpose | Notes |
|---|---|---|
| `/v5/market/time` | Server time, clock drift | Every scan and every health check |
| `/v5/market/instruments-info` | Universe discovery | `limit=1000`, follows `nextPageCursor` to exhaustion |
| `/v5/market/tickers` | Tier-1 ranking, reconciliation | One call returns a whole category |
| `/v5/market/kline` | Candle history | `limit≤1000`, newest-first, reversed to ascending |
| `/v5/market/open-interest` | Derivatives context | Linear only; absence is never an error |
| `/v5/market/funding/history` | Funding context | Linear only |
| `/v5/market/mark-price-kline` | Basis context | Linear only; allowlisted, reserved |
| `/v5/market/index-price-kline` | Basis context | Linear only; allowlisted, reserved |
| `/v5/market/orderbook` | Spread and depth | Allowlisted; used sparingly, never for the whole universe |
| `/v5/market/recent-trade` | Tape context | Allowlisted, reserved |

## Response contract

Every endpoint returns the same envelope:

```json
{ "retCode": 0, "retMsg": "OK", "result": { … }, "retExtInfo": {}, "time": 1730000000000 }
```

The client parses `retCode` rather than trusting the HTTP status: a `200` with `retCode != 0` is treated as a failure. `retCode` values below 10006 and those in the known-permanent set are never retried.

## Interval identifiers

Used exactly as documented — `5`, `15`, `30`, `60`, `120`, `240`, `D`. The app's `Timeframe` union (`5m`…`1d`) maps to these in `TIMEFRAME_TO_INTERVAL`.

## Kline row shape

`[startTime, open, high, low, close, volume, turnover]`, all strings, **newest first**. The client reverses to ascending, coerces to numbers, drops malformed rows, and — for detection — discards the final still-open candle.

## Instrument eligibility

**Spot:** `status === "Trading"`, `quoteCoin === "USDT"`, excluding stock tokens (`XSTOCK`) and leveraged tokens (symbols matching `\d[LS]USDT$`).

**Linear:** `status === "Trading"`, `quoteCoin === "USDT"`, `settleCoin === "USDT"`, `contractType === "LinearPerpetual"`, excluding instruments whose `launchTime` is in the future (pre-listing).

Spot and linear are distinct market identities throughout the system: `spot:BTCUSDT` and `linear:BTCUSDT` are different instruments with separate opportunities, fingerprints, and history.

> **Pagination is not optional.** Linear routinely exceeds 500 instruments. `getInstruments` loops on `nextPageCursor` (bounded at 20 pages as a runaway guard). The live verification asserts more than ~300 linear instruments specifically to catch a regression that reads only the first page.

## Rate limits

The client reads `X-Bapi-Limit`, `X-Bapi-Limit-Status`, and `X-Bapi-Limit-Reset-Timestamp` and surfaces them on the Health page. Actual usage is far below the documented public limits: Tier 1 costs two requests per scan for the entire universe, and Tier 2 is bounded by the configurable candidate cap.

Retries apply only to safe idempotent reads, with exponential backoff plus jitter, capped at two attempts. `429` and `5xx` are retried; validation errors never are.

## Not used

- **WebSocket streams.** See `docs/ARCHITECTURE.md` ADR-001 for the reasoning and the tradeoff.
- **Every private endpoint.** Order, position, account, asset, and user endpoints are on the forbidden-fragment list and blocked at runtime. See `docs/SECURITY.md`.

## Re-verification

Bybit can change field names, add instrument statuses, or adjust limits. Re-check this baseline when:

- the live verification starts failing without a code change,
- instrument counts shift sharply,
- a new `contractType` or `status` value appears in the wild.

Update this file with the new date and what changed.

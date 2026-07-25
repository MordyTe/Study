# Architecture

## Deployment topology

```
┌──────────────────────────── Vercel ────────────────────────────┐
│                                                                 │
│  Next.js App Router (TypeScript strict)                         │
│                                                                 │
│  Pages (client)          API routes (server, Node runtime)      │
│  ─────────────           ──────────────────────────────         │
│  Command Center   ───►   /api/market      live universe + rank   │
│  Live Scanner     ───►   /api/opportunities                      │
│  Opportunity      ───►   /api/opportunities/[id]                 │
│  Asset            ───►   /api/market?view=asset|klines           │
│  Backtest         ───►   /api/backtest                           │
│  Settings         ───►   /api/settings                           │
│  Health           ───►   /api/health, /api/verify-live           │
│  Alerts           ───►   /api/alerts, /api/telegram/test         │
│                                                                 │
│  Vercel Cron (*/15 * * * *)  ───►  /api/scan                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
  api.bybit.com          Supabase Postgres        api.telegram.org
  (public GET only,      (optional; in-memory     (outbound only)
   no credentials)        fallback otherwise)
```

## ADR-001 — REST at candle close, not a persistent WebSocket worker

**Context.** The system must run on Vercel. Vercel functions are short-lived; a long-running WebSocket connection cannot survive there, and a WebSocket worker would need a separate always-on host.

**Decision.** Poll the official REST endpoints on a cron cadence and detect on **closed candles only**.

**Why this is not a compromise for this product.** The specification already requires that a `CONFIRMED` opportunity be built from closed, reconciled candles — `confirm=true` data. WebSocket streaming exists to deliver sub-second tick updates, which by definition cannot participate in a closed-candle decision. Polling `/v5/market/kline` after each candle boundary yields exactly the same closed candles the stream would have delivered, plus the REST reconciliation step the spec demands anyway.

**What is genuinely traded away.**

| Lost | Impact |
|---|---|
| Sub-second price updates in the UI | The dashboard refreshes on a 20–30s poll instead of streaming ticks. |
| Order-book depth and trade-tape microstructure | Tier-2 confirmation uses candles, ticker, open interest and funding rather than L2 depth. |
| Instant `FORMING` updates mid-candle | Forming patterns update at scan cadence, not per tick. |

**Escape hatch.** `BybitPublicMarketDataAdapter` is the only module that touches the exchange. Adding a WebSocket layer later means adding a new module behind the same interface and running it on a persistent host — no detector, scorer, or UI code changes.

## ADR-002 — Zero-configuration first run

**Decision.** The app is fully functional with **no environment variables at all**.

Bybit public market data needs no credentials, so the scanner, all twelve detectors, the charts and the backtester work on the first deploy. `getStore()` resolves to a module-scoped in-memory store when Supabase is not configured; both implement the same `Store` interface, so nothing downstream knows the difference. The Settings page reports which integrations are live and gives the exact steps for the rest.

The in-memory store is honestly labelled as non-durable in the UI, on the Health page, and in the API response — not silently presented as persistence.

## ADR-003 — Target normalization lives in the registry, not the detectors

**Context.** During end-to-end testing the engine produced setups with a reward-to-risk of `0.19` and even `-0.03` — a "target" behind the entry. Root cause: detectors derive targets from geometry (measured moves, ATR extensions), but the invalidation comes from *structure*. When the structural stop is far away, or price has already run past the measured move, the resulting arithmetic is untradeable.

**Decision.** `runDetector()` in `src/lib/patterns/registry.ts` post-processes every candidate through `finalizeTargets()`, which guarantees each target lies strictly ahead of the entry and clears a minimum R multiple (1.5R for T1, 3R for T2), preserving the geometric level whenever it is already further out.

**Why here and not in each detector.** A future detector cannot forget a rule it does not have to remember. The live scanner, the backtester and the tests all call `runDetector` / `runAllDetectors`, so live and historical behaviour cannot diverge — which is the entire point of reusing production code in the backtester.

## Data flow through one scan

1. `GET /v5/market/time` — server time; clock drift feeds the verification record.
2. `getUniverse(category)` — `instruments-info` with full `nextPageCursor` pagination, cached for one hour. Filters: `status=Trading`, `quoteCoin=USDT`; linear additionally requires `settleCoin=USDT` and `contractType=LinearPerpetual`; spot excludes stock tokens and leveraged tokens.
3. `getTickers(category)` — one call returns the whole category.
4. `rankTier1()` — pure function scoring liquidity (log-scaled), volatility, position within the 24h range, momentum, and funding pressure. Applies turnover, spread, age, and mute filters.
5. For the top N candidates: `getKlines(300)`, drop the open candle, `buildIndicatorSnapshot()`, `runAllDetectors()`.
6. `buildVerificationRecord()` — candle integrity, gap count, ticker-vs-close reconciliation with an ATR-aware tolerance, clock drift, data age. Produces `HEALTHY | DEGRADED | STALE | DISCONNECTED | RECOVERING`.
7. `scoreCandidate()` — seven components, explicit penalties, attributable detail per component.
8. Fingerprint → dedupe against the store → cooldown check → persist.
9. `CONFIRMED` + Telegram configured + outside quiet hours → alert, with an idempotency key so a retry never double-sends.
10. Lifecycle sweep over tracked opportunities against fresh prices.

## Determinism

Given identical candles and settings, the pipeline produces byte-identical opportunities — asserted in `tests/pipeline.test.ts`. Wall-clock is used only for staleness and cooldown, never in detection or scoring geometry. This is what makes the backtester's reuse of production code meaningful.

## Performance

- Tier 1 costs 2 REST calls and covers the entire universe.
- Tier 2 costs roughly `candidates × timeframes` calls, bounded by `tier2Candidates` (default 60) and a 45-second wall-clock budget inside a 60-second function limit.
- When the budget is reached the scan records how many candidates were deferred rather than silently truncating.
- The universe cache (1 hour TTL) removes instrument pagination from the hot path.
- The dashboard never loads full candle history for the scanner table; charts fetch per-instrument on demand.

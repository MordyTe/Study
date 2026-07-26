# Bybit Pattern Scanner

A production-quality, **analysis-only** market pattern scanner for the full Bybit USDT universe — spot and USDT-settled linear perpetuals. It discovers instruments, ranks the entire market, detects twelve classes of technical pattern on verified closed candles, scores each setup with an explainable 0–100 breakdown, tracks the scenario forward, and sends Telegram alerts.

> ## ⛨ Analysis only — this system cannot execute trades
>
> This is a hard architectural boundary, not a setting.
>
> - No order creation, amendment, cancellation, position management, leverage, transfer, or withdrawal code exists anywhere in the repository.
> - **No Bybit API key is required or accepted.** A startup guard throws if `BYBIT_API_KEY` or `BYBIT_API_SECRET` is present in the environment.
> - Every outbound exchange request is validated against an explicit allowlist of public GET market-data endpoints before a socket opens.
> - `tests/no-trading-guard.test.ts` statically scans the source and **fails the build** if a forbidden trading path, private WebSocket URL, or trade-action UI control ever appears.

---

## Deploy in 3 minutes

The app runs on **live Bybit market data with zero configuration**. No API keys, no database, no setup. Everything else is optional and can be added later from the Settings screen.

### 1. Import to Vercel

1. Go to **[vercel.com/new](https://vercel.com/new)**
2. Import this GitHub repository
3. Framework preset: **Next.js** (auto-detected). Leave every other field at its default.
4. Press **Deploy**

That's it. The dashboard comes up live against `api.bybit.com` — hundreds of instruments, real prices, working charts.

### 2. Confirm it is really live

Open your deployment and go to **System Health → Run live verification**. It executes six checks against the real exchange right now:

| Check | What it proves |
|---|---|
| No trading credentials present | The no-trading guarantee holds in this deployment |
| Bybit server time | REST reachability and clock drift |
| Spot instruments | USDT spot universe discovery |
| Linear perpetuals | Full `nextPageCursor` pagination (fails if it stops at one page) |
| Live tickers | Real-time prices, including BTCUSDT |
| Klines + integrity | Candle boundary alignment, monotonicity, OHLC sanity, gaps |
| REST reconciliation | Kline close agrees with an independently fetched ticker |

You can also hit `GET /api/verify-live` directly — it returns `200` when everything passes and `503` when anything fails.

### 3. Optional: unlock persistence and alerts

Add these in **Vercel → Settings → Environment Variables**, then redeploy. Every one is optional.

| Variable | What it unlocks | How to get it |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL`<br>`SUPABASE_SERVICE_ROLE_KEY` | Durable opportunity history across deploys | Create a project at [supabase.com](https://supabase.com), then run `supabase/migrations/0001_init.sql` in the SQL Editor |
| `TELEGRAM_BOT_TOKEN`<br>`TELEGRAM_CHAT_ID` | Telegram alerts for confirmed setups | Message [@BotFather](https://t.me/BotFather) → `/newbot` for the token; message [@userinfobot](https://t.me/userinfobot) for your chat id |
| `CRON_SECRET` | Requires a bearer token on `/api/scan` | Any random string. Vercel Cron supplies it automatically once set. |
| `ADMIN_PASSWORD` | Password-protects saving settings | Any string you choose |

The **Settings** page shows a live connection status for each integration and the exact steps for anything not yet configured — you never have to read this file again to operate the system.

### 4. Scanning cadence

`vercel.json` ships a **daily** cron (`0 6 * * *`) because that is the finest granularity the **Vercel Hobby plan accepts** — a sub-daily schedule makes Vercel reject the deployment outright, before the build even starts.

A scanner that runs once a day is not much of a scanner, so pick one of these:

| Option | Cadence | Cost | How |
|---|---|---|---|
| **Scan now button** | On demand | Free | Command Center → **Scan now**. Always available. |
| **External cron** (recommended on Hobby) | Any | Free | Point [cron-job.org](https://cron-job.org) or UptimeRobot at `https://<your-app>.vercel.app/api/scan` every 15 minutes. If you set `CRON_SECRET`, add the header `Authorization: Bearer <secret>`. |
| **Vercel Pro** | Any | Paid | Change the schedule in `vercel.json` to `*/15 * * * *` and redeploy. |

---

## What it does

```
Bybit V5 public REST  ──►  Tier 1: rank the whole universe (1 call per category)
   instruments-info          liquidity · volatility · range position · funding pressure
   tickers                              │
   kline                                ▼
   open-interest             Tier 2: full analysis of the top N candidates
   funding/history           300 closed candles → indicators → 12 detectors → verification
                                         │
                                         ▼
                             Tier 3: score, de-duplicate, persist, track, alert
                             0–100 breakdown · lifecycle · Telegram · dashboard
```

**Tier 1** covers every eligible instrument on every scan using one `tickers` call per category — hundreds of instruments for two HTTP requests. **Tier 2** promotes the highest-energy candidates to full pattern analysis. **Tier 3** persists confirmed setups and tracks them forward.

### The twelve detectors

| Detector | Fires on |
|---|---|
| `structure_trend` | Break of Structure / Change of Character on ATR-adaptive swings |
| `breakout_retest` | Close beyond a clustered level, then retest and hold |
| `level_rejection` | Dominant wick rejection at a multi-touch level |
| `double_top_bottom` | Two comparable pivots + neckline close |
| `head_shoulders` | Prominent head, symmetric shoulders, neckline close |
| `triangle` | Ascending / descending / symmetrical, with real convergence |
| `wedge` | Rising (bearish) / falling (bullish), same-direction slopes |
| `flag_channel` | Impulse pole + controlled retracement + continuation break |
| `volatility_squeeze` | Bollinger inside Keltner, then a directional expansion bar |
| `momentum_divergence` | Regular bullish/bearish RSI divergence with a trigger |
| `volume_breakout` | Range expansion on statistically abnormal volume |
| `candlestick_context` | Engulfing / pin bar **only** at a level and against a stretched move |

Every detector is deterministic, versioned, free of lookahead, and returns a full evidence bundle: anchor pivots, fit quality, indicator values, confirmation bar, invalidation condition, entry scenario, targets with their derivation method, and reasons for *and against*.

### What makes a setup CONFIRMED

All four must hold. Any one failing leaves it at `FORMING`, which is recorded but never alerted:

1. Setup Quality ≥ the confirmed threshold (default 75)
2. Reward-to-risk ≥ the minimum (default 2.0)
3. The data verification record is fully `HEALTHY` — reconciliation passed, zero candle gaps, clock drift and data age inside tolerance
4. Only **closed** candles were used

This is deliberately strict. An empty opportunity deck is a valid, honest result.

---

## Setup Quality is not a win probability

The 0–100 score measures how **well-formed and well-supported** a setup is. It is not a prediction.

| Component | Max |
|---|---|
| Pattern geometry and fit | 25 |
| Confirmation quality | 20 |
| Structure / regime alignment | 15 |
| Volume and momentum | 15 |
| Multi-timeframe alignment | 10 |
| Liquidity and spread | 10 |
| Data verification | 5 |

Penalties are then subtracted for poor asymmetry, thin turnover, wide spread, very new listings, incomplete history, an opposing level blocking the path, crowded funding, and staleness. Every point is attributable and shown in the UI.

**No probability percentage is displayed anywhere**, because presenting one would require a separately validated calibration model built on a large sample of resolved outcomes with an out-of-sample Brier score and reliability curve. Until that exists, a percentage would be dishonest.

---

## Local development

```bash
npm install
npm run dev          # http://localhost:3000

npm run test         # 104 tests: indicators, detectors, engine, pipeline, security
npm run typecheck    # TypeScript strict, zero errors
npm run build        # production build
npm run check        # typecheck + tests
```

Local dev needs no `.env` file at all. Copy `.env.example` to `.env.local` only when adding Supabase or Telegram.

---

## Project layout

```
src/
  lib/
    bybit/           allowlist.ts (SECURITY BOUNDARY) · client.ts · types.ts
    ta/              indicators.ts · structure.ts (pivots, levels, trendlines)
    patterns/        types.ts (contract + target normalization) · registry.ts
                     detectors/  structure-trend · breakout · reversal
                                 consolidation · momentum
    engine/          scanner.ts (tiered scan) · scoring.ts · opportunity.ts
                     verification.ts · backtest.ts
    store/           index.ts (memory fallback) · supabase-store.ts
    telegram/        client.ts
    config/          settings.ts
  app/
    api/             scan · verify-live · market · opportunities · settings
                     health · alerts · patterns · backtest · telegram/test
    (pages)          Command Center · Scanner · Opportunities · Opportunity detail
                     Asset · Patterns · Backtest · Alerts · Health · Settings · About
supabase/migrations/ 0001_init.sql
tests/               6 suites, 104 tests
docs/                architecture, security, scoring, deployment, vendor baseline
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Full deploy walkthrough, environment variables, cron, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Tiered scan design, data flow, why REST-at-close rather than a WebSocket worker |
| [docs/SECURITY.md](docs/SECURITY.md) | No-trading boundary, threat model, allowlist, RLS |
| [docs/SCORING_MODEL.md](docs/SCORING_MODEL.md) | Score components, penalties, and the probability boundary |
| [docs/PATTERN_CATALOG.md](docs/PATTERN_CATALOG.md) | Every detector's logic, parameters, and failure modes |
| [docs/VENDOR_BASELINE.md](docs/VENDOR_BASELINE.md) | Official Bybit V5 endpoints used, verified with dates |
| [docs/STATUS.md](docs/STATUS.md) | Build status, what is verified, what needs the owner |

---

## Risk disclosure

Cryptocurrency trading involves substantial risk of loss and is not suitable for everyone. Leveraged perpetual futures can lose more than the initial margin. Nothing in this application is financial advice, a recommendation, or a solicitation. Backtest figures are simulated signal outcomes, not executed trades, and past behaviour does not predict future results. You alone are responsible for every decision you make with your own capital.

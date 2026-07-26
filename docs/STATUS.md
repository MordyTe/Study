# Status

**Build date:** 2026-07-25
**Version:** 1.0.0

## Verified in this environment

| Gate | Result |
|---|---|
| TypeScript strict typecheck | ✅ zero errors |
| Test suite | ✅ **104 / 104 passing** across 6 suites |
| No-trading static guard | ✅ 9 checks pass — no forbidden path, private socket, execution module, or trade-action UI anywhere in `src/` |
| Production build | ✅ compiles, 12 routes generated |
| Server boot | ✅ `next start` serves all 9 pages with HTTP 200 |
| API routes | ✅ `/api/health`, `/api/settings`, `/api/patterns` return correct JSON |
| Zero-config operation | ✅ app runs with no environment variables set |

### Test coverage by suite

| Suite | Tests | Covers |
|---|---|---|
| `indicators.test.ts` | 21 | SMA/EMA/ATR/RSI/MACD/Bollinger/z-score/CLV/slope against hand calculations |
| `detectors.test.ts` | 15 | Registry integrity, shared contract across five fixture regimes, no-lookahead determinism |
| `targets.test.ts` | 13 | Target normalization; asserts no detector can emit a non-positive R:R |
| `engine.test.ts` | 38 | Scoring components and penalties, fingerprinting, lifecycle, verification, Tier-1 ranking, settings, store, Telegram formatting |
| `pipeline.test.ts` | 8 | Full path: indicators → detectors → scoring → opportunity → gating → dedupe → alert formatting |
| `no-trading-guard.test.ts` | 9 | Security boundary |

## NOT verified in this environment — requires the deployment

The build sandbox blocks outbound access to `api.bybit.com` at the network-policy layer (`403` on CONNECT from the egress proxy). Vercel's network does not.

**Therefore the following are implemented and unit-tested, but have not executed against the live exchange from here:**

- Live instrument discovery and counts
- Live tickers, klines, open interest, funding
- REST reconciliation against real market data
- A real end-to-end scan producing real opportunities

**How to verify after deploying** — one click, no CLI:

1. Open the deployment → **System Health → Run live verification**
2. Seven checks run against `https://api.bybit.com` immediately

`GET /api/verify-live` returns `200` with instrument counts and a live BTCUSDT price when everything passes, `503` with per-check detail when anything fails. Nothing in this repository can fake that result — it is a live network call.

## Owner action required

| # | Action | Needed for | Optional |
|---|---|---|---|
| 1 | Import the repo at [vercel.com/new](https://vercel.com/new) and deploy | Everything | **No** — this is the only required step |
| 2 | Run **System Health → Run live verification** | Proving live data | **No** |
| 3 | Create a Supabase project, run `supabase/migrations/0001_init.sql`, add `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | Durable history | Yes |
| 4 | Create a bot with @BotFather, add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram alerts | Yes |
| 5 | Set `CRON_SECRET` | Protecting `/api/scan` | Yes |

Everything in step 3–5 is reported live on the **Settings** page with its exact setup steps, so the app is self-documenting for the operator.

## Bugs found and fixed during build

Two genuine defects were caught by the end-to-end pipeline test and fixed, not worked around:

**1. `findPivots` returned zero pivots on real-shaped data.** Prominence was measured as the gap to the single nearest neighbour, which in any smooth trend is a rounding error, so effectively every swing was rejected — and with no pivots, no levels, no structure, and no structural detector could ever fire. Fixed to measure swing depth against the window's opposing extreme (`src/lib/ta/structure.ts`).

**2. Detectors emitted untradeable scenario arithmetic.** Observed R:R values of `0.19` and `-0.03` — the latter meaning the "target" sat behind the entry. Root cause: targets come from geometry while invalidation comes from structure, so a wide structural stop or a move that already ran past its measured move produces nonsense. Fixed with `finalizeTargets()` applied centrally in `runDetector()`, so no future detector can reintroduce it (`src/lib/patterns/types.ts`, `src/lib/patterns/registry.ts`).

Both fixes are covered by dedicated regression tests.

## Known limitations

| Limitation | Detail |
|---|---|
| No WebSocket streaming | Deliberate — see `docs/ARCHITECTURE.md` ADR-001. Detection uses closed candles, which the spec requires anyway. Cost: no sub-second updates, no L2 depth in Tier 2. |
| Scan cadence is 15 minutes | Vercel Cron minimum practical interval for this workload. `Scan now` is always available. |
| In-memory store is not durable | Clearly labelled in the UI, on Health, and in API responses. Supabase removes it. |
| No probability displayed | Deliberate — see `docs/SCORING_MODEL.md`. Requires a validated calibration model that does not yet exist. |
| Backtest liquidity components held neutral | Historical per-bar turnover and spread are not reconstructable from the kline endpoint. Documented in every backtest result's assumptions list rather than fabricated. |
| Telegram sends text, not a rendered chart image | The message carries all scenario levels and a dashboard deep link. Server-side chart rendering would require an image pipeline not available in this runtime. |
| No Playwright/visual regression suite | Pages were verified by HTTP smoke test (all 200) rather than screenshot review; a browser was not driven in this environment. |

## Next steps

1. Deploy and run the live verification.
2. Let the cron run for a day, then open **Alerts → Scan history** to see real throughput.
3. Run the **Backtest Lab** on BTCUSDT 1h before trusting any threshold — and read the assumptions block, not just the hit rate.
4. Tune thresholds in **Settings** based on what the backtest shows, not on how busy the dashboard feels.

# Working in this repository

## The one rule that overrides everything

**This application must never gain the ability to place a trade.**

Before writing any code that touches the exchange, read `docs/SECURITY.md`. The boundary is enforced at four layers and `tests/no-trading-guard.test.ts` fails the build if any of them is breached. If that test ever fails, the change is wrong — not the test.

Never add `BYBIT_API_KEY`, `BYBIT_API_SECRET`, an order endpoint, a private WebSocket, or a trade-action UI control. Never add a "just for testing" execution stub; a stub is where a boundary starts to erode.

## Commands

```bash
npm run dev        # local dev, no .env required
npm run check      # typecheck + full test suite — run before every commit
npm run test       # 104 tests
npm run typecheck  # TypeScript strict
npm run build      # production build
```

## Architecture in one paragraph

A Next.js App Router app on Vercel. `src/lib/bybit/client.ts` is the **only** module that talks to the exchange, over an allowlisted set of public GET endpoints. `src/lib/engine/scanner.ts` runs a tiered scan: Tier 1 ranks the whole universe from one `tickers` call per category, Tier 2 pulls candles for the top candidates and runs all twelve detectors, Tier 3 scores, de-duplicates, persists, tracks, and alerts. Storage is behind a `Store` interface with an in-memory implementation so the app works with zero configuration and a Supabase implementation for durability.

## Invariants

| Invariant | Where enforced |
|---|---|
| Detection uses **closed candles only** | `analyzeInstrument` drops the open candle before anything else |
| No lookahead | Detectors receive `candles[0..i]`; asserted in `tests/detectors.test.ts` |
| Determinism | Same candles + settings → byte-identical output; asserted in `tests/pipeline.test.ts` |
| Every scenario is tradeable arithmetic | `finalizeTargets()` in `runDetector()`; asserted in `tests/targets.test.ts` |
| `CONFIRMED` requires verified data | `isVerifiedForConfirmation()` gates the status transition |
| Backtester reuses production code | `runDetector` is the shared entry point — never write a second detection path |

## Adding a detector

Implement `PatternDetector`, register it in `src/lib/patterns/registry.ts`, add fixtures. The shared contract tests apply automatically. Bump `version` on any logic change — versions are part of the opportunity fingerprint, which is what keeps historical results reproducible.

Do not apply target normalization inside your detector. Return your geometric targets; `runDetector` handles the rest. See `docs/ARCHITECTURE.md` ADR-003 for why.

## Honesty rules

These are product requirements, not style preferences:

- Never display a probability or win rate that has not been calibrated out-of-sample. See `docs/SCORING_MODEL.md`.
- Never show a hit rate on a sample too small to mean anything — the Pattern Library withholds it below five resolved signals.
- Never present simulated backtest results as achieved returns.
- Never let the UI imply the system acted on a setup. It never does.
- An empty opportunity deck is a valid result. Do not loosen thresholds to make the dashboard look busy.

## Style

TypeScript strict with `noUncheckedIndexedAccess`. Comments explain **why**, not what. Match the surrounding file's density and idiom. Every user-visible number needs a unit and a source.

# Pattern Catalog

Twelve detectors, all deterministic, versioned, and free of lookahead. Each returns a full evidence bundle plus reasons for **and against**.

Every detector implements the same contract (`src/lib/patterns/types.ts`) and is post-processed by `runDetector()` so scenario arithmetic is always tradeable — see `docs/ARCHITECTURE.md` ADR-003.

---

## `structure_trend` — Market Structure Break · v1.0.0

**Fires on** a Break of Structure (continuation) or Change of Character (early reversal), confirmed by a candle **close** beyond the relevant swing, with ADX ≥ 18 for BOS.

**Key parameters** `atrBufferMult: 0.6` · `minAdx: 18` · `target1Atr: 1.5` · `target2Atr: 3.0`

**Fails when** the trend is exhausted and the break is the final push. CHoCH in particular is an early warning — the prior trend frequently resumes.

---

## `breakout_retest` — Breakout + Retest · v1.0.0

**Fires on** a close beyond a level clustered from repeated swing touches, followed by a return to the level and a hold. **Wick-only penetration is explicitly rejected** — the break must be a body close at least 0.15 ATR beyond the level.

**Key parameters** `minLevelTouches: 2` · `minLevelStrength: 0.35` · `retestToleranceAtr: 0.5` · `invalidationBufferAtr: 0.7`

**Fails when** the breakout was a liquidity grab. A close back through the level invalidates immediately.

---

## `level_rejection` — Support / Resistance Rejection · v1.0.0

**Fires on** a candle whose rejection wick is ≥50% of its range at a level with ≥0.45 strength, closing back on the rejecting side with a confirming close-location value.

**Fails when** the level has been tested so often it is about to break. A single rejection candle needs follow-through.

---

## `double_top_bottom` — Double Top / Bottom · v1.0.0

**Fires on** two pivots within 0.8 ATR of each other, separated by 5–60 bars, with a neckline at the intervening extreme, confirmed by a **neckline close**. Pattern height must exceed 0.8 ATR and the break must be within 25 bars of the second pivot.

**Fails when** the broader trend strongly opposes the reversal.

---

## `head_shoulders` — Head & Shoulders / Inverse · v1.0.0

**Fires on** three same-kind pivots where the head is ≥0.8 ATR beyond both shoulders, shoulder asymmetry is within tolerance, and price closes through a neckline fitted from the intervening opposite pivots.

**Fails when** mis-identified — this is the most over-detected classical pattern. A fast neckline reclaim usually means the break was a liquidity grab.

---

## `triangle` — Ascending / Descending / Symmetrical · v1.0.0

**Fires on** upper and lower trendlines fitted through recent pivots with R² ≥ 0.55 each, ≥25% genuine convergence across the pattern, and a close beyond a boundary **before the apex**.

Variant is classified from normalized boundary slopes: flat top + rising bottom = ascending, flat bottom + falling top = descending, otherwise symmetrical.

**Fails when** the first close beyond a boundary reverses — common. Boundaries are zones, not exact lines.

---

## `wedge` — Rising / Falling · v1.0.0

**Fires on** converging boundaries sloping in the **same** direction (that is what separates a wedge from a triangle), with ≥20% convergence and a confirming close. Rising wedge is bearish; falling wedge is bullish.

**Fails when** the wedge sits inside a strong opposing trend, where it often continues rather than reverses. This is the most subjective pattern in the catalog — boundary selection materially changes the read.

---

## `flag_channel` — Bull / Bear Flag · v1.0.0

**Fires on** an impulse pole spanning ≥2.5 ATR followed by a controlled channel retracing 15–62% of it, then a close beyond the channel.

**Rejects** retracements deeper than 62% — that is trend failure, not consolidation.

**Fails when** the impulse was the end of a move rather than the start of one.

---

## `volatility_squeeze` — Squeeze Expansion · v1.0.0

**Fires on** ≥4 consecutive bars with Bollinger Bands inside the Keltner Channels (compression), followed by an expansion bar whose range ≥0.9 ATR closing beyond the prior band.

**Compression alone is never a signal** — it indicates stored energy but says nothing about direction. The directional read comes only from the expansion bar.

**Fails when** the release whipsaws, which it frequently does on the first attempt.

---

## `momentum_divergence` — RSI Divergence · v1.0.0

**Fires on** regular bullish or bearish divergence: price makes a new extreme while RSI does not, by at least 3 RSI points, with pivots ≥4 bars apart and the divergence current (within 12 bars). Requires a trigger — price must have reclaimed the divergent pivot.

Indicator pivots are matched to price pivots at their own indices, with no lookahead.

**Fails when** the trend is strong. Divergence can persist for many bars before, or without, resolving. Counter-trend by nature.

---

## `volume_breakout` — Volume Expansion Breakout · v1.0.0

**Fires on** a candle with volume ≥2.0 standard deviations above its 20-bar mean, range ≥1.2 ATR, close-location value ≥0.4, that also clears the 20-bar range. Requires ≥$2M 24h turnover so thin-book spikes are excluded.

**Fails when** the spike marks exhaustion rather than initiation — common after an extended move. The entry sits at the extreme of an expanded candle, so the invalidation distance is wide.

---

## `candlestick_context` — Contextual Candlestick Reversal · v1.0.0

**Fires on** an engulfing candle or pin bar — but **only** when two context gates both pass:

1. **Location** — the candle forms at a level with ≥0.3 strength, within 0.8 ATR.
2. **Stretch** — RSI confirms the move into the level was extended (<42 for longs, >58 for shorts).

**A candlestick name alone never produces a signal.** This is the single most common way retail pattern tooling generates noise, and the gates exist specifically to prevent it.

**Fails when** there is no follow-through on the next bar. The tightest invalidation in the catalog, so normal noise can stop it out.

---

## Adding a detector

1. Implement `PatternDetector` in `src/lib/patterns/detectors/`.
2. Register it in `src/lib/patterns/registry.ts`.
3. Add fixtures — positive, negative, and noise — to `tests/fixtures.ts`.

The shared contract tests in `tests/detectors.test.ts` then apply automatically: confirmation must be the last closed candle, invalidation must sit on the correct side of the entry, every target must be beyond the invalidation, reasons for and against are mandatory, and results must be deterministic. `tests/targets.test.ts` additionally asserts every emitted scenario has a positive reward-to-risk clearing the 1.5R floor.

Bump the detector's `version` whenever its logic changes — versions are part of the opportunity fingerprint, which is what keeps historical results reproducible.

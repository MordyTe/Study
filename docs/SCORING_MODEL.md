# Scoring Model

## What the number means

The Setup Quality Score is a **0–100 measure of how well-formed and well-supported a setup is** against explicit criteria. It is not a win probability, an expected return, or a prediction.

A 90 means the pattern is textbook-clean, confirmed decisively, aligned with structure and higher timeframe, backed by volume, liquid, and built on verified data. It does not mean the trade will work.

## Components (sum = 100)

| Component | Max | Measures |
|---|---|---|
| Pattern geometry and fit | 25 | The detector's own conviction: trendline R², pivot symmetry, level strength, convergence |
| Confirmation quality | 20 | Where the confirming candle closed within its range, and how large that range was in ATR terms |
| Structure / regime alignment | 15 | Whether the setup agrees with local market structure, weighted by ADX |
| Volume and momentum | 15 | Volume z-score on the confirming bar plus MACD histogram agreement |
| Multi-timeframe alignment | 10 | Agreement with the higher-timeframe structure (aligned 10, neutral 5, conflicting 1) |
| Liquidity and spread | 10 | Log-scaled 24h turnover plus spread relative to the configured maximum |
| Data verification | 5 | Health state, reconciliation result, and data age |

Every component carries a human-readable `detail` string explaining the number, rendered in the Opportunity detail page. Nothing is a black box.

## Penalties

Subtracted after the components, each with its own explanation:

| Penalty | Trigger |
|---|---|
| Poor reward-to-risk | R:R below the configured minimum. Scales with the shortfall, capped at −18. |
| Thin turnover | 24h turnover below the floor. −12 |
| Excessive spread | Spread above the maximum. −8 |
| Very new instrument | Listed more recently than the minimum age. −10 |
| Incomplete history | Fewer than 150 closed candles. −5 |
| Opposing level in the path | A level with ≥0.5 strength sits between the entry and target 1. −6 |
| Crowded funding | Funding rate beyond ±0.05% against the side you would join. −5 |
| Stale setup | Confirmed more than four hours ago; scales with age, capped at −10. |

The total is clamped to 0–100.

## Reward-to-risk

Computed from the **far edge** of the entry zone — the conservative assumption that you get filled at the worst price in the zone — against the invalidation level and target 1.

Targets pass through `finalizeTargets()` before scoring (see `docs/ARCHITECTURE.md` ADR-003), which guarantees target 1 is at least 1.5R and target 2 at least 3R, while preserving geometric levels that already exceed those floors.

**Consequence worth understanding:** the default `minRewardToRisk` is 2.0, above the 1.5R floor. So a setup only confirms when the *geometry itself* offers 2R or better — the floor prevents nonsense targets, it never manufactures a passing setup. This is intentional, and it makes `CONFIRMED` rare.

## Why no probability is displayed

Converting a quality score into a probability requires:

1. A large sample of **resolved** outcomes — hundreds per detector and timeframe, not dozens.
2. A calibration model fitted on that sample.
3. **Out-of-sample, time-split** evaluation — never in-sample, which always looks good.
4. A reported **Brier score** and a **reliability curve** showing that predicted 70% actually resolves near 70%.
5. A stated minimum sample size below which no number is shown.

Until all five exist, a percentage would be a fabricated number wearing the costume of a measurement. The system therefore shows the quality score and, on the Pattern Library, withholds even a hit rate until at least five signals from a detector have resolved.

If probability is added later it must be a **separate** field, never a relabelled quality score.

## Tuning

Every threshold, weight input, and filter is editable in **Settings** and takes effect on the next scan — no redeploy.

| Setting | Default | Effect of lowering |
|---|---|---|
| Watch threshold | 65 | More setups recorded as FORMING |
| Confirmed threshold | 75 | More alerts, lower average quality |
| Minimum R:R | 2.0 | More confirmations, worse asymmetry |
| Min 24h turnover | $5M | Includes thinner, less reliable markets |
| Max spread | 15 bps | Includes markets where scenario prices are less realistic |

Start strict. Loosen only after the Backtest Lab shows you what the change actually does to outcome distribution — not because the dashboard felt quiet.

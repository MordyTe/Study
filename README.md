# Scheduled-Data Edge

A research-only agent network that estimates probabilities for prediction markets whose outcome is
decided by a **scheduled public data release** — an inflation print, a jobs report, a rate
decision, a temperature reading — and records those estimates so its own calibration can be
measured against resolved outcomes.

**It holds no credentials and has no order path.** A test walks the entire source tree on every
commit to prove it. That is not a formality; it is the property that makes this safe to run
unattended.

---

## The line that makes this defensible

> **The agents never produce a probability. They locate and parse sources. The probability is
> arithmetic over a distribution of historical forecast error.**

For a market asking *"Will CPI year-over-year be above 3.0% at the September release?"*:

1. **Agents** extract the resolution rule and gather a point estimate `μ` from public nowcasts.
2. **A deterministic module** builds the empirical distribution of how wrong that kind of estimate
   has been at a comparable horizon — a kernel-smoothed CDF, not a fitted normal, because economic
   surprises have fat tails and a Gaussian understates exactly the outcomes that decide a threshold.
3. **The threshold is converted** from the published, *rounded* figure to the underlying value.

That third step is the edge. BLS publishes CPI year-over-year to one decimal, so a market resolving
on "above 3.0%" is asking about the rounded figure:

```
reported > 3.0  at 1 dp  ⟺  reported ≥ 3.1  ⟺  underlying ≥ 3.05
reported ≥ 3.0  at 1 dp  ⟺                      underlying ≥ 2.95
```

Half a reporting step. At these prices that is worth several points of probability, and it is
precisely the fine print that thin markets misprice.

Because the estimate is a pure function of an evidence bundle, it is testable, backtestable, and
auditable. No language model emits a percentage anywhere in this codebase.

---

## Why this target, and not arbitrage

An earlier design chased structural arbitrage — `YES + NO < $1` and friends — on the theory that it
is the only edge provable without forecasting. The 2026 fee schedule killed it. Takers pay

```
fee = shares × coefficient × p × (1 − p)
```

and a complement arbitrage buys both legs, where `p_NO ≈ 1 − p_YES` makes the `p(1−p)` term
identical on both. The fee is therefore paid twice at full rate, giving a break-even hurdle at
p = 0.50 of **2.0¢** (politics), **2.5¢** (economics/weather), **3.5¢** (crypto). Only geopolitics
is fee-free. Dislocations that large are taken in milliseconds by co-located bots, and the negRisk
conversion side is run as an industry by multi-wallet operations.

A small account's edge is **attention, not speed**. Thousands of markets exist; bots saturate the
liquid handful. In the long tail sit thin markets where nobody read the criteria carefully, and a
10–15¢ mispricing can sit for weeks. So Tier 1 ranks by **neglect** — low volume, wide spread, a
price away from the tails, a checkable scheduled source — and explicitly *not* by familiarity.
Headline CPI and nonfarm payrolls are the most efficiently priced things on the venue.

---

## The honest thesis being tested

> Do this system's probability estimates beat the market's, out-of-sample, by enough to survive
> fees and spread at $1,000 of capital?

Answered with a Brier score and a reliability curve over resolved markets — not with a backtest
narrative. Until those exist, every number here is a hypothesis. The Health page says so.

If the answer is yes, execution becomes a small, well-understood addition. If it is no, that was
learned for the price of compute instead of the price of a drawdown.

---

## Where it refuses to answer

Abstention is a first-class output, and a high abstention rate is correct behaviour:

- the resolution criteria carry any unresolved ambiguity;
- fewer than 12 comparable historical forecast errors exist (below that the tail is unstable, and
  an unstable tail produces confident wrong answers on exactly the markets that look most
  mispriced);
- no point estimate was gathered, or the one found is stale;
- the book is too thin to take the position at a meaningful size.

And no probability is ever reported outside `[0.005, 0.995]`. The chance that the model itself is
wrong — misparsed criteria, wrong series, a methodology change — exceeds anything more extreme.

---

## Running it

```bash
npm install
npm run check        # typecheck + 106 tests
npm run dev          # http://localhost:3000
npm run verify-live  # live smoke test against the venue
npm run scan         # one scan from the command line
```

**Zero configuration required.** With no environment variables the app runs against an in-memory
store and an unavailable agent provider — every market abstains, which is the honest result rather
than a crash. Non-durability is labelled in the UI, on the Health page, and in every API response;
it is never silently presented as persistence.

| Variable | Effect when set |
|---|---|
| `FRED_API_KEY` | Enables the statistical engine's data source. Free at fred.stlouisfed.org. |
| `ANTHROPIC_API_KEY` | Enables live agent extraction. Optional — see the subscription workflow below. |
| `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | Durable storage. Required before calibration means anything. |
| `RECORD_LLM=1` | Records live agent responses as fixtures for replay. |
| `FORCE_LLM_REPLAY=1` | Serves fixtures instead of calling the API. What CI uses. |

Apply `supabase/migrations/0001_init.sql` to enable durable storage.

### Running the agent tier on a Claude subscription instead of an API key

The extraction agents are single-shot, schema-constrained calls on purpose: it makes them
**replayable**, and replayability means the LLM does not have to be an API at all. A Claude
session (Claude Code on a Max plan, for instance) can *be* the agent tier:

1. `npm run scan` — markets missing a parser extraction are listed with their exact cache keys.
2. The session performs each extraction itself and records it, validated against the very schema
   the production agent uses — an invalid payload cannot be written:
   ```bash
   npm run record-fixture -- resolution-parser 'resolution-parser:v1:<conditionId>' payload.json
   ```
3. `npm run scan` again — fixtures replay automatically, and the deterministic tiers do the rest.

Only the parser and two fallback agents involve a model at all. The point estimate and the
residual distribution come from FRED arithmetic, so a scan's *numbers* never depend on who or
what performed the extraction.

### Network access

The venue and the data source must be reachable. v1 needs exactly four hosts:

```
gamma-api.polymarket.com   clob.polymarket.com          (market universe + books)
api.stlouisfed.org                                      (FRED — the statistical engine)
data-api.polymarket.com                                 (resolution outcomes, later)
```

`npm run verify-live` reports precisely which of these is unreachable and stops rather than
guessing. In a Claude Code cloud environment these are allowed under the environment's network
policy at claude.ai/code → the environment's settings → network access.

---

## Architecture

```
Tier 1  one cheap Gamma call covers the whole universe
        → rankTier1() — pure, no I/O — scores NEGLECT
                          │ top N; this gate is the cost control
Tier 2  the agent network, fanned out per candidate   ◄── the only LLM in the system
        → EvidenceBundle: structured, cached, replayable
                          │
Tier 3  DETERMINISTIC. No LLM below this line.
        → empirical residuals → threshold probability → fee-adjusted edge
        → depth-walked size curve → verification gate → fingerprint → persist
```

| Path | Responsibility |
|---|---|
| `src/lib/polymarket/allowlist.ts` | Read allowlist, forbidden fragments, credential ban |
| `src/lib/polymarket/read.ts` | The only module that touches the venue |
| `src/lib/net/client.ts` | Shared HTTP; cannot be called without an allowlist assertion |
| `src/lib/agents/` | Agent contract, registry middleware, LLM providers |
| `src/lib/estimate/` | Residuals, threshold conversion, fees, depth and sizing |
| `src/lib/engine/` | Neglect ranking, verification gate, assessment, scan orchestration |
| `tests/no-execution-guard.test.ts` | The security gate |

### Design decisions carried forward

The previous project in this repository was a Bybit pattern scanner. Its architecture transferred
almost wholesale, and three of its decisions are load-bearing here:

- **Cross-cutting rules live in the shared runner, not in each plugin.** `runAgent()` enforces the
  no-lookahead invariant, timeouts, and attribution for every agent, because *a future agent cannot
  forget a rule it does not have to remember*.
- **Zero-configuration first run**, with non-durability labelled honestly rather than faked.
- **Truncation is a recorded fact.** When the scan's wall-clock budget expires it writes what it
  deferred into the scan record. Silence would read as "covered everything".

The one decision that did **not** carry over is polling versus streaming. That system decided on
closed candles, so REST polling lost nothing. Here the relevant clock is the release calendar, so
polling is not a compromise — it is correct.

---

## Jurisdiction

Polymarket's international platform prohibits US persons. Polymarket US (QCX) is a separate venue
with a different API, different auth, and a far tighter rate limit. Resolving which venue is
lawfully available is the operator's responsibility and is not something this repository decides.

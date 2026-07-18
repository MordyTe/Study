# ⚡ ETH/USDT Private Signal Agent

A private, professional-grade trading signal agent for **ETH/USDT on Bybit**.
Multi-strategy confluence engine (7 proven methodologies), Smart Money Concepts edge layer,
derivatives sentiment, Gemini AI second opinion, Telegram delivery, live web dashboard,
self-tracking performance stats, and an honest backtester.

**Signals + analysis only — no order execution. You stay in control of every trade.**

---

## 🇮🇱 התקנה מהירה (עברית)

```bash
# 1. התקנת תלויות
pip install -e .

# 2. הגדרת מפתחות (אפשר גם דרך ה-Backoffice בדשבורד אחר כך)
cp .env.example .env
# ערוך את .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY

# 3. משיכת היסטוריה + בקטסט לכיול לפני הפעלה חיה
python -m agent backfill --days 180
python -m agent backtest

# 4. הרצה יבשה (איתותים ללוג בלבד, בלי טלגרם) — מומלץ ליום-יומיים
python -m agent dryrun

# 5. הפעלה חיה
python -m agent run
# דשבורד: http://127.0.0.1:8000  |  Backoffice: http://127.0.0.1:8000/settings
```

**איך יוצרים בוט טלגרם:** דברו עם [@BotFather](https://t.me/BotFather) → `/newbot` → העתיקו את הטוקן.
את ה-Chat ID מקבלים מ-[@userinfobot](https://t.me/userinfobot). שלחו `/start` לבוט שלכם פעם אחת.

---

## Architecture

```
Bybit WS (spot/linear klines · trades · tickers · liquidations)
   → CandleStore (multi-TF ring buffers, REST backfill, gap repair)
   → FlowTracker (CVD from trade stream) + DerivativesState (funding, OI, L/S, liqs)
   → on candle close: MarketContext snapshot (all TFs + indicators + structure)
   → 7 strategies vote (score −1..+1 each)
   → ConfluenceEngine (weighted score, HTF-bias gate, min-agreement, cooldowns)
   → RiskModule (entry zone, structure/ATR stop, TP1-3, R:R, size, leverage)
   → Gemini second opinion (CONFIRM/NEUTRAL/VETO — bounded, fail-open)
   → Telegram card + dashboard push + SQLite
   → SignalTracker (fill → TP/SL/BE lifecycle → win-rate & expectancy stats)
```

### The 7 strategies
| # | Strategy | Method |
|---|----------|--------|
| 1 | `trend_momentum` | EMA stack 9/21/50/200 alignment + ADX strength filter |
| 2 | `mean_reversion` | RSI + Bollinger extremes + confirmed RSI divergence |
| 3 | `vwap_bias` | Session VWAP position, reclaim/loss flips, overextension |
| 4 | `smc` | BOS/CHoCH structure, order blocks, FVGs, liquidity sweeps |
| 5 | `volume_flow` | Volume spikes with close-position, CVD divergence, absorption |
| 6 | `derivatives_sentiment` | Funding extremes, OI-vs-price quadrants, L/S ratio, liq cascades |
| 7 | `key_levels` | PDH/PDL, floor pivots, day open, round numbers — reaction based |

Signals fire only when the **weighted score ≥ 0.55 AND ≥ 3 strategies agree AND
the higher-timeframe bias allows the direction** (hard gate by default).

### Anti-repaint guarantees
- Only `confirm: true` candles are evaluated — never the forming bar
- Swing pivots require k bars of confirmation before strategies may use them
- Backtest replays bars oldest-first through the *identical* pipeline (strategies are pure functions)
- Same-bar SL+TP ambiguity always resolves as LOSS — live and backtest agree

## Commands

| Command | What it does |
|---------|-------------|
| `python -m agent run` | Live agent: signals → Telegram + dashboard |
| `python -m agent dryrun` | Live analysis, signals printed to console only |
| `python -m agent backfill --days 180` | Cache history into SQLite |
| `python -m agent backtest --from 2026-01-01` | Replay history, print win-rate/expectancy/attribution report |
| `pytest` | Run the test suite (indicators golden values, structure, confluence, tracker) |

## Telegram commands
`/status` — feed health, HTF bias, derivatives, open signals ·
`/analyze` — on-demand full Gemini regime report ·
`/signals` — recent signals ·
`/stats` — performance ·
`/settings` — active configuration

## Dashboard
`http://127.0.0.1:8000` — live chart (TradingView lightweight-charts, vendored) with signal
markers and SL/TP lines, market-state panel (bias per TF, funding, OI, CVD, L/S, liquidations),
signal history, performance tiles.

`http://127.0.0.1:8000/settings` — **Backoffice**: manage API keys from the browser.
Keys are written to the local `.env` (git-ignored, `chmod 600`), displayed masked,
and the server binds to localhost only.

## Configuration
Everything tunable lives in [`config/config.yaml`](config/config.yaml): strategy weights,
confluence threshold, style definitions (scalp / intraday), risk % and equity, LLM veto mode,
cooldowns. Secrets live only in `.env`.

Key knobs:
- `confluence.threshold` — raise for fewer, higher-conviction signals
- `confluence.htf_gate_mode` — `hard` (skip counter-trend) or `soft` (penalty)
- `risk.risk_pct` — % of equity risked per trade (position size suggestion)
- `llm.veto_mode` — `annotate` (default: deliver with warning) or `suppress`

## Workflow recommendation (the honest path)
1. **Backfill + backtest** — tune `config.yaml` until the report looks sane over 3-6 months
2. **Dryrun for a few days** — watch signals against the live chart, no noise in Telegram
3. **Go live** — small risk % first; the tracker builds your real win-rate statistics
4. **Review `/stats` weekly** — per-strategy attribution shows which confluences earn their weight

> ⚠️ Educational/personal tooling. Crypto derivatives carry substantial risk of loss.
> Signals are decision support, not financial advice — the final click is always yours.

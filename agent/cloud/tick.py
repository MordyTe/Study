"""The stateless cloud tick — the serverless heart of the agent.

Invoked every minute (external pinger or Vercel cron). Each invocation:
1. fetches fresh candles for every timeframe via Bybit REST (no WS in
   serverless), plus derivatives snapshots
2. restores durable state from Supabase (open signals, cooldowns,
   last-processed timestamps)
3. advances the signal tracker over 1m candles closed since the last tick
4. evaluates each style if its entry-TF candle closed since the last tick
5. delivers new signals (Telegram + DB) and persists all state back

Everything reuses the exact same strategy/confluence/risk/tracker code as
local mode — only the transport differs. CVD/liquidation-stream inputs are
unavailable here; those strategies degrade gracefully as designed.
"""
from __future__ import annotations

import logging
import time

from agent.bus import Bus
from agent.config import Config
from agent.data.bybit_rest import BybitRest
from agent.data.candles import CandleStore
from agent.data.derivatives import DerivativesState
from agent.engine.confluence import ConfluenceEngine, htf_bias
from agent.engine.context import ContextBuilder, build_frame
from agent.engine.risk import RiskModule
from agent.engine.tracker import SignalTracker
from agent.cloud.supabase_repo import SupabaseRepo
from agent.cloud.telegram_http import TelegramHttp
from agent.llm.gemini import GeminiAnalyst
from agent.models import Direction, SignalState, Style, TF_MS, TF_LABEL, now_ms
from agent.strategies import load_strategies

log = logging.getLogger(__name__)

# bars fetched per TF: enough for EMA200 + structure, small enough to be fast
FETCH_BARS = {"1": 200, "5": 800, "15": 800, "60": 800, "240": 800, "D": 400}


def apply_runtime_overrides(cfg: Config, settings: dict[str, str]) -> None:
    """Backoffice-editable knobs stored in ta_settings override config.yaml."""
    if v := settings.get("confluence_threshold"):
        cfg.confluence.threshold = float(v)
    if v := settings.get("htf_gate_mode"):
        cfg.confluence.htf_gate_mode = v
    if v := settings.get("risk_pct"):
        cfg.risk.risk_pct = float(v)
    if v := settings.get("account_equity_usd"):
        cfg.risk.account_equity_usd = float(v)
    if v := settings.get("llm_veto_mode"):
        cfg.llm.veto_mode = v


async def run_tick(cfg: Config, repo: SupabaseRepo) -> dict:
    t0 = time.monotonic()
    telegram = TelegramHttp()
    rest = BybitRest(cfg)
    market = cfg.signal_market
    symbol = cfg.signal_symbol

    settings = await repo.get_settings()
    apply_runtime_overrides(cfg, settings)

    # ---- 1. fresh market data ----------------------------------------------
    bus = Bus()
    store = CandleStore(bus, cfg.active_tfs, cfg.buffer_bars)
    for tf in cfg.active_tfs:
        candles = await rest.backfill(market, symbol, tf, FETCH_BARS.get(tf, 800))
        store.seed(market, tf, candles)

    deriv = DerivativesState()
    try:
        t = await rest.get_tickers("linear", cfg.symbols["linear"])
        deriv.on_ticker(t)
        deriv.set_oi_series(await rest.get_open_interest(cfg.symbols["linear"]))
        deriv.set_ls_ratio(await rest.get_long_short_ratio(cfg.symbols["linear"]))
    except Exception as e:
        log.warning("derivatives fetch failed: %s", e)

    builder = ContextBuilder(cfg, store, flow=None, deriv=deriv)
    strategies = load_strategies(cfg)
    engine = ConfluenceEngine(cfg, strategies)
    risk = RiskModule(cfg)

    # ---- 2. restore durable state ------------------------------------------
    state = await repo.get_state("tick", {}) or {}
    last_tracked = int(state.get("last_tracked_1m", 0))
    last_eval: dict[str, int] = dict(state.get("last_eval", {}))
    # restore cooldowns
    for key, (ts, score) in (state.get("last_fire") or {}).items():
        style_s, dir_s = key.split(":")
        engine._last_fire[(Style(style_s), Direction(dir_s))] = (int(ts), float(score))

    events: list[str] = []

    # ---- 3. tracker over newly closed 1m candles ---------------------------
    tracker = SignalTracker(bus)
    open_signals = await repo.load_open_signals()
    for s in open_signals:
        tracker.track(s)

    async def on_event(sig, frm, to, price):
        await repo.save_signal(sig)
        await repo.save_event(sig.id, now_ms(), frm, to, price)
        await telegram.notify_event(sig, frm, to, price)
        events.append(f"{sig.id}:{to.value}")

    tracker.add_notifier(on_event)

    import numpy as np
    m1 = np.asarray(store.series(market, "1").view())
    from agent.models import Candle
    new_1m = [
        Candle(ts=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
        for r in m1 if int(r[0]) > last_tracked
    ]
    for c in new_1m:
        await tracker.on_candle(c)
    if len(m1):
        last_tracked = int(m1[-1, 0])

    # ---- 4. style evaluation on newly closed entry-TF bars -----------------
    new_signals = []
    styles = [(Style(name), sc) for name, sc in cfg.styles.items() if sc.enabled]
    for style, sc in styles:
        s = store.series(market, sc.entry_tf)
        if not s.size:
            continue
        bar_ts = s.last_ts
        if bar_ts <= int(last_eval.get(style.value, 0)):
            continue  # this entry bar was already evaluated by a previous tick
        last_eval[style.value] = bar_ts
        close_ts = bar_ts + TF_MS[sc.entry_tf]
        tfs = list(dict.fromkeys([sc.entry_tf, *sc.gate_tfs, "D"]))
        ctx = builder.build(market, sc.entry_tf, tfs, close_ts)
        if ctx is None:
            continue
        cand = engine.evaluate(ctx, style, sc)
        if cand is None:
            continue
        sig = risk.build_signal(cand)
        if sig is None:
            continue

        llm = GeminiAnalyst(cfg, repo=None)
        await llm.validate_signal(sig, ctx)
        if sig.llm_verdict == "VETO" and cfg.llm.veto_mode == "suppress":
            sig.state = SignalState.REJECTED
            await repo.save_signal(sig)
            continue

        for other in tracker.open_signals:
            if other.style is sig.style and other.direction is not sig.direction:
                other.resolved_ts = close_ts
                await tracker._transition(other, SignalState.INVALIDATED, ctx.price)

        sig.state = SignalState.DELIVERED
        tracker.track(sig)
        await repo.save_signal(sig)
        await telegram.send_signal(sig)
        new_signals.append(sig.id)
        log.info("SIGNAL %s %s %s conf=%.2f", sig.id, sig.style.value,
                 sig.direction.value, sig.confidence)

    # ---- 4.5 periodic Gemini regime report ---------------------------------
    regime_ms = int(state.get("regime_ms", 0))
    regime_interval = cfg.llm.regime_report_hours * 3_600_000
    if cfg.llm.enabled and now_ms() - regime_ms >= regime_interval:
        regime_ms = now_ms()  # advance even on failure — never spam retries
        try:
            llm = GeminiAnalyst(cfg, repo=None)
            if llm.available:
                sc_i = cfg.styles.get("intraday")
                if sc_i is not None:
                    tfs_i = list(dict.fromkeys([sc_i.entry_tf, *sc_i.gate_tfs, "D"]))
                    ctx_i = builder.build(market, sc_i.entry_tf, tfs_i, now_ms())
                    if ctx_i is not None:
                        report = await llm.regime_report(ctx_i)
                        if report:
                            await telegram.send(f"<b>🧭 Market Regime Report</b>\n\n{report}")
        except Exception as e:
            log.warning("regime report failed: %s", e)

    # ---- 4.6 first successful tick — announce the pipeline is alive --------
    if not state.get("first_tick_done"):
        price = store.last_price(market)
        await telegram.send(
            "🚀 <b>Agent online</b> — first tick completed.\n"
            f"ETH: {price:,.2f}" + (f" · funding {deriv.funding_rate * 100:.4f}%"
                                    if deriv.funding_rate is not None else "") +
            "\nThe engine now evaluates the market every minute. "
            "Signals will arrive only on real confluence."
        )

    # ---- 5. persist state + market snapshot for the dashboard --------------
    fire_state = {
        f"{k[0].value}:{k[1].value}": [v[0], v[1]] for k, v in engine._last_fire.items()
    }
    await repo.set_state("tick", {
        "last_tracked_1m": last_tracked,
        "last_eval": last_eval,
        "last_fire": fire_state,
        "last_run_ms": now_ms(),
        "regime_ms": regime_ms,
        "first_tick_done": True,
    })

    biases = {}
    for tf in ("15", "60", "240", "D"):
        arr = store.series(market, tf).view()
        if len(arr) >= 60:
            frame = build_frame(cfg, tf, np.asarray(arr))
            if frame:
                b = htf_bias(frame)
                biases[TF_LABEL.get(tf, tf)] = "bull" if b > 0 else "bear" if b < 0 else "neutral"
    await repo.set_state("market", {
        "price": store.last_price(market),
        "biases": biases,
        "deriv": deriv.snapshot(),
        "updated_ms": now_ms(),
    })

    return {
        "ok": True,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "new_signals": new_signals,
        "tracker_events": events,
        "tracked_1m_bars": len(new_1m),
        "open_signals": len(tracker.open_signals),
    }

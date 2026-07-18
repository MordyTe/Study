"""Backtest: replay cached klines oldest-first through the IDENTICAL
strategy pipeline used live. Also hosts the `backfill` CLI command.

Honesty rules:
- bars stream strictly oldest-first; strategies see only the past
- flow (CVD) and derivatives strategies receive no data and return None;
  the confluence denominator adapts (report shows which strategies ran)
- resolution uses only bars after signal creation; same-bar SL+TP = LOSS
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from agent.bus import Bus
from agent.config import Config
from agent.data.bybit_rest import BybitRest
from agent.data.candles import CandleStore
from agent.engine.confluence import ConfluenceEngine
from agent.engine.context import ContextBuilder
from agent.engine.risk import RiskModule
from agent.engine.tracker import SignalTracker
from agent.models import Candle, Signal, SignalState, Style, TF_MS
from agent.store.db import Db
from agent.store.repo import Repo
from agent.strategies import load_strategies

log = logging.getLogger(__name__)


async def backfill_history(cfg: Config, days: int = 180) -> None:
    """Fetch history for every active TF of the signal market into SQLite."""
    db = Db(cfg.store.db_path)
    await db.open()
    repo = Repo(db)
    rest = BybitRest(cfg)
    market = cfg.signal_market
    symbol = cfg.signal_symbol
    try:
        for tf in cfg.active_tfs:
            bars_needed = min(days * 86_400_000 // TF_MS[tf], 200_000)
            log.info("backfilling %s %s: ~%d bars", market, tf, bars_needed)
            candles = await rest.backfill(market, symbol, tf, int(bars_needed))
            await repo.save_candles(market, tf, candles)
            lo, hi, n = await repo.candle_range(market, tf)
            log.info("  %s: %d bars stored (%s .. %s)", tf, n,
                     datetime.fromtimestamp(lo / 1000, tz=timezone.utc).date(),
                     datetime.fromtimestamp(hi / 1000, tz=timezone.utc).date())
    finally:
        await db.close()
    print("backfill complete.")


def _parse_date(s: str | None) -> int | None:
    if not s:
        return None
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


async def run_backtest(cfg: Config, date_from: str | None = None, date_to: str | None = None) -> dict:
    from agent.backtest.report import print_report

    t0 = time.monotonic()
    db = Db(cfg.store.db_path)
    await db.open()
    repo = Repo(db)
    market = cfg.signal_market
    ts_from = _parse_date(date_from)
    ts_to = _parse_date(date_to)

    # Load all TFs from the cache
    series: dict[str, list[Candle]] = {}
    for tf in cfg.active_tfs:
        series[tf] = await repo.load_candles(market, tf, None, ts_to)
        if not series[tf]:
            log.warning("no cached candles for tf=%s — run `python -m agent backfill` first", tf)
    await db.close()
    if not series.get("1"):
        raise SystemExit("backtest needs cached 1m candles; run: python -m agent backfill")

    bus = Bus()
    store = CandleStore(bus, cfg.active_tfs, cfg.buffer_bars)
    builder = ContextBuilder(cfg, store, flow=None, deriv=None)
    strategies = load_strategies(cfg)
    engine = ConfluenceEngine(cfg, strategies)
    risk = RiskModule(cfg)
    tracker = SignalTracker(bus)

    # Warmup: seed each TF with bars strictly before the eval window start
    warm_end = ts_from or series["1"][max(0, len(series["1"]) // 5)].ts
    pending: dict[str, list[Candle]] = {}
    for tf, candles in series.items():
        warm = [c for c in candles if c.ts + TF_MS[tf] <= warm_end]
        store.seed(market, tf, warm)
        pending[tf] = [c for c in candles if c.ts + TF_MS[tf] > warm_end]

    signals: list[Signal] = []
    styles = [(Style(name), sc) for name, sc in cfg.styles.items() if sc.enabled]

    # Merge all pending bars into one time-ordered stream keyed by bar CLOSE time
    stream: list[tuple[int, str, Candle]] = []
    for tf, candles in pending.items():
        for c in candles:
            stream.append((c.ts + TF_MS[tf], tf, c))
    stream.sort(key=lambda x: (x[0], TF_MS[x[1]]))
    log.info("replaying %d bars through the live pipeline...", len(stream))

    for close_ts, tf, candle in stream:
        store.on_kline(market, tf, candle)
        if tf == "1":
            await tracker.on_candle(candle)
        for style, sc in styles:
            if tf != sc.entry_tf:
                continue
            ctx = builder.build(market, sc.entry_tf,
                                [sc.entry_tf, *sc.gate_tfs, "1", "D"], close_ts)
            if ctx is None:
                continue
            cand = engine.evaluate(ctx, style, sc)
            if cand is None:
                continue
            sig = risk.build_signal(cand)
            if sig is None:
                continue
            sig.state = SignalState.DELIVERED
            tracker.track(sig)
            signals.append(sig)

    stats = tracker.stats()
    elapsed = time.monotonic() - t0
    live_strategies = sorted({v.strategy for s in signals for v in s.votes})
    print_report(signals, stats, live_strategies, elapsed)
    return stats

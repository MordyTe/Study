"""MarketContext assembly: a frozen snapshot of everything the strategies
are allowed to see at a candle close. Strategies are pure functions of this
object — which is what guarantees backtest == live behavior.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from agent.config import Config
from agent.data.candles import CandleStore, TS, O, H, L, C, V
from agent.data.derivatives import DerivativesState
from agent.data.flow import FlowTracker
from agent.indicators import core as ind
from agent.indicators import structure as st

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TfFrame:
    tf: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    ema: dict[int, np.ndarray]
    rsi: np.ndarray
    atr: np.ndarray
    adx: np.ndarray
    bb_upper: np.ndarray
    bb_mid: np.ndarray
    bb_lower: np.ndarray
    vwap: np.ndarray
    pivots: list[st.Pivot]
    events: list[st.StructureEvent]
    trend: int
    order_blocks: list[st.Zone]
    fvgs: list[st.Zone]

    @property
    def n(self) -> int:
        return len(self.close)

    @property
    def last_close(self) -> float:
        return float(self.close[-1])

    @property
    def last_atr(self) -> float:
        return float(self.atr[-1]) if not np.isnan(self.atr[-1]) else 0.0


@dataclass(slots=True)
class FlowSnapshot:
    cvd_30m: list[float]
    delta_5m: float
    delta_15m: float
    large_print_threshold: float


@dataclass(slots=True)
class MarketContext:
    symbol: str
    market: str
    ts: int                       # decision time (close ts of the triggering bar)
    entry_tf: str
    frames: dict[str, TfFrame]
    key_levels: dict[str, float] = field(default_factory=dict)
    flow: FlowSnapshot | None = None
    deriv: dict[str, Any] | None = None

    @property
    def entry(self) -> TfFrame:
        return self.frames[self.entry_tf]

    @property
    def price(self) -> float:
        return self.entry.last_close


# Bars used per frame build. Enough for EMA200 convergence + swing lookbacks
# while keeping per-close rebuild cost low.
FRAME_WINDOW = 800


def build_frame(cfg: Config, tf: str, arr: np.ndarray) -> TfFrame | None:
    """arr: (n, 6) oldest-first ts/o/h/l/c/v."""
    if len(arr) < 60:
        return None
    arr = arr[-FRAME_WINDOW:]
    ts_a = arr[:, TS]
    o = arr[:, O].copy()
    h = arr[:, H].copy()
    l = arr[:, L].copy()
    c = arr[:, C].copy()
    v = arr[:, V].copy()

    tm = cfg.strategy_params("trend_momentum")
    mr = cfg.strategy_params("mean_reversion")
    smc = cfg.strategy_params("smc")

    emas = {p: ind.ema(c, p) for p in tm.get("ema_periods", [9, 21, 50, 200])}
    rsi_a = ind.rsi(c, mr.get("rsi_period", 14))
    atr_a = ind.atr(h, l, c, 14)
    adx_a = ind.adx(h, l, c, tm.get("adx_period", 14))
    bb_u, bb_m, bb_l = ind.bollinger(c, mr.get("bb_period", 20), mr.get("bb_std", 2.0))
    vwap_a = ind.session_vwap(ts_a.astype(np.int64), h, l, c, v)

    k = smc.get("swing_k", 3)
    pivots = st.find_pivots(h, l, ts_a.astype(np.int64), k=k)
    events, trend = st.detect_structure(c, pivots)
    obs = st.find_order_blocks(
        o, h, l, c, events, atr_a,
        impulse_atr=smc.get("ob_impulse_atr", 1.5),
        max_age=smc.get("ob_max_age_bars", 120),
    )
    fvgs = st.find_fvgs(h, l, atr_a, min_atr=smc.get("fvg_min_atr", 0.3))

    return TfFrame(
        tf=tf, ts=ts_a, open=o, high=h, low=l, close=c, volume=v,
        ema=emas, rsi=rsi_a, atr=atr_a, adx=adx_a,
        bb_upper=bb_u, bb_mid=bb_m, bb_lower=bb_l, vwap=vwap_a,
        pivots=pivots, events=events, trend=trend,
        order_blocks=obs, fvgs=fvgs,
    )


def compute_key_levels(frames: dict[str, TfFrame], round_step: float = 50.0) -> dict[str, float]:
    levels: dict[str, float] = {}
    d = frames.get("D")
    if d is not None and d.n >= 2:
        # prior *completed* day
        levels["PDH"] = float(d.high[-2])
        levels["PDL"] = float(d.low[-2])
        levels["PDC"] = float(d.close[-2])
        levels["day_open"] = float(d.open[-1])
        piv = ind.floor_pivots(levels["PDH"], levels["PDL"], levels["PDC"])
        levels.update({f"pivot_{k}": v for k, v in piv.items()})
    entry = next(iter(frames.values()))
    price = entry.last_close
    levels["round_below"] = (price // round_step) * round_step
    levels["round_above"] = levels["round_below"] + round_step
    return levels


class ContextBuilder:
    def __init__(
        self, cfg: Config, store: CandleStore,
        flow: FlowTracker | None = None,
        deriv: DerivativesState | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.flow = flow
        self.deriv = deriv
        # frame cache: a frame is a pure function of its candle series, so it
        # is valid until that series gains a bar. Keyed by (market, tf).
        self._cache: dict[tuple[str, str], tuple[int, int, TfFrame]] = {}

    def _frame(self, market: str, tf: str) -> TfFrame | None:
        s = self.store.series(market, tf)
        key = (market, tf)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == s.last_ts and cached[1] == s.size:
            return cached[2]
        frame = build_frame(self.cfg, tf, np.asarray(s.view()))
        if frame is not None:
            self._cache[key] = (s.last_ts, s.size, frame)
        return frame

    def build(self, market: str, entry_tf: str, tfs: list[str], ts: int) -> MarketContext | None:
        frames: dict[str, TfFrame] = {}
        for tf in tfs:
            # the 1m frame is only consumed by flow comparisons — skip the
            # rebuild entirely when no live flow data exists (e.g. backtest)
            if tf == "1" and tf != entry_tf and (self.flow is None or not self.flow.available):
                continue
            frame = self._frame(market, tf)
            if frame is not None:
                frames[tf] = frame
        if entry_tf not in frames:
            return None

        kl_params = self.cfg.strategy_params("key_levels")
        key_levels = compute_key_levels(frames, kl_params.get("round_step", 50))

        flow_snap = None
        if self.flow is not None and self.flow.available:
            d5 = sum(self.flow.delta_series(5))
            d15 = sum(self.flow.delta_series(15))
            flow_snap = FlowSnapshot(
                cvd_30m=self.flow.cvd_series(30),
                delta_5m=d5, delta_15m=d15,
                large_print_threshold=self.flow.large_print_threshold(),
            )

        deriv_snap = self.deriv.snapshot() if self.deriv is not None else None

        return MarketContext(
            symbol=self.cfg.symbols[market], market=market, ts=ts,
            entry_tf=entry_tf, frames=frames,
            key_levels=key_levels, flow=flow_snap, deriv=deriv_snap,
        )

"""Confluence engine gating logic tests with stub strategies."""
import numpy as np
import pytest

from agent.config import load_config
from agent.engine.confluence import ConfluenceEngine
from agent.engine.context import MarketContext, TfFrame
from agent.models import Direction, StrategyVote, Style


class StubStrategy:
    def __init__(self, name: str, score: float | None):
        self.name = name
        self._score = score

    def evaluate(self, ctx):
        if self._score is None:
            return None
        return StrategyVote(strategy=self.name, score=self._score, timeframe="5", reasons=["stub"])


def make_frame(tf: str, trend: int = 1, bull: bool = True) -> TfFrame:
    n = 250
    base = np.linspace(100, 120, n) if bull else np.linspace(120, 100, n)
    ts = np.arange(n, dtype=np.int64) * 60_000
    ema = {p: base * (1 - 0.001 * i) if not bull else base * (1 - 0.001 * i)
           for i, p in enumerate([9, 21, 50, 200])}
    # for bull: shorter EMA above longer; for bear: inverted
    if bull:
        ema = {9: base, 21: base - 1, 50: base - 2, 200: base - 3}
    else:
        ema = {9: base, 21: base + 1, 50: base + 2, 200: base + 3}
    nanarr = np.full(n, 50.0)
    return TfFrame(
        tf=tf, ts=ts, open=base, high=base + 1, low=base - 1, close=base,
        volume=np.ones(n), ema=ema, rsi=nanarr, atr=np.ones(n), adx=np.full(n, 25.0),
        bb_upper=base + 2, bb_mid=base, bb_lower=base - 2,
        vwap=base - (1 if bull else -1),
        pivots=[], events=[], trend=trend, order_blocks=[], fvgs=[],
    )


def make_ctx(bull: bool = True) -> MarketContext:
    frames = {
        "5": make_frame("5", 1 if bull else -1, bull),
        "15": make_frame("15", 1 if bull else -1, bull),
        "60": make_frame("60", 1 if bull else -1, bull),
    }
    return MarketContext(symbol="ETHUSDT", market="linear", ts=10_000_000,
                         entry_tf="5", frames=frames)


@pytest.fixture
def cfg():
    return load_config()


def scalp_cfg(cfg):
    return cfg.styles["scalp"]


def test_fires_on_strong_agreement(cfg):
    strats = [StubStrategy(f"s{i}", 0.8) for i in range(4)]
    eng = ConfluenceEngine(cfg, strats)
    cand = eng.evaluate(make_ctx(bull=True), Style.SCALP, scalp_cfg(cfg))
    assert cand is not None
    assert cand.direction is Direction.LONG
    assert cand.confidence >= cfg.confluence.threshold


def test_below_threshold_no_fire(cfg):
    strats = [StubStrategy(f"s{i}", 0.3) for i in range(4)]
    eng = ConfluenceEngine(cfg, strats)
    assert eng.evaluate(make_ctx(True), Style.SCALP, scalp_cfg(cfg)) is None


def test_min_agreeing_guard(cfg):
    # one dominant vote, others silent -> must not fire
    strats = [StubStrategy("dominant", 1.0), StubStrategy("quiet1", None), StubStrategy("quiet2", None)]
    eng = ConfluenceEngine(cfg, strats)
    assert eng.evaluate(make_ctx(True), Style.SCALP, scalp_cfg(cfg)) is None


def test_htf_hard_gate_blocks_counter_trend(cfg):
    # bullish votes but bearish HTF frames -> hard gate discards
    strats = [StubStrategy(f"s{i}", 0.8) for i in range(4)]
    eng = ConfluenceEngine(cfg, strats)
    ctx = make_ctx(bull=False)  # HTF bearish
    assert eng.evaluate(ctx, Style.SCALP, scalp_cfg(cfg)) is None


def test_cooldown_dedup(cfg):
    strats = [StubStrategy(f"s{i}", 0.8) for i in range(4)]
    eng = ConfluenceEngine(cfg, strats)
    ctx1 = make_ctx(True)
    assert eng.evaluate(ctx1, Style.SCALP, scalp_cfg(cfg)) is not None
    # same score 1 minute later -> suppressed by cooldown
    ctx2 = make_ctx(True)
    ctx2.ts = ctx1.ts + 60_000
    assert eng.evaluate(ctx2, Style.SCALP, scalp_cfg(cfg)) is None

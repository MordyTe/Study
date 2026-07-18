"""Structure detection tests on hand-crafted candle fixtures."""
import numpy as np

from agent.indicators import structure as st


def _ts(n):
    return np.arange(n, dtype=np.int64) * 60_000


def test_pivot_detection_and_confirmation_lag():
    #        0   1   2   3    4   5   6
    high = np.array([10, 11, 15, 11, 10, 11, 10], dtype=float)
    low = high - 1
    pivots = st.find_pivots(high, low, _ts(7), k=2)
    highs = [p for p in pivots if p.is_high]
    assert len(highs) == 1
    assert highs[0].idx == 2
    assert highs[0].confirmed_idx == 4  # only known 2 bars later


def test_bos_choch_sequence():
    # Build: swing high at 15 (idx2), swing low at 5 (idx6), then close above 15 -> BOS/CHoCH logic
    high = np.array([10, 11, 15, 11, 9, 7, 6, 8, 9, 16, 17], dtype=float)
    low = np.array([9, 10, 13, 9, 7, 5, 4, 6, 8, 14, 16], dtype=float)
    close = np.array([9.5, 10.5, 14, 10, 8, 6, 5, 7, 8.5, 15.5, 16.5])
    pivots = st.find_pivots(high, low, _ts(11), k=2)
    events, trend = st.detect_structure(close, pivots)
    kinds = [(e.kind, e.direction) for e in events]
    # closing below the swing low first (downtrend), then breaking the swing high = CHoCH up
    assert ("CHOCH", 1) in kinds or ("BOS", 1) in kinds
    assert trend == 1


def test_fvg_detection_bullish():
    # bull FVG: low[i] > high[i-2]
    high = np.array([10, 11, 14, 15, 15.5], dtype=float)
    low = np.array([9, 10, 12.5, 14, 15], dtype=float)
    atr = np.full(5, 1.0)
    zones = st.find_fvgs(high, low, atr, min_atr=0.3)
    bulls = [z for z in zones if z.direction == 1]
    assert bulls
    z = bulls[0]
    assert z.bottom == 10.0 and z.top == 12.5


def test_sweep_and_reclaim():
    # level at 100; bar wicks to 99.5 but closes back above
    high = np.array([102, 103, 102, 101.5, 102.5], dtype=float)
    low = np.array([100.5, 101, 100.2, 99.5, 101], dtype=float)
    close = np.array([101, 102, 101, 100.8, 102], dtype=float)
    atr = np.full(5, 1.0)
    sweeps = st.find_sweeps(high, low, close, [(100.0, "PDL")], atr, max_atr=0.6)
    assert any(s.direction == 1 for s in sweeps)


def test_divergence_bearish():
    # price makes higher high, oscillator makes lower high
    n = 30
    high = np.full(n, 10.0)
    low = high - 1
    high[10] = 15.0   # pivot 1
    high[20] = 16.0   # pivot 2 (higher high)
    close = high - 0.5
    osc = np.full(n, 50.0)
    osc[10] = 80.0
    osc[20] = 70.0    # lower oscillator high
    pivots = st.find_pivots(high, low, _ts(n), k=3)
    div = st.detect_divergence(close, osc, pivots, min_gap=5, max_gap=60)
    assert div == -1

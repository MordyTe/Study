"""Golden-value tests for core indicators (Wilder/TradingView conventions)."""
import numpy as np
import pytest

from agent.indicators import core as ind


def test_sma_basic():
    v = np.array([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(v, 3)
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert out[2] == pytest.approx(2.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_seed_and_recursion():
    v = np.arange(1, 11, dtype=float)  # 1..10
    out = ind.ema(v, 5)
    # seed = SMA(1..5) = 3; alpha = 2/6
    assert out[4] == pytest.approx(3.0)
    expected = 3.0
    alpha = 2 / 6
    for i in range(5, 10):
        expected = alpha * v[i] + (1 - alpha) * expected
    assert out[9] == pytest.approx(expected)


def test_rsi_all_gains_is_100():
    v = np.arange(1, 31, dtype=float)
    out = ind.rsi(v, 14)
    assert out[-1] == pytest.approx(100.0)


def test_rsi_alternating_is_bounded():
    v = np.array([10 + (i % 2) for i in range(40)], dtype=float)
    out = ind.rsi(v, 14)
    assert 30 < out[-1] < 70


def test_rsi_known_sequence():
    # Classic Wilder example-style check: constant equal gains/losses -> RSI 50
    v = np.cumsum(np.tile([1.0, -1.0], 30)) + 100
    out = ind.rsi(v, 14)
    assert out[-1] == pytest.approx(50.0, abs=3)


def test_atr_constant_range():
    n = 50
    h = np.full(n, 12.0)
    l = np.full(n, 10.0)
    c = np.full(n, 11.0)
    out = ind.atr(h, l, c, 14)
    assert out[-1] == pytest.approx(2.0)


def test_adx_trending_market_high():
    n = 80
    base = np.arange(n, dtype=float)
    h, l, c = base + 1.0, base, base + 0.8
    out = ind.adx(h, l, c, 14)
    assert out[-1] > 60  # strong one-way trend


def test_bollinger_flat_series():
    v = np.full(30, 5.0)
    u, m, lo = ind.bollinger(v, 20, 2.0)
    assert u[-1] == pytest.approx(5.0)
    assert m[-1] == pytest.approx(5.0)
    assert lo[-1] == pytest.approx(5.0)


def test_session_vwap_resets_daily():
    day = 86_400_000
    ts = np.array([0, 60_000, day, day + 60_000], dtype=np.int64)
    h = np.array([10.0, 20.0, 100.0, 200.0])
    l = h - 2
    c = h - 1
    v = np.ones(4)
    out = ind.session_vwap(ts, h, l, c, v)
    # first bar of day 2 must ignore day 1 prices entirely
    typical_d2 = (100 + 98 + 99) / 3
    assert out[2] == pytest.approx(typical_d2)


def test_floor_pivots():
    p = ind.floor_pivots(110, 90, 100)
    assert p["P"] == pytest.approx(100.0)
    assert p["R1"] == pytest.approx(110.0)
    assert p["S1"] == pytest.approx(90.0)

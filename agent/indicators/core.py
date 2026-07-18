"""Vectorized numpy indicators. Wilder smoothing conventions match
TradingView so values can be visually verified on the chart.

All functions take oldest-first arrays and return arrays of the same
length with np.nan during warmup.
"""
from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(values, np.nan, dtype=np.float64)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    # Seed with SMA of the first `period` values (TradingView convention)
    seed = values[:period].mean()
    out[period - 1] = seed
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(values, np.nan, dtype=np.float64)
    if len(values) < period:
        return out
    csum = np.cumsum(np.insert(values, 0, 0.0))
    out[period - 1:] = (csum[period:] - csum[:-period]) / period
    return out


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """RMA / Wilder's smoothing: alpha = 1/period, seeded with SMA."""
    out = np.full_like(values, np.nan, dtype=np.float64)
    if len(values) < period:
        return out
    out[period - 1] = values[:period].mean()
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full_like(close, np.nan, dtype=np.float64)
    if len(close) < period + 1:
        return out
    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        r = 100 - 100 / (1 + rs)
    r = np.where(np.isnan(avg_loss), np.nan, np.where(avg_loss == 0, 100.0, r))
    out[1:] = r
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    tr = np.empty_like(high)
    tr[0] = high[0] - low[0]
    prev_close = close[:-1]
    tr[1:] = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    return _wilder_smooth(true_range(high, low, close), period)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(high)
    out = np.full(n, np.nan)
    if n < 2 * period:
        return out
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)[1:]
    atr_s = _wilder_smooth(tr, period)
    plus_s = _wilder_smooth(plus_dm, period)
    minus_s = _wilder_smooth(minus_dm, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * plus_s / atr_s
        minus_di = 100 * minus_s / atr_s
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx_s = _wilder_smooth(np.nan_to_num(dx, nan=0.0), period)
    # first valid dx is at index period-1 (in the diff array); ADX needs another `period`
    adx_s[: 2 * period - 2] = np.nan
    out[1:] = adx_s
    return out


def bollinger(close: np.ndarray, period: int = 20, num_std: float = 2.0):
    mid = sma(close, period)
    out_std = np.full_like(close, np.nan, dtype=np.float64)
    if len(close) >= period:
        windows = np.lib.stride_tricks.sliding_window_view(close, period)
        out_std[period - 1:] = windows.std(axis=1, ddof=0)
    upper = mid + num_std * out_std
    lower = mid - num_std * out_std
    return upper, mid, lower


def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    out = np.zeros_like(close)
    direction = np.sign(np.diff(close))
    out[1:] = np.cumsum(direction * volume[1:])
    return out


def session_vwap(ts: np.ndarray, high: np.ndarray, low: np.ndarray,
                 close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """VWAP anchored at each UTC daily open."""
    typical = (high + low + close) / 3
    day = (ts // 86_400_000).astype(np.int64)
    out = np.full_like(close, np.nan, dtype=np.float64)
    pv_acc = 0.0
    v_acc = 0.0
    cur_day = -1
    for i in range(len(close)):
        if day[i] != cur_day:
            cur_day = day[i]
            pv_acc = 0.0
            v_acc = 0.0
        pv_acc += typical[i] * volume[i]
        v_acc += volume[i]
        out[i] = pv_acc / v_acc if v_acc else np.nan
    return out


def anchored_vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  volume: np.ndarray, anchor_idx: int) -> float:
    """VWAP from anchor bar to the last bar (single value)."""
    typical = (high[anchor_idx:] + low[anchor_idx:] + close[anchor_idx:]) / 3
    v = volume[anchor_idx:]
    tv = v.sum()
    return float((typical * v).sum() / tv) if tv else float("nan")


def floor_pivots(prev_high: float, prev_low: float, prev_close: float) -> dict[str, float]:
    p = (prev_high + prev_low + prev_close) / 3
    return {
        "P": p,
        "R1": 2 * p - prev_low,
        "S1": 2 * p - prev_high,
        "R2": p + (prev_high - prev_low),
        "S2": p - (prev_high - prev_low),
    }

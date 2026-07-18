"""Market structure / Smart Money Concepts primitives.

Everything here works only on CONFIRMED information: a fractal pivot at bar
i requires k bars after it, so it is only usable from bar i+k onward — zero
repaint. BOS/CHoCH use candle closes beyond levels, not wicks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Pivot:
    idx: int
    ts: int
    price: float
    is_high: bool
    confirmed_idx: int  # bar index at which this pivot became known


@dataclass(frozen=True, slots=True)
class StructureEvent:
    kind: str        # "BOS" | "CHOCH"
    direction: int   # +1 bullish, -1 bearish
    idx: int         # bar index where the break closed
    level: float     # the swing level that broke


@dataclass(slots=True)
class Zone:
    kind: str        # "OB" | "FVG"
    direction: int   # +1 demand/bullish, -1 supply/bearish
    top: float
    bottom: float
    created_idx: int
    mitigated: bool = False

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True, slots=True)
class Sweep:
    idx: int         # bar index of the reclaim close
    direction: int   # +1 = swept lows & reclaimed (bullish), -1 = swept highs (bearish)
    level: float


def find_pivots(high: np.ndarray, low: np.ndarray, ts: np.ndarray, k: int = 3) -> list[Pivot]:
    """Fractal pivots: bar i is a swing high if high[i] is the strict max of
    high[i-k .. i+k] (ties resolve to the earliest bar). Confirmed k bars later."""
    n = len(high)
    pivots: list[Pivot] = []
    for i in range(k, n - k):
        win_h = high[i - k: i + k + 1]
        if high[i] == win_h.max() and (win_h == high[i]).sum() == 1:
            pivots.append(Pivot(i, int(ts[i]), float(high[i]), True, i + k))
        win_l = low[i - k: i + k + 1]
        if low[i] == win_l.min() and (win_l == low[i]).sum() == 1:
            pivots.append(Pivot(i, int(ts[i]), float(low[i]), False, i + k))
    pivots.sort(key=lambda p: p.idx)
    return pivots


def detect_structure(close: np.ndarray, pivots: list[Pivot]) -> tuple[list[StructureEvent], int]:
    """Walk bars in order; track last confirmed swing high/low; emit BOS/CHoCH.

    Returns (events, current_trend) where trend is +1/-1/0.
    A close above the last swing high is BOS in an uptrend (continuation) or
    CHoCH when the prior trend was down. Mirror for lows.
    """
    events: list[StructureEvent] = []
    trend = 0
    last_high: Pivot | None = None
    last_low: Pivot | None = None
    piv_iter = iter(pivots)
    upcoming = next(piv_iter, None)
    broken_high_idx = -1
    broken_low_idx = -1

    for i in range(len(close)):
        # Activate pivots as they become confirmed
        while upcoming is not None and upcoming.confirmed_idx <= i:
            if upcoming.is_high:
                last_high = upcoming
            else:
                last_low = upcoming
            upcoming = next(piv_iter, None)

        if last_high is not None and last_high.idx > broken_high_idx and close[i] > last_high.price:
            kind = "CHOCH" if trend == -1 else "BOS"
            events.append(StructureEvent(kind, +1, i, last_high.price))
            trend = +1
            broken_high_idx = last_high.idx
        if last_low is not None and last_low.idx > broken_low_idx and close[i] < last_low.price:
            kind = "CHOCH" if trend == +1 else "BOS"
            events.append(StructureEvent(kind, -1, i, last_low.price))
            trend = -1
            broken_low_idx = last_low.idx
    return events, trend


def find_order_blocks(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    events: list[StructureEvent], atr_arr: np.ndarray,
    impulse_atr: float = 1.5, max_age: int = 120,
) -> list[Zone]:
    """On each BOS/CHoCH, walk back from the break bar to the last
    opposite-colored candle that originated the impulse. Its range is the OB.
    Marks zones mitigated once price closes through the 50% level.
    """
    n = len(c)
    zones: list[Zone] = []
    for ev in events:
        if n - ev.idx > max_age:
            continue
        # impulse must be meaningful vs ATR at the break
        a = atr_arr[ev.idx] if not np.isnan(atr_arr[ev.idx]) else None
        # walk back max 10 bars for the origin candle
        found = None
        for j in range(ev.idx, max(ev.idx - 10, 0), -1):
            bearish_candle = c[j] < o[j]
            bullish_candle = c[j] > o[j]
            if ev.direction == +1 and bearish_candle:
                found = j
                break
            if ev.direction == -1 and bullish_candle:
                found = j
                break
        if found is None:
            continue
        if a is not None:
            impulse = abs(c[ev.idx] - (l[found] if ev.direction == 1 else h[found]))
            if impulse < impulse_atr * a:
                continue
        top = float(max(o[found], c[found], h[found]) if ev.direction == -1 else max(o[found], c[found]))
        bottom = float(min(o[found], c[found]) if ev.direction == -1 else min(o[found], c[found], l[found]))
        zone = Zone("OB", ev.direction, top=top, bottom=bottom, created_idx=found)
        # mitigation check: any later close beyond the zone midpoint
        for j in range(ev.idx + 1, n):
            if ev.direction == +1 and c[j] < zone.mid:
                zone.mitigated = True
                break
            if ev.direction == -1 and c[j] > zone.mid:
                zone.mitigated = True
                break
        zones.append(zone)
    return zones


def find_fvgs(h: np.ndarray, l: np.ndarray, atr_arr: np.ndarray,
              min_atr: float = 0.3, lookback: int = 120) -> list[Zone]:
    """3-candle imbalances. Bull FVG: low[i] > high[i-2]; zone [high[i-2], low[i]].
    A gap fully traded through is dropped; partially filled zones shrink."""
    n = len(h)
    zones: list[Zone] = []
    start = max(2, n - lookback)
    for i in range(start, n):
        a = atr_arr[i] if not np.isnan(atr_arr[i]) else 0.0
        # bullish gap
        if l[i] > h[i - 2] and (l[i] - h[i - 2]) >= min_atr * a:
            top, bottom = float(l[i]), float(h[i - 2])
            # forward-fill: later lows eat into the gap from above
            filled = False
            for j in range(i + 1, n):
                if l[j] <= bottom:
                    filled = True
                    break
                top = min(top, float(l[j]))
            if not filled and top > bottom:
                zones.append(Zone("FVG", +1, top=top, bottom=bottom, created_idx=i))
        # bearish gap
        if h[i] < l[i - 2] and (l[i - 2] - h[i]) >= min_atr * a:
            top, bottom = float(l[i - 2]), float(h[i])
            filled = False
            for j in range(i + 1, n):
                if h[j] >= top:
                    filled = True
                    break
                bottom = max(bottom, float(h[j]))
            if not filled and top > bottom:
                zones.append(Zone("FVG", -1, top=top, bottom=bottom, created_idx=i))
    return zones


def find_sweeps(
    h: np.ndarray, l: np.ndarray, c: np.ndarray,
    levels: list[tuple[float, str]], atr_arr: np.ndarray,
    max_atr: float = 0.6, reclaim_bars: int = 2, lookback: int = 20,
) -> list[Sweep]:
    """Liquidity sweep: a wick pierces a level by <= max_atr*ATR but closes
    back on the original side within `reclaim_bars` bars."""
    n = len(c)
    sweeps: list[Sweep] = []
    start = max(1, n - lookback)
    for level, _name in levels:
        for i in range(start, n):
            a = atr_arr[i] if not np.isnan(atr_arr[i]) else 0.0
            if not a:
                continue
            # sweep of a low (stop hunt below): wick below, close back above
            if l[i] < level and (level - l[i]) <= max_atr * a and c[i] < level:
                for j in range(i, min(i + reclaim_bars + 1, n)):
                    if c[j] > level:
                        sweeps.append(Sweep(j, +1, level))
                        break
            elif l[i] < level <= c[i] and (level - l[i]) <= max_atr * a:
                sweeps.append(Sweep(i, +1, level))
            # sweep of a high
            if h[i] > level and (h[i] - level) <= max_atr * a and c[i] > level:
                for j in range(i, min(i + reclaim_bars + 1, n)):
                    if c[j] < level:
                        sweeps.append(Sweep(j, -1, level))
                        break
            elif h[i] > level >= c[i] and (h[i] - level) <= max_atr * a:
                sweeps.append(Sweep(i, -1, level))
    sweeps.sort(key=lambda s: s.idx)
    return sweeps


def detect_divergence(
    close: np.ndarray, osc: np.ndarray, pivots: list[Pivot],
    min_gap: int = 5, max_gap: int = 60,
) -> int:
    """Regular divergence on the last two confirmed pivots of the same kind.

    Returns +1 (bullish: lower low in price, higher low in oscillator),
    -1 (bearish: higher high in price, lower high in oscillator), or 0.
    Only pivots already confirmed by the last bar are considered.
    """
    n = len(close)
    highs = [p for p in pivots if p.is_high and p.confirmed_idx <= n - 1]
    lows = [p for p in pivots if not p.is_high and p.confirmed_idx <= n - 1]

    if len(highs) >= 2:
        p1, p2 = highs[-2], highs[-1]
        gap = p2.idx - p1.idx
        if min_gap <= gap <= max_gap and not (np.isnan(osc[p1.idx]) or np.isnan(osc[p2.idx])):
            if p2.price > p1.price and osc[p2.idx] < osc[p1.idx]:
                return -1
    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        gap = p2.idx - p1.idx
        if min_gap <= gap <= max_gap and not (np.isnan(osc[p1.idx]) or np.isnan(osc[p2.idx])):
            if p2.price < p1.price and osc[p2.idx] > osc[p1.idx]:
                return +1
    return 0

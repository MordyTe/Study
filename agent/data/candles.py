"""Multi-timeframe candle store backed by numpy ring buffers.

One CandleStore instance holds every (market, tf) series. Confirmed candles
trigger CANDLE_CLOSED events on the bus; unconfirmed updates flow on CANDLE
for the dashboard's live bar. REST backfill seeds history; gap repair splices
holes after reconnects.
"""
from __future__ import annotations

import logging

import numpy as np

from agent.bus import Bus, CANDLE, CANDLE_CLOSED
from agent.models import Candle, TF_MS

log = logging.getLogger(__name__)

# Column layout of the ring buffer
TS, O, H, L, C, V = range(6)


class Series:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.buf = np.zeros((capacity, 6), dtype=np.float64)
        self.size = 0  # number of valid rows; buffer is kept contiguous, newest last

    def append(self, c: Candle) -> None:
        if self.size < self.capacity:
            self.buf[self.size] = (c.ts, c.open, c.high, c.low, c.close, c.volume)
            self.size += 1
        else:
            self.buf[:-1] = self.buf[1:]
            self.buf[-1] = (c.ts, c.open, c.high, c.low, c.close, c.volume)

    def replace_last(self, c: Candle) -> None:
        if self.size == 0:
            self.append(c)
        else:
            self.buf[self.size - 1] = (c.ts, c.open, c.high, c.low, c.close, c.volume)

    @property
    def last_ts(self) -> int:
        return int(self.buf[self.size - 1, TS]) if self.size else 0

    def view(self) -> np.ndarray:
        """Contiguous read-only view, oldest-first."""
        v = self.buf[: self.size]
        v.flags.writeable = False
        return v

    def last(self) -> Candle | None:
        if not self.size:
            return None
        r = self.buf[self.size - 1]
        return Candle(ts=int(r[TS]), open=r[O], high=r[H], low=r[L], close=r[C], volume=r[V])


class CandleStore:
    def __init__(self, bus: Bus, tfs: list[str], capacity: int = 1500) -> None:
        self.bus = bus
        self.tfs = tfs
        self.capacity = capacity
        self._series: dict[tuple[str, str], Series] = {}
        # forming (unconfirmed) bar per (market, tf) — kept out of the ring buffer
        self._forming: dict[tuple[str, str], Candle] = {}

    def series(self, market: str, tf: str) -> Series:
        key = (market, tf)
        if key not in self._series:
            self._series[key] = Series(self.capacity)
        return self._series[key]

    def seed(self, market: str, tf: str, candles: list[Candle]) -> None:
        s = self.series(market, tf)
        for c in candles:
            if c.ts > s.last_ts:
                s.append(c)
        log.info("seeded %s %s with %d bars (last ts=%d)", market, tf, s.size, s.last_ts)

    def on_kline(self, market: str, tf: str, c: Candle) -> None:
        """WS kline handler — both confirmed and forming bars."""
        s = self.series(market, tf)
        if not c.confirmed:
            self._forming[(market, tf)] = c
            self.bus.publish(CANDLE, (market, tf, c))
            return
        if c.ts <= s.last_ts:
            if c.ts == s.last_ts:
                s.replace_last(c)  # backfill/WS splice: WS confirm wins
            return
        gap = self.detect_gap(market, tf, c.ts)
        if gap:
            log.warning("gap detected on %s %s: missing %d bars before %d", market, tf, gap, c.ts)
        s.append(c)
        self._forming.pop((market, tf), None)
        self.bus.publish(CANDLE, (market, tf, c))
        self.bus.publish(CANDLE_CLOSED, (market, tf, c))

    def detect_gap(self, market: str, tf: str, next_ts: int) -> int:
        s = self.series(market, tf)
        if not s.size:
            return 0
        interval = TF_MS[tf]
        missing = (next_ts - s.last_ts) // interval - 1
        return max(0, int(missing))

    def repair(self, market: str, tf: str, candles: list[Candle]) -> int:
        """Insert missing historical candles fetched via REST. Returns inserted count."""
        s = self.series(market, tf)
        existing = set(s.view()[:, TS].astype(np.int64).tolist())
        fresh = [c for c in candles if c.ts not in existing]
        if not fresh:
            return 0
        # Rebuild the series in order (rare path — only after gaps)
        rebuilt = Series(self.capacity)
        merged_map: dict[int, np.ndarray] = {int(row[TS]): row for row in s.view()}
        for c in fresh:
            merged_map[c.ts] = np.array([c.ts, c.open, c.high, c.low, c.close, c.volume])
        for ts in sorted(merged_map):
            r = merged_map[ts]
            rebuilt.append(Candle(ts=int(r[0]), open=float(r[1]), high=float(r[2]),
                                  low=float(r[3]), close=float(r[4]), volume=float(r[5])))
        self._series[(market, tf)] = rebuilt
        log.info("repaired %s %s: inserted %d bars", market, tf, len(fresh))
        return len(fresh)

    def forming(self, market: str, tf: str) -> Candle | None:
        return self._forming.get((market, tf))

    def last_price(self, market: str) -> float | None:
        f = self._forming.get((market, "1"))
        if f:
            return f.close
        last = self.series(market, "1").last()
        return last.close if last else None

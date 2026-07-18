"""Order-flow tracking from the public trade stream.

Builds per-minute buy/sell taker volume and a session-anchored CVD
(cumulative volume delta). CVD is only valid from process start / session
anchor — it is never faked historically, and strategies must degrade
gracefully when flow data is absent (e.g., in backtests).
"""
from __future__ import annotations

import logging
from collections import deque

from agent.models import Trade

log = logging.getLogger(__name__)

MINUTE_MS = 60_000
DAY_MS = 86_400_000


class FlowTracker:
    def __init__(self, max_minutes: int = 720) -> None:
        # (minute_ts, buy_vol, sell_vol) rolling window
        self.minutes: deque[tuple[int, float, float]] = deque(maxlen=max_minutes)
        self.cvd = 0.0
        self.session_anchor = 0  # UTC day open the CVD is anchored to
        self.started_ts = 0
        # rolling sample of trade sizes for large-print detection
        self._sizes: deque[float] = deque(maxlen=5000)

    def on_trade(self, t: Trade) -> None:
        if not self.started_ts:
            self.started_ts = t.ts
        day_open = (t.ts // DAY_MS) * DAY_MS
        if day_open != self.session_anchor:
            self.session_anchor = day_open
            self.cvd = 0.0
        delta = t.size if t.is_buy else -t.size
        self.cvd += delta
        self._sizes.append(t.size)

        minute = (t.ts // MINUTE_MS) * MINUTE_MS
        if self.minutes and self.minutes[-1][0] == minute:
            ts, b, s = self.minutes[-1]
            self.minutes[-1] = (ts, b + (t.size if t.is_buy else 0.0), s + (0.0 if t.is_buy else t.size))
        else:
            self.minutes.append((minute, t.size if t.is_buy else 0.0, 0.0 if t.is_buy else t.size))

    @property
    def available(self) -> bool:
        """Flow needs some warmup before it means anything."""
        return len(self.minutes) >= 15

    def delta_series(self, n: int) -> list[float]:
        """Per-minute delta (buy - sell) for the last n minutes, oldest-first."""
        rows = list(self.minutes)[-n:]
        return [b - s for _, b, s in rows]

    def cvd_series(self, n: int) -> list[float]:
        """Running CVD over the last n minutes (relative, oldest-first)."""
        deltas = self.delta_series(n)
        out, acc = [], 0.0
        for d in deltas:
            acc += d
            out.append(acc)
        return out

    def large_print_threshold(self, pctile: float = 99.0) -> float:
        if len(self._sizes) < 100:
            return float("inf")
        s = sorted(self._sizes)
        idx = min(len(s) - 1, int(len(s) * pctile / 100))
        return s[idx]

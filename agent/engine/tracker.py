"""Signal lifecycle tracker.

Watches 1m candles and drives each delivered signal through:
DELIVERED -> ACTIVE -> TP1/TP2/TP3 | LOSS | WIN_PARTIAL | EXPIRED_*.

Resolution rules (identical in live and backtest):
- fills/hits are checked against 1m candle high/low
- if a single candle spans both SL and TP, resolve conservatively as LOSS
- after TP1, stop moves to breakeven (entry mid); a BE tag-out = WIN_PARTIAL
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from agent.bus import Bus, SIGNAL_EVENT
from agent.models import Candle, Direction, Signal, SignalState

log = logging.getLogger(__name__)

Notifier = Callable[[Signal, SignalState, SignalState, float], Awaitable[None]]


class SignalTracker:
    def __init__(self, bus: Bus | None = None) -> None:
        self.bus = bus
        self.signals: dict[str, Signal] = {}
        self._notifiers: list[Notifier] = []

    def add_notifier(self, fn: Notifier) -> None:
        self._notifiers.append(fn)

    def track(self, sig: Signal) -> None:
        self.signals[sig.id] = sig

    @property
    def open_signals(self) -> list[Signal]:
        return [s for s in self.signals.values() if not s.state.terminal]

    async def _transition(self, sig: Signal, to: SignalState, price: float) -> None:
        frm = sig.state
        sig.state = to
        log.info("signal %s: %s -> %s @ %.2f", sig.id, frm.value, to.value, price)
        if self.bus is not None:
            self.bus.publish(SIGNAL_EVENT, (sig, frm, to, price))
        for fn in self._notifiers:
            try:
                await fn(sig, frm, to, price)
            except Exception:
                log.exception("notifier failed for signal %s", sig.id)

    async def on_candle(self, c: Candle) -> None:
        """Feed a confirmed 1m candle of the signal market."""
        bar_end = c.ts + 60_000
        for sig in list(self.signals.values()):
            if sig.state.terminal:
                continue
            await self._step(sig, c, bar_end)

    async def _step(self, sig: Signal, c: Candle, now_ts: int) -> None:
        long = sig.direction is Direction.LONG

        if sig.state is SignalState.DELIVERED:
            # Entry fill: bar traded into the entry zone
            if c.low <= sig.entry_hi and c.high >= sig.entry_lo:
                sig.fill_price = min(max(c.close, sig.entry_lo), sig.entry_hi)
                await self._transition(sig, SignalState.ACTIVE, sig.fill_price)
                # fall through — same bar may also hit SL (conservative)
                await self._check_exits(sig, c, now_ts, just_filled=True)
            elif now_ts >= sig.entry_ttl_ts:
                sig.resolved_ts = now_ts
                await self._transition(sig, SignalState.EXPIRED_UNFILLED, c.close)
            return

        if sig.state in (SignalState.ACTIVE, SignalState.TP1_HIT, SignalState.TP2_HIT):
            await self._check_exits(sig, c, now_ts, just_filled=False)

    async def _check_exits(self, sig: Signal, c: Candle, now_ts: int, just_filled: bool) -> None:
        long = sig.direction is Direction.LONG
        entry = sig.fill_price if sig.fill_price is not None else sig.entry_mid
        risk = abs(entry - sig.sl) or 1e-9

        # effective stop: original SL before TP1, breakeven after TP1
        past_tp1 = sig.state in (SignalState.TP1_HIT, SignalState.TP2_HIT)
        eff_sl = entry if past_tp1 else sig.sl

        hit_sl = c.low <= eff_sl if long else c.high >= eff_sl
        tp_levels = [(SignalState.TP1_HIT, sig.tp1), (SignalState.TP2_HIT, sig.tp2),
                     (SignalState.WIN, sig.tp3)]
        order = {SignalState.ACTIVE: 0, SignalState.TP1_HIT: 1, SignalState.TP2_HIT: 2}
        next_i = order.get(sig.state, 0)

        def tp_hit(level: float) -> bool:
            return c.high >= level if long else c.low <= level

        # Conservative same-bar rule: SL first when both hit in one bar
        if hit_sl:
            if past_tp1:
                sig.realized_r = round((abs(sig.tp1 - entry) * 0.5) / risk, 2) if sig.state is SignalState.TP1_HIT else 1.5
                sig.resolved_ts = now_ts
                await self._transition(sig, SignalState.WIN_PARTIAL, eff_sl)
            else:
                sig.realized_r = -1.0
                sig.resolved_ts = now_ts
                await self._transition(sig, SignalState.LOSS, eff_sl)
            return

        for i in range(next_i, len(tp_levels)):
            state, level = tp_levels[i]
            if tp_hit(level):
                if state is SignalState.WIN:
                    sig.realized_r = round(abs(level - entry) / risk, 2)
                    sig.resolved_ts = now_ts
                await self._transition(sig, state, level)
                if state is SignalState.WIN:
                    return
            else:
                break

        if not sig.state.terminal and now_ts >= sig.max_duration_ts:
            sig.realized_r = round((c.close - entry) / risk * (1 if long else -1), 2)
            sig.resolved_ts = now_ts
            await self._transition(sig, SignalState.EXPIRED_ACTIVE, c.close)

    # -- stats ---------------------------------------------------------------
    def stats(self) -> dict:
        terminal = [s for s in self.signals.values()
                    if s.state.terminal and s.state not in (SignalState.REJECTED, SignalState.EXPIRED_UNFILLED)]
        wins = [s for s in terminal if (s.realized_r or 0) > 0]
        losses = [s for s in terminal if (s.realized_r or 0) <= 0]
        total_r = sum(s.realized_r or 0 for s in terminal)
        gross_win = sum(s.realized_r or 0 for s in wins)
        gross_loss = abs(sum(s.realized_r or 0 for s in losses))
        return {
            "resolved": len(terminal),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(terminal) * 100, 1) if terminal else None,
            "total_r": round(total_r, 2),
            "expectancy_r": round(total_r / len(terminal), 3) if terminal else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "open": len(self.open_signals),
        }

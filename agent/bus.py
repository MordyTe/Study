"""Tiny in-process async pub/sub. Topics fan out to per-subscriber queues.

Keeps modules decoupled so the backtest runner can drive the identical
pipeline by publishing synthetic events.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)

# Topic names used across the agent
CANDLE = "candle"                # (market, tf, Candle) — includes unconfirmed
CANDLE_CLOSED = "candle_closed"  # (market, tf, Candle) — confirm:true only
TRADE = "trade"                  # (market, Trade)
DERIVATIVES = "derivatives"      # dict snapshot updates
LIQUIDATION = "liquidation"      # dict per liquidation event
SIGNAL_NEW = "signal_new"        # Signal
SIGNAL_EVENT = "signal_event"    # (Signal, from_state, to_state, price)
RESYNC = "resync_needed"         # str reason


class Bus:
    def __init__(self, maxsize: int = 4096) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._maxsize = maxsize

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        try:
            self._subs[topic].remove(q)
        except ValueError:
            pass

    def publish(self, topic: str, payload: Any) -> None:
        for q in self._subs.get(topic, ()):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest to keep the pipeline moving; log loudly.
                log.warning("bus queue full on topic %s — dropping oldest", topic)
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def stream(self, topic: str) -> AsyncIterator[Any]:
        q = self.subscribe(topic)
        try:
            while True:
                yield await q.get()
        finally:
            self.unsubscribe(topic, q)

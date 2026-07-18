"""Bybit v5 public WebSocket wrapper.

pybit runs its callbacks on its own thread — every message is bridged into
asyncio via loop.call_soon_threadsafe onto a single queue. A watchdog
rebuilds the socket if a subscribed topic goes silent, then requests a
REST gap repair via the RESYNC bus topic.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from pybit.unified_trading import WebSocket

from agent.bus import Bus, RESYNC
from agent.config import Config

log = logging.getLogger(__name__)


class BybitWsFeed:
    """One feed = one Bybit channel_type (spot or linear) with its topics."""

    def __init__(
        self,
        cfg: Config,
        bus: Bus,
        loop: asyncio.AbstractEventLoop,
        market: str,                      # "spot" | "linear"
        queue: asyncio.Queue,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self.loop = loop
        self.market = market
        self.queue = queue
        self._ws: WebSocket | None = None
        self._last_msg = time.monotonic()
        self._subs: list[tuple[str, dict[str, Any]]] = []  # (kind, kwargs)

    # -- subscription plan ---------------------------------------------------
    def plan_kline(self, symbol: str, tfs: list[str]) -> None:
        for tf in tfs:
            self._subs.append(("kline", {"interval": tf, "symbol": symbol}))

    def plan_trades(self, symbol: str) -> None:
        self._subs.append(("publicTrade", {"symbol": symbol}))

    def plan_tickers(self, symbol: str) -> None:
        self._subs.append(("tickers", {"symbol": symbol}))

    def plan_liquidations(self, symbol: str) -> None:
        self._subs.append(("allLiquidation", {"symbol": symbol}))

    # -- lifecycle -----------------------------------------------------------
    def _bridge(self, msg: dict) -> None:
        """Runs on the pybit thread — hand off to asyncio, nothing else."""
        self._last_msg = time.monotonic()
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (self.market, msg))
        except RuntimeError:
            pass  # loop closed during shutdown

    def _connect(self) -> None:
        self._ws = WebSocket(testnet=self.cfg.ws.testnet, channel_type=self.market)
        for kind, kw in self._subs:
            if kind == "kline":
                self._ws.kline_stream(callback=self._bridge, **kw)
            elif kind == "publicTrade":
                self._ws.trade_stream(callback=self._bridge, **kw)
            elif kind == "tickers":
                self._ws.ticker_stream(callback=self._bridge, **kw)
            elif kind == "allLiquidation":
                self._ws.all_liquidation_stream(callback=self._bridge, **kw)
        log.info("ws[%s] connected with %d subscriptions", self.market, len(self._subs))

    def _teardown(self) -> None:
        if self._ws is not None:
            try:
                self._ws.exit()
            except Exception:
                pass
            self._ws = None

    async def run(self) -> None:
        """Supervise the socket: connect, watch for silence, rebuild on death."""
        timeout = self.cfg.ws.watchdog_timeout_seconds
        while True:
            try:
                await asyncio.to_thread(self._connect)
                self._last_msg = time.monotonic()
                while True:
                    await asyncio.sleep(5)
                    silent = time.monotonic() - self._last_msg
                    if silent > timeout:
                        log.warning("ws[%s] silent for %.0fs — rebuilding", self.market, silent)
                        break
            except asyncio.CancelledError:
                await asyncio.to_thread(self._teardown)
                raise
            except Exception as e:
                log.error("ws[%s] error: %s", self.market, e)
            await asyncio.to_thread(self._teardown)
            self.bus.publish(RESYNC, f"ws_{self.market}_rebuild")
            await asyncio.sleep(2)


def parse_kline(msg: dict) -> list[dict]:
    """Extract kline payload rows from a WS message."""
    return msg.get("data", []) if "kline" in msg.get("topic", "") else []


def parse_trades(msg: dict) -> list[dict]:
    return msg.get("data", []) if "publicTrade" in msg.get("topic", "") else []

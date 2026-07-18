"""Bybit v5 REST wrapper: kline backfill + derivatives pollers.

All public endpoints — no API key required. A single token-bucket limiter
funnels every request so we stay far under Bybit's public rate limits.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pybit.unified_trading import HTTP

from agent.config import Config
from agent.models import Candle, TF_MS

log = logging.getLogger(__name__)


class TokenBucket:
    """Simple async token bucket: `rate` requests per second, burst `burst`."""

    def __init__(self, rate: float = 4.0, burst: int = 8) -> None:
        self.rate = rate
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class BybitRest:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._http = HTTP(testnet=cfg.ws.testnet)
        self._bucket = TokenBucket()

    async def _call(self, fn, **kwargs) -> dict[str, Any]:
        await self._bucket.acquire()
        for attempt in range(3):
            try:
                resp = await asyncio.to_thread(fn, **kwargs)
                if resp.get("retCode") != 0:
                    raise RuntimeError(f"bybit retCode={resp.get('retCode')} {resp.get('retMsg')}")
                return resp["result"]
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                log.warning("REST call failed (%s), retry in %ss", e, wait)
                await asyncio.sleep(wait)
        raise RuntimeError("unreachable")

    async def get_klines(
        self, market: str, symbol: str, tf: str, start_ms: int | None = None,
        end_ms: int | None = None, limit: int = 1000,
    ) -> list[Candle]:
        """Fetch klines, returned oldest-first."""
        category = "linear" if market == "linear" else "spot"
        kwargs: dict[str, Any] = dict(category=category, symbol=symbol, interval=tf, limit=limit)
        if start_ms is not None:
            kwargs["start"] = start_ms
        if end_ms is not None:
            kwargs["end"] = end_ms
        result = await self._call(self._http.get_kline, **kwargs)
        rows = result.get("list", [])
        # Bybit returns newest-first: [startTime, open, high, low, close, volume, turnover]
        candles = [
            Candle(ts=int(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]),
                   close=float(r[4]), volume=float(r[5]), confirmed=True)
            for r in rows
        ]
        candles.sort(key=lambda c: c.ts)
        return candles

    async def backfill(
        self, market: str, symbol: str, tf: str, bars: int,
        end_ms: int | None = None,
    ) -> list[Candle]:
        """Page backwards until `bars` candles collected; returns oldest-first."""
        out: list[Candle] = []
        cursor_end = end_ms or int(time.time() * 1000)
        while len(out) < bars:
            batch = await self.get_klines(market, symbol, tf, end_ms=cursor_end, limit=1000)
            if not batch:
                break
            out = batch + out
            cursor_end = batch[0].ts - 1
            if len(batch) < 1000:
                break
        # Drop the still-forming last bar if present (its ts + interval > now)
        now = int(time.time() * 1000)
        interval = TF_MS[tf]
        out = [c for c in out if c.ts + interval <= now]
        return out[-bars:]

    async def get_open_interest(self, symbol: str, interval: str = "5min", limit: int = 48) -> list[dict]:
        result = await self._call(
            self._http.get_open_interest, category="linear", symbol=symbol,
            intervalTime=interval, limit=limit,
        )
        rows = result.get("list", [])
        rows.reverse()  # oldest-first
        return [{"ts": int(r["timestamp"]), "oi": float(r["openInterest"])} for r in rows]

    async def get_long_short_ratio(self, symbol: str, period: str = "5min", limit: int = 24) -> list[dict]:
        result = await self._call(
            self._http.get_long_short_ratio, category="linear", symbol=symbol,
            period=period, limit=limit,
        )
        rows = result.get("list", [])
        rows.reverse()
        return [
            {"ts": int(r["timestamp"]), "buy_ratio": float(r["buyRatio"]), "sell_ratio": float(r["sellRatio"])}
            for r in rows
        ]

    async def get_funding_history(self, symbol: str, limit: int = 20) -> list[dict]:
        result = await self._call(
            self._http.get_funding_rate_history, category="linear", symbol=symbol, limit=limit,
        )
        rows = result.get("list", [])
        rows.reverse()
        return [
            {"ts": int(r["fundingRateTimestamp"]), "rate": float(r["fundingRate"])}
            for r in rows
        ]

    async def get_tickers(self, market: str, symbol: str) -> dict:
        category = "linear" if market == "linear" else "spot"
        result = await self._call(self._http.get_tickers, category=category, symbol=symbol)
        return result["list"][0] if result.get("list") else {}

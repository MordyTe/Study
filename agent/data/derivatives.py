"""Derivatives market state: funding, open interest, long/short ratio,
liquidation rollups. Sourced from the linear tickers stream (delta-merged)
plus REST pollers.
"""
from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)


class DerivativesState:
    def __init__(self) -> None:
        self.funding_rate: float | None = None
        self.next_funding_ts: int | None = None
        self.mark_price: float | None = None
        self.index_price: float | None = None
        self.open_interest: float | None = None
        # series oldest-first
        self.oi_series: deque[tuple[int, float]] = deque(maxlen=288)          # ~24h at 5min
        self.ls_ratio_series: deque[tuple[int, float, float]] = deque(maxlen=288)
        self.funding_history: deque[tuple[int, float]] = deque(maxlen=64)
        # (ts, side, notional_usd) individual liquidations, rolling ~2h
        self.liquidations: deque[tuple[int, str, float]] = deque(maxlen=5000)

    # -- tickers stream (delta updates: merge, don't replace) ---------------
    def on_ticker(self, data: dict) -> None:
        if "fundingRate" in data and data["fundingRate"] != "":
            self.funding_rate = float(data["fundingRate"])
        if "nextFundingTime" in data and data["nextFundingTime"]:
            self.next_funding_ts = int(data["nextFundingTime"])
        if "markPrice" in data and data["markPrice"]:
            self.mark_price = float(data["markPrice"])
        if "indexPrice" in data and data["indexPrice"]:
            self.index_price = float(data["indexPrice"])
        if "openInterest" in data and data["openInterest"]:
            self.open_interest = float(data["openInterest"])

    def on_liquidation(self, rows: list[dict]) -> None:
        for r in rows:
            try:
                notional = float(r["v"]) * float(r["p"])
                # Bybit: side is the liquidated position's closing order side.
                # "Buy" order = short liquidation; "Sell" order = long liquidation.
                side = "short_liq" if r.get("S") == "Buy" else "long_liq"
                self.liquidations.append((int(r["T"]), side, notional))
            except (KeyError, ValueError):
                continue

    def set_oi_series(self, rows: list[dict]) -> None:
        self.oi_series.clear()
        for r in rows:
            self.oi_series.append((r["ts"], r["oi"]))

    def set_ls_ratio(self, rows: list[dict]) -> None:
        self.ls_ratio_series.clear()
        for r in rows:
            self.ls_ratio_series.append((r["ts"], r["buy_ratio"], r["sell_ratio"]))

    def set_funding_history(self, rows: list[dict]) -> None:
        self.funding_history.clear()
        for r in rows:
            self.funding_history.append((r["ts"], r["rate"]))

    # -- derived readings ----------------------------------------------------
    def oi_change_pct(self, window_minutes: int) -> float | None:
        if len(self.oi_series) < 2:
            return None
        now_ts, now_oi = self.oi_series[-1]
        cutoff = now_ts - window_minutes * 60_000
        past = [oi for ts, oi in self.oi_series if ts <= cutoff]
        base = past[-1] if past else self.oi_series[0][1]
        if not base:
            return None
        return (now_oi - base) / base * 100

    def ls_ratio(self) -> float | None:
        if not self.ls_ratio_series:
            return None
        _, buy, sell = self.ls_ratio_series[-1]
        return buy / sell if sell else None

    def liq_notional(self, side: str, window_minutes: int = 5) -> float:
        cutoff = int(time.time() * 1000) - window_minutes * 60_000
        return sum(n for ts, s, n in self.liquidations if s == side and ts >= cutoff)

    def snapshot(self) -> dict:
        return {
            "funding_rate": self.funding_rate,
            "next_funding_ts": self.next_funding_ts,
            "mark_price": self.mark_price,
            "open_interest": self.open_interest,
            "oi_change_1h_pct": self.oi_change_pct(60),
            "ls_ratio": self.ls_ratio(),
            "long_liq_5m_usd": self.liq_notional("long_liq", 5),
            "short_liq_5m_usd": self.liq_notional("short_liq", 5),
        }

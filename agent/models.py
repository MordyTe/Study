"""Core domain models shared across the agent."""
from __future__ import annotations

import enum
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


class Direction(str, enum.Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Direction.LONG else -1


class Style(str, enum.Enum):
    SCALP = "scalp"
    INTRADAY = "intraday"


class SignalState(str, enum.Enum):
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    DELIVERED = "delivered"
    ACTIVE = "active"
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    WIN = "win"                 # TP3 hit
    WIN_PARTIAL = "win_partial" # stopped at/above BE after TP1
    LOSS = "loss"
    EXPIRED_UNFILLED = "expired_unfilled"
    EXPIRED_ACTIVE = "expired_active"
    INVALIDATED = "invalidated"

    @property
    def terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES = {
    SignalState.REJECTED,
    SignalState.WIN,
    SignalState.WIN_PARTIAL,
    SignalState.LOSS,
    SignalState.EXPIRED_UNFILLED,
    SignalState.EXPIRED_ACTIVE,
    SignalState.INVALIDATED,
}


@dataclass(frozen=True, slots=True)
class Candle:
    ts: int          # bar open time, UTC ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool = True

    @property
    def bullish(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True, slots=True)
class Trade:
    ts: int
    price: float
    size: float
    is_buy: bool  # taker side


@dataclass(frozen=True, slots=True)
class StrategyVote:
    strategy: str
    score: float                 # -1..+1, sign = direction, magnitude = conviction
    timeframe: str
    reasons: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Signal:
    id: str
    created_ts: int
    symbol: str
    market: str                  # spot | linear
    style: Style
    direction: Direction
    entry_lo: float
    entry_hi: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    rr_tp2: float
    confidence: float            # |confluence score| 0..1
    votes: list[StrategyVote] = field(default_factory=list)
    qty: float = 0.0
    leverage: int = 1
    invalidation: str = ""
    state: SignalState = SignalState.CANDIDATE
    llm_verdict: str | None = None       # CONFIRM | NEUTRAL | VETO
    llm_reasoning: str | None = None
    entry_ttl_ts: int = 0
    max_duration_ts: int = 0
    fill_price: float | None = None
    resolved_ts: int | None = None
    realized_r: float | None = None

    @property
    def entry_mid(self) -> float:
        return (self.entry_lo + self.entry_hi) / 2

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_mid - self.sl)

    def votes_json(self) -> str:
        return json.dumps([asdict(v) for v in self.votes])


def now_ms() -> int:
    return int(time.time() * 1000)


# Bybit interval -> milliseconds
TF_MS: dict[str, int] = {
    "1": 60_000,
    "5": 300_000,
    "15": 900_000,
    "60": 3_600_000,
    "240": 14_400_000,
    "D": 86_400_000,
}

TF_LABEL: dict[str, str] = {
    "1": "1m", "5": "5m", "15": "15m", "60": "1h", "240": "4h", "D": "1D",
}

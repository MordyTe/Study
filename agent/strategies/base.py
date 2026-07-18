"""Strategy contract: pure evaluation over MarketContext.

evaluate() must not do I/O, read clocks, or mutate anything — determinism
from context is what makes backtest identical to live.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.engine.context import MarketContext
from agent.models import StrategyVote


class Strategy(ABC):
    name: str = "base"

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params

    @abstractmethod
    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        """Return a vote (score in [-1, +1]) or None if not applicable."""


def load_strategies(cfg) -> list[Strategy]:
    from agent.strategies.trend_momentum import TrendMomentum
    from agent.strategies.mean_reversion import MeanReversion
    from agent.strategies.vwap_bias import VwapBias
    from agent.strategies.smc import SmartMoney
    from agent.strategies.volume_flow import VolumeFlow
    from agent.strategies.derivatives_sentiment import DerivativesSentiment
    from agent.strategies.key_levels import KeyLevels

    classes = [TrendMomentum, MeanReversion, VwapBias, SmartMoney,
               VolumeFlow, DerivativesSentiment, KeyLevels]
    return [cls(cfg.strategy_params(cls.name)) for cls in classes]

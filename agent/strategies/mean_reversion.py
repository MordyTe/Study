"""RSI + Bollinger extremes with confirmed regular divergence."""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.indicators.structure import detect_divergence
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class MeanReversion(Strategy):
    name = "mean_reversion"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        rsi_val = f.rsi[-1]
        if np.isnan(rsi_val) or np.isnan(f.bb_upper[-1]):
            return None
        ob = self.params.get("rsi_overbought", 70)
        os_ = self.params.get("rsi_oversold", 30)
        price = f.last_close
        reasons: list[str] = []
        score = 0.0

        if rsi_val <= os_:
            score += 0.45
            reasons.append(f"RSI oversold ({rsi_val:.0f})")
        elif rsi_val >= ob:
            score -= 0.45
            reasons.append(f"RSI overbought ({rsi_val:.0f})")

        if price <= f.bb_lower[-1]:
            score += 0.3
            reasons.append("price at/below lower Bollinger band")
        elif price >= f.bb_upper[-1]:
            score -= 0.3
            reasons.append("price at/above upper Bollinger band")

        div = detect_divergence(
            f.close, f.rsi, f.pivots,
            min_gap=self.params.get("divergence_min_gap", 5),
            max_gap=self.params.get("divergence_max_gap", 60),
        )
        if div == +1:
            score += 0.4
            reasons.append("bullish RSI divergence (confirmed pivots)")
        elif div == -1:
            score -= 0.4
            reasons.append("bearish RSI divergence (confirmed pivots)")

        if abs(score) < 0.3:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=f.tf, reasons=reasons,
            meta={"rsi": float(rsi_val), "divergence": div},
        )

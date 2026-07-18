"""Session VWAP bias: position relative to VWAP plus reclaim/rejection logic."""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class VwapBias(Strategy):
    name = "vwap_bias"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        vwap = f.vwap[-1]
        if np.isnan(vwap) or f.last_atr == 0:
            return None
        price = f.last_close
        dist_atr = (price - vwap) / f.last_atr
        reasons: list[str] = []
        score = 0.0

        # Base bias: above VWAP = buyers in control this session
        if dist_atr > 0.1:
            score += min(0.5, 0.2 + 0.1 * dist_atr)
            reasons.append(f"price above session VWAP (+{dist_atr:.1f} ATR)")
        elif dist_atr < -0.1:
            score -= min(0.5, 0.2 + 0.1 * abs(dist_atr))
            reasons.append(f"price below session VWAP ({dist_atr:.1f} ATR)")

        # Reclaim: crossed VWAP within the last 3 bars and held
        n = f.n
        if n >= 4:
            prev = f.close[-4:-1]
            prev_vwap = f.vwap[-4:-1]
            was_below = bool((prev < prev_vwap).all())
            was_above = bool((prev > prev_vwap).all())
            if was_below and price > vwap:
                score += 0.4
                reasons.append("VWAP reclaim from below (bullish flip)")
            elif was_above and price < vwap:
                score -= 0.4
                reasons.append("VWAP loss from above (bearish flip)")

        # Overextension fade: > 3 ATR from VWAP argues against chasing
        if dist_atr > 3:
            score -= 0.3
            reasons.append("overextended above VWAP — chase risk")
        elif dist_atr < -3:
            score += 0.3
            reasons.append("overextended below VWAP — capitulation zone")

        if abs(score) < 0.2:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=f.tf, reasons=reasons,
            meta={"vwap": float(vwap), "dist_atr": float(dist_atr)},
        )

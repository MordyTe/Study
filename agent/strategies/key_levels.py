"""Key horizontal levels: prior day high/low, day open, floor pivots,
round numbers. Scores reactions at levels, not mere proximity.
"""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class KeyLevels(Strategy):
    name = "key_levels"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        if f.last_atr == 0 or not ctx.key_levels:
            return None
        price = f.last_close
        atr_val = f.last_atr
        prox = self.params.get("proximity_atr", 0.5) * atr_val
        reasons: list[str] = []
        score = 0.0

        def near(level: float) -> bool:
            return abs(price - level) <= prox

        # Reaction logic: bounced off a level from above = support held (bullish)
        prev_low = f.low[-2] if f.n >= 2 else f.low[-1]
        prev_high = f.high[-2] if f.n >= 2 else f.high[-1]

        for name in ("PDL", "pivot_S1", "pivot_S2", "round_below"):
            level = ctx.key_levels.get(name)
            if level is None:
                continue
            touched = min(f.low[-1], prev_low) <= level + prox
            held = price > level
            if touched and held and near(level):
                score += 0.35
                reasons.append(f"{name} {level:.0f} tested and held (support)")
                break

        for name in ("PDH", "pivot_R1", "pivot_R2", "round_above"):
            level = ctx.key_levels.get(name)
            if level is None:
                continue
            touched = max(f.high[-1], prev_high) >= level - prox
            rejected = price < level
            if touched and rejected and near(level):
                score -= 0.35
                reasons.append(f"{name} {level:.0f} tested and rejected (resistance)")
                break

        # Breakout-and-hold above PDH / below PDL
        pdh, pdl = ctx.key_levels.get("PDH"), ctx.key_levels.get("PDL")
        if pdh and price > pdh + prox:
            score += 0.25
            reasons.append(f"trading above PDH {pdh:.0f} (range expansion up)")
        elif pdl and price < pdl - prox:
            score -= 0.25
            reasons.append(f"trading below PDL {pdl:.0f} (range expansion down)")

        # Day open bias
        day_open = ctx.key_levels.get("day_open")
        if day_open:
            if price > day_open:
                score += 0.1
                reasons.append("above day open")
            else:
                score -= 0.1
                reasons.append("below day open")

        if abs(score) < 0.25 or not reasons:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=f.tf, reasons=reasons,
            meta={k: v for k, v in ctx.key_levels.items()},
        )

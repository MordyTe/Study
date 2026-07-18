"""EMA stack alignment (9/21/50/200) with ADX trend-strength filter."""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class TrendMomentum(Strategy):
    name = "trend_momentum"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        periods = sorted(self.params.get("ema_periods", [9, 21, 50, 200]))
        emas = [f.ema[p][-1] for p in periods]
        if any(np.isnan(e) for e in emas):
            return None
        adx_min = self.params.get("adx_min", 18)
        adx_val = f.adx[-1]
        if np.isnan(adx_val):
            return None

        price = f.last_close
        reasons: list[str] = []
        # Pairwise stack ordering: fast above slow = bullish points
        pairs = list(zip(emas, emas[1:]))
        bull_pairs = sum(1 for fast, slow in pairs if fast > slow)
        bear_pairs = sum(1 for fast, slow in pairs if fast < slow)
        align = (bull_pairs - bear_pairs) / len(pairs)  # -1..+1

        # Price location vs fastest/slowest EMA adds conviction
        loc = 0.0
        if price > emas[0]:
            loc += 0.5
        if price > emas[-1]:
            loc += 0.5
        if price < emas[0]:
            loc -= 0.5
        if price < emas[-1]:
            loc -= 0.5

        raw = 0.7 * align + 0.3 * loc
        if adx_val < adx_min:
            raw *= 0.4  # weak trend — heavily discount
            reasons.append(f"ADX {adx_val:.0f} below {adx_min} (weak trend)")
        else:
            reasons.append(f"ADX {adx_val:.0f} confirms trend strength")

        if abs(raw) < 0.15:
            return None
        if align > 0:
            reasons.insert(0, f"EMA stack bullish ({bull_pairs}/{len(pairs)} aligned)")
        elif align < 0:
            reasons.insert(0, f"EMA stack bearish ({bear_pairs}/{len(pairs)} aligned)")

        return StrategyVote(
            strategy=self.name, score=float(np.clip(raw, -1, 1)),
            timeframe=f.tf, reasons=reasons,
            meta={"adx": float(adx_val), "ema": {p: float(f.ema[p][-1]) for p in periods}},
        )

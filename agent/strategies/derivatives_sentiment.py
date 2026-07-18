"""Derivatives positioning as a contrarian/confirmation input:
funding extremes, OI-vs-price quadrants, long/short ratio skew,
liquidation cascades. Live-only (returns None in backtests).
"""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class DerivativesSentiment(Strategy):
    name = "derivatives_sentiment"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        d = ctx.deriv
        if not d:
            return None
        reasons: list[str] = []
        score = 0.0

        funding = d.get("funding_rate")
        extreme = self.params.get("funding_extreme", 0.0005)
        if funding is not None:
            if funding >= extreme:
                score -= 0.35
                reasons.append(f"funding elevated ({funding * 100:.3f}%) — longs crowded, squeeze risk down")
            elif funding <= -extreme:
                score += 0.35
                reasons.append(f"funding negative ({funding * 100:.3f}%) — shorts crowded, squeeze fuel up")

        # OI vs price quadrant over the last hour
        oi_chg = d.get("oi_change_1h_pct")
        f = ctx.entry
        if oi_chg is not None and f.n >= 5:
            px_chg = (f.close[-1] - f.close[-5]) / f.close[-5] * 100
            sig = self.params.get("oi_change_pct", 2.0)
            if abs(oi_chg) >= sig:
                if oi_chg > 0 and px_chg > 0:
                    score += 0.25
                    reasons.append(f"OI +{oi_chg:.1f}% with rising price — new longs, trend fuel")
                elif oi_chg > 0 and px_chg < 0:
                    score -= 0.25
                    reasons.append(f"OI +{oi_chg:.1f}% with falling price — aggressive shorts")
                elif oi_chg < 0 and px_chg > 0:
                    score -= 0.15
                    reasons.append(f"OI {oi_chg:.1f}% on rally — short covering, weak rally")
                elif oi_chg < 0 and px_chg < 0:
                    score += 0.15
                    reasons.append(f"OI {oi_chg:.1f}% on dip — long capitulation, flush maturing")

        ls = d.get("ls_ratio")
        if ls is not None:
            if ls >= 2.5:
                score -= 0.2
                reasons.append(f"long/short ratio {ls:.1f} — retail heavily long (contrarian)")
            elif ls <= 0.6:
                score += 0.2
                reasons.append(f"long/short ratio {ls:.1f} — retail heavily short (contrarian)")

        cascade = self.params.get("liq_cascade_usd", 2_000_000)
        long_liq = d.get("long_liq_5m_usd", 0.0)
        short_liq = d.get("short_liq_5m_usd", 0.0)
        if long_liq >= cascade:
            score += 0.35
            reasons.append(f"long liquidation cascade (${long_liq/1e6:.1f}M/5m) — flush, reversal window")
        if short_liq >= cascade:
            score -= 0.35
            reasons.append(f"short liquidation cascade (${short_liq/1e6:.1f}M/5m) — squeeze exhausting")

        if abs(score) < 0.2 or not reasons:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=ctx.entry_tf, reasons=reasons,
            meta={"funding": funding, "oi_change_1h": oi_chg, "ls_ratio": ls},
        )

"""Volume and order-flow analysis: volume spikes with direction, CVD
divergence against price. Degrades gracefully (returns None) when live
flow data is unavailable — e.g., in backtests or right after restart.
"""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.indicators.core import sma
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class VolumeFlow(Strategy):
    name = "volume_flow"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        reasons: list[str] = []
        score = 0.0
        meta: dict = {}

        # Volume spike on the closing bar, signed by the candle direction
        vol_sma = sma(f.volume, self.params.get("vol_sma_period", 20))
        if not np.isnan(vol_sma[-1]) and vol_sma[-1] > 0:
            ratio = f.volume[-1] / vol_sma[-1]
            meta["vol_ratio"] = float(ratio)
            if ratio >= self.params.get("spike_mult", 2.0):
                candle_dir = 1 if f.close[-1] >= f.open[-1] else -1
                # spike + close near extreme = initiative; close mid-range = absorption
                rng = f.high[-1] - f.low[-1]
                if rng > 0:
                    close_pos = (f.close[-1] - f.low[-1]) / rng  # 0..1
                    if candle_dir > 0 and close_pos > 0.7:
                        score += 0.5
                        reasons.append(f"bullish volume spike ({ratio:.1f}x avg, strong close)")
                    elif candle_dir < 0 and close_pos < 0.3:
                        score -= 0.5
                        reasons.append(f"bearish volume spike ({ratio:.1f}x avg, weak close)")
                    elif close_pos > 0.6 and candle_dir < 0:
                        score += 0.3
                        reasons.append(f"absorption: heavy sell volume but close held high ({ratio:.1f}x)")
                    elif close_pos < 0.4 and candle_dir > 0:
                        score -= 0.3
                        reasons.append(f"absorption: heavy buy volume but close rejected ({ratio:.1f}x)")

        # CVD vs price divergence over the last 30 minutes (live only)
        if ctx.flow is not None and len(ctx.flow.cvd_30m) >= 15:
            cvd = ctx.flow.cvd_30m
            cvd_trend = cvd[-1] - cvd[0]
            m1 = ctx.frames.get("1")
            if m1 is not None and m1.n >= 30:
                px_trend = m1.close[-1] - m1.close[-30]
                meta["cvd_30m"] = float(cvd_trend)
                if px_trend < 0 and cvd_trend > 0:
                    score += 0.35
                    reasons.append("CVD divergence: price down but net buying (accumulation)")
                elif px_trend > 0 and cvd_trend < 0:
                    score -= 0.35
                    reasons.append("CVD divergence: price up but net selling (distribution)")
                elif abs(px_trend) > 0 and np.sign(px_trend) == np.sign(cvd_trend):
                    score += 0.15 * np.sign(px_trend)
                    reasons.append("CVD confirms price direction")

        if abs(score) < 0.25 or not reasons:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=f.tf, reasons=reasons, meta=meta,
        )

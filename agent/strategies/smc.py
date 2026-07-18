"""Smart Money Concepts — the edge layer.

Combines: structure state (BOS/CHoCH), unmitigated order-block retests,
fair value gap interaction, and liquidity sweep-and-reclaim setups.
"""
from __future__ import annotations

import numpy as np

from agent.engine.context import MarketContext
from agent.indicators.structure import find_sweeps
from agent.models import StrategyVote
from agent.strategies.base import Strategy


class SmartMoney(Strategy):
    name = "smc"

    def evaluate(self, ctx: MarketContext) -> StrategyVote | None:
        f = ctx.entry
        if f.last_atr == 0:
            return None
        price = f.last_close
        reasons: list[str] = []
        meta: dict = {}
        score = 0.0

        # 1) Recent structure event (within last 10 bars)
        recent = [e for e in f.events if f.n - 1 - e.idx <= 10]
        if recent:
            last_ev = recent[-1]
            w = 0.35 if last_ev.kind == "CHOCH" else 0.25
            score += w * last_ev.direction
            reasons.append(
                f"{last_ev.kind} {'bullish' if last_ev.direction > 0 else 'bearish'} "
                f"@ {last_ev.level:.0f} ({f.n - 1 - last_ev.idx} bars ago)"
            )
            meta["last_event"] = {"kind": last_ev.kind, "dir": last_ev.direction, "level": last_ev.level}

        # 2) Unmitigated order block retest aligned with its direction
        for ob in reversed(f.order_blocks):
            if ob.mitigated:
                continue
            near = ob.bottom - 0.3 * f.last_atr <= price <= ob.top + 0.3 * f.last_atr
            if near:
                score += 0.4 * ob.direction
                kind = "demand" if ob.direction > 0 else "supply"
                reasons.append(f"retesting unmitigated {kind} OB {ob.bottom:.0f}-{ob.top:.0f}")
                meta["ob"] = {"top": ob.top, "bottom": ob.bottom, "dir": ob.direction}
                break

        # 3) Fair value gap interaction
        for gap in reversed(f.fvgs):
            if gap.contains(price):
                score += 0.2 * gap.direction
                kind = "bullish" if gap.direction > 0 else "bearish"
                reasons.append(f"inside {kind} FVG {gap.bottom:.0f}-{gap.top:.0f}")
                meta["fvg"] = {"top": gap.top, "bottom": gap.bottom, "dir": gap.direction}
                break

        # 4) Liquidity sweep-and-reclaim of key levels / recent swings
        levels: list[tuple[float, str]] = []
        for name in ("PDH", "PDL"):
            if name in ctx.key_levels:
                levels.append((ctx.key_levels[name], name))
        swing_highs = [p for p in f.pivots if p.is_high][-3:]
        swing_lows = [p for p in f.pivots if not p.is_high][-3:]
        levels += [(p.price, "swing_high") for p in swing_highs]
        levels += [(p.price, "swing_low") for p in swing_lows]
        sweeps = find_sweeps(
            f.high, f.low, f.close, levels, f.atr,
            max_atr=self.params.get("sweep_max_atr", 0.6),
            reclaim_bars=self.params.get("sweep_reclaim_bars", 2),
            lookback=8,
        )
        fresh = [s for s in sweeps if f.n - 1 - s.idx <= 3]
        if fresh:
            s = fresh[-1]
            score += 0.45 * s.direction
            side = "lows swept & reclaimed" if s.direction > 0 else "highs swept & rejected"
            reasons.append(f"liquidity sweep: {side} @ {s.level:.0f}")
            meta["sweep"] = {"level": s.level, "dir": s.direction}

        if abs(score) < 0.25 or not reasons:
            return None
        return StrategyVote(
            strategy=self.name, score=float(np.clip(score, -1, 1)),
            timeframe=f.tf, reasons=reasons, meta=meta,
        )

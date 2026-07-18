"""Risk module: turns a Candidate into a full Signal with entry zone,
structure/ATR stop, tiered take-profits, R:R, size and leverage suggestion.
"""
from __future__ import annotations

import logging
import uuid

import numpy as np

from agent.config import Config
from agent.engine.confluence import Candidate
from agent.models import Direction, Signal, SignalState

log = logging.getLogger(__name__)


def _structure_stop(cand: Candidate) -> float | None:
    """Stop beyond the structure that justifies the entry: the OB/sweep level
    or the last confirmed swing on the entry TF."""
    f = cand.ctx.entry
    smc_meta = next((v.meta for v in cand.votes if v.strategy == "smc"), {})
    if cand.direction is Direction.LONG:
        candidates = []
        if "ob" in smc_meta and smc_meta["ob"]["dir"] > 0:
            candidates.append(smc_meta["ob"]["bottom"])
        if "sweep" in smc_meta and smc_meta["sweep"]["dir"] > 0:
            candidates.append(min(float(f.low[-3:].min()), smc_meta["sweep"]["level"]))
        swing_lows = [p for p in f.pivots if not p.is_high and p.confirmed_idx <= f.n - 1]
        if swing_lows:
            candidates.append(swing_lows[-1].price)
        return min(candidates) if candidates else None
    else:
        candidates = []
        if "ob" in smc_meta and smc_meta["ob"]["dir"] < 0:
            candidates.append(smc_meta["ob"]["top"])
        if "sweep" in smc_meta and smc_meta["sweep"]["dir"] < 0:
            candidates.append(max(float(f.high[-3:].max()), smc_meta["sweep"]["level"]))
        swing_highs = [p for p in f.pivots if p.is_high and p.confirmed_idx <= f.n - 1]
        if swing_highs:
            candidates.append(swing_highs[-1].price)
        return max(candidates) if candidates else None


def _next_opposing_level(cand: Candidate, entry: float, r_dist: float, max_r: float) -> float:
    """TP3: nearest meaningful opposing level, capped at max_r multiples."""
    kl = cand.ctx.key_levels
    sign = cand.direction.sign
    cap = entry + sign * max_r * r_dist
    level_names = (
        ("PDH", "pivot_R1", "pivot_R2", "round_above")
        if cand.direction is Direction.LONG
        else ("PDL", "pivot_S1", "pivot_S2", "round_below")
    )
    opposing = []
    for name in level_names:
        lv = kl.get(name)
        if lv is None:
            continue
        # must be beyond TP2 (2R) to be a useful runner target
        if sign * (lv - entry) > 2 * r_dist:
            opposing.append(lv)
    if not opposing:
        return cap
    nearest = min(opposing, key=lambda lv: sign * (lv - entry))
    return min(nearest, cap) if sign > 0 else max(nearest, cap)


class RiskModule:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def build_signal(self, cand: Candidate) -> Signal | None:
        rc = self.cfg.risk
        f = cand.ctx.entry
        atr_val = f.last_atr
        if atr_val <= 0:
            return None
        price = f.last_close
        sign = cand.direction.sign

        # Entry zone: from a slight retrace to the close (never chase far)
        entry_near = price
        entry_far = price - sign * 0.25 * atr_val
        entry_lo, entry_hi = sorted((entry_near, entry_far))
        entry_mid = (entry_lo + entry_hi) / 2

        # Stop: the further of structure stop vs ATR stop, plus a buffer
        atr_stop = entry_mid - sign * rc.atr_stop_mult * atr_val
        struct = _structure_stop(cand)
        if struct is not None:
            struct = struct - sign * rc.stop_buffer_atr * atr_val
            sl = min(atr_stop, struct) if sign > 0 else max(atr_stop, struct)
        else:
            sl = atr_stop
        r_dist = abs(entry_mid - sl)
        if r_dist <= 0 or r_dist > 3 * atr_val:
            return None  # nonsensical stop distance

        tp1 = entry_mid + sign * r_dist
        tp2 = entry_mid + sign * 2 * r_dist
        tp3 = _next_opposing_level(cand, entry_mid, r_dist, rc.tp3_max_r)
        rr_tp2 = abs(tp2 - entry_mid) / r_dist

        if rr_tp2 < rc.min_rr_tp2:
            return None

        qty = (rc.account_equity_usd * rc.risk_pct / 100) / r_dist
        notional = qty * entry_mid
        leverage = max(1, min(rc.max_leverage, int(np.ceil(notional / rc.account_equity_usd))))

        style_cfg = self.cfg.styles[cand.style.value]
        # Invalidation narrative: last opposing confirmed swing
        if cand.direction is Direction.LONG:
            lows = [p for p in f.pivots if not p.is_high and p.confirmed_idx <= f.n - 1]
            inval = f"close below {lows[-1].price:.0f} on {f.tf}m structure" if lows else f"close below {sl:.0f}"
        else:
            highs = [p for p in f.pivots if p.is_high and p.confirmed_idx <= f.n - 1]
            inval = f"close above {highs[-1].price:.0f} on {f.tf}m structure" if highs else f"close above {sl:.0f}"

        return Signal(
            id=uuid.uuid4().hex[:10],
            created_ts=cand.ctx.ts,
            symbol=cand.ctx.symbol,
            market=cand.ctx.market,
            style=cand.style,
            direction=cand.direction,
            entry_lo=round(entry_lo, 2), entry_hi=round(entry_hi, 2),
            sl=round(sl, 2),
            tp1=round(tp1, 2), tp2=round(tp2, 2), tp3=round(tp3, 2),
            rr_tp2=round(rr_tp2, 2),
            confidence=round(cand.confidence, 3),
            votes=cand.votes,
            qty=round(qty, 3),
            leverage=leverage,
            invalidation=inval,
            state=SignalState.CONFIRMED,
            entry_ttl_ts=cand.ctx.ts + style_cfg.entry_ttl_minutes * 60_000,
            max_duration_ts=cand.ctx.ts + style_cfg.max_duration_minutes * 60_000,
        )

"""Confluence engine: weighted vote aggregation, HTF-bias gating,
threshold + min-agreement checks, cooldown/dedup. Emits SignalCandidate
dicts that the risk module turns into full Signals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from agent.config import Config, StyleCfg
from agent.engine.context import MarketContext, TfFrame
from agent.models import Direction, StrategyVote, Style

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Candidate:
    style: Style
    direction: Direction
    score: float                 # signed weighted score
    confidence: float            # |score|
    votes: list[StrategyVote]
    htf_bias: int
    ctx: MarketContext
    gate_notes: list[str] = field(default_factory=list)


def htf_bias(frame: TfFrame) -> int:
    """Bias of one gate timeframe: EMA stack + structure trend + VWAP side."""
    points = 0
    e21, e50 = frame.ema.get(21), frame.ema.get(50)
    if e21 is not None and e50 is not None and not np.isnan(e21[-1]) and not np.isnan(e50[-1]):
        points += 1 if e21[-1] > e50[-1] else -1
    points += frame.trend
    if not np.isnan(frame.vwap[-1]):
        points += 1 if frame.last_close > frame.vwap[-1] else -1
    return 1 if points > 0 else (-1 if points < 0 else 0)


class ConfluenceEngine:
    def __init__(self, cfg: Config, strategies: list) -> None:
        self.cfg = cfg
        self.strategies = strategies
        # (style, direction) -> (last_fire_ts_ms, last_score)
        self._last_fire: dict[tuple[Style, Direction], tuple[int, float]] = {}

    def evaluate(self, ctx: MarketContext, style: Style, style_cfg: StyleCfg) -> Candidate | None:
        votes: list[StrategyVote] = []
        for s in self.strategies:
            try:
                v = s.evaluate(ctx)
            except Exception:
                log.exception("strategy %s failed", s.name)
                continue
            if v is not None:
                votes.append(v)
        if not votes:
            return None

        weights = self.cfg.strategy_weights
        wsum = sum(weights.get(v.strategy, 1.0) for v in votes)
        if not wsum:
            return None
        score = sum(weights.get(v.strategy, 1.0) * v.score for v in votes) / wsum

        conf_cfg = self.cfg.confluence
        direction = Direction.LONG if score > 0 else Direction.SHORT
        agreeing = sum(1 for v in votes if np.sign(v.score) == np.sign(score))

        if abs(score) < conf_cfg.threshold:
            return None
        if agreeing < conf_cfg.min_agreeing:
            return None

        # HTF gate: majority bias across the style's gate timeframes
        gate_notes: list[str] = []
        biases = []
        for tf in style_cfg.gate_tfs:
            frame = ctx.frames.get(tf)
            if frame is None:
                continue
            b = htf_bias(frame)
            biases.append(b)
            gate_notes.append(f"{tf}: {'bull' if b > 0 else 'bear' if b < 0 else 'neutral'}")
        bias_total = int(np.sign(sum(biases))) if biases else 0

        if bias_total != 0 and bias_total != direction.sign:
            if conf_cfg.htf_gate_mode == "hard":
                log.debug("candidate %s %s discarded by HTF gate (%s)",
                          style.value, direction.value, ", ".join(gate_notes))
                return None
            score_adj = score - 0.3 * direction.sign
            if abs(score_adj) < conf_cfg.threshold or np.sign(score_adj) != np.sign(score):
                return None
            score = score_adj
            gate_notes.append("soft gate penalty applied (-0.3)")

        # Cooldown / dedup
        key = (style, direction)
        last = self._last_fire.get(key)
        if last is not None:
            last_ts, last_score = last
            cooldown_ms = style_cfg.cooldown_minutes * 60_000
            if ctx.ts - last_ts < cooldown_ms and abs(score) < last_score + conf_cfg.improve_delta:
                return None

        self._last_fire[key] = (ctx.ts, abs(score))
        return Candidate(
            style=style, direction=direction, score=float(score),
            confidence=float(abs(score)), votes=votes,
            htf_bias=bias_total, ctx=ctx, gate_notes=gate_notes,
        )

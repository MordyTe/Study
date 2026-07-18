"""Prompt templates + compact market-state serialization for Gemini.

The serializer is token-budgeted: indicator readings and recent deltas,
never raw arrays.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from agent.engine.context import MarketContext
from agent.models import Signal, TF_LABEL

VALIDATE_SYSTEM = """You are a senior crypto derivatives trader reviewing a signal produced by a
quantitative confluence engine for ETH/USDT on Bybit. Your job is a second opinion, not a
prediction: assess whether the trade thesis is coherent, whether any listed confluence is
contradicted by the market state, and what the main risks are. Be skeptical and concise.
Respond with the JSON schema you are given. Verdict guide:
- CONFIRM: thesis coherent, no material contradiction
- NEUTRAL: tradeable but with reservations worth flagging
- VETO: a material contradiction or dangerous context (e.g., entry into news-driven chop,
  counter-trend against a strong impulse, funding about to flip the trade)"""

REGIME_SYSTEM = """You are a senior crypto trader writing a concise market regime briefing for
ETH/USDT (Bybit). Cover: current regime (trend/range/transition), the levels that matter now,
derivatives positioning read (funding, OI, liquidations), and 2-3 concrete scenarios with
invalidations. No filler, no disclaimers, no financial advice boilerplate. Write for a
professional who will scan this in 30 seconds."""


def _frame_summary(ctx: MarketContext, tf: str) -> dict | None:
    f = ctx.frames.get(tf)
    if f is None:
        return None
    def last(arr):
        v = arr[-1]
        return round(float(v), 2) if not np.isnan(v) else None
    closes = f.close[-6:]
    return {
        "tf": TF_LABEL.get(tf, tf),
        "close": round(f.last_close, 2),
        "chg_5bars_pct": round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 6 else None,
        "ema21": last(f.ema[21]) if 21 in f.ema else None,
        "ema50": last(f.ema[50]) if 50 in f.ema else None,
        "ema200": last(f.ema[200]) if 200 in f.ema else None,
        "rsi": last(f.rsi),
        "adx": last(f.adx),
        "atr": last(f.atr),
        "vwap": last(f.vwap),
        "structure_trend": {1: "up", -1: "down", 0: "flat"}[f.trend],
        "recent_events": [
            {"kind": e.kind, "dir": "bull" if e.direction > 0 else "bear", "level": round(e.level, 2)}
            for e in f.events[-3:]
        ],
    }


def serialize_context(ctx: MarketContext, tfs: list[str] | None = None) -> str:
    tfs = tfs or list(ctx.frames.keys())
    payload = {
        "symbol": ctx.symbol,
        "time_utc": datetime.fromtimestamp(ctx.ts / 1000, tz=timezone.utc).isoformat(),
        "price": round(ctx.price, 2),
        "frames": [s for tf in tfs if (s := _frame_summary(ctx, tf))],
        "key_levels": {k: round(v, 2) for k, v in ctx.key_levels.items()},
        "derivatives": ctx.deriv,
        "flow": {
            "delta_5m": round(ctx.flow.delta_5m, 1),
            "delta_15m": round(ctx.flow.delta_15m, 1),
            "cvd_30m_net": round(ctx.flow.cvd_30m[-1] - ctx.flow.cvd_30m[0], 1) if ctx.flow.cvd_30m else 0,
        } if ctx.flow else None,
    }
    return json.dumps(payload, default=str)


def validate_prompt(sig: Signal, ctx_json: str) -> str:
    votes = [
        {"strategy": v.strategy, "score": round(v.score, 2), "reasons": v.reasons}
        for v in sig.votes
    ]
    signal_json = json.dumps({
        "style": sig.style.value,
        "direction": sig.direction.value,
        "entry_zone": [sig.entry_lo, sig.entry_hi],
        "stop_loss": sig.sl,
        "take_profits": [sig.tp1, sig.tp2, sig.tp3],
        "rr_to_tp2": sig.rr_tp2,
        "confidence": sig.confidence,
        "invalidation": sig.invalidation,
        "confluences": votes,
    })
    return (
        f"MARKET STATE:\n{ctx_json}\n\n"
        f"PROPOSED SIGNAL:\n{signal_json}\n\n"
        "Review the signal against the market state and answer in the required JSON."
    )


VALIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["CONFIRM", "NEUTRAL", "VETO"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "reasoning"],
}


def regime_prompt(ctx_json: str) -> str:
    return f"MARKET STATE:\n{ctx_json}\n\nWrite the regime briefing now."

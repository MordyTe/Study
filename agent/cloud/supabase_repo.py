"""Supabase persistence for cloud (serverless) mode.

Talks to PostgREST directly with httpx + the service-role key — deliberately
avoids the heavy supabase-py dependency tree. All tables use the ta_ prefix
and are RLS-locked, so only this service key can touch them.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from agent.models import Direction, Signal, SignalState, StrategyVote, Style

log = logging.getLogger(__name__)

OPEN_STATES = ("delivered", "active", "tp1_hit", "tp2_hit")


class SupabaseRepo:
    def __init__(self, url: str | None = None, service_key: str | None = None) -> None:
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        key = service_key or os.environ["SUPABASE_SERVICE_KEY"]
        self._client = httpx.AsyncClient(
            base_url=f"{self.url}/rest/v1",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _upsert(self, table: str, rows: list[dict]) -> None:
        r = await self._client.post(
            f"/{table}", json=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        r.raise_for_status()

    async def _select(self, table: str, query: str) -> list[dict]:
        r = await self._client.get(f"/{table}?{query}")
        r.raise_for_status()
        return r.json()

    async def rpc(self, fn: str, args: dict | None = None):
        """Call a Postgres function via PostgREST RPC (service role only)."""
        r = await self._client.post(f"/rpc/{fn}", json=args or {})
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return r.text

    # -- signals -------------------------------------------------------------
    async def save_signal(self, s: Signal) -> None:
        await self._upsert("ta_signals", [{
            "id": s.id, "created_ts": s.created_ts, "symbol": s.symbol,
            "market": s.market, "style": s.style.value, "direction": s.direction.value,
            "entry_lo": s.entry_lo, "entry_hi": s.entry_hi, "sl": s.sl,
            "tp1": s.tp1, "tp2": s.tp2, "tp3": s.tp3,
            "rr_tp2": s.rr_tp2, "confidence": s.confidence,
            "qty": s.qty, "leverage": s.leverage, "invalidation": s.invalidation,
            "votes_json": json.loads(s.votes_json()),
            "llm_verdict": s.llm_verdict, "llm_reasoning": s.llm_reasoning,
            "state": s.state.value, "fill_price": s.fill_price,
            "resolved_ts": s.resolved_ts, "realized_r": s.realized_r,
            "entry_ttl_ts": s.entry_ttl_ts, "max_duration_ts": s.max_duration_ts,
        }])

    async def save_event(self, signal_id: str, ts: int, frm: SignalState,
                         to: SignalState, price: float) -> None:
        r = await self._client.post("/ta_signal_events", json=[{
            "signal_id": signal_id, "ts": ts,
            "from_state": frm.value, "to_state": to.value, "price": price,
        }])
        r.raise_for_status()

    async def recent_signals(self, limit: int = 50) -> list[dict]:
        return await self._select(
            "ta_signals",
            f"select=id,created_ts,style,direction,entry_lo,entry_hi,sl,tp1,tp2,tp3,"
            f"rr_tp2,confidence,state,realized_r,llm_verdict"
            f"&order=created_ts.desc&limit={limit}",
        )

    async def load_open_signals(self) -> list[Signal]:
        rows = await self._select(
            "ta_signals", f"select=*&state=in.({','.join(OPEN_STATES)})&order=created_ts.asc")
        return [_signal_from_row(r) for r in rows]

    async def resolved_stats(self) -> dict:
        rows = await self._select(
            "ta_signals",
            "select=realized_r,state&resolved_ts=not.is.null"
            "&state=not.in.(rejected,expired_unfilled)&limit=2000",
        )
        rs = [r["realized_r"] or 0.0 for r in rows]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        open_rows = await self._select(
            "ta_signals", f"select=id&state=in.({','.join(OPEN_STATES)})")
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "resolved": len(rs), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(rs) * 100, 1) if rs else None,
            "total_r": round(sum(rs), 2),
            "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "open": len(open_rows),
        }

    # -- engine state / settings --------------------------------------------
    async def get_state(self, key: str, default: Any = None) -> Any:
        rows = await self._select("ta_engine_state", f"select=value&key=eq.{key}")
        return rows[0]["value"] if rows else default

    async def set_state(self, key: str, value: Any) -> None:
        await self._upsert("ta_engine_state", [{"key": key, "value": value}])

    async def get_settings(self) -> dict[str, str]:
        rows = await self._select("ta_settings", "select=key,value")
        return {r["key"]: r["value"] for r in rows}

    async def set_setting(self, key: str, value: str) -> None:
        await self._upsert("ta_settings", [{"key": key, "value": value}])

    async def log_llm_call(self, ts: int, kind: str, model: str, latency_ms: int, ok: bool) -> None:
        try:
            r = await self._client.post("/ta_llm_calls", json=[{
                "ts": ts, "kind": kind, "model": model, "latency_ms": latency_ms, "ok": ok,
            }])
            r.raise_for_status()
        except Exception:
            log.warning("llm call log failed", exc_info=True)


def _signal_from_row(r: dict) -> Signal:
    votes = []
    for v in (r.get("votes_json") or []):
        try:
            votes.append(StrategyVote(
                strategy=v["strategy"], score=v["score"], timeframe=v.get("timeframe", ""),
                reasons=v.get("reasons", []), meta=v.get("meta", {}),
            ))
        except (KeyError, TypeError):
            continue
    return Signal(
        id=r["id"], created_ts=r["created_ts"], symbol=r["symbol"], market=r["market"],
        style=Style(r["style"]), direction=Direction(r["direction"]),
        entry_lo=r["entry_lo"], entry_hi=r["entry_hi"], sl=r["sl"],
        tp1=r["tp1"], tp2=r["tp2"], tp3=r["tp3"],
        rr_tp2=r["rr_tp2"], confidence=r["confidence"], votes=votes,
        qty=r.get("qty") or 0.0, leverage=r.get("leverage") or 1,
        invalidation=r.get("invalidation") or "",
        state=SignalState(r["state"]),
        llm_verdict=r.get("llm_verdict"), llm_reasoning=r.get("llm_reasoning"),
        entry_ttl_ts=r.get("entry_ttl_ts") or 0,
        max_duration_ts=r.get("max_duration_ts") or 0,
        fill_price=r.get("fill_price"), resolved_ts=r.get("resolved_ts"),
        realized_r=r.get("realized_r"),
    )

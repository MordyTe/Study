"""Typed queries over the SQLite store."""
from __future__ import annotations

import logging

from agent.models import Candle, Signal, SignalState
from agent.store.db import Db

log = logging.getLogger(__name__)


class Repo:
    def __init__(self, db: Db) -> None:
        self.db = db

    # -- candles -------------------------------------------------------------
    async def save_candles(self, market: str, tf: str, candles: list[Candle]) -> None:
        if not candles or self.db.conn is None:
            return
        await self.db.conn.executemany(
            "INSERT OR REPLACE INTO candles (market, tf, ts, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(market, tf, c.ts, c.open, c.high, c.low, c.close, c.volume) for c in candles],
        )
        await self.db.conn.commit()

    async def load_candles(self, market: str, tf: str,
                           ts_from: int | None = None, ts_to: int | None = None) -> list[Candle]:
        q = "SELECT ts, open, high, low, close, volume FROM candles WHERE market=? AND tf=?"
        args: list = [market, tf]
        if ts_from is not None:
            q += " AND ts >= ?"
            args.append(ts_from)
        if ts_to is not None:
            q += " AND ts <= ?"
            args.append(ts_to)
        q += " ORDER BY ts ASC"
        assert self.db.conn is not None
        rows = await (await self.db.conn.execute(q, args)).fetchall()
        return [Candle(ts=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows]

    async def candle_range(self, market: str, tf: str) -> tuple[int, int, int]:
        assert self.db.conn is not None
        row = await (await self.db.conn.execute(
            "SELECT MIN(ts), MAX(ts), COUNT(*) FROM candles WHERE market=? AND tf=?",
            (market, tf))).fetchone()
        return (row[0] or 0, row[1] or 0, row[2] or 0)

    # -- signals -------------------------------------------------------------
    async def save_signal(self, s: Signal) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            "INSERT OR REPLACE INTO signals (id, created_ts, symbol, market, style, direction, "
            "entry_lo, entry_hi, sl, tp1, tp2, tp3, rr_tp2, confidence, qty, leverage, "
            "invalidation, votes_json, llm_verdict, llm_reasoning, state, fill_price, "
            "resolved_ts, realized_r) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.id, s.created_ts, s.symbol, s.market, s.style.value, s.direction.value,
             s.entry_lo, s.entry_hi, s.sl, s.tp1, s.tp2, s.tp3, s.rr_tp2, s.confidence,
             s.qty, s.leverage, s.invalidation, s.votes_json(), s.llm_verdict,
             s.llm_reasoning, s.state.value, s.fill_price, s.resolved_ts, s.realized_r),
        )
        await self.db.conn.commit()

    async def save_event(self, signal_id: str, ts: int, frm: SignalState,
                         to: SignalState, price: float) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            "INSERT INTO signal_events (signal_id, ts, from_state, to_state, price) VALUES (?,?,?,?,?)",
            (signal_id, ts, frm.value, to.value, price),
        )
        await self.db.conn.commit()

    async def recent_signals(self, limit: int = 20) -> list[dict]:
        assert self.db.conn is not None
        self.db.conn.row_factory = None
        cur = await self.db.conn.execute(
            "SELECT id, created_ts, style, direction, entry_lo, entry_hi, sl, tp1, tp2, tp3, "
            "rr_tp2, confidence, state, realized_r, llm_verdict FROM signals "
            "ORDER BY created_ts DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        cols = ["id", "created_ts", "style", "direction", "entry_lo", "entry_hi", "sl",
                "tp1", "tp2", "tp3", "rr_tp2", "confidence", "state", "realized_r", "llm_verdict"]
        return [dict(zip(cols, r)) for r in rows]

    async def log_llm_call(self, ts: int, kind: str, model: str, latency_ms: int, ok: bool) -> None:
        assert self.db.conn is not None
        await self.db.conn.execute(
            "INSERT INTO llm_calls (ts, kind, model, latency_ms, ok) VALUES (?,?,?,?,?)",
            (ts, kind, model, latency_ms, int(ok)),
        )
        await self.db.conn.commit()

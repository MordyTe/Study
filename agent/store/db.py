"""SQLite persistence (WAL mode) for candles, signals, events, llm calls."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    market TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (market, tf, ts)
);
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    created_ts INTEGER,
    symbol TEXT, market TEXT, style TEXT, direction TEXT,
    entry_lo REAL, entry_hi REAL, sl REAL,
    tp1 REAL, tp2 REAL, tp3 REAL,
    rr_tp2 REAL, confidence REAL,
    qty REAL, leverage INTEGER,
    invalidation TEXT,
    votes_json TEXT,
    llm_verdict TEXT, llm_reasoning TEXT,
    state TEXT,
    fill_price REAL, resolved_ts INTEGER, realized_r REAL
);
CREATE TABLE IF NOT EXISTS signal_events (
    signal_id TEXT, ts INTEGER, from_state TEXT, to_state TEXT, price REAL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    ts INTEGER, kind TEXT, model TEXT, latency_ms INTEGER, ok INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Db:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        log.info("db open at %s", self.path)

    async def close(self) -> None:
        if self.conn:
            await self.conn.commit()
            await self.conn.close()
            self.conn = None

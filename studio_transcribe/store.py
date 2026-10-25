"""Persistent, searchable transcript store (Stage 2).

A thin wrapper over the stdlib ``sqlite3``. Every transcription run is a
*session*; its merged, speaker-tagged segments are stored and made searchable.
Full-text search uses SQLite's **FTS5** when the runtime provides it, and falls
back to ``LIKE`` scanning otherwise — so the module works on any Python build.

No third-party dependencies.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from .models import Segment


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def _fts_match_query(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression (terms AND-ed)."""

    terms = [t for t in query.split() if t]
    if not terms:
        return '""'
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    return " ".join(quoted)


class TranscriptStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.fts_enabled = _fts5_available(self.conn)
        self._create_schema()

    def _create_schema(self) -> None:
        cur = self.conn
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                source TEXT,
                started_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                channel INTEGER,
                speaker TEXT,
                start REAL,
                end REAL,
                text TEXT,
                avg_logprob REAL,
                no_speech_prob REAL,
                compression_ratio REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id)"
        )
        if self.fts_enabled:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts "
                "USING fts5(text, content='segments', content_rowid='id')"
            )
        self.conn.commit()

    def create_session(
        self,
        name: str,
        source: str = "",
        started_at: Optional[str] = None,
    ) -> int:
        started_at = started_at or datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO sessions (name, source, started_at) VALUES (?, ?, ?)",
            (name, source, started_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_segments(self, session_id: int, segments: Sequence[Segment]) -> int:
        count = 0
        for seg in segments:
            cur = self.conn.execute(
                """
                INSERT INTO segments
                    (session_id, channel, speaker, start, end, text,
                     avg_logprob, no_speech_prob, compression_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    seg.channel,
                    seg.speaker,
                    seg.start,
                    seg.end,
                    seg.text,
                    seg.avg_logprob,
                    seg.no_speech_prob,
                    seg.compression_ratio,
                ),
            )
            if self.fts_enabled:
                self.conn.execute(
                    "INSERT INTO segments_fts (rowid, text) VALUES (?, ?)",
                    (cur.lastrowid, seg.text),
                )
            count += 1
        self.conn.commit()
        return count

    def search(
        self,
        query: str,
        speaker: Optional[str] = None,
        session_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        params: List = []
        if self.fts_enabled and query.strip():
            sql = (
                "SELECT s.*, ses.name AS session_name, ses.started_at "
                "FROM segments_fts f "
                "JOIN segments s ON s.id = f.rowid "
                "JOIN sessions ses ON ses.id = s.session_id "
                "WHERE segments_fts MATCH ?"
            )
            params.append(_fts_match_query(query))
        else:
            sql = (
                "SELECT s.*, ses.name AS session_name, ses.started_at "
                "FROM segments s "
                "JOIN sessions ses ON ses.id = s.session_id "
                "WHERE s.text LIKE ?"
            )
            params.append(f"%{query}%")

        if speaker:
            sql += " AND s.speaker = ?"
            params.append(speaker)
        if session_id is not None:
            sql += " AND s.session_id = ?"
            params.append(session_id)
        if since:
            sql += " AND ses.started_at >= ?"
            params.append(since)
        if until:
            sql += " AND ses.started_at <= ?"
            params.append(until)

        sql += " ORDER BY s.session_id, s.start LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_session_segments(self, session_id: int) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM segments WHERE session_id = ? ORDER BY start",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "TranscriptStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

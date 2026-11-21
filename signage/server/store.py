"""SQLite storage: slides, settings, sessions."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS slides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template TEXT NOT NULL,
  data TEXT NOT NULL,
  duration INTEGER NOT NULL DEFAULT 12,
  enabled INTEGER NOT NULL DEFAULT 1,
  schedule TEXT,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tracks (name TEXT PRIMARY KEY, title TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, created REAL NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(slides)")}
            if "expires" not in columns:  # databases created before slides could expire
                db.execute("ALTER TABLE slides ADD COLUMN expires TEXT")
            if "screens" not in columns:  # NULL = every screen, otherwise a JSON list of screen numbers
                db.execute("ALTER TABLE slides ADD COLUMN screens TEXT")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # --- settings -------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        with self._db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def version(self) -> int:
        return int(self.get("version", "0"))

    def bump(self) -> None:
        self.set("version", str(self.version() + 1))

    # --- sessions -------------------------------------------------------
    def add_session(self, token: str, created: float) -> None:
        with self._db() as db:
            db.execute("INSERT INTO sessions(token,created) VALUES(?,?)", (token, created))

    def has_session(self, token: str, not_before: float) -> bool:
        with self._db() as db:
            row = db.execute("SELECT 1 FROM sessions WHERE token=? AND created>=?", (token, not_before)).fetchone()
        return row is not None

    def drop_sessions(self, token: str | None = None) -> None:
        with self._db() as db:
            if token is None:
                db.execute("DELETE FROM sessions")
            else:
                db.execute("DELETE FROM sessions WHERE token=?", (token,))

    # --- slides ---------------------------------------------------------
    @staticmethod
    def _slide(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "template": row["template"],
            "data": json.loads(row["data"]),
            "duration": row["duration"],
            "enabled": bool(row["enabled"]),
            "schedule": json.loads(row["schedule"]) if row["schedule"] else None,
            "expires": row["expires"],
            "screens": json.loads(row["screens"]) if row["screens"] else None,
        }

    def slides(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM slides ORDER BY position, id").fetchall()
        return [self._slide(r) for r in rows]

    def slide(self, slide_id: int) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM slides WHERE id=?", (slide_id,)).fetchone()
        return self._slide(row) if row else None

    def add_slide(self, template: str, data: dict, duration: int, enabled: bool, schedule: dict | None,
                  expires: str | None = None, screens: list[int] | None = None) -> int:
        with self._db() as db:
            pos = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM slides").fetchone()[0]
            cur = db.execute(
                "INSERT INTO slides(template,data,duration,enabled,schedule,position,expires,screens) VALUES(?,?,?,?,?,?,?,?)",
                (template, json.dumps(data, ensure_ascii=False), duration, int(enabled),
                 json.dumps(schedule) if schedule else None, pos, expires, json.dumps(screens) if screens else None),
            )
            new_id = cur.lastrowid
        self.bump()
        return new_id

    def update_slide(self, slide_id: int, data: dict, duration: int, enabled: bool, schedule: dict | None,
                     expires: str | None = None, screens: list[int] | None = None) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE slides SET data=?, duration=?, enabled=?, schedule=?, expires=?, screens=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), duration, int(enabled),
                 json.dumps(schedule) if schedule else None, expires, json.dumps(screens) if screens else None, slide_id),
            )
        self.bump()

    def set_slide_screens(self, slide_id: int, screens: list[int] | None) -> None:
        with self._db() as db:
            db.execute("UPDATE slides SET screens=? WHERE id=?", (json.dumps(screens) if screens else None, slide_id))

    def delete_slide(self, slide_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM slides WHERE id=?", (slide_id,))
        self.bump()

    def reorder(self, ids: list[int]) -> None:
        with self._db() as db:
            for pos, slide_id in enumerate(ids, start=1):
                db.execute("UPDATE slides SET position=? WHERE id=?", (pos, slide_id))
        self.bump()

    # --- music tracks ---------------------------------------------------
    def tracks(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT name, title FROM tracks ORDER BY position, name").fetchall()
        return [{"name": r["name"], "title": r["title"]} for r in rows]

    def add_track(self, name: str, title: str) -> None:
        with self._db() as db:
            pos = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM tracks").fetchone()[0]
            db.execute("INSERT INTO tracks(name,title,position) VALUES(?,?,?)", (name, title, pos))
        self.bump()

    def delete_track(self, name: str) -> bool:
        with self._db() as db:
            found = db.execute("DELETE FROM tracks WHERE name=?", (name,)).rowcount > 0
        self.bump()
        return found

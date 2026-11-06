"""Append-only JSONL trace of what the agent did, with text values redacted by default."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any

from agent_play import __version__

REDACTED_KEYS = {"text", "value", "name", "title", "label", "description", "password", "summary", "task", "note"}


def sanitize(value: Any, redact: bool) -> Any:
    if not redact:
        return value
    if isinstance(value, dict):
        return {key: ({"redacted": True} if key in REDACTED_KEYS and val not in (None, "") else sanitize(val, redact)) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize(item, redact) for item in value]
    return value


class Trace:
    def __init__(self, path: Path | None, session_id: str, redact: bool = True) -> None:
        self.path = path
        self.session_id = session_id
        self.redact = redact
        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.write("trace.meta", {"schema": 1, "version": __version__, "os": platform.system().lower(), "pid": os.getpid()})

    def write(self, event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.seq += 1
            record = {"seq": self.seq, "ts_ms": int(time.time() * 1000), "session_id": self.session_id, "event": event}
            record.update(sanitize(data or {}, self.redact))
            self.events.append(record)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.events[-limit:] if limit else list(self.events)

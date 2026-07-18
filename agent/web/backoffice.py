"""Backoffice: manage API keys (.env) and core tunables from the dashboard.

Security model: the dashboard binds to 127.0.0.1 only, so only the machine
owner can reach this. Secrets are write-mostly — reads return masked values
(last 4 chars), never the full key. Writes go to the project .env file;
key changes take effect after restart (a restart hint is returned).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

SECRET_KEYS = [
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token"),
    ("TELEGRAM_CHAT_ID", "Telegram Chat ID"),
    ("GEMINI_API_KEY", "Gemini API Key"),
    ("BYBIT_API_KEY", "Bybit API Key (optional, read-only)"),
    ("BYBIT_API_SECRET", "Bybit API Secret (optional)"),
]
_ALLOWED = {k for k, _ in SECRET_KEYS}
# secrets are single-line values; forbid quotes/newlines that could mangle .env
_VALUE_RE = re.compile(r"^[^\r\n'\"]*$")


class SecretUpdate(BaseModel):
    key: str
    value: str


class EnvStore:
    def __init__(self, root: Path) -> None:
        self.path = root / ".env"

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text().splitlines()

    def read_masked(self) -> list[dict]:
        current: dict[str, str] = {}
        for line in self._read_lines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()
        out = []
        for key, label in SECRET_KEYS:
            val = current.get(key, "")
            if not val:
                masked, is_set = "", False
            elif key == "TELEGRAM_CHAT_ID":
                masked, is_set = val, True  # chat id is not sensitive to the owner
            else:
                masked, is_set = ("•" * 8 + val[-4:]) if len(val) > 4 else "•" * 8, True
            out.append({"key": key, "label": label, "masked": masked, "is_set": is_set})
        return out

    def set_secret(self, key: str, value: str) -> None:
        if key not in _ALLOWED:
            raise ValueError(f"unknown key: {key}")
        value = value.strip()
        if not _VALUE_RE.match(value):
            raise ValueError("value contains forbidden characters")
        lines = self._read_lines()
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        self.path.write_text("\n".join(lines) + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        log.info("backoffice: %s %s", key, "updated" if value else "cleared")

    def delete_secret(self, key: str) -> None:
        self.set_secret(key, "")

"""Serverless-friendly Telegram: plain Bot API over HTTPS.

Outbound: sendMessage for signal cards and lifecycle events.
Inbound: webhook updates (set the webhook to POST /api/telegram with a
secret token) handled without aiogram.
"""
from __future__ import annotations

import logging
import os

import httpx

from agent.delivery import formatting as fmt
from agent.models import Signal, SignalState

log = logging.getLogger(__name__)


class TelegramHttp:
    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)

    async def send(self, text: str) -> None:
        if not self.enabled:
            log.info("[telegram-off] %s", text.replace("\n", " | ")[:200])
            return
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in _split(text):
                try:
                    r = await client.post(
                        f"https://api.telegram.org/bot{self.token}/sendMessage",
                        json={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML"},
                    )
                    if r.status_code != 200:
                        log.warning("telegram send failed: %s %s", r.status_code, r.text[:200])
                except httpx.HTTPError as e:
                    log.warning("telegram send error: %s", e)

    async def send_signal(self, sig: Signal) -> None:
        await self.send(fmt.signal_card(sig))

    async def notify_event(self, sig: Signal, frm: SignalState, to: SignalState, price: float) -> None:
        msg = fmt.event_message(sig, frm, to, price)
        if msg:
            await self.send(msg)

    def allowed_update(self, update: dict) -> bool:
        chat = (update.get("message") or {}).get("chat") or {}
        return str(chat.get("id", "")) == str(self.chat_id)

    @staticmethod
    def command_of(update: dict) -> str | None:
        text = ((update.get("message") or {}).get("text") or "").strip()
        if text.startswith("/"):
            return text.split()[0].split("@")[0].lstrip("/").lower()
        return None


def _split(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts

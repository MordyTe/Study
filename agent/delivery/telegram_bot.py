"""Private Telegram bot (aiogram 3, long polling).

Hard allowlist: any chat other than TELEGRAM_CHAT_ID is ignored.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message

from agent.config import Config
from agent.delivery import formatting as fmt
from agent.models import Signal, SignalState

log = logging.getLogger(__name__)


class TelegramDelivery:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.chat_id = cfg.secrets.telegram_chat_id
        self.enabled = bool(
            cfg.telegram.get("enabled", True)
            and cfg.secrets.telegram_bot_token
            and self.chat_id
        )
        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        # hooks wired by App
        self.get_status: Callable[[], Awaitable[str]] | None = None
        self.get_analysis: Callable[[], Awaitable[str]] | None = None
        self.get_signals: Callable[[], Awaitable[str]] | None = None
        self.get_stats: Callable[[], Awaitable[str]] | None = None
        self.get_settings: Callable[[], Awaitable[str]] | None = None

        if self.enabled:
            self.bot = Bot(
                token=cfg.secrets.telegram_bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            self.dp = Dispatcher()
            self._register_handlers()
        else:
            log.warning("telegram disabled (missing token/chat id) — signals go to log only")

    def _allowed(self, message: Message) -> bool:
        return str(message.chat.id) == str(self.chat_id)

    def _register_handlers(self) -> None:
        assert self.dp is not None

        @self.dp.message(Command("start", "help"))
        async def cmd_start(message: Message) -> None:
            if not self._allowed(message):
                return
            await message.answer(
                "<b>ETH/USDT Signal Agent</b>\n"
                "/status — feed health, bias, open signals\n"
                "/analyze — full on-demand analysis (Gemini)\n"
                "/signals — recent signals\n"
                "/stats — performance\n"
                "/settings — current configuration"
            )

        @self.dp.message(Command("status"))
        async def cmd_status(message: Message) -> None:
            if not self._allowed(message) or self.get_status is None:
                return
            await message.answer(await self.get_status())

        @self.dp.message(Command("analyze"))
        async def cmd_analyze(message: Message) -> None:
            if not self._allowed(message) or self.get_analysis is None:
                return
            await message.answer("🔍 Running full analysis…")
            text = await self.get_analysis()
            for chunk in _split(text):
                await message.answer(chunk)

        @self.dp.message(Command("signals"))
        async def cmd_signals(message: Message) -> None:
            if not self._allowed(message) or self.get_signals is None:
                return
            await message.answer(await self.get_signals())

        @self.dp.message(Command("stats"))
        async def cmd_stats(message: Message) -> None:
            if not self._allowed(message) or self.get_stats is None:
                return
            await message.answer(await self.get_stats())

        @self.dp.message(Command("settings"))
        async def cmd_settings(message: Message) -> None:
            if not self._allowed(message) or self.get_settings is None:
                return
            await message.answer(await self.get_settings())

    async def run(self) -> None:
        if not self.enabled:
            return
        assert self.bot and self.dp
        log.info("telegram bot polling started")
        await self.dp.start_polling(self.bot, handle_signals=False)

    async def send(self, text: str) -> None:
        if not self.enabled or self.bot is None:
            log.info("[telegram-off] %s", text.replace("\n", " | ")[:300])
            return
        try:
            for chunk in _split(text):
                await self.bot.send_message(self.chat_id, chunk)
        except Exception:
            log.exception("telegram send failed")

    async def send_signal(self, sig: Signal) -> None:
        await self.send(fmt.signal_card(sig))

    async def notify_event(self, sig: Signal, frm: SignalState, to: SignalState, price: float) -> None:
        msg = fmt.event_message(sig, frm, to, price)
        if msg:
            await self.send(msg)


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

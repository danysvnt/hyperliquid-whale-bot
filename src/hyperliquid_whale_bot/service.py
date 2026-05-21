"""Top-level service: ties together Watcher, Bot, and the notifier consumer."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .bot.formatters import format_event
from .bot.keyboards import explorer_keyboard
from .bot.main import build_bot, build_dispatcher
from .config import Settings
from .hl import HyperliquidClient, Watcher
from .hl.watcher import DispatchedEvent
from .logging_setup import get_logger
from .storage import Database, Repository

log = get_logger(__name__)


class Service:
    """Owns all long-lived components and orchestrates them under a single asyncio loop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_path)
        self.repo = Repository(self.db)
        self.hl = HyperliquidClient(network=settings.hl_network)
        self.queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
        self.watcher = Watcher(
            settings=settings,
            client=self.hl,
            repo=self.repo,
            out_queue=self.queue,
        )
        self.bot: Bot = build_bot(settings)
        self.dispatcher = build_dispatcher(settings=settings, repo=self.repo, hl=self.hl)

    async def run(self) -> None:
        await self.db.initialize()
        log.info("service.starting", network=self.settings.hl_network)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.watcher.run(), name="watcher")
            tg.create_task(self._notifier_loop(), name="notifier")
            tg.create_task(self._run_bot(), name="bot")

    async def _run_bot(self) -> None:
        try:
            await self.dispatcher.start_polling(self.bot, handle_signals=False)
        finally:
            await self.bot.session.close()

    async def _notifier_loop(self) -> None:
        """Consume DispatchedEvents from the queue and send them to Telegram."""
        while True:
            dispatched = await self.queue.get()
            try:
                await self._send_event(dispatched)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "notifier.send_failed",
                    chat_id=dispatched.chat_id,
                    error=repr(exc),
                )
            finally:
                self.queue.task_done()

    async def _send_event(self, dispatched: DispatchedEvent) -> None:
        # Each subscriber may have a different language preference.
        lang = await self.repo.get_user_language(dispatched.chat_id)
        text = format_event(dispatched.event, label=dispatched.label, lang=lang)
        try:
            await self.bot.send_message(
                chat_id=dispatched.chat_id,
                text=text,
                reply_markup=explorer_keyboard(dispatched.event.address, lang),
                disable_web_page_preview=True,
            )
        except TelegramAPIError as exc:
            log.warning(
                "notifier.telegram_error",
                chat_id=dispatched.chat_id,
                error=repr(exc),
            )

    async def stop(self) -> None:
        self.watcher.stop()

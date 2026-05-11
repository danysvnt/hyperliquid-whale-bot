"""aiogram bootstrap: build the Bot + Dispatcher with our handlers wired in."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ..config import Settings
from ..hl import HyperliquidClient
from ..storage import Repository
from .handlers import build_router


def build_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(settings: Settings, repo: Repository, hl: HyperliquidClient) -> Dispatcher:
    # MemoryStorage is enough for our FSM needs (single-process; states are short-lived).
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router(settings=settings, repo=repo, hl=hl))
    return dp

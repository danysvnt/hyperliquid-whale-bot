"""Telegram command handlers (aiogram v3)."""

from __future__ import annotations

import contextlib

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..hl import HyperliquidClient
from ..logging_setup import get_logger
from ..storage import Repository
from .formatters import format_snapshot
from .i18n import SUPPORTED_LANGS, button_texts, t
from .keyboards import (
    explorer_keyboard,
    language_keyboard,
    main_reply_keyboard,
    positions_menu_keyboard,
    wallet_picker_keyboard,
)

log = get_logger(__name__)


def build_router(settings: Settings, repo: Repository, hl: HyperliquidClient) -> Router:
    """Create the aiogram Router wired to our dependencies."""
    router = Router(name="commands")

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        await repo.upsert_user(chat_id)
        lang = await repo.get_user_language(chat_id)
        text = f"{t('welcome.title', lang)}\n\n{t('welcome.help_hint', lang)}"
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_reply_keyboard(lang),
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await _send_help(message, lang)

    @router.message(Command("add"))
    async def cmd_add(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        await repo.upsert_user(chat_id)
        lang = await repo.get_user_language(chat_id)

        args = (message.text or "").split(maxsplit=2)
        if len(args) < 2:
            await message.answer(t("add.usage", lang), parse_mode=ParseMode.HTML)
            return

        address = args[1].strip()
        label = args[2].strip() if len(args) >= 3 else _short_label(address)

        if not _looks_like_address(address):
            await message.answer(t("add.invalid_address", lang), parse_mode=ParseMode.HTML)
            return

        # Enforce per-user wallet limit (skip enforcement in whitelist mode for the owner).
        current_count = await repo.count_wallets(chat_id)
        if current_count >= settings.max_wallets_per_user:
            await message.answer(
                t("add.limit_reached", lang, limit=settings.max_wallets_per_user),
                parse_mode=ParseMode.HTML,
            )
            return

        existing_label = await repo.find_label(chat_id, address)
        if existing_label is not None:
            await message.answer(
                t("add.already_tracked", lang, label=_html_escape(existing_label)),
                parse_mode=ParseMode.HTML,
            )
            return

        await repo.add_wallet(chat_id, address, label)
        await message.answer(
            t("add.success", lang, label=_html_escape(label), address=address.lower()),
            parse_mode=ParseMode.HTML,
            reply_markup=explorer_keyboard(address, lang),
        )

    @router.message(Command("remove"))
    async def cmd_remove(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer(t("remove.usage", lang), parse_mode=ParseMode.HTML)
            return

        target = args[1].strip()
        removed = await repo.remove_wallet(chat_id, target)
        key = "remove.success" if removed else "remove.not_found"
        await message.answer(t(key, lang), parse_mode=ParseMode.HTML)

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        await _send_wallet_list(message, repo, settings, chat_id, lang)

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer(t("status.usage", lang), parse_mode=ParseMode.HTML)
            return

        target = args[1].strip()
        wallet = await _resolve_wallet(repo, chat_id, target)
        if wallet is None:
            await message.answer(t("remove.not_found", lang), parse_mode=ParseMode.HTML)
            return

        await _send_wallet_snapshot(message, hl, wallet.address, wallet.label, lang)

    @router.message(Command("positions"))
    async def cmd_positions(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        await _send_positions_menu(message, repo, chat_id, lang)

    @router.message(Command("lang"))
    async def cmd_lang(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await message.answer(t("lang.choose", lang), reply_markup=language_keyboard())

    # --- Reply-keyboard buttons (text matches in any supported language) ----
    @router.message(F.text.in_(button_texts("kb.wallets")))
    async def kb_wallets(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        await _send_wallet_list(message, repo, settings, chat_id, lang)

    @router.message(F.text.in_(button_texts("kb.positions")))
    async def kb_positions(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        await _send_positions_menu(message, repo, chat_id, lang)

    @router.message(F.text.in_(button_texts("kb.help")))
    async def kb_help(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await _send_help(message, lang)

    @router.message(F.text.in_(button_texts("kb.lang")))
    async def kb_lang(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await message.answer(t("lang.choose", lang), reply_markup=language_keyboard())

    # --- Inline callbacks ---------------------------------------------------
    @router.callback_query(F.data.startswith("lang:"))
    async def cb_lang(query: CallbackQuery) -> None:
        if query.data is None or not query.message or query.from_user is None:
            await query.answer()
            return
        new_lang = query.data.split(":", 1)[1]
        if new_lang not in SUPPORTED_LANGS:
            await query.answer()
            return
        chat_id = query.message.chat.id
        await repo.upsert_user(chat_id, language=new_lang)
        with contextlib.suppress(Exception):
            # query.message may be inaccessible in groups or no longer editable.
            await query.message.edit_text(t("lang.changed", new_lang))  # type: ignore[union-attr]
        # Refresh reply keyboard with new language labels.
        if query.bot is not None:
            await query.bot.send_message(
                chat_id,
                t("welcome.help_hint", new_lang),
                reply_markup=main_reply_keyboard(new_lang),
            )
        await query.answer()

    @router.callback_query(F.data == "pos:all")
    async def cb_positions_all(query: CallbackQuery) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallets = await repo.list_wallets(chat_id)
        if not wallets:
            await query.answer()
            await query.bot.send_message(chat_id, t("positions.empty", lang))
            return
        await query.answer()
        for w in wallets:
            await _send_wallet_snapshot_via_bot(query.bot, chat_id, hl, w.address, w.label, lang)

    @router.callback_query(F.data == "pos:pick")
    async def cb_positions_pick(query: CallbackQuery) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallets = await repo.list_wallets(chat_id)
        if not wallets:
            await query.answer()
            await query.bot.send_message(chat_id, t("positions.empty", lang))
            return
        await query.answer()
        await query.bot.send_message(
            chat_id,
            t("positions.pick_prompt", lang),
            reply_markup=wallet_picker_keyboard(wallets, lang),
        )

    @router.callback_query(F.data.startswith("pos:show:"))
    async def cb_positions_show(query: CallbackQuery) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        address = query.data.split(":", 2)[2]
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallet = await _resolve_wallet(repo, chat_id, address)
        if wallet is None:
            await query.answer()
            await query.bot.send_message(chat_id, t("positions.not_found", lang))
            return
        await query.answer()
        await _send_wallet_snapshot_via_bot(
            query.bot, chat_id, hl, wallet.address, wallet.label, lang
        )

    return router


# --- helpers ---------------------------------------------------------------


def _chat_id(message: Message) -> int:
    return message.chat.id


async def _send_help(message: Message, lang: str) -> None:
    lines = [
        t("help.title", lang),
        "",
        t("help.add", lang),
        t("help.remove", lang),
        t("help.list", lang),
        t("help.status", lang),
        t("help.positions", lang),
        t("help.lang", lang),
    ]
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _send_wallet_list(
    message: Message, repo: Repository, settings: Settings, chat_id: int, lang: str
) -> None:
    wallets = await repo.list_wallets(chat_id)
    if not wallets:
        await message.answer(t("list.empty", lang))
        return
    lines = [t("list.title", lang, count=len(wallets), limit=settings.max_wallets_per_user)]
    for w in wallets:
        lines.append(f"• <b>{_html_escape(w.label)}</b> — <code>{w.address}</code>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _send_positions_menu(message: Message, repo: Repository, chat_id: int, lang: str) -> None:
    wallets = await repo.list_wallets(chat_id)
    if not wallets:
        await message.answer(t("positions.empty", lang))
        return
    await message.answer(
        t("positions.choose", lang),
        reply_markup=positions_menu_keyboard(lang),
    )


async def _send_wallet_snapshot(
    message: Message,
    hl: HyperliquidClient,
    address: str,
    label: str,
    lang: str,
) -> None:
    await message.answer(t("status.fetching", lang))
    try:
        snapshot = await hl.fetch_snapshot(address)
    except Exception as exc:  # noqa: BLE001
        log.error("status.fetch_failed", address=address, error=repr(exc))
        await message.answer(t("status.error", lang))
        return
    text = format_snapshot(snapshot, label=label, lang=lang)
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=explorer_keyboard(address, lang),
    )


async def _send_wallet_snapshot_via_bot(
    bot: Bot,
    chat_id: int,
    hl: HyperliquidClient,
    address: str,
    label: str,
    lang: str,
) -> None:
    """Same as _send_wallet_snapshot but for callbacks (no source Message to .answer on)."""
    await bot.send_message(chat_id, t("status.fetching", lang))
    try:
        snapshot = await hl.fetch_snapshot(address)
    except Exception as exc:  # noqa: BLE001
        log.error("status.fetch_failed", address=address, error=repr(exc))
        await bot.send_message(chat_id, t("status.error", lang))
        return
    text = format_snapshot(snapshot, label=label, lang=lang)
    await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=explorer_keyboard(address, lang),
    )


def _looks_like_address(addr: str) -> bool:
    s = addr.strip().lower()
    if not s.startswith("0x") or len(s) != 42:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


def _short_label(address: str) -> str:
    """Build a human-readable default label like '0xab...cd12'."""
    a = address.lower()
    return f"{a[:6]}…{a[-4:]}"


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


async def _resolve_wallet(repo: Repository, chat_id: int, target: str) -> _ResolvedWallet | None:
    """Resolve user input (address or label) to a tracked wallet of this chat."""
    target = target.strip()
    wallets = await repo.list_wallets(chat_id)
    target_lower = target.lower()
    for w in wallets:
        if w.address.lower() == target_lower or w.label == target:
            return _ResolvedWallet(address=w.address, label=w.label)
    return None


async def _ensure_access(message: Message, settings: Settings) -> bool:
    """Whitelist check. Returns True if the chat is allowed; otherwise sends a denial reply."""
    if settings.is_whitelisted(message.chat.id):
        return True
    await message.answer(t("access.denied"))
    return False


# Tiny dataclass-like resolution result (kept private to this module).
class _ResolvedWallet:
    __slots__ = ("address", "label")

    def __init__(self, address: str, label: str) -> None:
        self.address = address
        self.label = label

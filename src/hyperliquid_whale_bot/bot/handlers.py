"""Telegram command handlers (aiogram v3)."""

from __future__ import annotations

import asyncio
import contextlib

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Settings
from ..hl import HyperliquidClient
from ..logging_setup import get_logger
from ..models import NotificationKind, TrackedWallet, WalletSnapshot
from ..storage import Repository
from .formatters import format_multi_snapshot, format_snapshot
from .i18n import SUPPORTED_LANGS, button_texts, t
from .keyboards import (
    ask_label_keyboard,
    cancel_keyboard,
    explorer_keyboard,
    language_keyboard,
    main_reply_keyboard,
    positions_menu_keyboard,
    wallet_list_keyboard,
    wallet_picker_keyboard,
    wallet_settings_keyboard,
)

log = get_logger(__name__)

# Max characters allowed in a wallet label. Telegram inline button captions
# render fine up to ~30 chars; we keep some headroom for emoji + ellipsis.
MAX_LABEL_LEN = 32


class AddWalletStates(StatesGroup):
    """FSM states for the two-step /add flow."""

    awaiting_address = State()  # entered via the "Add wallet" button (no address yet)
    awaiting_label = State()  # address already validated, asking for a label


class EditWalletStates(StatesGroup):
    """FSM state for inline rename."""

    awaiting_new_label = State()


def build_router(settings: Settings, repo: Repository, hl: HyperliquidClient) -> Router:
    """Create the aiogram Router wired to our dependencies."""
    router = Router(name="commands")

    # === Command handlers ====================================================

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        if not await _ensure_access(message, settings):
            return
        await state.clear()
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
    async def cmd_add(message: Message, state: FSMContext) -> None:
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
        if not _looks_like_address(address):
            await message.answer(t("add.invalid_address", lang), parse_mode=ParseMode.HTML)
            return

        if not await _check_capacity_and_dup(message, repo, settings, chat_id, address, lang):
            return

        if len(args) >= 3:
            # Inline form: /add 0x... label  — old behavior preserved.
            await _do_add_wallet(message, repo, chat_id, address, args[2].strip(), lang)
            return

        # Two-step form: store the address, ask for a label, set FSM state.
        await state.set_state(AddWalletStates.awaiting_label)
        await state.update_data(address=address.lower())
        await message.answer(
            t("add.ask_label", lang),
            reply_markup=ask_label_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )

    @router.message(AddWalletStates.awaiting_label, F.text)
    async def fsm_add_label(message: Message, state: FSMContext) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        data = await state.get_data()
        address_raw = data.get("address")
        if not isinstance(address_raw, str):
            await state.clear()
            return
        # Reject commands (user might type /cancel; route through proper cancel).
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            await message.answer(t("edit.empty", lang))
            return
        if len(text) > MAX_LABEL_LEN:
            await message.answer(
                t("edit.too_long", lang, max=MAX_LABEL_LEN), parse_mode=ParseMode.HTML
            )
            return
        await state.clear()
        await _do_add_wallet(message, repo, chat_id, address_raw, text, lang)

    @router.message(AddWalletStates.awaiting_address, F.text)
    async def fsm_add_address(message: Message, state: FSMContext) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        address = (message.text or "").strip()
        if not _looks_like_address(address):
            await message.answer(
                t("add.invalid_address", lang),
                parse_mode=ParseMode.HTML,
                reply_markup=cancel_keyboard(lang, "add:cancel"),
            )
            return
        if not await _check_capacity_and_dup(message, repo, settings, chat_id, address, lang):
            await state.clear()
            return
        await state.set_state(AddWalletStates.awaiting_label)
        await state.update_data(address=address.lower())
        await message.answer(
            t("add.ask_label", lang),
            reply_markup=ask_label_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )

    @router.message(EditWalletStates.awaiting_new_label, F.text)
    async def fsm_edit_label(message: Message, state: FSMContext) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        data = await state.get_data()
        address_raw = data.get("address")
        if not isinstance(address_raw, str):
            await state.clear()
            return
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            await message.answer(t("edit.empty", lang))
            return
        if len(text) > MAX_LABEL_LEN:
            await message.answer(
                t("edit.too_long", lang, max=MAX_LABEL_LEN), parse_mode=ParseMode.HTML
            )
            return
        ok = await repo.update_wallet_label(chat_id, address_raw, text)
        await state.clear()
        if not ok:
            await message.answer(t("wset.gone", lang))
            await _show_wallet_list(message.bot, chat_id, repo, settings, lang)
            return
        await message.answer(
            t("edit.success", lang, label=_html_escape(text)), parse_mode=ParseMode.HTML
        )
        wallet = await repo.get_wallet(chat_id, address_raw)
        if wallet is not None and message.bot is not None:
            await _send_wallet_settings(message.bot, chat_id, wallet, lang)

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
        if message.bot is not None:
            await _show_wallet_list(message.bot, chat_id, repo, settings, lang)

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

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext) -> None:
        """Allow text-based cancel as a fallback in case the inline cancel button is unreachable."""
        if not await _ensure_access(message, settings):
            return
        await state.clear()
        lang = await repo.get_user_language(_chat_id(message))
        await message.answer(t("add.cancelled", lang))

    # === Reply-keyboard text-button handlers =================================

    @router.message(StateFilter(None), F.text.in_(button_texts("kb.wallets")))
    async def kb_wallets(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        if message.bot is not None:
            await _show_wallet_list(message.bot, chat_id, repo, settings, lang)

    @router.message(StateFilter(None), F.text.in_(button_texts("kb.positions")))
    async def kb_positions(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        chat_id = _chat_id(message)
        lang = await repo.get_user_language(chat_id)
        await _send_positions_menu(message, repo, chat_id, lang)

    @router.message(StateFilter(None), F.text.in_(button_texts("kb.help")))
    async def kb_help(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await _send_help(message, lang)

    @router.message(StateFilter(None), F.text.in_(button_texts("kb.lang")))
    async def kb_lang(message: Message) -> None:
        if not await _ensure_access(message, settings):
            return
        lang = await repo.get_user_language(_chat_id(message))
        await message.answer(t("lang.choose", lang), reply_markup=language_keyboard())

    # === Inline callbacks ====================================================

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
        if query.bot is not None:
            await query.bot.send_message(
                chat_id,
                t("welcome.help_hint", new_lang),
                reply_markup=main_reply_keyboard(new_lang),
            )
        await query.answer()

    # --- Positions menu ------------------------------------------------------
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
        await query.bot.send_message(chat_id, t("status.fetching", lang))
        results = await asyncio.gather(
            *(hl.fetch_snapshot(w.address) for w in wallets),
            return_exceptions=True,
        )
        items: list[tuple[str, WalletSnapshot]] = []
        any_failed = False
        for w, result in zip(wallets, results, strict=True):
            if isinstance(result, BaseException):
                log.error("positions.fetch_failed", address=w.address, error=repr(result))
                any_failed = True
                continue
            items.append((w.label, result))
        if not items:
            await query.bot.send_message(chat_id, t("status.error", lang))
            return
        for chunk in format_multi_snapshot(items, lang):
            await query.bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)
        if any_failed:
            await query.bot.send_message(chat_id, t("status.error", lang))

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

    # --- Wallet list / settings ----------------------------------------------
    @router.callback_query(F.data == "w:back")
    async def cb_wallet_back(query: CallbackQuery, state: FSMContext) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        await state.clear()
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        await query.answer()
        await _edit_to_wallet_list(query, repo, settings, chat_id, lang)

    @router.callback_query(F.data.startswith("w:open:"))
    async def cb_wallet_open(query: CallbackQuery) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        address = query.data.split(":", 2)[2]
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallet = await repo.get_wallet(chat_id, address)
        if wallet is None:
            await query.answer(t("wset.gone", lang), show_alert=True)
            await _edit_to_wallet_list(query, repo, settings, chat_id, lang)
            return
        await query.answer()
        await _edit_to_wallet_settings(query, wallet, lang)

    @router.callback_query(F.data.startswith("w:tog:"))
    async def cb_wallet_toggle(query: CallbackQuery) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        _, _, kind_raw, address = query.data.split(":", 3)
        kind = _toggle_kind_from(kind_raw)
        if kind is None:
            await query.answer()
            return
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallet = await repo.get_wallet(chat_id, address)
        if wallet is None:
            await query.answer(t("wset.gone", lang), show_alert=True)
            await _edit_to_wallet_list(query, repo, settings, chat_id, lang)
            return
        new_value = not wallet.is_notification_enabled(kind)
        await repo.set_notification(chat_id, address, kind, new_value)
        refreshed = await repo.get_wallet(chat_id, address)
        await query.answer()
        if refreshed is not None:
            await _edit_to_wallet_settings(query, refreshed, lang)

    @router.callback_query(F.data.startswith("w:edit:"))
    async def cb_wallet_edit(query: CallbackQuery, state: FSMContext) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        address = query.data.split(":", 2)[2]
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        wallet = await repo.get_wallet(chat_id, address)
        if wallet is None:
            await query.answer(t("wset.gone", lang), show_alert=True)
            await _edit_to_wallet_list(query, repo, settings, chat_id, lang)
            return
        await state.set_state(EditWalletStates.awaiting_new_label)
        await state.update_data(address=address.lower())
        await query.answer()
        await query.bot.send_message(
            chat_id,
            t(
                "edit.ask_new_label",
                lang,
                label=_html_escape(wallet.label),
                address=wallet.address.lower(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_keyboard(lang, f"edit:cancel:{address.lower()}"),
        )

    @router.callback_query(F.data.startswith("w:del:"))
    async def cb_wallet_delete(query: CallbackQuery) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        address = query.data.split(":", 2)[2]
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        await repo.remove_wallet(chat_id, address)
        await query.answer(t("wset.deleted", lang), show_alert=False)
        await _edit_to_wallet_list(query, repo, settings, chat_id, lang)

    @router.callback_query(F.data == "w:add")
    async def cb_wallet_add(query: CallbackQuery, state: FSMContext) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        current = await repo.count_wallets(chat_id)
        if current >= settings.max_wallets_per_user:
            await query.answer(
                t("add.limit_reached", lang, limit=settings.max_wallets_per_user),
                show_alert=True,
            )
            return
        await state.set_state(AddWalletStates.awaiting_address)
        await query.answer()
        await query.bot.send_message(
            chat_id,
            t("add.ask_address", lang),
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_keyboard(lang, "add:cancel"),
        )

    # --- /add FSM cancel / skip ---------------------------------------------
    @router.callback_query(F.data == "add:cancel")
    async def cb_add_cancel(query: CallbackQuery, state: FSMContext) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        await state.clear()
        lang = await repo.get_user_language(query.message.chat.id)
        with contextlib.suppress(Exception):
            await query.message.edit_text(t("add.cancelled", lang))  # type: ignore[union-attr]
        await query.answer()

    @router.callback_query(F.data == "add:skip")
    async def cb_add_skip(query: CallbackQuery, state: FSMContext) -> None:
        if query.message is None or query.bot is None:
            await query.answer()
            return
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        data = await state.get_data()
        address_raw = data.get("address")
        await state.clear()
        if not isinstance(address_raw, str) or not _looks_like_address(address_raw):
            await query.answer()
            return
        label = _short_label(address_raw)
        with contextlib.suppress(Exception):
            await query.message.delete()  # type: ignore[union-attr]
        await query.answer()
        await _do_add_wallet_via_bot(query.bot, chat_id, repo, address_raw, label, lang)

    @router.callback_query(F.data.startswith("edit:cancel:"))
    async def cb_edit_cancel(query: CallbackQuery, state: FSMContext) -> None:
        if query.data is None or query.message is None or query.bot is None:
            await query.answer()
            return
        address = query.data.split(":", 2)[2]
        await state.clear()
        chat_id = query.message.chat.id
        lang = await repo.get_user_language(chat_id)
        with contextlib.suppress(Exception):
            await query.message.edit_text(t("edit.cancelled", lang))  # type: ignore[union-attr]
        wallet = await repo.get_wallet(chat_id, address)
        await query.answer()
        if wallet is not None:
            await _send_wallet_settings(query.bot, chat_id, wallet, lang)

    return router


# === Helpers ================================================================


def _chat_id(message: Message) -> int:
    return message.chat.id


def _toggle_kind_from(raw: str) -> NotificationKind | None:
    if raw == "pos":
        return NotificationKind.POSITIONS
    if raw == "twap":
        return NotificationKind.TWAP
    if raw == "limit":
        return NotificationKind.LIMIT
    return None


async def _check_capacity_and_dup(
    message: Message,
    repo: Repository,
    settings: Settings,
    chat_id: int,
    address: str,
    lang: str,
) -> bool:
    """Reply with a friendly error and return False if user is over capacity or already tracks the wallet."""
    if await repo.count_wallets(chat_id) >= settings.max_wallets_per_user:
        await message.answer(
            t("add.limit_reached", lang, limit=settings.max_wallets_per_user),
            parse_mode=ParseMode.HTML,
        )
        return False
    existing = await repo.find_label(chat_id, address)
    if existing is not None:
        await message.answer(
            t("add.already_tracked", lang, label=_html_escape(existing)),
            parse_mode=ParseMode.HTML,
        )
        return False
    return True


async def _do_add_wallet(
    message: Message,
    repo: Repository,
    chat_id: int,
    address: str,
    label: str,
    lang: str,
) -> None:
    await repo.add_wallet(chat_id, address, label[:MAX_LABEL_LEN])
    await message.answer(
        t("add.success", lang, label=_html_escape(label), address=address.lower()),
        parse_mode=ParseMode.HTML,
        reply_markup=explorer_keyboard(address, lang),
    )


async def _do_add_wallet_via_bot(
    bot: Bot,
    chat_id: int,
    repo: Repository,
    address: str,
    label: str,
    lang: str,
) -> None:
    await repo.add_wallet(chat_id, address, label[:MAX_LABEL_LEN])
    await bot.send_message(
        chat_id,
        t("add.success", lang, label=_html_escape(label), address=address.lower()),
        parse_mode=ParseMode.HTML,
        reply_markup=explorer_keyboard(address, lang),
    )


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


async def _show_wallet_list(
    bot: Bot | None,
    chat_id: int,
    repo: Repository,
    settings: Settings,
    lang: str,
) -> None:
    """Send the wallet list as a fresh message (used for /list and reply-keyboard tap)."""
    if bot is None:
        return
    wallets = await repo.list_wallets(chat_id)
    text, keyboard = _wallet_list_view(wallets, settings, lang)
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _edit_to_wallet_list(
    query: CallbackQuery,
    repo: Repository,
    settings: Settings,
    chat_id: int,
    lang: str,
) -> None:
    """Edit the current message in place to show the wallet list (used by 'Back' button)."""
    wallets = await repo.list_wallets(chat_id)
    text, keyboard = _wallet_list_view(wallets, settings, lang)
    if query.message is None:
        return
    with contextlib.suppress(Exception):
        await query.message.edit_text(  # type: ignore[union-attr]
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )


def _wallet_list_view(
    wallets: list[TrackedWallet], settings: Settings, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    if not wallets:
        return t("wlist.empty", lang), wallet_list_keyboard([], lang)
    text = t(
        "wlist.title",
        lang,
        count=len(wallets),
        limit=settings.max_wallets_per_user,
    )
    return text, wallet_list_keyboard(wallets, lang)


async def _send_wallet_settings(bot: Bot, chat_id: int, wallet: TrackedWallet, lang: str) -> None:
    text = t(
        "wset.title",
        lang,
        label=_html_escape(wallet.label),
        address=wallet.address.lower(),
    )
    await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_settings_keyboard(wallet, lang),
    )


async def _edit_to_wallet_settings(query: CallbackQuery, wallet: TrackedWallet, lang: str) -> None:
    """Edit the current message in place to show the wallet settings screen."""
    if query.message is None:
        return
    text = t(
        "wset.title",
        lang,
        label=_html_escape(wallet.label),
        address=wallet.address.lower(),
    )
    with contextlib.suppress(Exception):
        await query.message.edit_text(  # type: ignore[union-attr]
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_settings_keyboard(wallet, lang),
        )


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

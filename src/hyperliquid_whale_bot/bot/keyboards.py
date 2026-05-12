"""Reply + inline keyboards used in bot replies."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from ..models import TrackedWallet
from .i18n import t


def main_reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Persistent 2x2 menu under the input field: Wallets / Positions / Help / Lang."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("kb.wallets", lang)),
                KeyboardButton(text=t("kb.positions", lang)),
            ],
            [
                KeyboardButton(text=t("kb.help", lang)),
                KeyboardButton(text=t("kb.lang", lang)),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def explorer_keyboard(address: str, lang: str) -> InlineKeyboardMarkup:
    """Three explorer buttons under any wallet-specific reply.

    Hyperliquid app explorer doesn't expose per-wallet position context, so we
    omit it here. Coinmarketman's app is login-walled (no public per-address
    URL), so the Coinmarketman button opens the app root.
    """
    addr = address.lower()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn.hypurrscan", lang),
                    url=f"https://hypurrscan.io/address/{addr}",
                ),
                InlineKeyboardButton(
                    text=t("btn.hyperdash", lang),
                    url=f"https://hyperdash.info/address/{addr}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn.cmm", lang),
                    url="https://app.coinmarketman.com/",
                ),
            ],
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    """Three-button row for language selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang:uk"),
            ]
        ]
    )


def positions_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """After tapping 'Positions': choose between 'All wallets' or 'Pick one'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("positions.btn_all", lang),
                    callback_data="pos:all",
                ),
                InlineKeyboardButton(
                    text=t("positions.btn_pick", lang),
                    callback_data="pos:pick",
                ),
            ]
        ]
    )


def wallet_picker_keyboard(wallets: list[TrackedWallet], lang: str) -> InlineKeyboardMarkup:
    """One row per tracked wallet. Tap a row -> we show that wallet's snapshot."""
    rows = [
        [
            InlineKeyboardButton(
                text=w.label,
                callback_data=f"pos:show:{w.address.lower()}",
            )
        ]
        for w in wallets
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_list_keyboard(wallets: list[TrackedWallet], lang: str) -> InlineKeyboardMarkup:
    """Wallet list as inline buttons: one row per wallet + bottom 'Add wallet' button.

    Tapping a wallet row opens that wallet's settings (see `wallet_settings_keyboard`).
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=w.label,
                callback_data=f"w:open:{w.address.lower()}",
            )
        ]
        for w in wallets
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("wlist.add_btn", lang),
                callback_data="w:add",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_settings_keyboard(wallet: TrackedWallet, lang: str) -> InlineKeyboardMarkup:
    """Per-wallet settings: 3 notification toggles + rename + delete + back."""
    addr = wallet.address.lower()
    pos_key = "wset.toggle.positions.on" if wallet.notify_positions else "wset.toggle.positions.off"
    twap_key = "wset.toggle.twap.on" if wallet.notify_twap else "wset.toggle.twap.off"
    limit_key = "wset.toggle.limit.on" if wallet.notify_limit else "wset.toggle.limit.off"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(pos_key, lang), callback_data=f"w:tog:pos:{addr}")],
            [InlineKeyboardButton(text=t(twap_key, lang), callback_data=f"w:tog:twap:{addr}")],
            [InlineKeyboardButton(text=t(limit_key, lang), callback_data=f"w:tog:limit:{addr}")],
            [InlineKeyboardButton(text=t("wset.edit_name", lang), callback_data=f"w:edit:{addr}")],
            [
                InlineKeyboardButton(text=t("wset.delete", lang), callback_data=f"w:del:{addr}"),
                InlineKeyboardButton(text=t("wset.back", lang), callback_data="w:back"),
            ],
        ]
    )


def cancel_keyboard(lang: str, cancel_data: str) -> InlineKeyboardMarkup:
    """Single 'Cancel' button used during FSM flows (add / rename).

    `cancel_data` is the callback payload so the handler can route back to
    the appropriate screen (wallet list, settings, etc.).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("common.cancel", lang), callback_data=cancel_data)]
        ]
    )


def ask_label_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Used during the /add flow: 'Skip' (use auto-label) + 'Cancel'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("edit.skip", lang), callback_data="add:skip"),
                InlineKeyboardButton(text=t("common.cancel", lang), callback_data="add:cancel"),
            ]
        ]
    )

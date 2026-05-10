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
    """Four explorer buttons under any wallet-specific reply, in two rows.

    Coinmarketman's app is login-walled (no public per-address URL), so the
    Coinmarketman button opens the app root; the user navigates from there.
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
                    url=f"https://hyperdash.info/trader/{addr}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn.hyperliquid", lang),
                    url=f"https://app.hyperliquid.xyz/explorer/address/{addr}",
                ),
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

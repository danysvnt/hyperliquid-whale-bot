"""Inline keyboards used in bot replies."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .i18n import t


def explorer_keyboard(address: str, lang: str) -> InlineKeyboardMarkup:
    """Three-button row: Hypurrscan / Hyperdash / Hyperliquid app."""
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
                InlineKeyboardButton(
                    text=t("btn.hyperliquid", lang),
                    url=f"https://app.hyperliquid.xyz/explorer/address/{addr}",
                ),
            ]
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

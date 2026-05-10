"""Unit tests for the keyboards module."""

from __future__ import annotations

from hyperliquid_whale_bot.bot.i18n import button_texts, t
from hyperliquid_whale_bot.bot.keyboards import (
    explorer_keyboard,
    main_reply_keyboard,
    positions_menu_keyboard,
    wallet_picker_keyboard,
)
from hyperliquid_whale_bot.models import TrackedWallet


def test_main_reply_keyboard_has_four_buttons_in_two_rows_for_each_lang() -> None:
    """The persistent reply keyboard is a 2x2 grid in every supported language."""
    for lang in ("ru", "en", "uk"):
        kb = main_reply_keyboard(lang)
        assert len(kb.keyboard) == 2, f"expected 2 rows for {lang}"
        assert all(len(row) == 2 for row in kb.keyboard), f"each row 2 buttons for {lang}"
        texts = [btn.text for row in kb.keyboard for btn in row]
        assert texts[0] == t("kb.wallets", lang)
        assert texts[1] == t("kb.positions", lang)
        assert texts[2] == t("kb.help", lang)
        assert texts[3] == t("kb.lang", lang)
        assert kb.resize_keyboard is True
        assert kb.is_persistent is True


def test_button_texts_returns_all_localized_variants() -> None:
    """button_texts(key) must include the localized button text for each language."""
    for kb_key in ("kb.wallets", "kb.positions", "kb.help", "kb.lang"):
        texts = button_texts(kb_key)
        assert t(kb_key, "ru") in texts
        assert t(kb_key, "en") in texts
        assert t(kb_key, "uk") in texts


def test_explorer_keyboard_has_four_buttons_including_coinmarketman() -> None:
    """Each wallet-related reply must surface 4 explorer links: Hypurrscan, Hyperdash, HL, CMM."""
    kb = explorer_keyboard("0x" + "ab" * 20, "ru")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert len(flat) == 4, "expected 4 explorer buttons"

    urls = {btn.url for btn in flat}
    assert any("hypurrscan.io" in (u or "") for u in urls)
    assert any("hyperdash.info" in (u or "") for u in urls)
    assert any("app.hyperliquid.xyz" in (u or "") for u in urls)
    assert any(u == "https://app.coinmarketman.com/" for u in urls)


def test_explorer_keyboard_uses_lowercased_address() -> None:
    """User can pass any case; we always lowercase before building deep-links."""
    upper = "0x" + "AB" * 20
    kb = explorer_keyboard(upper, "en")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    addr_lower = upper.lower()
    has_lowercased = any(btn.url and addr_lower in btn.url for btn in flat)
    assert has_lowercased, "no explorer button referenced the lowercased address"


def test_positions_menu_keyboard_has_two_buttons() -> None:
    """The /positions menu must present exactly 'All wallets' and 'Pick one'."""
    kb = positions_menu_keyboard("ru")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert len(flat) == 2
    callbacks = {btn.callback_data for btn in flat}
    assert "pos:all" in callbacks
    assert "pos:pick" in callbacks


def test_wallet_picker_keyboard_one_row_per_wallet() -> None:
    """wallet_picker_keyboard must emit one button per tracked wallet with stable callback_data."""
    wallets = [
        TrackedWallet(chat_id=1, address="0x" + "ab" * 20, label="alpha"),
        TrackedWallet(chat_id=1, address="0x" + "cd" * 20, label="beta"),
        TrackedWallet(chat_id=1, address="0x" + "EF" * 20, label="gamma"),
    ]
    kb = wallet_picker_keyboard(wallets, "en")
    assert len(kb.inline_keyboard) == 3, "expected 3 rows for 3 wallets"
    for row, expected in zip(kb.inline_keyboard, wallets, strict=True):
        assert len(row) == 1
        assert row[0].text == expected.label
        assert row[0].callback_data == f"pos:show:{expected.address.lower()}"

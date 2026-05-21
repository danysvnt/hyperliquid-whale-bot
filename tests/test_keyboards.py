"""Unit tests for the keyboards module."""

from __future__ import annotations

from hyperliquid_whale_bot.bot.i18n import button_texts, t
from hyperliquid_whale_bot.bot.keyboards import (
    ask_label_keyboard,
    cancel_keyboard,
    explorer_keyboard,
    main_reply_keyboard,
    positions_menu_keyboard,
    wallet_list_keyboard,
    wallet_picker_keyboard,
    wallet_settings_keyboard,
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


def test_wallet_list_keyboard_has_per_wallet_buttons_and_add_button() -> None:
    """wallet_list_keyboard emits one row per wallet plus an 'Add wallet' row at the bottom."""
    wallets = [
        TrackedWallet(chat_id=1, address="0x" + "ab" * 20, label="alpha"),
        TrackedWallet(chat_id=1, address="0x" + "cd" * 20, label="beta"),
    ]
    kb = wallet_list_keyboard(wallets, "ru")
    assert len(kb.inline_keyboard) == 3, "2 wallets + 1 add row"
    for row, expected in zip(kb.inline_keyboard[:2], wallets, strict=True):
        assert len(row) == 1
        assert row[0].text == expected.label
        assert row[0].callback_data == f"w:open:{expected.address.lower()}"
    add_row = kb.inline_keyboard[-1]
    assert len(add_row) == 1
    assert add_row[0].callback_data == "w:add"
    assert add_row[0].text == t("wlist.add_btn", "ru")


def test_wallet_list_keyboard_empty_only_has_add_button() -> None:
    """With no wallets the keyboard still surfaces the 'Add wallet' button."""
    kb = wallet_list_keyboard([], "en")
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].callback_data == "w:add"


def test_wallet_settings_keyboard_reflects_toggle_state_and_has_all_actions() -> None:
    """Per-wallet settings keyboard shows 3 toggles + edit/delete/back, all wired to the right callbacks."""
    wallet = TrackedWallet(
        chat_id=1,
        address="0x" + "ab" * 20,
        label="alpha",
        notify_positions=True,
        notify_twap=False,
        notify_limit=True,
    )
    kb = wallet_settings_keyboard(wallet, "ru")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in flat]

    addr = wallet.address.lower()
    assert f"w:tog:pos:{addr}" in callbacks
    assert f"w:tog:twap:{addr}" in callbacks
    assert f"w:tog:limit:{addr}" in callbacks
    assert f"w:edit:{addr}" in callbacks
    assert f"w:del:{addr}" in callbacks
    assert "w:back" in callbacks

    pos_btn = next(b for b in flat if b.callback_data == f"w:tog:pos:{addr}")
    twap_btn = next(b for b in flat if b.callback_data == f"w:tog:twap:{addr}")
    limit_btn = next(b for b in flat if b.callback_data == f"w:tog:limit:{addr}")
    assert pos_btn.text == t("wset.toggle.positions.on", "ru")
    assert twap_btn.text == t("wset.toggle.twap.off", "ru")
    assert limit_btn.text == t("wset.toggle.limit.on", "ru")


def test_wallet_settings_keyboard_twap_limit_buttons_mention_soon() -> None:
    """TWAP and limit toggle labels carry the 'soon' qualifier so users see those are phase-2."""
    wallet = TrackedWallet(chat_id=1, address="0x" + "ab" * 20, label="alpha")
    for lang in ("ru", "en", "uk"):
        kb = wallet_settings_keyboard(wallet, lang)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("скоро" in lbl or "soon" in lbl.lower() for lbl in labels)


def test_cancel_keyboard_emits_single_button_with_payload() -> None:
    """cancel_keyboard wraps a single 'Cancel' button with the caller-provided callback_data."""
    kb = cancel_keyboard("en", "add:cancel")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert len(flat) == 1
    assert flat[0].callback_data == "add:cancel"
    assert flat[0].text == t("common.cancel", "en")


def test_ask_label_keyboard_has_skip_and_cancel() -> None:
    """The 'ask for label' keyboard during /add surfaces both Skip and Cancel."""
    kb = ask_label_keyboard("en")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    callbacks = {btn.callback_data for btn in flat}
    assert callbacks == {"add:skip", "add:cancel"}

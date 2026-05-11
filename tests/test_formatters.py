"""Unit tests for the formatters module — focus on the new UX (PnL emoji, copyable address)."""

from __future__ import annotations

from datetime import UTC, datetime

from hyperliquid_whale_bot.bot.formatters import format_event, format_snapshot
from hyperliquid_whale_bot.models import (
    EventKind,
    Position,
    PositionEvent,
    Side,
    WalletSnapshot,
)

ADDR = "0x" + "ab" * 20
LABEL = "alpha"


def _make_position(
    *,
    coin: str = "BTC",
    side: Side = Side.LONG,
    size: float = 1.0,
    notional: float = 100_000.0,
    entry: float = 100_000.0,
    pnl: float = 0.0,
    leverage: float = 5.0,
) -> Position:
    return Position(
        coin=coin,
        side=side,
        size=size,
        entry_price=entry,
        notional_usd=notional,
        leverage=leverage,
        leverage_type="cross",
        unrealized_pnl=pnl,
    )


def _make_snapshot(positions: list[Position]) -> WalletSnapshot:
    return WalletSnapshot(
        address=ADDR,
        positions=tuple(positions),
        captured_at=datetime.now(UTC),
    )


def test_format_snapshot_includes_copyable_address_in_code_tag() -> None:
    """Every /status snapshot must wrap the address in <code> so Telegram allows copy-on-tap."""
    snap = _make_snapshot([_make_position()])
    text = format_snapshot(snap, label=LABEL, lang="en")
    assert f"<code>{ADDR.lower()}</code>" in text


def test_format_snapshot_with_no_positions_still_shows_copyable_address() -> None:
    """Even the 'no open positions' reply must surface the copyable address."""
    snap = _make_snapshot([])
    text = format_snapshot(snap, label=LABEL, lang="en")
    assert f"<code>{ADDR.lower()}</code>" in text


def test_format_snapshot_uses_amount_label_not_notional() -> None:
    """The user-facing label is 'Amount/Сумма/Сума', not 'Notional'."""
    snap = _make_snapshot([_make_position()])
    for lang, expected in (("en", "Amount:"), ("ru", "Сумма:"), ("uk", "Сума:")):
        text = format_snapshot(snap, label=LABEL, lang=lang)
        assert expected in text, f"missing '{expected}' for {lang}"
        assert "Notional" not in text, f"legacy 'Notional' leaked for {lang}"
        assert "Ноционал" not in text, f"legacy 'Ноционал' leaked for {lang}"


def test_format_snapshot_pnl_marker_for_positive_negative_zero() -> None:
    """PnL line must carry a visual marker: green for positive, red for negative, white for zero."""
    pos_positive = _make_position(pnl=1234.0)
    pos_negative = _make_position(pnl=-1234.0)
    pos_zero = _make_position(pnl=0.0)
    for pos, marker in (
        (pos_positive, "\U0001f7e2"),
        (pos_negative, "\U0001f534"),
        (pos_zero, "\u26aa"),
    ):
        snap = _make_snapshot([pos])
        text = format_snapshot(snap, label=LABEL, lang="en")
        assert marker in text, f"missing PnL marker {marker!r} for pnl={pos.unrealized_pnl}"


def test_format_event_includes_copyable_address() -> None:
    """Every wallet event message must surface the copyable address (so users can paste into trackers)."""
    pos = _make_position()
    event = PositionEvent(
        kind=EventKind.OPEN,
        address=ADDR,
        coin=pos.coin,
        position=pos,
        previous=None,
        notional_delta_usd=pos.notional_usd,
        pct_change=0.0,
        captured_at=datetime.now(UTC),
    )
    text = format_event(event, label=LABEL, lang="en")
    assert f"<code>{ADDR.lower()}</code>" in text


def test_format_event_close_uses_pnl_marker() -> None:
    """CLOSE events report PnL of the closed position — with the colored marker."""
    prev = _make_position(pnl=-5_000.0)
    event = PositionEvent(
        kind=EventKind.CLOSE,
        address=ADDR,
        coin=prev.coin,
        position=prev,  # The 'position' for CLOSE is whatever existed (rendered for prev anyway).
        previous=prev,
        notional_delta_usd=-prev.notional_usd,
        pct_change=-100.0,
        captured_at=datetime.now(UTC),
    )
    text = format_event(event, label=LABEL, lang="ru")
    assert "\U0001f534" in text, "negative PnL must include the red marker"

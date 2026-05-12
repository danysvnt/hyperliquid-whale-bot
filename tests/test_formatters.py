"""Unit tests for the formatters module — focus on the new UX (PnL emoji, copyable address)."""

from __future__ import annotations

from datetime import UTC, datetime

from hyperliquid_whale_bot.bot.formatters import (
    format_event,
    format_multi_snapshot,
    format_snapshot,
)
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


def test_format_multi_snapshot_renders_all_wallets_in_one_message() -> None:
    """Multi-snapshot rendering combines wallets into a single message with title + per-wallet blocks."""
    snap_with_pos = WalletSnapshot(
        address="0x" + "11" * 20,
        positions=(_make_position(coin="BTC"),),
        captured_at=datetime.now(UTC),
    )
    snap_empty = WalletSnapshot(
        address="0x" + "22" * 20,
        positions=(),
        captured_at=datetime.now(UTC),
    )
    snap_with_pos2 = WalletSnapshot(
        address="0x" + "33" * 20,
        positions=(_make_position(coin="ETH", side=Side.SHORT),),
        captured_at=datetime.now(UTC),
    )
    items = [("alpha", snap_with_pos), ("beta", snap_empty), ("gamma", snap_with_pos2)]
    chunks = format_multi_snapshot(items, lang="ru")
    assert len(chunks) == 1, "small payload should fit in one message"
    text = chunks[0]
    assert "Все открытые позиции" in text
    for snap in (snap_with_pos, snap_empty, snap_with_pos2):
        assert f"<code>{snap.address.lower()}</code>" in text
    for label in ("alpha", "beta", "gamma"):
        assert label in text
    assert "нет открытых позиций" in text, "empty wallet renders the placeholder line"


def test_format_multi_snapshot_escapes_html_in_labels() -> None:
    """User-supplied wallet labels must be HTML-escaped to prevent injection."""
    snap = WalletSnapshot(
        address="0x" + "ab" * 20,
        positions=(),
        captured_at=datetime.now(UTC),
    )
    chunks = format_multi_snapshot([("<script>x</script>", snap)], lang="en")
    text = chunks[0]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_format_multi_snapshot_splits_into_chunks_when_oversized() -> None:
    """When the combined render exceeds Telegram's soft limit, it splits on wallet boundaries."""
    # Build many wallets so combined render must exceed _TG_MSG_SOFT_LIMIT (3900).
    snaps = []
    for i in range(40):
        addr = "0x" + f"{i:02x}" * 20
        snaps.append(
            (
                f"wallet_{i}",
                WalletSnapshot(
                    address=addr,
                    positions=(_make_position(coin=f"C{i}"),),
                    captured_at=datetime.now(UTC),
                ),
            )
        )
    chunks = format_multi_snapshot(snaps, lang="en")
    assert len(chunks) >= 2, "expected at least two chunks for 40 wallets"
    for chunk in chunks:
        assert len(chunk) <= 4096
        assert "All open positions" in chunk, "title must appear on every chunk for context"


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

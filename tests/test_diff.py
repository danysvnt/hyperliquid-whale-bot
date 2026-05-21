"""Unit tests for the position diff engine."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hyperliquid_whale_bot.diff import diff_snapshots
from hyperliquid_whale_bot.models import EventKind, Position, Side, WalletSnapshot

# --- helpers ---------------------------------------------------------------

ADDR = "0x000000000000000000000000000000000000dead"
NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2025, 1, 1, 12, 5, 0, tzinfo=UTC)


def make_pos(
    coin: str,
    side: Side,
    size: float,
    notional: float,
    leverage: float = 10.0,
    entry: float = 100.0,
) -> Position:
    return Position(
        coin=coin,
        side=side,
        size=size,
        entry_price=entry,
        notional_usd=notional,
        leverage=leverage,
        leverage_type="cross",
        unrealized_pnl=0.0,
    )


def snap(positions: list[Position], at: datetime = NOW) -> WalletSnapshot:
    return WalletSnapshot(address=ADDR, positions=tuple(positions), captured_at=at)


# --- tests -----------------------------------------------------------------


def test_first_observation_emits_no_events() -> None:
    """When previous snapshot is None we don't fire events for "starting" positions."""
    current = snap([make_pos("BTC", Side.LONG, 1.0, 100_000)])
    events = diff_snapshots(previous=None, current=current)
    assert events == []


def test_open_event() -> None:
    prev = snap([])
    curr = snap([make_pos("BTC", Side.LONG, 0.5, 50_000)], at=LATER)
    events = diff_snapshots(prev, curr)
    assert len(events) == 1
    e = events[0]
    assert e.kind == EventKind.OPEN
    assert e.coin == "BTC"
    assert e.position.side == Side.LONG
    assert e.previous is None
    assert e.size_delta == pytest.approx(0.5)


def test_close_event() -> None:
    prev = snap([make_pos("ETH", Side.SHORT, 10.0, 30_000)])
    curr = snap([], at=LATER)
    events = diff_snapshots(prev, curr)
    assert len(events) == 1
    e = events[0]
    assert e.kind == EventKind.CLOSE
    assert e.coin == "ETH"
    assert e.previous is not None and e.previous.side == Side.SHORT
    assert e.notional_delta_usd == pytest.approx(-30_000)


def test_increase_above_thresholds() -> None:
    prev = snap([make_pos("BTC", Side.LONG, 1.0, 100_000)])
    curr = snap([make_pos("BTC", Side.LONG, 1.5, 150_000)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=10.0, usd_threshold=10_000)
    assert len(events) == 1
    assert events[0].kind == EventKind.INCREASE
    assert events[0].pct_change == pytest.approx(50.0)
    assert events[0].notional_delta_usd == pytest.approx(50_000)


def test_decrease_above_thresholds() -> None:
    prev = snap([make_pos("BTC", Side.LONG, 2.0, 200_000)])
    curr = snap([make_pos("BTC", Side.LONG, 1.0, 100_000)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=10.0, usd_threshold=10_000)
    assert len(events) == 1
    assert events[0].kind == EventKind.DECREASE
    assert events[0].pct_change == pytest.approx(-50.0)


def test_change_below_pct_threshold_is_filtered() -> None:
    """1% change with $1k diff — both below defaults — should produce no event."""
    prev = snap([make_pos("BTC", Side.LONG, 1.0, 100_000)])
    curr = snap([make_pos("BTC", Side.LONG, 1.01, 101_000)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=5.0, usd_threshold=5_000)
    assert events == []


def test_change_above_pct_but_below_usd_is_filtered() -> None:
    """20% change but only $200 USD — below USD threshold — filtered."""
    prev = snap([make_pos("PEPE", Side.LONG, 100.0, 1_000)])
    curr = snap([make_pos("PEPE", Side.LONG, 120.0, 1_200)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=5.0, usd_threshold=5_000)
    assert events == []


def test_change_above_usd_but_below_pct_is_filtered() -> None:
    """$10k change on a huge $1M position is only 1% — filtered."""
    prev = snap([make_pos("BTC", Side.LONG, 10.0, 1_000_000)])
    curr = snap([make_pos("BTC", Side.LONG, 10.1, 1_010_000)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=5.0, usd_threshold=5_000)
    assert events == []


def test_leverage_change_emits_dedicated_event() -> None:
    prev = snap([make_pos("BTC", Side.LONG, 1.0, 100_000, leverage=10.0)])
    curr = snap([make_pos("BTC", Side.LONG, 1.0, 100_000, leverage=20.0)], at=LATER)
    events = diff_snapshots(prev, curr)
    assert len(events) == 1
    assert events[0].kind == EventKind.LEVERAGE_CHANGE
    assert events[0].previous is not None
    assert events[0].previous.leverage == 10.0
    assert events[0].position.leverage == 20.0


def test_leverage_change_and_size_change_emit_two_events() -> None:
    prev = snap([make_pos("BTC", Side.LONG, 1.0, 100_000, leverage=10.0)])
    curr = snap([make_pos("BTC", Side.LONG, 1.5, 150_000, leverage=20.0)], at=LATER)
    events = diff_snapshots(prev, curr, pct_threshold=10.0, usd_threshold=10_000)
    kinds = {e.kind for e in events}
    assert kinds == {EventKind.INCREASE, EventKind.LEVERAGE_CHANGE}


def test_side_flip_emits_single_event() -> None:
    """If the wallet flipped from long to short on the same coin, fire SIDE_FLIP only."""
    prev = snap([make_pos("BTC", Side.LONG, 1.0, 100_000)])
    curr = snap([make_pos("BTC", Side.SHORT, 1.0, 100_000)], at=LATER)
    events = diff_snapshots(prev, curr)
    assert len(events) == 1
    assert events[0].kind == EventKind.SIDE_FLIP
    assert events[0].previous is not None and events[0].previous.side == Side.LONG
    assert events[0].position.side == Side.SHORT


def test_multiple_coins_emit_independent_events() -> None:
    prev = snap(
        [
            make_pos("BTC", Side.LONG, 1.0, 100_000),
            make_pos("ETH", Side.SHORT, 10.0, 30_000),
        ]
    )
    curr = snap(
        [
            make_pos("BTC", Side.LONG, 2.0, 200_000),  # +100% (INCREASE)
            # ETH closed
            make_pos("SOL", Side.LONG, 50.0, 10_000),  # new (OPEN)
        ],
        at=LATER,
    )
    events = diff_snapshots(prev, curr, pct_threshold=10.0, usd_threshold=5_000)
    kinds_by_coin = {(e.coin, e.kind) for e in events}
    assert kinds_by_coin == {
        ("BTC", EventKind.INCREASE),
        ("ETH", EventKind.CLOSE),
        ("SOL", EventKind.OPEN),
    }


def test_addresses_must_match() -> None:
    prev = WalletSnapshot(address="0x1111", positions=(), captured_at=NOW)
    curr = WalletSnapshot(address="0x2222", positions=(), captured_at=LATER)
    with pytest.raises(ValueError, match="different wallets"):
        diff_snapshots(prev, curr)


def test_addresses_match_case_insensitive() -> None:
    prev = WalletSnapshot(address="0xAbCd", positions=(), captured_at=NOW)
    curr = WalletSnapshot(address="0xabcd", positions=(), captured_at=LATER)
    # Should NOT raise.
    events = diff_snapshots(prev, curr)
    assert events == []

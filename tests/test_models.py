"""Unit tests for Position parsing from raw Hyperliquid API responses."""

from __future__ import annotations

from hyperliquid_whale_bot.models import (
    Position,
    Side,
    TwapStatus,
    parse_twap_state,
)


def test_position_from_long_dict() -> None:
    raw = {
        "coin": "ETH",
        "szi": "0.5",
        "entryPx": "2986.3",
        "leverage": {"type": "cross", "value": 20, "rawUsd": "-95.06"},
        "positionValue": "1493.15",
        "unrealizedPnl": "-0.01",
        "liquidationPx": "100.0",
        "maxLeverage": 50,
    }
    pos = Position.from_hl_dict(raw)
    assert pos is not None
    assert pos.coin == "ETH"
    assert pos.side == Side.LONG
    assert pos.size == 0.5
    assert pos.entry_price == 2986.3
    assert pos.notional_usd == 1493.15
    assert pos.leverage == 20.0
    assert pos.leverage_type == "cross"
    assert pos.liquidation_price == 100.0
    assert pos.max_leverage == 50


def test_position_from_short_dict() -> None:
    raw = {
        "coin": "BTC",
        "szi": "-0.1",
        "entryPx": "60000",
        "leverage": {"type": "isolated", "value": 5},
        "positionValue": "6000",
        "unrealizedPnl": "0.0",
    }
    pos = Position.from_hl_dict(raw)
    assert pos is not None
    assert pos.side == Side.SHORT
    assert pos.size == 0.1


def test_position_zero_size_returns_none() -> None:
    raw = {
        "coin": "ETH",
        "szi": "0.0",
        "entryPx": "0",
        "leverage": {"type": "cross", "value": 1},
        "positionValue": "0",
        "unrealizedPnl": "0",
    }
    assert Position.from_hl_dict(raw) is None


def test_position_handles_missing_optional_fields() -> None:
    raw = {
        "coin": "SOL",
        "szi": "100",
        "entryPx": "150",
        "leverage": {"type": "cross", "value": 10},
        "positionValue": "15000",
        "unrealizedPnl": "0",
        # liquidationPx and maxLeverage missing
    }
    pos = Position.from_hl_dict(raw)
    assert pos is not None
    assert pos.liquidation_price is None
    assert pos.max_leverage is None


# --- TwapState parsing -------------------------------------------------------


def test_parse_twap_state_from_activated_history_entry() -> None:
    """A typical 'activated' history entry parses into a TwapState."""
    raw = {
        "time": 1758728334,
        "state": {
            "coin": "BTC",
            "user": "0xabc",
            "side": "B",
            "sz": "1.5",
            "executedSz": "0.0",
            "executedNtl": "0.0",
            "minutes": 30,
            "reduceOnly": False,
            "randomize": False,
            "timestamp": 1758728334355,
        },
        "status": {"status": "activated"},
        "_twap_id": 9001,
    }
    state = parse_twap_state(raw, executed_size=0.0, executed_notional_usd=0.0)
    assert state is not None
    assert state.twap_id == 9001
    assert state.coin == "BTC"
    assert state.side == Side.LONG
    assert state.total_size == 1.5
    assert state.executed_size == 0.0
    assert state.minutes == 30
    assert state.status == TwapStatus.ACTIVATED


def test_parse_twap_state_short_side_a_and_overrides_executed_from_fills() -> None:
    """side='A' -> SHORT; executed_size/executed_notional_usd are caller-supplied."""
    raw = {
        "time": 1758728636,
        "state": {
            "coin": "ETH",
            "side": "A",
            "sz": "10",
            "executedSz": "0.0",
            "minutes": 5,
            "timestamp": 1758728334000,
        },
        "status": {"status": "finished"},
        "_twap_id": 42,
    }
    state = parse_twap_state(raw, executed_size=10.0, executed_notional_usd=30_000.0)
    assert state is not None
    assert state.side == Side.SHORT
    assert state.executed_size == 10.0
    assert state.executed_notional_usd == 30_000.0
    assert state.status == TwapStatus.FINISHED
    assert state.progress_pct == 100.0


def test_parse_twap_state_returns_none_on_bad_payload() -> None:
    """Missing fields or unknown status returns None (defensive)."""
    for raw in (
        {"state": {}, "status": {"status": "activated"}, "_twap_id": 1},  # zero sz
        {"state": {"sz": "1", "side": "X"}, "status": {"status": "activated"}, "_twap_id": 1},
        {"state": {"sz": "1", "side": "A"}, "status": {"status": "weird"}, "_twap_id": 1},
        {"state": {"sz": "1", "side": "A"}, "status": {"status": "activated"}},  # no twap_id
    ):
        assert parse_twap_state(raw) is None, f"unexpected parse success for {raw}"


def test_parse_twap_state_progress_clamps_above_total() -> None:
    """executed_size > total_size doesn't push progress over 100%."""
    raw = {
        "state": {"coin": "BTC", "side": "B", "sz": "1.0", "timestamp": 1758728334000, "minutes": 5},
        "status": {"status": "activated"},
        "_twap_id": 7,
    }
    state = parse_twap_state(raw, executed_size=10.0)  # bug-shaped input
    assert state is not None
    assert state.progress_pct == 100.0

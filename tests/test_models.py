"""Unit tests for Position parsing from raw Hyperliquid API responses."""

from __future__ import annotations

from hyperliquid_whale_bot.models import Position, Side


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

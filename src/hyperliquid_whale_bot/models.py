"""Domain models — pure dataclasses used across the app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


def _as_str(v: object) -> str:
    """Best-effort coerce to str (HL API uses both numeric and string types)."""
    return str(v) if v is not None else ""


class Side(StrEnum):
    """Position direction."""

    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class Position:
    """A single open perp position on Hyperliquid for a given wallet.

    Notes:
    - `size` is unsigned (always positive).
    - `side` encodes direction.
    - All monetary values are in USD.
    """

    coin: str
    side: Side
    size: float  # unsigned size of the asset (e.g. 0.5 BTC)
    entry_price: float  # avg entry price in USD
    notional_usd: float  # |size| * mark price
    leverage: float  # e.g. 20.0
    leverage_type: str  # "cross" or "isolated"
    unrealized_pnl: float
    liquidation_price: float | None = None
    max_leverage: int | None = None

    @classmethod
    def from_hl_dict(cls, raw: dict[str, object]) -> Position | None:
        """Build a Position from the `assetPositions[i].position` dict returned by the SDK.

        Returns None when the size is zero (a closed position can briefly remain in the response).
        """
        szi = float(_as_str(raw.get("szi", "0")))
        if szi == 0.0:
            return None

        leverage_block_raw = raw.get("leverage")
        leverage_block: dict[str, object] = (
            leverage_block_raw if isinstance(leverage_block_raw, dict) else {}
        )
        liq_px_raw = raw.get("liquidationPx")
        max_lev_raw = raw.get("maxLeverage")

        return cls(
            coin=_as_str(raw.get("coin", "")),
            side=Side.LONG if szi > 0 else Side.SHORT,
            size=abs(szi),
            entry_price=float(_as_str(raw.get("entryPx", 0) or 0)),
            notional_usd=abs(float(_as_str(raw.get("positionValue", 0) or 0))),
            leverage=float(_as_str(leverage_block.get("value", 0) or 0)),
            leverage_type=_as_str(leverage_block.get("type", "cross")),
            unrealized_pnl=float(_as_str(raw.get("unrealizedPnl", 0) or 0)),
            liquidation_price=(
                float(_as_str(liq_px_raw)) if liq_px_raw not in (None, "") else None
            ),
            max_leverage=int(_as_str(max_lev_raw)) if max_lev_raw is not None else None,
        )


@dataclass(frozen=True, slots=True)
class WalletSnapshot:
    """A snapshot of all open perp positions for one wallet at one point in time."""

    address: str
    positions: tuple[Position, ...]
    captured_at: datetime

    def by_coin(self) -> dict[str, Position]:
        """Index positions by coin (Hyperliquid allows only one position per coin per wallet)."""
        return {p.coin: p for p in self.positions}


class EventKind(StrEnum):
    """Type of position change detected by the diff engine."""

    OPEN = "open"
    CLOSE = "close"
    INCREASE = "increase"
    DECREASE = "decrease"
    LEVERAGE_CHANGE = "leverage_change"
    SIDE_FLIP = "side_flip"  # rare: closing long and immediately opening short on same coin


@dataclass(frozen=True, slots=True)
class PositionEvent:
    """A single change detected between two consecutive wallet snapshots."""

    kind: EventKind
    address: str
    coin: str
    # New state (for OPEN/INCREASE/DECREASE/LEVERAGE_CHANGE/SIDE_FLIP this is the current position;
    # for CLOSE this is the position immediately before close).
    position: Position
    # Previous position (None for OPEN; populated for everything else).
    previous: Position | None = None
    # Computed deltas (populated where applicable).
    size_delta: float = 0.0
    notional_delta_usd: float = 0.0
    pct_change: float = 0.0  # percent change in size
    captured_at: datetime | None = None


class NotificationKind(StrEnum):
    """Per-wallet notification toggle (one flag per row in tracked_wallets)."""

    POSITIONS = "positions"  # open/close/increase/decrease/leverage/side_flip
    TWAP = "twap"  # phase-2: TWAP slices
    LIMIT = "limit"  # phase-2: open/cancel/fill of limit orders


@dataclass(frozen=True, slots=True)
class TrackedWallet:
    """A wallet that some Telegram chat is subscribed to."""

    address: str  # 0x...
    label: str  # human-friendly nickname
    chat_id: int  # Telegram chat that owns this subscription
    notify_positions: bool = True
    notify_twap: bool = True
    notify_limit: bool = True

    def is_notification_enabled(self, kind: NotificationKind) -> bool:
        if kind == NotificationKind.POSITIONS:
            return self.notify_positions
        if kind == NotificationKind.TWAP:
            return self.notify_twap
        return self.notify_limit

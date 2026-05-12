"""Domain models — pure dataclasses used across the app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
    TWAP = "twap"  # TWAP order started / sliced / finished / cancelled
    LIMIT = "limit"  # phase-2: open/cancel/fill of limit orders


class TwapStatus(StrEnum):
    """Lifecycle status of a TWAP order on Hyperliquid.

    Mirrors the upstream `status.status` field. We treat unknown / "error" as
    terminal too — see `is_terminal`.
    """

    ACTIVATED = "activated"
    FINISHED = "finished"
    TERMINATED = "terminated"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self in (TwapStatus.FINISHED, TwapStatus.TERMINATED, TwapStatus.ERROR)


@dataclass(frozen=True, slots=True)
class TwapState:
    """A single TWAP order on Hyperliquid at a given point in time.

    Aggregated from `twapHistory` (the lifecycle entry) and `userTwapSliceFills`
    (per-slice executions summed by `twapId`).

    `executed_size` is the sum of slice fills observed so far; it grows over
    the TWAP's lifetime.
    """

    twap_id: int
    coin: str
    side: Side  # B (buy/long) -> LONG, A (ask/sell/short) -> SHORT
    total_size: float  # `sz` — target size to execute
    executed_size: float  # sum of slice `fill.sz`
    executed_notional_usd: float  # sum of slice |fill.sz * fill.px|
    minutes: int  # duration of the TWAP order
    status: TwapStatus
    started_at: datetime  # from state.timestamp (ms since epoch)
    reduce_only: bool = False
    randomize: bool = False

    @property
    def progress_pct(self) -> float:
        """Executed / total as a percent in [0, 100]. Clamps for safety."""
        if self.total_size <= 0:
            return 0.0
        pct = self.executed_size / self.total_size * 100.0
        if pct < 0:
            return 0.0
        if pct > 100.0:
            return 100.0
        return pct


@dataclass(frozen=True, slots=True)
class WalletTwapSnapshot:
    """Snapshot of all known TWAP orders for a wallet at one point in time.

    Includes both active TWAPs and recent terminal ones (so the diff engine can
    tell whether an active TWAP we saw last tick has now finished/cancelled).
    """

    address: str
    twaps: tuple[TwapState, ...]
    captured_at: datetime

    def by_id(self) -> dict[int, TwapState]:
        return {t.twap_id: t for t in self.twaps}


class TwapEventKind(StrEnum):
    """Type of TWAP change detected by the twap-diff engine.

    `TERMINATED` and `ERROR` are split from `CANCELLED` so we can render them
    differently — terminated = user-cancelled, error = HL-side failure. `CANCELLED`
    remains for the "TWAP disappeared between snapshots" fallback and for
    `finished` with partial progress (rare HL edge case).
    """

    STARTED = "twap_started"
    SLICE = "twap_slice"
    FINISHED = "twap_finished"
    CANCELLED = "twap_cancelled"
    TERMINATED = "twap_terminated"
    ERROR = "twap_error"


@dataclass(frozen=True, slots=True)
class TwapEvent:
    """A single TWAP lifecycle change for a wallet."""

    kind: TwapEventKind
    address: str
    twap: TwapState
    previous: TwapState | None = None
    progress_pct: float = 0.0  # snapshot of twap.progress_pct at emit time
    captured_at: datetime | None = None

    # For SLICE events: the cumulative % bucket that triggered this slice
    # (e.g. 10, 20, 30, ...). Lets formatters say "10%", "20%", etc. without
    # recomputing from progress_pct.
    bucket_pct: int = 0

    # For STARTED events: mark price of `coin` at the moment the TWAP started.
    # Used to render an approximate USD size in the STARTED message. None when
    # the watcher couldn't fetch a mark price (the message falls back to "By market").
    mark_price_usd: float | None = None

    @property
    def coin(self) -> str:
        return self.twap.coin


def parse_twap_state(
    history_entry: dict[str, object],
    executed_size: float = 0.0,
    executed_notional_usd: float = 0.0,
) -> TwapState | None:
    """Build a `TwapState` from one entry of the `twapHistory` info endpoint.

    `history_entry` shape (subset, verified against mainnet):
        {
          "time": 1758728334,
          "state": {
            "coin": "BTC",
            "user": "0x...",
            "side": "A",            # "B" -> LONG, "A" -> SHORT
            "sz": "14.6764",
            "executedSz": "0.0",    # not trustworthy across SLICE events; we re-sum from fills
            "executedNtl": "0.0",
            "minutes": 5,
            "reduceOnly": false,
            "randomize": false,
            "timestamp": 1758728334355
          },
          "status": { "status": "activated" }      # or "finished" / "terminated" / "error"
        }

    The `twap_id` is NOT in the history payload — it must be supplied by the
    caller (deduced from `userTwapSliceFills` or assigned by enumeration). We
    require a non-zero twap_id stamped on the dict via the `_twap_id` key so
    that this helper can stay pure.

    Returns None if the payload is malformed (defensive — HL may evolve the
    schema and we'd rather skip than crash the watcher).
    """
    state_raw = history_entry.get("state")
    if not isinstance(state_raw, dict):
        return None
    status_raw = history_entry.get("status")
    status_str = ""
    if isinstance(status_raw, dict):
        status_str = _as_str(status_raw.get("status", "")).lower()
    elif isinstance(status_raw, str):
        status_str = status_raw.lower()
    try:
        status = TwapStatus(status_str)
    except ValueError:
        return None

    twap_id_raw = history_entry.get("_twap_id")
    if twap_id_raw is None:
        return None
    try:
        twap_id = int(_as_str(twap_id_raw))
    except ValueError:
        return None

    side_raw = _as_str(state_raw.get("side", "")).upper()
    if side_raw not in ("A", "B"):
        return None
    side = Side.LONG if side_raw == "B" else Side.SHORT

    try:
        total = float(_as_str(state_raw.get("sz", 0) or 0))
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None

    minutes_raw = state_raw.get("minutes", 0)
    try:
        minutes = int(_as_str(minutes_raw) or 0)
    except ValueError:
        minutes = 0

    ts_raw = state_raw.get("timestamp", 0)
    try:
        ts_ms = int(_as_str(ts_raw) or 0)
    except ValueError:
        ts_ms = 0
    started_at = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC) if ts_ms > 0 else datetime.now(UTC)

    return TwapState(
        twap_id=twap_id,
        coin=_as_str(state_raw.get("coin", "")),
        side=side,
        total_size=total,
        executed_size=max(0.0, executed_size),
        executed_notional_usd=max(0.0, executed_notional_usd),
        minutes=minutes,
        status=status,
        started_at=started_at,
        reduce_only=bool(state_raw.get("reduceOnly", False)),
        randomize=bool(state_raw.get("randomize", False)),
    )


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

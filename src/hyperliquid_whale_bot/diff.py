"""Position diff engine — pure functions, no I/O.

Compares two snapshots of a wallet's positions and returns the meaningful changes.

Design goals:
- Pure: easy to unit test, no side effects.
- Threshold-aware: small changes below configured % AND USD threshold are filtered out
  to avoid notification spam (both conditions must be met for an `INCREASE`/`DECREASE` event).
- Always emits OPEN/CLOSE/SIDE_FLIP events regardless of threshold (these are atomic).
- Always emits LEVERAGE_CHANGE when leverage value changes (rare event, low spam risk).
"""

from __future__ import annotations

from datetime import datetime

from .models import EventKind, Position, PositionEvent, Side, WalletSnapshot


def diff_snapshots(
    previous: WalletSnapshot | None,
    current: WalletSnapshot,
    pct_threshold: float = 5.0,
    usd_threshold: float = 5_000.0,
) -> list[PositionEvent]:
    """Compute the list of `PositionEvent`s between two snapshots of the same wallet.

    Args:
        previous: Earlier snapshot (None on the very first observation — emits no events,
            since we only learn the wallet's "starting" positions).
        current: Latest snapshot.
        pct_threshold: Min |% change in size| to trigger INCREASE/DECREASE.
        usd_threshold: Min |USD notional change| to trigger INCREASE/DECREASE.

    Both thresholds must be exceeded for an INCREASE/DECREASE event.

    Returns:
        List of events ordered by coin (deterministic for tests).
    """
    if previous is None:
        return []  # bootstrap snapshot — nothing to diff against yet

    if previous.address.lower() != current.address.lower():
        raise ValueError(
            f"Cannot diff snapshots from different wallets: {previous.address} vs {current.address}"
        )

    prev_by_coin = previous.by_coin()
    curr_by_coin = current.by_coin()
    all_coins = sorted(set(prev_by_coin) | set(curr_by_coin))

    events: list[PositionEvent] = []
    captured = current.captured_at

    for coin in all_coins:
        prev = prev_by_coin.get(coin)
        curr = curr_by_coin.get(coin)

        if prev is None and curr is not None:
            events.append(_open_event(current.address, curr, captured))
        elif prev is not None and curr is None:
            events.append(_close_event(current.address, prev, captured))
        elif prev is not None and curr is not None:
            events.extend(
                _diff_existing_position(
                    address=current.address,
                    prev=prev,
                    curr=curr,
                    captured=captured,
                    pct_threshold=pct_threshold,
                    usd_threshold=usd_threshold,
                )
            )

    return events


def _open_event(address: str, curr: Position, captured: datetime) -> PositionEvent:
    return PositionEvent(
        kind=EventKind.OPEN,
        address=address,
        coin=curr.coin,
        position=curr,
        previous=None,
        size_delta=curr.size,
        notional_delta_usd=curr.notional_usd,
        pct_change=100.0,
        captured_at=captured,
    )


def _close_event(address: str, prev: Position, captured: datetime) -> PositionEvent:
    return PositionEvent(
        kind=EventKind.CLOSE,
        address=address,
        coin=prev.coin,
        position=prev,
        previous=prev,
        size_delta=-prev.size,
        notional_delta_usd=-prev.notional_usd,
        pct_change=-100.0,
        captured_at=captured,
    )


def _diff_existing_position(
    address: str,
    prev: Position,
    curr: Position,
    captured: datetime,
    pct_threshold: float,
    usd_threshold: float,
) -> list[PositionEvent]:
    """Diff a coin where the wallet had a position both before and after."""
    events: list[PositionEvent] = []

    # Side flip: long ↔ short on the same coin without going through size=0
    # (rare in practice — Hyperliquid usually closes first, but possible across two snapshots).
    if prev.side != curr.side:
        events.append(
            PositionEvent(
                kind=EventKind.SIDE_FLIP,
                address=address,
                coin=curr.coin,
                position=curr,
                previous=prev,
                size_delta=curr.size,
                notional_delta_usd=curr.notional_usd - prev.notional_usd,
                pct_change=_safe_pct(curr.size, prev.size),
                captured_at=captured,
            )
        )
        return events  # don't emit a redundant size-change event in this case

    # Size change (only relevant when side is unchanged).
    size_delta = curr.size - prev.size
    notional_delta = curr.notional_usd - prev.notional_usd
    pct_change = _safe_pct(curr.size, prev.size)

    pct_above = abs(pct_change) >= pct_threshold
    usd_above = abs(notional_delta) >= usd_threshold

    if pct_above and usd_above and size_delta != 0:
        kind = EventKind.INCREASE if size_delta > 0 else EventKind.DECREASE
        events.append(
            PositionEvent(
                kind=kind,
                address=address,
                coin=curr.coin,
                position=curr,
                previous=prev,
                size_delta=size_delta,
                notional_delta_usd=notional_delta,
                pct_change=pct_change,
                captured_at=captured,
            )
        )

    # Leverage change — independent of size change, fired separately.
    if prev.leverage != curr.leverage:
        events.append(
            PositionEvent(
                kind=EventKind.LEVERAGE_CHANGE,
                address=address,
                coin=curr.coin,
                position=curr,
                previous=prev,
                size_delta=0.0,
                notional_delta_usd=0.0,
                pct_change=0.0,
                captured_at=captured,
            )
        )

    return events


def _safe_pct(new: float, old: float) -> float:
    """Return percent change from old → new. Returns 0 if old is zero."""
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


__all__ = ["EventKind", "Position", "PositionEvent", "Side", "WalletSnapshot", "diff_snapshots"]

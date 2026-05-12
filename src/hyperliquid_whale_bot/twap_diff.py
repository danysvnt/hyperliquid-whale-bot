"""TWAP diff engine — pure functions, no I/O.

Compares two TWAP-state snapshots of a wallet and emits lifecycle events:

  STARTED   — TWAP id appears for the first time
              (we observed it now, but not in the previous snapshot).
  SLICE     — TWAP's executed_size crossed a new percent bucket
              (10%, 20%, ..., 90%).
  FINISHED  — TWAP transitioned to a terminal `finished` status AND
              progress >= ~99% (treat ≥99 as "fully filled").
  CANCELLED — TWAP transitioned to a terminal `terminated` / `error` status,
              OR `finished` with progress < 99% (rare: filled less than total),
              OR the TWAP simply disappeared from history between snapshots.

Design goals:
- Pure: trivial unit tests, no DB / network.
- Idempotent buckets: if a SLICE for bucket 30% was already emitted in some
  past tick, callers persist that fact (`TwapBucketState.last_emitted_bucket_pct`).
  The diff only emits buckets STRICTLY greater than the persisted floor.
- Tolerant: if a TWAP id disappears entirely between snapshots, treat as
  CANCELLED (once) to avoid silently losing the lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import TwapEvent, TwapEventKind, TwapState, TwapStatus, WalletTwapSnapshot

# A TWAP that reports progress >= this is considered "fully filled" on FINISHED.
FINISHED_PROGRESS_FLOOR_PCT = 99.0


@dataclass(frozen=True, slots=True)
class TwapBucketState:
    """Per-twap state persisted between watcher ticks.

    The watcher loads these from storage (keyed on `(address, twap_id)`) before
    calling `diff_twap_snapshots`, then persists the returned state.
    """

    twap_id: int
    last_emitted_bucket_pct: int = 0  # multiple of `slice_pct_bucket`; 0 = none yet
    started_emitted: bool = False  # have we already sent the STARTED message?
    terminal_emitted: bool = False  # have we already sent FINISHED/CANCELLED?


def diff_twap_snapshots(
    previous: WalletTwapSnapshot | None,
    current: WalletTwapSnapshot,
    bucket_states: dict[int, TwapBucketState] | None = None,
    slice_pct_bucket: int = 10,
) -> tuple[list[TwapEvent], dict[int, TwapBucketState]]:
    """Compute TWAP events and updated per-twap bucket state.

    Args:
        previous: Earlier snapshot (None on bootstrap).
        current: Latest snapshot.
        bucket_states: Persisted per-twap bucket state from prior ticks.
            Empty/None means "fresh start"; we still gate STARTED on
            `started_emitted` so a known-but-unseen-before TWAP gets one event.
        slice_pct_bucket: Step (in percent) between SLICE notifications,
            in (0, 100].

    Returns:
        (events, updated_bucket_states)

        `events` is ordered: STARTED → SLICE (ascending bucket) → FINISHED/CANCELLED.
        Within each kind, ordered by twap_id (deterministic for tests).
    """
    if slice_pct_bucket <= 0 or slice_pct_bucket > 100:
        raise ValueError(f"slice_pct_bucket must be in (0, 100], got {slice_pct_bucket}")

    if previous is not None and previous.address.lower() != current.address.lower():
        raise ValueError(
            f"Cannot diff TWAP snapshots from different wallets: "
            f"{previous.address} vs {current.address}"
        )

    address = current.address.lower()
    bucket_states = dict(bucket_states or {})
    captured = current.captured_at

    prev_by_id = previous.by_id() if previous is not None else {}
    curr_by_id = current.by_id()
    all_ids = sorted(set(prev_by_id) | set(curr_by_id) | set(bucket_states))

    started: list[TwapEvent] = []
    sliced: list[TwapEvent] = []
    terminal: list[TwapEvent] = []

    for twap_id in all_ids:
        prev = prev_by_id.get(twap_id)
        curr = curr_by_id.get(twap_id)
        bucket = bucket_states.get(twap_id, TwapBucketState(twap_id=twap_id))

        # CASE 1: TWAP is currently visible.
        if curr is not None:
            is_first_sighting = prev is None and not bucket.started_emitted

            # Silent bootstrap: if the very first time we observe this TWAP
            # it's already terminal, the user does not care about a historical
            # order that finished long before they added the wallet. Persist
            # the flags so we never emit anything for it, but don't queue any
            # events. Mainnet whales can have hundreds of historical TWAPs;
            # without this gate the first poll would flood Telegram.
            if is_first_sighting and curr.status.is_terminal:
                bucket_states[twap_id] = TwapBucketState(
                    twap_id=twap_id,
                    last_emitted_bucket_pct=100,
                    started_emitted=True,
                    terminal_emitted=True,
                )
                continue

            # STARTED — first time we ever see this twap_id AND it's still active.
            if is_first_sighting:
                started.append(
                    TwapEvent(
                        kind=TwapEventKind.STARTED,
                        address=address,
                        twap=curr,
                        previous=None,
                        progress_pct=curr.progress_pct,
                        captured_at=captured,
                    )
                )
                bucket = TwapBucketState(
                    twap_id=twap_id,
                    last_emitted_bucket_pct=bucket.last_emitted_bucket_pct,
                    started_emitted=True,
                    terminal_emitted=bucket.terminal_emitted,
                )

            # SLICE — emit one event per bucket crossed since last persisted bucket.
            new_slices, new_bucket_pct = _slice_events(
                address=address,
                state=curr,
                captured=captured,
                last_bucket=bucket.last_emitted_bucket_pct,
                bucket_step=slice_pct_bucket,
            )
            if new_slices:
                sliced.extend(new_slices)
                bucket = TwapBucketState(
                    twap_id=twap_id,
                    last_emitted_bucket_pct=new_bucket_pct,
                    started_emitted=bucket.started_emitted,
                    terminal_emitted=bucket.terminal_emitted,
                )

            # FINISHED / CANCELLED.
            if curr.status.is_terminal and not bucket.terminal_emitted:
                if (
                    curr.status == TwapStatus.FINISHED
                    and curr.progress_pct >= FINISHED_PROGRESS_FLOOR_PCT
                ):
                    kind = TwapEventKind.FINISHED
                else:
                    kind = TwapEventKind.CANCELLED
                terminal.append(
                    TwapEvent(
                        kind=kind,
                        address=address,
                        twap=curr,
                        previous=prev,
                        progress_pct=curr.progress_pct,
                        captured_at=captured,
                    )
                )
                bucket = TwapBucketState(
                    twap_id=twap_id,
                    last_emitted_bucket_pct=bucket.last_emitted_bucket_pct,
                    started_emitted=bucket.started_emitted,
                    terminal_emitted=True,
                )

            bucket_states[twap_id] = bucket
            continue

        # CASE 2: TWAP disappeared but we tracked it before — emit CANCELLED once.
        if curr is None and prev is not None and not bucket.terminal_emitted:
            terminal.append(
                TwapEvent(
                    kind=TwapEventKind.CANCELLED,
                    address=address,
                    twap=prev,
                    previous=prev,
                    progress_pct=prev.progress_pct,
                    captured_at=captured,
                )
            )
            bucket_states[twap_id] = TwapBucketState(
                twap_id=twap_id,
                last_emitted_bucket_pct=bucket.last_emitted_bucket_pct,
                started_emitted=bucket.started_emitted,
                terminal_emitted=True,
            )

    events = started + sliced + terminal
    return events, bucket_states


def _slice_events(
    *,
    address: str,
    state: TwapState,
    captured: datetime,
    last_bucket: int,
    bucket_step: int,
) -> tuple[list[TwapEvent], int]:
    """Emit SLICE events for every bucket crossed since `last_bucket`.

    Buckets are multiples of `bucket_step` in `[bucket_step, 100 - bucket_step]`.
    The 100% bucket is intentionally not emitted — FINISHED subsumes it.
    """
    progress = state.progress_pct
    raw_bucket = int(progress // bucket_step) * bucket_step
    cap = 100 - bucket_step
    new_bucket = min(raw_bucket, cap)
    if new_bucket <= last_bucket:
        return [], last_bucket

    events: list[TwapEvent] = []
    bucket = last_bucket + bucket_step
    while bucket <= new_bucket:
        events.append(
            TwapEvent(
                kind=TwapEventKind.SLICE,
                address=address,
                twap=state,
                previous=None,
                progress_pct=progress,
                captured_at=captured,
                bucket_pct=bucket,
            )
        )
        bucket += bucket_step
    return events, new_bucket


__all__ = [
    "FINISHED_PROGRESS_FLOOR_PCT",
    "TwapBucketState",
    "diff_twap_snapshots",
]

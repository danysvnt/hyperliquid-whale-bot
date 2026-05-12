"""Unit tests for the TWAP diff engine."""

from __future__ import annotations

from datetime import UTC, datetime

from hyperliquid_whale_bot.models import (
    Side,
    TwapEventKind,
    TwapState,
    TwapStatus,
    WalletTwapSnapshot,
)
from hyperliquid_whale_bot.twap_diff import (
    TwapBucketState,
    diff_twap_snapshots,
)

ADDR = "0x" + "ab" * 20


def _state(
    *,
    twap_id: int = 1,
    coin: str = "BTC",
    side: Side = Side.LONG,
    total: float = 100.0,
    executed: float = 0.0,
    executed_usd: float = 0.0,
    status: TwapStatus = TwapStatus.ACTIVATED,
    minutes: int = 30,
) -> TwapState:
    return TwapState(
        twap_id=twap_id,
        coin=coin,
        side=side,
        total_size=total,
        executed_size=executed,
        executed_notional_usd=executed_usd,
        minutes=minutes,
        status=status,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _snap(twaps: list[TwapState]) -> WalletTwapSnapshot:
    return WalletTwapSnapshot(
        address=ADDR,
        twaps=tuple(twaps),
        captured_at=datetime.now(UTC),
    )


def test_started_emitted_for_brand_new_active_twap() -> None:
    """First time we see an active TWAP, emit STARTED."""
    curr = _snap([_state()])
    events, buckets = diff_twap_snapshots(previous=None, current=curr)
    assert len(events) == 1
    assert events[0].kind == TwapEventKind.STARTED
    assert buckets[1].started_emitted is True
    assert buckets[1].terminal_emitted is False


def test_started_not_re_emitted_after_persisted_state() -> None:
    """If bucket_states already records started_emitted=True, no new STARTED."""
    prior = {1: TwapBucketState(twap_id=1, started_emitted=True)}
    curr = _snap([_state()])
    events, _ = diff_twap_snapshots(previous=None, current=curr, bucket_states=prior)
    assert all(e.kind != TwapEventKind.STARTED for e in events)


def test_slice_emitted_when_progress_crosses_bucket() -> None:
    """Progress 0% -> 25% with bucket=10 emits SLICE for 10% and 20%."""
    prev = _snap([_state(executed=0.0)])
    curr = _snap([_state(executed=25.0)])  # 25% of 100
    events, buckets = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={1: TwapBucketState(twap_id=1, started_emitted=True)},
        slice_pct_bucket=10,
    )
    slice_events = [e for e in events if e.kind == TwapEventKind.SLICE]
    assert [e.bucket_pct for e in slice_events] == [10, 20]
    assert buckets[1].last_emitted_bucket_pct == 20


def test_slice_does_not_re_emit_existing_buckets() -> None:
    """If we already emitted up through 20%, only 30% should fire on next 35% tick."""
    prev = _snap([_state(executed=25.0)])
    curr = _snap([_state(executed=35.0)])
    events, buckets = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=20, started_emitted=True
            )
        },
        slice_pct_bucket=10,
    )
    slice_events = [e for e in events if e.kind == TwapEventKind.SLICE]
    assert [e.bucket_pct for e in slice_events] == [30]
    assert buckets[1].last_emitted_bucket_pct == 30


def test_slice_caps_at_90_for_100_pct_bucket_step_10() -> None:
    """A TWAP that is 100% executed (pre-FINISHED) emits SLICE at 90%, never 100%."""
    prev = _snap([_state(executed=85.0)])
    curr = _snap([_state(executed=100.0, status=TwapStatus.ACTIVATED)])
    events, _buckets = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=80, started_emitted=True
            )
        },
        slice_pct_bucket=10,
    )
    slice_buckets = [e.bucket_pct for e in events if e.kind == TwapEventKind.SLICE]
    assert slice_buckets == [90]


def test_finished_event_when_terminal_finished_with_full_progress() -> None:
    """status=finished AND progress >= 99% emits FINISHED, not CANCELLED."""
    prev = _snap([_state(executed=50.0)])
    curr = _snap(
        [_state(executed=100.0, executed_usd=10000.0, status=TwapStatus.FINISHED)]
    )
    events, buckets = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=50, started_emitted=True
            )
        },
        slice_pct_bucket=10,
    )
    terminal = [e for e in events if e.kind in (TwapEventKind.FINISHED, TwapEventKind.CANCELLED)]
    assert len(terminal) == 1
    assert terminal[0].kind == TwapEventKind.FINISHED
    assert buckets[1].terminal_emitted is True


def test_cancelled_event_when_terminated() -> None:
    """status=terminated -> CANCELLED, regardless of progress."""
    prev = _snap([_state(executed=20.0)])
    curr = _snap([_state(executed=20.0, status=TwapStatus.TERMINATED)])
    events, _ = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=20, started_emitted=True
            )
        },
    )
    terminal = [e for e in events if e.kind in (TwapEventKind.FINISHED, TwapEventKind.CANCELLED)]
    assert [e.kind for e in terminal] == [TwapEventKind.CANCELLED]


def test_cancelled_when_finished_with_partial_progress() -> None:
    """status=finished but progress < 99% is treated as CANCELLED (rare HL case)."""
    curr = _snap([_state(executed=50.0, status=TwapStatus.FINISHED)])
    events, _ = diff_twap_snapshots(
        previous=_snap([_state(executed=50.0)]),
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=50, started_emitted=True
            )
        },
    )
    assert any(e.kind == TwapEventKind.CANCELLED for e in events)
    assert all(e.kind != TwapEventKind.FINISHED for e in events)


def test_terminal_event_emitted_only_once() -> None:
    """Once we've emitted FINISHED/CANCELLED, a re-tick with the same terminal status is silent."""
    curr = _snap([_state(executed=100.0, status=TwapStatus.FINISHED)])
    events, _ = diff_twap_snapshots(
        previous=curr,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1,
                last_emitted_bucket_pct=90,
                started_emitted=True,
                terminal_emitted=True,
            )
        },
    )
    assert events == []


def test_disappeared_twap_emits_cancelled_once() -> None:
    """If we tracked a TWAP and it vanishes from history, emit CANCELLED once."""
    prev = _snap([_state(executed=30.0)])
    curr = _snap([])  # twap_id=1 disappeared
    events, buckets = diff_twap_snapshots(
        previous=prev,
        current=curr,
        bucket_states={
            1: TwapBucketState(
                twap_id=1, last_emitted_bucket_pct=30, started_emitted=True
            )
        },
    )
    assert [e.kind for e in events] == [TwapEventKind.CANCELLED]
    assert buckets[1].terminal_emitted is True

    # Second tick with same input — no re-emission.
    events2, _ = diff_twap_snapshots(
        previous=curr, current=curr, bucket_states=buckets
    )
    assert events2 == []


def test_rejects_mismatched_addresses() -> None:
    """Sanity guard: prev and curr must be for the same wallet."""
    other = "0x" + "cd" * 20
    prev = WalletTwapSnapshot(
        address=other, twaps=(_state(),), captured_at=datetime.now(UTC)
    )
    curr = _snap([_state()])
    try:
        diff_twap_snapshots(previous=prev, current=curr)
    except ValueError as e:
        assert "different wallets" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_rejects_invalid_bucket_step() -> None:
    """slice_pct_bucket must be in (0, 100]."""
    curr = _snap([])
    for bad in (0, -10, 101):
        try:
            diff_twap_snapshots(previous=None, current=curr, slice_pct_bucket=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for slice_pct_bucket={bad}")


def test_started_then_slice_in_same_tick() -> None:
    """A new TWAP that already shows progress emits STARTED + SLICE in one tick."""
    curr = _snap([_state(executed=25.0)])
    events, _ = diff_twap_snapshots(previous=None, current=curr, slice_pct_bucket=10)
    kinds = [e.kind for e in events]
    # STARTED first, then SLICE for 10% and 20%.
    assert kinds == [
        TwapEventKind.STARTED,
        TwapEventKind.SLICE,
        TwapEventKind.SLICE,
    ]
    slice_buckets = [e.bucket_pct for e in events if e.kind == TwapEventKind.SLICE]
    assert slice_buckets == [10, 20]

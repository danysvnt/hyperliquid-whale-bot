"""Integration-style tests for the Watcher's TWAP branch.

Verifies that:
- A new TWAP discovered by the stub client produces a STARTED DispatchedEvent.
- Progress crossing a bucket emits SLICE.
- TWAP turning terminal emits FINISHED or CANCELLED.
- Failure of the TWAP fetch does NOT block the position fetch (and vice versa).
- Only chats with notify_twap=True receive TWAP events; the positions toggle
  is independent.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hyperliquid_whale_bot.config import Settings
from hyperliquid_whale_bot.hl.watcher import DispatchedEvent, Watcher
from hyperliquid_whale_bot.models import (
    NotificationKind,
    Position,
    PositionEvent,
    Side,
    TwapEvent,
    TwapEventKind,
    TwapState,
    TwapStatus,
    WalletSnapshot,
    WalletTwapSnapshot,
)
from hyperliquid_whale_bot.storage.db import Database
from hyperliquid_whale_bot.storage.repo import Repository

ADDR = "0x" + "ab" * 20


def _pos_snapshot(positions: tuple[Position, ...] = ()) -> WalletSnapshot:
    return WalletSnapshot(address=ADDR, positions=positions, captured_at=datetime.now(UTC))


def _twap(
    *,
    twap_id: int = 1,
    coin: str = "BTC",
    total: float = 100.0,
    executed: float = 0.0,
    executed_usd: float = 0.0,
    status: TwapStatus = TwapStatus.ACTIVATED,
) -> TwapState:
    return TwapState(
        twap_id=twap_id,
        coin=coin,
        side=Side.LONG,
        total_size=total,
        executed_size=executed,
        executed_notional_usd=executed_usd,
        minutes=30,
        status=status,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _twap_snapshot(twaps: tuple[TwapState, ...] = ()) -> WalletTwapSnapshot:
    return WalletTwapSnapshot(address=ADDR, twaps=twaps, captured_at=datetime.now(UTC))


class StubClient:
    """Replacement for HyperliquidClient with controllable per-call behavior."""

    def __init__(
        self,
        *,
        positions: tuple[Position, ...] = (),
        twaps: tuple[TwapState, ...] = (),
        positions_error: Exception | None = None,
        twap_error: Exception | None = None,
    ) -> None:
        self.positions = positions
        self.twaps = twaps
        self.positions_error = positions_error
        self.twap_error = twap_error
        self.fetch_snapshot_calls = 0
        self.fetch_twap_calls = 0

    async def fetch_snapshot(self, address: str) -> WalletSnapshot:
        self.fetch_snapshot_calls += 1
        if self.positions_error:
            raise self.positions_error
        return WalletSnapshot(
            address=address.lower(), positions=self.positions, captured_at=datetime.now(UTC)
        )

    async def fetch_twap_state(self, address: str) -> WalletTwapSnapshot:
        self.fetch_twap_calls += 1
        if self.twap_error:
            raise self.twap_error
        return WalletTwapSnapshot(
            address=address.lower(), twaps=self.twaps, captured_at=datetime.now(UTC)
        )


async def _make_repo() -> tuple[Repository, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="hl-watcher-twap-")) / "test.db"
    db = Database(tmp)
    await db.initialize()
    return Repository(db), tmp


def _settings(db_path: Path, *, twap_bucket: int = 10) -> Settings:
    # `_env_file=None` skips loading `.env` so tests are deterministic regardless
    # of the developer's local environment.
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        telegram_bot_token="12345:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        database_path=db_path,
        watcher_poll_interval_seconds=10,
        alert_pct_threshold=5.0,
        alert_usd_threshold=5000.0,
        twap_slice_pct_bucket=twap_bucket,
        max_wallets_per_user=10,
    )


@pytest.mark.asyncio
async def test_watcher_emits_started_event_for_new_twap() -> None:
    repo, db_path = await _make_repo()
    await repo.add_wallet(chat_id=111, address=ADDR, label="alpha")

    client = StubClient(twaps=(_twap(),))
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=_settings(db_path),
        client=client,  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue,
    )
    await watcher._tick()

    events = _drain(queue)
    twap_events = [e for e in events if isinstance(e.event, TwapEvent)]
    assert len(twap_events) == 1
    assert twap_events[0].event.kind == TwapEventKind.STARTED
    assert twap_events[0].chat_id == 111
    assert twap_events[0].label == "alpha"


@pytest.mark.asyncio
async def test_watcher_emits_slice_then_finished_on_progress() -> None:
    repo, db_path = await _make_repo()
    await repo.add_wallet(chat_id=111, address=ADDR, label="alpha")
    settings = _settings(db_path)

    # Tick 1: TWAP just started at 0%.
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=settings,
        client=StubClient(twaps=(_twap(executed=0.0),)),  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue,
    )
    await watcher._tick()
    tick1 = _drain(queue)
    assert any(isinstance(e.event, TwapEvent) and e.event.kind == TwapEventKind.STARTED for e in tick1)

    # Tick 2: progress jumps to 25% (crosses 10% and 20% buckets).
    queue2: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher2 = Watcher(
        settings=settings,
        client=StubClient(twaps=(_twap(executed=25.0),)),  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue2,
    )
    await watcher2._tick()
    tick2_slices = [
        e
        for e in _drain(queue2)
        if isinstance(e.event, TwapEvent) and e.event.kind == TwapEventKind.SLICE
    ]
    assert [e.event.bucket_pct for e in tick2_slices] == [10, 20]

    # Tick 3: TWAP fills entirely.
    queue3: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher3 = Watcher(
        settings=settings,
        client=StubClient(  # type: ignore[arg-type]
            twaps=(_twap(executed=100.0, executed_usd=100.0, status=TwapStatus.FINISHED),)
        ),
        repo=repo,
        out_queue=queue3,
    )
    await watcher3._tick()
    tick3 = [e for e in _drain(queue3) if isinstance(e.event, TwapEvent)]
    assert any(e.event.kind == TwapEventKind.FINISHED for e in tick3)


@pytest.mark.asyncio
async def test_twap_fetch_error_does_not_block_positions() -> None:
    """If the TWAP endpoint fails, position events still flow."""
    repo, db_path = await _make_repo()
    await repo.add_wallet(chat_id=111, address=ADDR, label="alpha")

    pos = Position(
        coin="BTC",
        side=Side.LONG,
        size=1.0,
        entry_price=50_000.0,
        notional_usd=50_000.0,
        leverage=5.0,
        leverage_type="cross",
        unrealized_pnl=0.0,
    )
    # Seed an empty previous snapshot so the next tick sees an OPEN.
    await repo.save_snapshot(_pos_snapshot(()))

    client = StubClient(
        positions=(pos,),
        twap_error=RuntimeError("synthetic twap failure"),
    )
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=_settings(db_path),
        client=client,  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue,
    )
    await watcher._tick()

    events = _drain(queue)
    pos_events = [e for e in events if isinstance(e.event, PositionEvent)]
    twap_events = [e for e in events if isinstance(e.event, TwapEvent)]
    assert len(pos_events) >= 1, "position events must still flow despite TWAP failure"
    assert twap_events == [], "no TWAP events when fetch failed"


@pytest.mark.asyncio
async def test_position_fetch_error_does_not_block_twap() -> None:
    """And vice versa — a position failure must not kill the TWAP branch."""
    repo, db_path = await _make_repo()
    await repo.add_wallet(chat_id=111, address=ADDR, label="alpha")

    client = StubClient(
        twaps=(_twap(),),
        positions_error=RuntimeError("synthetic position failure"),
    )
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=_settings(db_path),
        client=client,  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue,
    )
    await watcher._tick()

    events = _drain(queue)
    twap_events = [e for e in events if isinstance(e.event, TwapEvent)]
    assert any(e.event.kind == TwapEventKind.STARTED for e in twap_events)


@pytest.mark.asyncio
async def test_twap_event_not_sent_when_notify_twap_disabled() -> None:
    """A wallet with notify_twap=False receives no TWAP events."""
    repo, db_path = await _make_repo()
    await repo.add_wallet(chat_id=111, address=ADDR, label="alpha")
    await repo.set_notification(
        chat_id=111, address=ADDR, kind=NotificationKind.TWAP, enabled=False
    )

    client = StubClient(twaps=(_twap(),))
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=_settings(db_path),
        client=client,  # type: ignore[arg-type]
        repo=repo,
        out_queue=queue,
    )
    await watcher._tick()

    twap_events = [e for e in _drain(queue) if isinstance(e.event, TwapEvent)]
    assert twap_events == []


def _drain(queue: asyncio.Queue[DispatchedEvent]) -> list[DispatchedEvent]:
    out: list[DispatchedEvent] = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out

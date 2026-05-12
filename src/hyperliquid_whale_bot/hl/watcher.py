"""Position + TWAP watcher — periodically polls all tracked wallets and emits events.

Architecture:
- Polls every configured interval (default 10 sec).
- For each unique address (across all chats), fetches in parallel:
    * `fetch_snapshot`     -> WalletSnapshot (perp positions)
    * `fetch_twap_state`   -> WalletTwapSnapshot (TWAP orders)
  Both calls run via `asyncio.gather(return_exceptions=True)` so one failing
  endpoint does not silence the other.
- Loads previous snapshots from storage, computes both diffs.
- Persists new snapshots and per-twap bucket state.
- Pushes (chat_id, event, label) tuples into an asyncio queue — `event` is
  either a `PositionEvent` or a `TwapEvent`. Subscribers branch on isinstance.
- Polls in parallel (with concurrency cap) to spread load over the poll interval.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import Settings
from ..diff import diff_snapshots
from ..logging_setup import get_logger
from ..models import (
    NotificationKind,
    PositionEvent,
    TwapEvent,
    TwapEventKind,
    WalletSnapshot,
    WalletTwapSnapshot,
)
from ..storage import Repository
from ..twap_diff import diff_twap_snapshots
from .client import HyperliquidClient

log = get_logger(__name__)

# Max wallets polled in parallel. Keeps the load on Hyperliquid REST predictable.
_DEFAULT_CONCURRENCY = 8


@dataclass(frozen=True, slots=True)
class DispatchedEvent:
    """An event paired with the chat that should receive it.

    `event` is a union: `PositionEvent` for perp-position changes (open/close/
    increase/decrease/leverage/side_flip), or `TwapEvent` for TWAP lifecycle
    changes (started/slice/finished/cancelled). The notifier branches on
    `isinstance(event, ...)`.
    """

    chat_id: int
    label: str
    event: PositionEvent | TwapEvent


class Watcher:
    """Long-running async task: polls Hyperliquid → diff → enqueue events."""

    def __init__(
        self,
        settings: Settings,
        client: HyperliquidClient,
        repo: Repository,
        out_queue: asyncio.Queue[DispatchedEvent],
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self._settings = settings
        self._client = client
        self._repo = repo
        self._out = out_queue
        self._semaphore = asyncio.Semaphore(concurrency)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Run forever (until `stop()` is called)."""
        log.info(
            "watcher.starting",
            interval_seconds=self._settings.watcher_poll_interval_seconds,
            pct_threshold=self._settings.alert_pct_threshold,
            usd_threshold=self._settings.alert_usd_threshold,
            twap_slice_pct_bucket=self._settings.twap_slice_pct_bucket,
        )
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001 -- the watcher loop must survive any tick failure
                log.error("watcher.tick_failed", error=repr(exc))
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._settings.watcher_poll_interval_seconds,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        addresses = await self._repo.all_unique_addresses()
        if not addresses:
            log.debug("watcher.no_wallets")
            return

        log.debug("watcher.tick", wallet_count=len(addresses))
        await asyncio.gather(*(self._poll_one(addr) for addr in addresses), return_exceptions=False)

    async def _poll_one(self, address: str) -> None:
        async with self._semaphore:
            # Fetch positions + TWAP state in parallel; one failure must not
            # cancel the sibling. `return_exceptions=True` makes that explicit.
            results = await asyncio.gather(
                self._client.fetch_snapshot(address),
                self._client.fetch_twap_state(address),
                return_exceptions=True,
            )
            snapshot_result, twap_result = results

            # Handle positions branch.
            if isinstance(snapshot_result, BaseException):
                log.warning(
                    "watcher.fetch_failed",
                    address=address,
                    error=repr(snapshot_result),
                )
            else:
                try:
                    await self._handle_position_snapshot(snapshot_result)
                except Exception as exc:  # noqa: BLE001
                    log.error("watcher.handle_failed", address=address, error=repr(exc))

            # Handle TWAP branch.
            if isinstance(twap_result, BaseException):
                log.warning(
                    "watcher.twap_fetch_failed",
                    address=address,
                    error=repr(twap_result),
                )
            else:
                try:
                    await self._handle_twap_snapshot(twap_result)
                except Exception as exc:  # noqa: BLE001
                    log.error("watcher.twap_handle_failed", address=address, error=repr(exc))

    async def _enrich_started_events(self, events: list[TwapEvent]) -> list[TwapEvent]:
        """Attach mark prices to STARTED events. Other event kinds pass through unchanged."""
        out: list[TwapEvent] = []
        for ev in events:
            if ev.kind != TwapEventKind.STARTED:
                out.append(ev)
                continue
            try:
                price = await self._client.fetch_mark_price(ev.twap.coin)
            except Exception as exc:  # noqa: BLE001 -- never let enrichment fail dispatch
                log.warning(
                    "watcher.mark_price_failed",
                    coin=ev.twap.coin,
                    error=repr(exc),
                )
                price = None
            out.append(
                TwapEvent(
                    kind=ev.kind,
                    address=ev.address,
                    twap=ev.twap,
                    previous=ev.previous,
                    progress_pct=ev.progress_pct,
                    captured_at=ev.captured_at,
                    bucket_pct=ev.bucket_pct,
                    mark_price_usd=price,
                )
            )
        return out

    async def _handle_position_snapshot(self, snapshot: WalletSnapshot) -> None:
        previous = await self._repo.get_snapshot(snapshot.address)
        events = diff_snapshots(
            previous=previous,
            current=snapshot,
            pct_threshold=self._settings.alert_pct_threshold,
            usd_threshold=self._settings.alert_usd_threshold,
        )
        await self._repo.save_snapshot(snapshot)

        if not events:
            return

        # Fan out only to chats that have the 'positions' notification toggle ON.
        chats = await self._repo.chats_subscribed_to(
            snapshot.address, kind=NotificationKind.POSITIONS
        )
        if not chats:
            return

        for event in events:
            for chat_id, label in chats:
                await self._out.put(DispatchedEvent(chat_id=chat_id, label=label, event=event))
        log.info(
            "watcher.events_emitted",
            address=snapshot.address,
            count=len(events),
            chats=len(chats),
        )

    async def _handle_twap_snapshot(self, snapshot: WalletTwapSnapshot) -> None:
        previous = await self._repo.get_twap_snapshot(snapshot.address)
        bucket_states = await self._repo.get_twap_bucket_states(snapshot.address)
        events, new_bucket_states = diff_twap_snapshots(
            previous=previous,
            current=snapshot,
            bucket_states=bucket_states,
            slice_pct_bucket=self._settings.twap_slice_pct_bucket,
        )
        await self._repo.save_twap_snapshot_and_buckets(snapshot, new_bucket_states)

        if not events:
            return

        chats = await self._repo.chats_subscribed_to(snapshot.address, kind=NotificationKind.TWAP)
        if not chats:
            return

        # Enrich STARTED events with a mark price so formatters can render an
        # approximate USD size. Best-effort: if the price fetch fails, the
        # formatter falls back to "By market" without the USD line.
        enriched_events = await self._enrich_started_events(events)

        for event in enriched_events:
            for chat_id, label in chats:
                await self._out.put(DispatchedEvent(chat_id=chat_id, label=label, event=event))
        log.info(
            "watcher.twap_events_emitted",
            address=snapshot.address,
            count=len(events),
            chats=len(chats),
        )

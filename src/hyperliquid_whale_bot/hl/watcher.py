"""Position watcher — periodically polls all tracked wallets and emits events.

Architecture:
- Polls every configured interval (default 10 sec).
- For each unique address (across all chats), calls HL client → fetches snapshot.
- Loads previous snapshot from storage, computes diff with thresholds.
- Stores the new snapshot.
- Pushes (chat_id, event, label) tuples into an asyncio queue for the bot to consume.
- Polls in parallel (with concurrency cap) to spread load over the poll interval.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import Settings
from ..diff import diff_snapshots
from ..logging_setup import get_logger
from ..models import PositionEvent, WalletSnapshot
from ..storage import Repository
from .client import HyperliquidClient

log = get_logger(__name__)

# Max wallets polled in parallel. Keeps the load on Hyperliquid REST predictable.
_DEFAULT_CONCURRENCY = 8


@dataclass(frozen=True, slots=True)
class DispatchedEvent:
    """A position event paired with the chat that should receive it."""

    chat_id: int
    label: str
    event: PositionEvent


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
            try:
                snapshot = await self._client.fetch_snapshot(address)
            except Exception as exc:  # noqa: BLE001 -- one bad wallet must not stop polling others
                log.warning("watcher.fetch_failed", address=address, error=repr(exc))
                return

            await self._handle_snapshot(snapshot)

    async def _handle_snapshot(self, snapshot: WalletSnapshot) -> None:
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

        # Fan out to every chat subscribed to this wallet.
        chats = await self._repo.chats_subscribed_to(snapshot.address)
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

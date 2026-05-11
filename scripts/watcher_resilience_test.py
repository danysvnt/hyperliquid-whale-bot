"""Watcher resilience — one wallet failing must not cancel sibling polls.

Adversarial test for the Devin Review fix on `_handle_snapshot`. In commit
06df560a we wrapped `_handle_snapshot` in its own try/except so that a DB or
dispatch error on wallet A does not propagate up through `asyncio.gather` and
cancel the concurrent poll for wallet B in the same tick.

Setup:
- two real tracked wallets, A and B, in the DB
- a `HyperliquidClient` stub that returns a valid snapshot for both
- a `Repository` proxy that raises a synthetic exception on `save_snapshot`
  for address A and forwards the call to the real repo for address B
- run exactly one `_tick()`; afterwards:
    PASS if the DB has a snapshot for B (sibling poll completed)
    PASS if no unhandled exception escaped the tick

Without the fix, B's snapshot would never be persisted because the `asyncio.gather`
that fans out `_poll_one` for [A, B] would short-circuit on A's exception.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hyperliquid_whale_bot.config import Settings
from hyperliquid_whale_bot.hl.watcher import DispatchedEvent, Watcher
from hyperliquid_whale_bot.models import Position, Side, WalletSnapshot
from hyperliquid_whale_bot.storage.db import Database
from hyperliquid_whale_bot.storage.repo import Repository

ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20


def fake_snapshot(addr: str) -> WalletSnapshot:
    pos = Position(
        coin="BTC",
        side=Side.LONG,
        size=1.0,
        entry_price=50_000.0,
        notional_usd=50_000.0,
        unrealized_pnl=0.0,
        leverage=5.0,
        leverage_type="cross",
        liquidation_price=None,
    )
    return WalletSnapshot(
        address=addr.lower(),
        positions=(pos,),
        captured_at=datetime.now(UTC),
    )


class StubClient:
    """Replacement for HyperliquidClient: always returns a synthetic snapshot."""

    async def fetch_snapshot(self, address: str) -> WalletSnapshot:
        return fake_snapshot(address)


class FailingRepoProxy:
    """Wraps a real Repository; raises for address A on `save_snapshot`."""

    def __init__(self, inner: Repository, failing_addr: str) -> None:
        self._inner = inner
        self._failing = failing_addr.lower()
        self.save_calls: list[str] = []
        self.save_errors: list[str] = []

    async def all_unique_addresses(self) -> list[str]:
        return await self._inner.all_unique_addresses()

    async def get_snapshot(self, address: str):
        return await self._inner.get_snapshot(address)

    async def save_snapshot(self, snapshot: WalletSnapshot) -> None:
        self.save_calls.append(snapshot.address)
        if snapshot.address.lower() == self._failing:
            self.save_errors.append(snapshot.address)
            raise RuntimeError("synthetic DB failure on address A")
        await self._inner.save_snapshot(snapshot)

    async def chats_subscribed_to(self, address: str) -> list[tuple[int, str]]:
        return await self._inner.chats_subscribed_to(address)


async def main() -> int:
    print("=" * 78)
    print("Watcher resilience test")
    print("=" * 78)

    tmpdir = tempfile.mkdtemp(prefix="hl-resilience-")
    db_path = Path(tmpdir) / "test.db"

    settings = Settings(
        telegram_bot_token="12345:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        database_path=db_path,
        watcher_poll_interval_seconds=10,
        alert_pct_threshold=5.0,
        alert_usd_threshold=5000.0,
        max_wallets_per_user=10,
    )
    db = Database(settings.database_path)
    await db.initialize()
    repo = Repository(db)

    # Seed: two users each tracking one of the two addresses.
    await repo.add_wallet(chat_id=111, address=ADDR_A, label="A")
    await repo.add_wallet(chat_id=222, address=ADDR_B, label="B")
    addrs = await repo.all_unique_addresses()
    print(f"seeded {len(addrs)} unique addresses: {sorted(addrs)}")
    assert sorted(addrs) == sorted([ADDR_A.lower(), ADDR_B.lower()]), "seed failed"

    failing_repo = FailingRepoProxy(repo, failing_addr=ADDR_A)
    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=settings,
        client=StubClient(),  # type: ignore[arg-type]
        repo=failing_repo,  # type: ignore[arg-type]
        out_queue=queue,
        concurrency=4,
    )

    failures: list[str] = []

    # Run a single tick directly (no run-loop, no sleep).
    try:
        await watcher._tick()
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] _tick() raised an unhandled exception: {exc!r}")
        failures.append(f"_tick raised: {exc!r}")

    print(f"\nsave_snapshot called for: {failing_repo.save_calls}")
    print(f"save_snapshot raised for: {failing_repo.save_errors}")

    if ADDR_A.lower() in failing_repo.save_errors:
        print("  [PASS] failing wallet A raised as expected")
    else:
        print("  [FAIL] failing wallet A did NOT raise — test setup broken")
        failures.append("setup: A never raised")

    snap_b = await repo.get_snapshot(ADDR_B)
    if snap_b is not None:
        print(f"  [PASS] sibling wallet B's snapshot persisted ({len(snap_b.positions)} positions)")
    else:
        print("  [FAIL] sibling wallet B's snapshot is NOT in DB — fix regressed")
        failures.append("B snapshot missing")

    snap_a = await repo.get_snapshot(ADDR_A)
    if snap_a is None:
        print("  [PASS] failing wallet A's snapshot is NOT in DB (expected)")
    else:
        print("  [WARN] failing wallet A is somehow in DB — investigate")

    print("\n" + "=" * 78)
    if not failures:
        print("Watcher resilience: ALL PASS")
        return 0
    print(f"Watcher resilience: {len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

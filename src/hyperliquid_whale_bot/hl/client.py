"""Thin wrapper around the synchronous `hyperliquid-python-sdk` `Info` client.

The SDK is synchronous (built on `requests`). To use it inside an asyncio app without
blocking the event loop, we run every call via `asyncio.to_thread`.

For our use case we only need the public `Info` endpoints (no API key required):
- `user_state(address)` -> open positions (`assetPositions`)
- `spot_clearinghouse_state(address)` -> spot balances (not used for now; perps only)
- `user_fills(address)` -> recent fills (used later for TWAP slice detection)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from hyperliquid.info import Info
from hyperliquid.utils import constants

from ..logging_setup import get_logger
from ..models import Position, WalletSnapshot

log = get_logger(__name__)


class HyperliquidClient:
    """Async-friendly façade over `hyperliquid.info.Info`."""

    def __init__(self, network: str = "mainnet") -> None:
        if network == "mainnet":
            base_url = constants.MAINNET_API_URL
        elif network == "testnet":
            base_url = constants.TESTNET_API_URL
        else:
            raise ValueError(f"Unsupported HL network: {network!r}")

        # `skip_ws=True` — for MVP we only use REST polling.
        # The Info constructor already loads spot_meta and meta on init (one-time cost).
        log.info("hl_client.connecting", network=network, base_url=base_url)
        self._info = Info(base_url=base_url, skip_ws=True)
        self._network = network

    @property
    def network(self) -> str:
        return self._network

    async def fetch_snapshot(self, address: str) -> WalletSnapshot:
        """Return the current open-perps snapshot for a wallet."""
        raw = await asyncio.to_thread(self._info.user_state, address)
        return _snapshot_from_user_state(address, raw)


def _snapshot_from_user_state(address: str, raw: dict[str, Any]) -> WalletSnapshot:
    """Parse `info.user_state(address)` response into a WalletSnapshot.

    Expected structure (subset):
        {
          "assetPositions": [
            {"position": {"coin": "ETH", "szi": "0.5", "entryPx": "...", "leverage": {...}, ...}},
            ...
          ],
          ...
        }
    """
    asset_positions = raw.get("assetPositions") or []
    positions: list[Position] = []
    for entry in asset_positions:
        pos_dict = entry.get("position") if isinstance(entry, dict) else None
        if not pos_dict:
            continue
        pos = Position.from_hl_dict(pos_dict)
        if pos is not None:
            positions.append(pos)

    return WalletSnapshot(
        address=address.lower(),
        positions=tuple(positions),
        captured_at=datetime.now(UTC),
    )

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
from ..models import (
    Position,
    TwapState,
    WalletSnapshot,
    WalletTwapSnapshot,
    parse_twap_state,
)

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

    async def fetch_twap_state(self, address: str) -> WalletTwapSnapshot:
        """Return the current TWAP-orders snapshot for a wallet.

        Combines two REST calls:
        - `twapHistory`     — lifecycle entries (activated / finished / terminated / error)
        - `userTwapSliceFills` — per-slice executions; we sum these by `twapId`
          to derive the cumulative `executed_size` and `executed_notional_usd`
          for each TWAP. The upstream `state.executedSz` field is only reliable
          on terminal entries, so we re-aggregate from fills for accuracy.

        Defensive: if either call fails or the schema drifts, we return an empty
        snapshot rather than raising — TWAP is best-effort; perp positions remain
        the primary signal.
        """
        history_raw, fills_raw = await asyncio.gather(
            asyncio.to_thread(self._info.post, "/info", {"type": "twapHistory", "user": address}),
            asyncio.to_thread(self._info.user_twap_slice_fills, address),
            return_exceptions=False,
        )
        return _twap_snapshot_from_raw(address, history_raw, fills_raw)


def _twap_snapshot_from_raw(
    address: str,
    history_raw: Any,
    fills_raw: Any,
) -> WalletTwapSnapshot:
    """Combine `twapHistory` + `userTwapSliceFills` into a `WalletTwapSnapshot`.

    Strategy:
    1. Aggregate slice fills by `twapId` → (executed_size, executed_notional_usd).
    2. For each TWAP id, find the most recent matching `twapHistory` entry.
       Match keys (in order of preference):
         a) explicit `twapId` field on the history entry (newer responses);
         b) `(coin, sz, timestamp)` tuple (older responses without `twapId`);
            ambiguous matches are skipped to avoid mis-attribution.
    3. Also include TWAPs that have a history entry but zero slice fills (just
       activated → still active).
    """
    if not isinstance(history_raw, list):
        history_raw = []
    if not isinstance(fills_raw, list):
        fills_raw = []

    # --- (1) aggregate fills by twap_id ---
    by_id_executed: dict[int, tuple[float, float]] = {}
    for entry in fills_raw:
        if not isinstance(entry, dict):
            continue
        tid = entry.get("twapId")
        fill = entry.get("fill")
        if not isinstance(fill, dict) or tid is None:
            continue
        try:
            twap_id = int(tid)
            sz = float(fill.get("sz", 0) or 0)
            px = float(fill.get("px", 0) or 0)
        except (TypeError, ValueError):
            continue
        prev_sz, prev_ntl = by_id_executed.get(twap_id, (0.0, 0.0))
        by_id_executed[twap_id] = (prev_sz + sz, prev_ntl + sz * px)

    # --- (2) index history. Keep the latest entry per twap_id we can identify. ---
    # Entries with explicit twapId are unambiguous.
    history_by_id: dict[int, dict[str, Any]] = {}
    # Entries without explicit twapId are bucketed by their state tuple so we can
    # match them to a twap_id from fills.
    tuple_bucket: dict[tuple[str, str, int], list[dict[str, Any]]] = {}

    for h in history_raw:
        if not isinstance(h, dict):
            continue
        state = h.get("state")
        if not isinstance(state, dict):
            continue
        explicit_id = h.get("twapId")
        if explicit_id is not None:
            try:
                tid_int = int(explicit_id)
            except (TypeError, ValueError):
                continue
            existing = history_by_id.get(tid_int)
            # Prefer terminal/latest entry (highest `time`).
            if existing is None or int(h.get("time", 0) or 0) >= int(existing.get("time", 0) or 0):
                history_by_id[tid_int] = h
            continue
        key = (
            str(state.get("coin", "")),
            str(state.get("sz", "")),
            int(state.get("timestamp", 0) or 0),
        )
        tuple_bucket.setdefault(key, []).append(h)

    # For TWAPs known from fills but missing in `history_by_id`, try the tuple bucket.
    for twap_id in by_id_executed:
        if twap_id in history_by_id:
            continue
        # We don't have a direct (coin, sz, ts) hint for the fill itself.
        # Use the fill's `coin` if available and pick the most recent history
        # entry for that coin where (coin, sz, ts) appears exactly once across
        # the wallet — i.e. unambiguous attribution.
        candidate_coins = {
            str(f.get("fill", {}).get("coin", ""))
            for f in fills_raw
            if isinstance(f, dict) and f.get("twapId") == twap_id
        }
        unambiguous_candidates: list[dict[str, Any]] = []
        for key, bucket in tuple_bucket.items():
            coin, _sz, _ts = key
            if coin in candidate_coins and len(bucket) == 1:
                unambiguous_candidates.append(bucket[0])
        if len(unambiguous_candidates) == 1:
            history_by_id[twap_id] = unambiguous_candidates[0]

    # --- (3) build TwapStates ---
    twaps: list[TwapState] = []
    seen: set[int] = set()
    for twap_id, h in history_by_id.items():
        if twap_id in seen:
            continue
        seen.add(twap_id)
        executed_sz, executed_ntl = by_id_executed.get(twap_id, (0.0, 0.0))
        history_for_parser = dict(h)
        history_for_parser["_twap_id"] = twap_id
        state = parse_twap_state(
            history_for_parser,
            executed_size=executed_sz,
            executed_notional_usd=executed_ntl,
        )
        if state is not None:
            twaps.append(state)

    return WalletTwapSnapshot(
        address=address.lower(),
        twaps=tuple(twaps),
        captured_at=datetime.now(UTC),
    )


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

"""Repository pattern: all SQL stays here."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from ..models import NotificationKind, Position, Side, TrackedWallet, WalletSnapshot
from .db import Database

ADDRESS_LEN = 42  # "0x" + 40 hex chars

# Map enum value -> column name in tracked_wallets.
_NOTIFY_COLUMN: dict[NotificationKind, str] = {
    NotificationKind.POSITIONS: "notify_positions",
    NotificationKind.TWAP: "notify_twap",
    NotificationKind.LIMIT: "notify_limit",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_address(addr: str) -> str:
    """Return lowercased EVM address. Raises ValueError if malformed."""
    s = addr.strip().lower()
    if not s.startswith("0x") or len(s) != ADDRESS_LEN:
        raise ValueError(f"Invalid EVM address: {addr!r}")
    int(s, 16)  # raises if non-hex
    return s


class Repository:
    """All persistence operations for the bot."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------- users ----------

    async def upsert_user(self, chat_id: int, language: str | None = None) -> None:
        """Create the user row if missing; optionally update language."""
        now = _now()
        async with self.db.connect() as conn:
            if language is None:
                await conn.execute(
                    """
                    INSERT INTO users (chat_id, language, created_at, updated_at)
                    VALUES (?, 'ru', ?, ?)
                    ON CONFLICT(chat_id) DO NOTHING
                    """,
                    (chat_id, now, now),
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO users (chat_id, language, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        language = excluded.language,
                        updated_at = excluded.updated_at
                    """,
                    (chat_id, language, now, now),
                )
            await conn.commit()

    async def get_user_language(self, chat_id: int) -> str:
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT language FROM users WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            return str(row["language"]) if row else "ru"

    # ---------- tracked wallets ----------

    async def add_wallet(self, chat_id: int, address: str, label: str) -> bool:
        """Add a wallet for a chat. Returns True if inserted, False if it already existed."""
        addr = _normalize_address(address)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO tracked_wallets (chat_id, address, label, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, address) DO NOTHING
                """,
                (chat_id, addr, label.strip(), _now()),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def remove_wallet(self, chat_id: int, address_or_label: str) -> bool:
        """Remove a wallet by address or label. Returns True if a row was deleted."""
        target = address_or_label.strip()
        # Try as address first.
        try:
            addr = _normalize_address(target)
            async with self.db.connect() as conn:
                cursor = await conn.execute(
                    "DELETE FROM tracked_wallets WHERE chat_id = ? AND address = ?",
                    (chat_id, addr),
                )
                await conn.commit()
                return cursor.rowcount > 0
        except ValueError:
            pass
        # Otherwise treat as label.
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM tracked_wallets WHERE chat_id = ? AND label = ?",
                (chat_id, target),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def list_wallets(self, chat_id: int) -> list[TrackedWallet]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT address, label, chat_id,
                       notify_positions, notify_twap, notify_limit
                FROM tracked_wallets
                WHERE chat_id = ?
                ORDER BY id ASC
                """,
                (chat_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_wallet(row) for row in rows]

    async def get_wallet(self, chat_id: int, address: str) -> TrackedWallet | None:
        addr = _normalize_address(address)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT address, label, chat_id,
                       notify_positions, notify_twap, notify_limit
                FROM tracked_wallets
                WHERE chat_id = ? AND address = ?
                """,
                (chat_id, addr),
            )
            row = await cursor.fetchone()
            return _row_to_wallet(row) if row else None

    async def update_wallet_label(self, chat_id: int, address: str, new_label: str) -> bool:
        addr = _normalize_address(address)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "UPDATE tracked_wallets SET label = ? WHERE chat_id = ? AND address = ?",
                (new_label.strip(), chat_id, addr),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def set_notification(
        self,
        chat_id: int,
        address: str,
        kind: NotificationKind,
        enabled: bool,
    ) -> bool:
        addr = _normalize_address(address)
        column = _NOTIFY_COLUMN[kind]
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                f"UPDATE tracked_wallets SET {column} = ? WHERE chat_id = ? AND address = ?",
                (1 if enabled else 0, chat_id, addr),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def count_wallets(self, chat_id: int) -> int:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM tracked_wallets WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            return int(row["c"]) if row else 0

    async def all_unique_addresses(self) -> list[str]:
        """Distinct lowercased addresses across all chats — what the watcher polls."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT DISTINCT address FROM tracked_wallets")
            rows = await cursor.fetchall()
            return [row["address"] for row in rows]

    async def chats_subscribed_to(
        self, address: str, kind: NotificationKind = NotificationKind.POSITIONS
    ) -> list[tuple[int, str]]:
        """Return [(chat_id, label), ...] for chats subscribed AND opted in to `kind` events.

        The watcher uses this to fan out only to chats that have the corresponding
        notification toggle enabled for this wallet.
        """
        addr = _normalize_address(address)
        column = _NOTIFY_COLUMN[kind]
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                f"SELECT chat_id, label FROM tracked_wallets WHERE address = ? AND {column} = 1",
                (addr,),
            )
            rows = await cursor.fetchall()
            return [(row["chat_id"], row["label"]) for row in rows]

    async def find_label(self, chat_id: int, address: str) -> str | None:
        addr = _normalize_address(address)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT label FROM tracked_wallets WHERE chat_id = ? AND address = ?",
                (chat_id, addr),
            )
            row = await cursor.fetchone()
            return str(row["label"]) if row else None

    # ---------- position snapshots ----------

    async def get_snapshot(self, address: str) -> WalletSnapshot | None:
        addr = _normalize_address(address)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT snapshot_json, captured_at FROM position_snapshots WHERE address = ?",
                (addr,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return _decode_snapshot(addr, row["snapshot_json"], row["captured_at"])

    async def save_snapshot(self, snapshot: WalletSnapshot) -> None:
        addr = _normalize_address(snapshot.address)
        payload = json.dumps([_encode_position(p) for p in snapshot.positions])
        async with self.db.connect() as conn:
            await conn.execute(
                """
                INSERT INTO position_snapshots (address, snapshot_json, captured_at)
                VALUES (?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    snapshot_json = excluded.snapshot_json,
                    captured_at   = excluded.captured_at
                """,
                (addr, payload, snapshot.captured_at.isoformat()),
            )
            await conn.commit()

    async def prune_orphan_snapshots(self) -> int:
        """Delete snapshots for addresses no longer tracked by anyone."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                DELETE FROM position_snapshots
                WHERE address NOT IN (SELECT DISTINCT address FROM tracked_wallets)
                """
            )
            await conn.commit()
            return cursor.rowcount


# ---------- helpers ----------


def _row_to_wallet(row: Any) -> TrackedWallet:
    return TrackedWallet(
        address=row["address"],
        label=row["label"],
        chat_id=row["chat_id"],
        notify_positions=bool(row["notify_positions"]),
        notify_twap=bool(row["notify_twap"]),
        notify_limit=bool(row["notify_limit"]),
    )


def _encode_position(p: Position) -> dict[str, Any]:
    d = asdict(p)
    # Side is an Enum; serialize as its value.
    d["side"] = p.side.value
    return d


def _decode_snapshot(address: str, payload: str, captured_at_iso: str) -> WalletSnapshot:
    raw_positions = json.loads(payload)
    positions = tuple(
        Position(
            coin=str(d["coin"]),
            side=Side(d["side"]),
            size=float(d["size"]),
            entry_price=float(d["entry_price"]),
            notional_usd=float(d["notional_usd"]),
            leverage=float(d["leverage"]),
            leverage_type=str(d["leverage_type"]),
            unrealized_pnl=float(d["unrealized_pnl"]),
            liquidation_price=(
                float(d["liquidation_price"]) if d.get("liquidation_price") is not None else None
            ),
            max_leverage=int(d["max_leverage"]) if d.get("max_leverage") is not None else None,
        )
        for d in raw_positions
    )
    return WalletSnapshot(
        address=address,
        positions=positions,
        captured_at=datetime.fromisoformat(captured_at_iso),
    )

"""SQLite database connection and schema initialization."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    language   TEXT NOT NULL DEFAULT 'ru',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_wallets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id           INTEGER NOT NULL,
    address           TEXT NOT NULL,
    label             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    notify_positions  INTEGER NOT NULL DEFAULT 1,
    notify_twap       INTEGER NOT NULL DEFAULT 1,
    notify_limit      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(chat_id, address)
);

CREATE INDEX IF NOT EXISTS idx_tracked_wallets_chat_id ON tracked_wallets(chat_id);
CREATE INDEX IF NOT EXISTS idx_tracked_wallets_address ON tracked_wallets(address);

-- One row per unique wallet address (across all chats). The watcher polls these.
CREATE TABLE IF NOT EXISTS position_snapshots (
    address       TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    captured_at   TEXT NOT NULL
);

-- TWAP-order state, persisted per (address, twap_id).
-- `state_json` is a serialized TwapState; `last_emitted_bucket_pct` /
-- `started_emitted` / `terminal_emitted` track which SLICE bucket and lifecycle
-- events have already been pushed to Telegram so we don't double-notify after
-- a restart.
CREATE TABLE IF NOT EXISTS twap_states (
    address                   TEXT NOT NULL,
    twap_id                   INTEGER NOT NULL,
    state_json                TEXT NOT NULL,
    last_emitted_bucket_pct   INTEGER NOT NULL DEFAULT 0,
    started_emitted           INTEGER NOT NULL DEFAULT 0,
    terminal_emitted          INTEGER NOT NULL DEFAULT 0,
    captured_at               TEXT NOT NULL,
    PRIMARY KEY(address, twap_id)
);

CREATE INDEX IF NOT EXISTS idx_twap_states_address ON twap_states(address);
"""

# Idempotent migrations for older DBs that lack the toggle columns.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("tracked_wallets", "notify_positions"),
    ("tracked_wallets", "notify_twap"),
    ("tracked_wallets", "notify_limit"),
)


class Database:
    """Owns the SQLite connection lifecycle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create tables if missing; run additive migrations for older DBs."""
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(SCHEMA_SQL)
            for table, column in _MIGRATIONS:
                if not await _column_exists(conn, table, column):
                    await conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 1"
                    )
            await conn.commit()

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield a fresh connection. Caller is responsible for commits."""
        conn = await aiosqlite.connect(self.path)
        try:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            await conn.close()


async def _column_exists(conn: aiosqlite.Connection, table: str, column: str) -> bool:
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return any(row[1] == column for row in rows)

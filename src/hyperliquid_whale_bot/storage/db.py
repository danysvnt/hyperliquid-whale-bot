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
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    address    TEXT NOT NULL,
    label      TEXT NOT NULL,
    created_at TEXT NOT NULL,
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
"""


class Database:
    """Owns the SQLite connection lifecycle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create tables if they do not exist."""
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(SCHEMA_SQL)
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

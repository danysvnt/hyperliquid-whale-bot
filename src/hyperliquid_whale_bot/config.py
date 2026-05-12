"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the bot.

    Values are loaded (in order of precedence) from:
    1. Process environment variables.
    2. A `.env` file in the project root.
    3. Defaults defined here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(..., description="Token from @BotFather")

    # --- Hyperliquid ---
    hl_network: Literal["mainnet", "testnet"] = Field(
        default="mainnet",
        description="Hyperliquid network to use",
    )

    # --- Watcher ---
    watcher_poll_interval_seconds: int = Field(
        default=10,
        ge=5,
        le=300,
        description="How often to poll wallet positions via REST",
    )
    alert_pct_threshold: float = Field(
        default=5.0,
        ge=0.0,
        description="Min % change in position size to trigger an alert",
    )
    alert_usd_threshold: float = Field(
        default=5_000.0,
        ge=0.0,
        description="Min USD notional change in position to trigger an alert",
    )
    twap_slice_pct_bucket: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Step (in percent) between TWAP SLICE notifications. 10 = notify at 10%, 20%, ..., 90%.",
    )

    # --- Bot policy ---
    max_wallets_per_user: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max number of wallets a single Telegram user can track",
    )
    # `NoDecode` tells pydantic-settings to skip JSON-decoding this list and
    # hand the raw env-var string to the `_parse_chat_ids` validator below.
    # Without it, `WHITELIST_CHAT_IDS=` (empty) raises a JSONDecodeError before
    # the validator ever runs (regression introduced in pydantic-settings 2.x).
    whitelist_chat_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        description="If non-empty, only these chat_ids may use the bot",
    )

    # --- Storage ---
    database_path: Path = Field(
        default=Path("data/whale_bot.db"),
        description="Path to the SQLite database file",
    )

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    @field_validator("whitelist_chat_ids", mode="before")
    @classmethod
    def _parse_chat_ids(cls, v: object) -> list[int]:
        """Allow CSV input from .env: WHITELIST_CHAT_IDS=123,456 → [123, 456]."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        raise ValueError(f"Cannot parse whitelist_chat_ids: {v!r}")

    @property
    def hl_api_url(self) -> str:
        """REST/WS base URL based on selected network."""
        if self.hl_network == "mainnet":
            return "https://api.hyperliquid.xyz"
        return "https://api.hyperliquid-testnet.xyz"

    def is_whitelisted(self, chat_id: int) -> bool:
        """Whether a chat_id is allowed to use the bot in private mode."""
        if not self.whitelist_chat_ids:
            return True  # public mode
        return chat_id in self.whitelist_chat_ids

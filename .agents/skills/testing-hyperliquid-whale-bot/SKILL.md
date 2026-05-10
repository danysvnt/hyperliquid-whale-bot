---
name: testing-hyperliquid-whale-bot
description: Test the Hyperliquid whale-tracker Telegram bot end-to-end. Use when verifying changes to bot handlers, the watcher loop, the diff engine, the Hyperliquid client wrapper, or i18n / formatters.
---

# Testing the Hyperliquid whale-tracker bot

The project is a multi-user aiogram-v3 Telegram bot that polls Hyperliquid mainnet REST for tracked wallets and notifies subscribers on meaningful position changes. There is no real Telegram client on the Devin VM, so prefer in-process testing over Telethon unless the user has explicitly provisioned a dedicated test account.

## Devin secrets needed

- `TELEGRAM_BOT_TOKEN` — required by `Settings(...)`. Validated for format (`<digits>:<base64>`) by pydantic. A throw-away token of the right shape works for in-process tests; only `Bot.session` is exercised, and we replace it with a fake.
- `TELEGRAM_TEST_API_ID` / `TELEGRAM_TEST_API_HASH` / `TELEGRAM_TEST_PHONE` — only needed if the user opts for Telethon-driven end-to-end testing (variant B). Skip otherwise.

Hyperliquid mainnet REST (`https://api.hyperliquid.xyz`) is publicly reachable and needs no credentials.

## Default test approach: in-process aiogram Dispatcher

1. Build the bot with a fake `BaseSession` that captures every Telegram API call instead of sending it.
2. Feed `Update` objects through `Dispatcher.feed_update`.
3. Read captured calls and assert on text / reply_markup / parse_mode.
4. Run the real `Watcher`, the real `HyperliquidClient`, and a real SQLite DB (use a tmpdir).

Sketch:

```python
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, User

class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        # capture method.model_dump(...) into a list; return a synthesised
        # Message / User / True depending on method.__api_method__
```

Replace `make_request` only — do not override `check_response`. For `sendMessage` and `editMessageText` return a `Message.model_validate({...})` with at least `message_id`, `date`, `chat`, `text`. For `answerCallbackQuery` return `True`. For `getMe` return a `User(id=..., is_bot=True, first_name=..., username=...)`.

Drive commands by building `Update` with a `message` payload; drive callbacks with a `callback_query` payload that has `from`, `chat_instance`, `data`, and a synthetic `message`.

## Live mainnet target

The address `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` is a known whale with multiple permanent perp positions (BTC long, ETH/SOL/XRP shorts, etc.) and an account value in the millions. Useful for `/status` and watcher tests because it almost always has > 5 open positions. If you need a different target, query `https://api.hyperliquid.xyz/info` with `{"type":"clearinghouseState","user":"0x..."}` first to confirm it has `assetPositions` with non-zero `szi`.

## Things that bite

- `Settings.watcher_poll_interval_seconds` is `ge=5`; pydantic will reject 1–4. Use 5 if you want fast ticks in tests.
- `Database.connect()` is an `@asynccontextmanager`, not an awaitable. Use `await db.initialize()` to create the schema.
- `HyperliquidClient(network="mainnet")` (keyword `network`, not `testnet`).
- `Position.from_hl_dict` filters zero-size positions silently. If a fixture shows 0 positions but the wallet "should" have some, check `szi == 0`.
- The watcher fans wallets out with `asyncio.gather(..., return_exceptions=False)`. Two try/except blocks in `_poll_one` (one around `fetch_snapshot`, one around `_handle_snapshot`) keep one bad wallet from cancelling siblings — regression-test both layers.
- User-provided labels MUST be HTML-escaped before formatting into HTML messages. The `_html_escape` helper in `bot/handlers.py` escapes `&<>"`. If you add a new handler that interpolates a user-provided label, run a regression test with a `<evil>` label.
- Dual-threshold filter: events emit only when both `pct_change >= ALERT_PCT_THRESHOLD` **and** `notional_delta >= ALERT_USD_THRESHOLD`. An `or` would spam users on micro-noise; a regression test should include a case where only one threshold is exceeded.

## Suggested test scripts

Write one-shot scripts under `scripts/` (not part of pytest, just shell-run):

- `inproc_test.py` — round-trip every command via the in-process driver. Asserts on captured Telegram payloads.
- `threshold_test.py` — pure-function adversarial test for `diff_snapshots` and `format_event` (Cases: both-under, both-over, pct-over-but-USD-under).
- `watcher_resilience_test.py` — inject a `Repository` proxy that raises from `save_snapshot` for one address; assert the sibling address's snapshot still persists.

Each script should `sys.exit(0)` on success and `sys.exit(1)` on any failed assertion so the runner can tell at a glance.

## Recording

If the user opts for variant C (in-process) or variant A (user drives the real bot), do NOT start a screen recording — the test is shell-only or shell+screenshots and there is no GUI activity to capture. Only record if variant B (Telethon) is used and you actually see Telegram client UI updates.

## CI status

The repo has no GitHub Actions checks defined; `git pr_checks` returns 0/0/0/0. Devin Review runs and posts inline comments — always re-check `gh api /repos/{owner}/{repo}/pulls/{n}/reviews` after pushing fixes to confirm the latest commit has no new findings.

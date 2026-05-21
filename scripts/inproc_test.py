"""End-to-end driver test for the bot via aiogram Dispatcher.

This test exercises every command handler, the watcher loop, and the real
Hyperliquid client without ever talking to Telegram.

What we mock:
- The Telegram session: a fake `BaseSession` that captures every API call the
  bot would make and returns just enough of a synthetic response for aiogram
  to keep going.

What is NOT mocked:
- aiogram Dispatcher routing + filters
- Our handlers
- The Hyperliquid client (real REST calls to mainnet)
- The watcher loop
- SQLite storage

The script prints a structured pass/fail report at the end and exits non-zero
on any failure so CI / a human can tell at a glance whether testing succeeded.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

# Ensure src/ is on the path before importing the package.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

from hyperliquid_whale_bot.bot.handlers import build_router
from hyperliquid_whale_bot.config import Settings
from hyperliquid_whale_bot.hl.client import HyperliquidClient
from hyperliquid_whale_bot.hl.watcher import DispatchedEvent, Watcher
from hyperliquid_whale_bot.storage.db import Database
from hyperliquid_whale_bot.storage.repo import Repository

TEST_CHAT_ID = 1234567890
TEST_USER_ID = TEST_CHAT_ID
TEST_USERNAME = "test_user"
WHALE_ADDRESS = "0x5b5d51203a0f9079f8aeb098a6523a13f298c060"
EVIL_ADDRESS = "0x1111111111111111111111111111111111111111"
NEXT_MESSAGE_ID = 1000


@dataclass
class CapturedCall:
    """A single Telegram API call intercepted by the fake session."""

    method_name: str
    payload: dict[str, Any]
    text: str | None
    chat_id: int | None
    reply_markup: InlineKeyboardMarkup | None
    reply_markup_raw: dict[str, Any] | None = None


@dataclass
class CaptureBox:
    calls: list[CapturedCall] = field(default_factory=list)

    def messages_to(self, chat_id: int) -> list[CapturedCall]:
        return [c for c in self.calls if c.chat_id == chat_id and c.text is not None]

    def reset(self) -> None:
        self.calls.clear()


def _next_message_id() -> int:
    global NEXT_MESSAGE_ID
    NEXT_MESSAGE_ID += 1
    return NEXT_MESSAGE_ID


class FakeSession(BaseSession):
    """Capture Telegram calls in memory instead of hitting api.telegram.org."""

    def __init__(self, box: CaptureBox) -> None:
        super().__init__(api=TelegramAPIServer.from_base("https://example.invalid"))
        self._box = box

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None

    async def stream_content(self, *_args: object, **_kwargs: object) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        payload = method.model_dump(exclude_none=True, mode="python")
        method_name = method.__api_method__

        text = payload.get("text") if isinstance(payload.get("text"), str) else None
        chat_id = payload.get("chat_id") if isinstance(payload.get("chat_id"), int) else None
        markup_raw = payload.get("reply_markup")
        markup: InlineKeyboardMarkup | None = None
        if isinstance(markup_raw, dict) and "inline_keyboard" in markup_raw:
            markup = InlineKeyboardMarkup.model_validate(markup_raw)

        self._box.calls.append(
            CapturedCall(
                method_name=method_name,
                payload=payload,
                text=text,
                chat_id=chat_id,
                reply_markup=markup,
                reply_markup_raw=markup_raw if isinstance(markup_raw, dict) else None,
            )
        )

        if method_name == "getMe":
            return cast(
                TelegramType,
                User(
                    id=8311183557,
                    is_bot=True,
                    first_name="HL Tracker Bot",
                    username="trackinghl_bot",
                ),
            )
        if method_name == "sendMessage":
            msg = Message.model_validate(
                {
                    "message_id": _next_message_id(),
                    "date": int(time.time()),
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": 8311183557, "is_bot": True, "first_name": "HL Tracker Bot"},
                    "text": text or "",
                }
            )
            return cast(TelegramType, msg)
        if method_name == "editMessageText":
            msg = Message.model_validate(
                {
                    "message_id": payload.get("message_id", _next_message_id()),
                    "date": int(time.time()),
                    "chat": {"id": chat_id or TEST_CHAT_ID, "type": "private"},
                    "from": {"id": 8311183557, "is_bot": True, "first_name": "HL Tracker Bot"},
                    "text": text or "",
                }
            )
            return cast(TelegramType, msg)
        if method_name == "answerCallbackQuery":
            return cast(TelegramType, True)
        # Default: return True for unknown bool methods, raise otherwise.
        return cast(TelegramType, True)


def _make_message(text: str, chat_id: int = TEST_CHAT_ID) -> Message:
    return Message.model_validate(
        {
            "message_id": _next_message_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private", "username": TEST_USERNAME},
            "from": {
                "id": TEST_USER_ID,
                "is_bot": False,
                "first_name": "Test",
                "username": TEST_USERNAME,
            },
            "text": text,
        }
    )


def _make_command_update(text: str, chat_id: int = TEST_CHAT_ID) -> Update:
    return Update.model_validate(
        {
            "update_id": _next_message_id(),
            "message": _make_message(text, chat_id).model_dump(exclude_none=True, mode="python"),
        }
    )


def _make_callback_update(data: str, message_id: int, chat_id: int = TEST_CHAT_ID) -> Update:
    return Update.model_validate(
        {
            "update_id": _next_message_id(),
            "callback_query": {
                "id": str(_next_message_id()),
                "from": {
                    "id": TEST_USER_ID,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": TEST_USERNAME,
                },
                "chat_instance": "test_instance",
                "data": data,
                "message": {
                    "message_id": message_id,
                    "date": int(time.time()),
                    "chat": {"id": chat_id, "type": "private", "username": TEST_USERNAME},
                    "from": {
                        "id": 8311183557,
                        "is_bot": True,
                        "first_name": "HL Tracker Bot",
                    },
                    "text": "language prompt",
                },
            },
        }
    )


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


RESULTS: list[TestResult] = []


def assert_step(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")
    RESULTS.append(TestResult(name=name, passed=condition, detail=detail))


def find_text(box: CaptureBox, substr: str) -> CapturedCall | None:
    for call in reversed(box.calls):
        if call.text and substr in call.text:
            return call
    return None


def find_text_anywhere(box: CaptureBox, substr: str) -> bool:
    return find_text(box, substr) is not None


async def feed_and_wait(dp: Dispatcher, bot: Bot, update: Update) -> None:
    await dp.feed_update(bot=bot, update=update)


async def main() -> int:
    print("=" * 78)
    print(f"In-process bot test  |  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 78)

    db_dir = tempfile.mkdtemp(prefix="hl-bot-test-")
    db_path = os.path.join(db_dir, "test.db")
    print(f"DB: {db_path}")

    settings = Settings(
        telegram_bot_token="12345:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # valid format, never used
        database_path=db_path,
        watcher_poll_interval_seconds=5,
        alert_pct_threshold=5.0,
        alert_usd_threshold=5000.0,
        max_wallets_per_user=10,
        log_level="INFO",
    )

    db = Database(settings.database_path)
    await db.initialize()
    repo = Repository(db)

    hl_client = HyperliquidClient(network=settings.hl_network)

    box = CaptureBox()
    bot = Bot(token=settings.telegram_bot_token, session=FakeSession(box))
    dp = Dispatcher()
    dp.include_router(build_router(settings, repo, hl_client))

    queue: asyncio.Queue[DispatchedEvent] = asyncio.Queue()
    watcher = Watcher(
        settings=settings,
        client=hl_client,
        repo=repo,
        out_queue=queue,
        concurrency=4,
    )
    watcher_task = asyncio.create_task(watcher.run())

    try:
        # ---- Step 1: service starts cleanly --------------------------------
        print("\n--- Step 1: service starts cleanly ----------------------------------")
        await asyncio.sleep(0.5)
        assert_step(
            "watcher task is alive after 0.5s",
            not watcher_task.done(),
            detail="task exception: " + repr(watcher_task.exception())
            if watcher_task.done()
            else "",
        )

        # ---- Step 2: /start in default lang (RU) ---------------------------
        print("\n--- Step 2: /start (default RU) -------------------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/start"))
        msgs = box.messages_to(TEST_CHAT_ID)
        assert_step("got >=1 reply to /start", len(msgs) >= 1)
        assert_step(
            "/start reply contains RU welcome 'Привет!'",
            any("Привет!" in (m.text or "") for m in msgs),
            detail=(msgs[-1].text[:120] if msgs else "<no reply>"),
        )
        assert_step(
            "/start reply mentions /help",
            any("/help" in (m.text or "") for m in msgs),
        )

        # ---- Step 3: /lang -> tap English ---------------------------------
        print("\n--- Step 3: /lang then switch to English ----------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/lang"))
        lang_prompt = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "/lang produced a reply",
            len(lang_prompt) >= 1,
        )
        # The keyboard should have 3 language buttons
        kb = lang_prompt[-1].reply_markup if lang_prompt else None
        assert_step(
            "/lang reply has inline keyboard with 3 buttons",
            kb is not None and sum(len(row) for row in kb.inline_keyboard) == 3,
        )
        prompt_message_id = lang_prompt[-1].payload.get("chat_id")  # placeholder
        # The lang callback edits the message; use any message id since FakeSession
        # ignores message_id for capturing. We use the prompt's chat_id.
        box.reset()
        await feed_and_wait(dp, bot, _make_callback_update("lang:en", message_id=99999))
        post_switch = box.calls
        edited = [c for c in post_switch if c.method_name == "editMessageText"]
        cb_answers = [c for c in post_switch if c.method_name == "answerCallbackQuery"]
        assert_step(
            "language switch edited the message",
            len(edited) >= 1,
            detail=(edited[-1].text or "")[:120] if edited else "",
        )
        assert_step(
            "edited text is the English 'Language set: English.'",
            any("Language set: English." in (e.text or "") for e in edited),
        )
        assert_step(
            "callback was answered",
            len(cb_answers) >= 1,
        )

        # Sanity check that DB now has user lang=en
        post_lang = await repo.get_user_language(TEST_CHAT_ID)
        assert_step(
            "DB user lang is 'en' after callback",
            post_lang == "en",
            detail=f"got lang={post_lang!r}",
        )

        # ---- Step 4: /add whale --------------------------------------------
        print("\n--- Step 4: /add real whale -----------------------------------------")
        box.reset()
        await feed_and_wait(
            dp,
            bot,
            _make_command_update(f"/add {WHALE_ADDRESS} whale"),
        )
        add_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step("/add produced a reply", len(add_msgs) >= 1)
        assert_step(
            "/add reply contains EN 'Added <b>whale</b>'",
            any("Added <b>whale</b>" in (m.text or "") for m in add_msgs),
            detail=(add_msgs[-1].text[:200] if add_msgs else ""),
        )
        last_add = add_msgs[-1]
        assert_step(
            "/add reply has explorer keyboard with 4 buttons (incl. Coinmarketman)",
            last_add.reply_markup is not None
            and sum(len(r) for r in last_add.reply_markup.inline_keyboard) == 4,
        )
        if last_add.reply_markup:
            urls = [
                btn.url for row in last_add.reply_markup.inline_keyboard for btn in row if btn.url
            ]
            assert_step(
                "Hypurrscan url points at the whale address",
                any(
                    f"https://hypurrscan.io/address/{WHALE_ADDRESS}".lower() == u.lower()
                    for u in urls
                ),
                detail=str(urls),
            )
            assert_step(
                "Hyperdash url points at the whale address",
                any(
                    f"https://hyperdash.info/trader/{WHALE_ADDRESS}".lower() == u.lower()
                    for u in urls
                ),
                detail=str(urls),
            )

        # ---- Step 5: /list -------------------------------------------------
        print("\n--- Step 5: /list ----------------------------------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/list"))
        list_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step("/list produced a reply", len(list_msgs) >= 1)
        list_text = (list_msgs[-1].text or "") if list_msgs else ""
        list_kb = list_msgs[-1].reply_markup if list_msgs else None
        assert_step(
            "/list reply contains an inline wallet-list keyboard",
            list_kb is not None
            and any(
                btn.callback_data and btn.callback_data.startswith("w:open:")
                for row in list_kb.inline_keyboard
                for btn in row
            ),
            detail=str(list_kb)[:200] if list_kb else "",
        )
        assert_step(
            "/list reply has the 'Add wallet' button",
            list_kb is not None
            and any(
                btn.callback_data == "w:add"
                for row in list_kb.inline_keyboard
                for btn in row
            ),
            detail=str(list_kb)[:200] if list_kb else "",
        )
        assert_step(
            "/list shows wallet count header",
            "1/10" in list_text or "· 1" in list_text,
            detail=list_text[:200],
        )

        # ---- Step 6: /status whale  (REAL Hyperliquid mainnet call) -------
        print("\n--- Step 6: /status whale (real HL mainnet) -------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/status whale"))
        # Wait a moment for the snapshot fetch to complete and the second reply to land.
        await asyncio.sleep(3.0)
        status_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "/status produced >=2 replies (fetching... + result)",
            len(status_msgs) >= 2,
            detail=f"got {len(status_msgs)} replies",
        )
        if len(status_msgs) >= 2:
            final = status_msgs[-1]
            ft = final.text or ""
            has_coin = any(coin in ft for coin in ("BTC", "ETH", "SOL", "SUI", "XRP"))
            assert_step("/status final reply mentions a known coin", has_coin, detail=ft[:300])
            assert_step("/status mentions 'Size:'", "Size:" in ft)
            assert_step("/status mentions 'Amount:'", "Amount:" in ft)
            assert_step("/status mentions 'Entry:'", "Entry:" in ft)
            assert_step("/status mentions 'Leverage:'", "Leverage:" in ft)
            assert_step("/status mentions a dollar amount", "$" in ft)
            assert_step(
                "/status header includes copyable address (<code>0x...)",
                f"<code>{WHALE_ADDRESS.lower()}</code>" in ft,
                detail=ft[:200],
            )
            assert_step(
                "/status has 4-button explorer keyboard (incl. Coinmarketman)",
                final.reply_markup is not None
                and sum(len(r) for r in final.reply_markup.inline_keyboard) == 4,
            )

        # ---- Step 7: watcher actually polls --------------------------------
        print("\n--- Step 7: watcher polls Hyperliquid for the tracked address -------")
        # The watcher poll interval is 3s; wait long enough to see at least one tick.
        await asyncio.sleep(4.0)
        # The snapshot table should have an entry for the whale.
        snap = await repo.get_snapshot(WHALE_ADDRESS)
        assert_step(
            "DB has a snapshot row for the tracked whale after a watcher tick",
            snap is not None,
        )
        if snap is not None:
            assert_step(
                "snapshot has at least one open position",
                len(snap.positions) > 0,
                detail=f"positions: {[p.coin for p in snap.positions[:5]]}",
            )

        # ---- Step 8: /remove whale ----------------------------------------
        print("\n--- Step 8: /remove ---------------------------------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/remove whale"))
        rm_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "/remove succeeded ('Removed from your list.')",
            any("Removed from your list." in (m.text or "") for m in rm_msgs),
            detail=(rm_msgs[-1].text[:200] if rm_msgs else ""),
        )
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/list"))
        list_after = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "/list now reports 'No wallets yet' empty state",
            any("no wallets yet" in (m.text or "").lower() for m in list_after),
            detail=(list_after[-1].text[:200] if list_after else ""),
        )

        # ---- Step 9: HTML-escape regression -------------------------------
        print("\n--- Step 9: /add with HTML-special label ----------------------------")
        box.reset()
        await feed_and_wait(
            dp,
            bot,
            _make_command_update(f"/add {EVIL_ADDRESS} <evil>"),
        )
        ev_msgs = box.messages_to(TEST_CHAT_ID)
        ev_text = (ev_msgs[-1].text or "") if ev_msgs else ""
        assert_step(
            "label '<evil>' is HTML-escaped in reply",
            "&lt;evil&gt;" in ev_text and "<evil>" not in ev_text.replace("&lt;evil&gt;", ""),
            detail=ev_text[:200],
        )

        # ---- Step 10: reply keyboard sent on /start -----------------------
        print("\n--- Step 10: /start sends persistent reply keyboard ----------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/start"))
        start_msgs = box.messages_to(TEST_CHAT_ID)
        start_kb = start_msgs[-1].reply_markup_raw if start_msgs else None
        assert_step(
            "/start reply includes a reply_keyboard (not inline)",
            isinstance(start_kb, dict) and "keyboard" in start_kb,
            detail=str(start_kb)[:200],
        )
        if isinstance(start_kb, dict) and "keyboard" in start_kb:
            rows = start_kb["keyboard"]
            flat = [btn["text"] for row in rows for btn in row]
            assert_step(
                "reply keyboard contains 4 buttons (Wallets / Positions / Help / Lang)",
                len(flat) == 4,
                detail=str(flat),
            )
            assert_step(
                "reply keyboard contains a 'Wallets' button label",
                any("\U0001f433" in b for b in flat),
                detail=str(flat),
            )
            assert_step(
                "reply keyboard contains a 'Positions' button label",
                any("\U0001f4ca" in b for b in flat),
                detail=str(flat),
            )
            assert_step(
                "reply keyboard is persistent + resized",
                start_kb.get("is_persistent") is True
                and start_kb.get("resize_keyboard") is True,
            )

        # ---- Step 11: tapping the 'Wallets' reply button shows /list ------
        print("\n--- Step 11: reply-keyboard text triggers /list flow ----------------")
        await feed_and_wait(
            dp, bot, _make_command_update(f"/add {WHALE_ADDRESS} whale")
        )  # add one back
        box.reset()
        await feed_and_wait(
            dp,
            bot,
            _make_command_update("\U0001f433 \u041a\u043e\u0448\u0435\u043b\u044c\u043a\u0438"),
        )
        kb_msgs = box.messages_to(TEST_CHAT_ID)
        kb_reply_markup = kb_msgs[-1].reply_markup if kb_msgs else None
        assert_step(
            "tapping 'Wallets' text produces a wallet-list inline keyboard",
            kb_reply_markup is not None
            and any(
                btn.callback_data and btn.callback_data.startswith("w:open:")
                for row in kb_reply_markup.inline_keyboard
                for btn in row
            ),
            detail=(kb_msgs[-1].text[:200] if kb_msgs else "<no reply>"),
        )

        # ---- Step 12: /positions menu + pos:all callback ------------------
        print("\n--- Step 12: /positions opens menu, pos:all fetches all wallets ----")
        box.reset()
        await feed_and_wait(dp, bot, _make_command_update("/positions"))
        pos_msgs = box.messages_to(TEST_CHAT_ID)
        pos_kb = pos_msgs[-1].reply_markup if pos_msgs else None
        assert_step(
            "/positions shows an inline 'All / Pick one' menu",
            pos_kb is not None
            and sum(len(row) for row in pos_kb.inline_keyboard) == 2,
            detail=str(pos_kb)[:200] if pos_kb else "<none>",
        )
        if pos_kb is not None:
            callback_data = {
                btn.callback_data for row in pos_kb.inline_keyboard for btn in row
            }
            assert_step(
                "menu has pos:all and pos:pick callback data",
                {"pos:all", "pos:pick"}.issubset(callback_data),
                detail=str(callback_data),
            )

        box.reset()
        await feed_and_wait(dp, bot, _make_callback_update("pos:all", message_id=99998))
        await asyncio.sleep(3.0)  # let the real HL fetch land
        all_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "pos:all callback produces at least 2 messages (fetching + result)",
            len(all_msgs) >= 2,
            detail=f"got {len(all_msgs)} replies",
        )
        assert_step(
            "pos:all final reply renders a real snapshot",
            any("Size:" in (m.text or "") for m in all_msgs),
            detail=(all_msgs[-1].text[:200] if all_msgs else ""),
        )

        # ---- Step 13: /positions -> pos:pick -> pick a wallet -------------
        print("\n--- Step 13: pos:pick + tap wallet picker ---------------------------")
        box.reset()
        await feed_and_wait(dp, bot, _make_callback_update("pos:pick", message_id=99997))
        pick_msgs = box.messages_to(TEST_CHAT_ID)
        pick_kb = pick_msgs[-1].reply_markup if pick_msgs else None
        assert_step(
            "pos:pick shows a wallet picker keyboard",
            pick_kb is not None
            and sum(len(row) for row in pick_kb.inline_keyboard) >= 1,
            detail=str(pick_kb)[:200] if pick_kb else "<none>",
        )
        box.reset()
        await feed_and_wait(
            dp,
            bot,
            _make_callback_update(f"pos:show:{WHALE_ADDRESS}", message_id=99996),
        )
        await asyncio.sleep(3.0)
        show_msgs = box.messages_to(TEST_CHAT_ID)
        assert_step(
            "pos:show:<addr> produces a snapshot reply",
            any("Size:" in (m.text or "") for m in show_msgs),
            detail=(show_msgs[-1].text[:200] if show_msgs else ""),
        )

        # ---- Final summary -------------------------------------------------
        print("\n" + "=" * 78)
        passed = sum(1 for r in RESULTS if r.passed)
        failed = sum(1 for r in RESULTS if not r.passed)
        print(f"Summary: {passed} passed, {failed} failed (total {len(RESULTS)})")
        if failed:
            print("\nFailures:")
            for r in RESULTS:
                if not r.passed:
                    print(f"  - {r.name}  | detail: {r.detail}")
        print("=" * 78)
        return 0 if failed == 0 else 1

    finally:
        watcher.stop()
        try:
            await asyncio.wait_for(watcher_task, timeout=5)
        except (asyncio.TimeoutError, Exception):
            watcher_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

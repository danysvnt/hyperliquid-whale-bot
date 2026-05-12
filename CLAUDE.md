# CLAUDE.md — контекст проекта для Claude Code

> Этот файл Claude Code читает автоматически при старте сессии в этом репо. Он восстанавливает «память» о проекте, чтобы не приходилось каждый раз пересказывать стек и правила.

---

## Кто я и что мы делаем

Меня зовут **Даня**, я вайбкодер. Этот проект — **Telegram-бот для трекинга позиций китов на Hyperliquid** (perp DEX, без CEX-аккаунтов).

Когда бот видит крупное изменение позиции у отслеживаемого кошелька — присылает уведомление с эмодзи, цветным PnL и копируемым адресом.

---

## Стек (не подменяй на «что попроще»)

- **Python 3.12+** (mypy strict)
- **uv** — менеджер пакетов. **НЕ pip, НЕ poetry.** Источник истины: `pyproject.toml` + `uv.lock`.
- **aiogram v3** — Telegram (Bot, Dispatcher, FSM, inline + reply клавиатуры)
- **aiosqlite** — БД (SQLite файл в `data/whale_bot.db`)
- **hyperliquid-python-sdk** — REST к Hyperliquid (синхронный `Info` client, обёрнут в `asyncio.to_thread`)
- **ruff** — линтер, **pytest** — тесты

---

## Команды (запуск, тесты, lint)

| Что | Команда |
|---|---|
| Запустить бота | `uv run python -m hyperliquid_whale_bot` |
| Установить/обновить зависимости | `uv sync` |
| Юнит-тесты (быстрые, ~2с) | `uv run pytest` |
| E2E через in-process Dispatcher (медленнее, ходит в Hyperliquid) | `uv run python scripts/inproc_test.py` |
| E2E проверка двойного порога | `uv run python scripts/threshold_test.py` |
| E2E устойчивости watcher'а | `uv run python scripts/watcher_resilience_test.py` |
| Lint | `uv run ruff check .` |
| Type check | `uv run mypy src/` |

**Перед каждым PR / коммитом «готово» прогоняй:** `uv run ruff check . && uv run mypy src/ && uv run pytest` — все три должны быть зелёными.

---

## Структура проекта

```
src/hyperliquid_whale_bot/
  __main__.py          — entry point (python -m hyperliquid_whale_bot)
  bot/
    main.py            — bootstrap aiogram bot + watcher
    handlers.py        — все хэндлеры команд и колбэков
    keyboards.py       — reply + inline клавиатуры
    formatters.py      — рендер позиций, событий, PnL emoji
    i18n.py            — RU/EN/UK строки
  hl/
    client.py          — обёртка над hyperliquid-python-sdk
    watcher.py         — фоновый polling-цикл (10с)
  storage/
    db.py              — SQLite + миграции (3 таблицы)
  service.py           — оркестратор (склеивает watcher + bot + db)
  diff.py              — diff позиций (вычисляет события)
  models.py            — Pydantic-модели событий/позиций
  config.py            — Settings из .env
tests/                 — 36 юнит-тестов
scripts/               — 3 e2e-скрипта (live Hyperliquid)
data/whale_bot.db      — runtime DB (gitignored)
.env                   — runtime config (gitignored, см. .env.example)
handover.md            — полный backstory фазы 1 (если приложен к чату)
```

---

## Ветки

- `main` — пустой scaffold. **Не пушить туда напрямую.**
- `devin/1778432484-initial-bot` — фаза 1 MVP (открытый PR #1, ещё не замёрджен)
- `feat/twap-stream` — фаза 2 (TWAP + лимитные ордера, в работе)

Новые фичи — всегда в новой ветке от текущей рабочей. Не лить разные фичи в один PR.

---

## Правила работы (важно, не нарушай)

1. **Не ломай существующие тесты.** Все 36 юнит + 3 e2e-скрипта должны оставаться зелёными.
2. **Миграции БД — только аддитивные.** Никогда не drop колонок. Паттерн: `_column_exists()` через `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`.
3. **Адреса (`0x...`) всегда оборачивай в `<code>...</code>`** в Telegram-сообщениях — для tap-to-copy.
4. **User-supplied лейблы кошельков всегда HTML-escape** перед рендером (защита от `<script>`-в-имени). Адреса не эскейпятся — они валидированы regex'ом.
5. **i18n обязательна:** каждая новая user-facing строка → RU + EN + UK.
6. **Palette для PnL:** 🟢 плюс, 🔴 минус, ⚪ ноль.
7. **Watcher использует `asyncio.gather(..., return_exceptions=True)`** — падение одного кошелька в тике не должно ронять опрос соседей.
8. **Polling = 10с**, alert threshold = **5% И $5000 одновременно** (оба условия, не «или»).
9. **Не править `.env`** — это секреты. Только `.env.example`.
10. **Не править `uv.lock` руками** — он генерится через `uv sync` / `uv lock`.

---

## Стиль общения

- Отвечай **по-русски** по умолчанию (если я задал вопрос на русском).
- **Терсе и по делу.** Минимум воды, максимум сигнала.
- **Перед большой работой — план + вопрос «погнали?»**, не прыгай сразу в код.
- Для **багрепортов**: спроси у меня точные шаги воспроизведения + последние ~20 строк логов + скриншот, прежде чем гадать.
- Для **UI-изменений**: опиши mockup словами или текстом, прежде чем кодить.

---

## Если что-то непонятно

1. Прочитай `handover.md` (приложен к чату, или попроси меня прислать его) — там полный backstory фазы 1 и решения по архитектуре.
2. Посмотри последние commit messages — там объяснения решений.
3. `.claude/settings.json` определяет какие shell-команды можно запускать без вопросов — уважай deny-list (никаких `rm -rf`, `sudo`, force push, push в main).
4. Если всё равно непонятно — **спроси меня**, а не угадывай.

---

## Чего я НЕ хочу

- Большие рефакторинги без моего согласия.
- Замены `uv` на pip / poetry / requirements.txt.
- Замены `aiogram v3` на `python-telegram-bot` или что-то другое.
- Замены SQLite на Postgres «для масштабируемости» (пока не дам команду).
- Закомментированный мёртвый код «на всякий».
- Файлы `*.test.ts`-style в проекте без тестфреймворка (используем pytest).

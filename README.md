# Hyperliquid Whale Bot

Telegram-бот, который **отслеживает позиции произвольных кошельков на Hyperliquid в реальном времени** и присылает уведомления, когда «киты» открывают, закрывают или существенно меняют свои перп-позиции.

> Проект написан как обучающий: код хорошо разнесён по модулям, бизнес-логика покрыта unit-тестами, конфигурация ведётся через `.env`. Идеально для тех, кто только начинает программировать.

## Что умеет

### Команды

- `/add 0xADDRESS [метка]` — добавить кошелёк в слежение (по умолчанию метка генерится из адреса).
- `/remove <адрес или метка>` — убрать.
- `/list` — все отслеживаемые кошельки.
- `/status <адрес или метка>` — текущий снимок позиций конкретного кошелька.
- `/positions` — меню «📋 Все кошельки» / «🎯 Один кошелёк» (вторая опция показывает inline-список твоих кошельков).
- `/lang` — переключить язык интерфейса (русский / English / українська).
- `/help` — справка.

### Reply-клавиатура

После `/start` под полем ввода появляются 4 постоянные кнопки-ярлыка:

| 🐳 Кошельки | 📊 Позиции |
|------------|-----------|
| ❔ Помощь  | 🌐 Язык   |

Они дублируют `/list`, `/positions`, `/help`, `/lang` соответственно — чтобы не печатать команды руками.

### Уведомления

Когда у любого из отслеживаемых кошельков:
- **открывается** новая позиция → уведомление `🟢 Открыл LONG/SHORT BTC`
- **закрывается** позиция → уведомление `⚪ Закрыл …`
- **значительно изменяется размер** → уведомление `➕ Увеличил…` / `➖ Уменьшил…`
  - срабатывает только если изменение одновременно превышает `ALERT_PCT_THRESHOLD` (по умолчанию 5%) **и** `ALERT_USD_THRESHOLD` (по умолчанию $5000)
- **меняется плечо** → уведомление `⚙️ Сменил плечо`
- **переворачивается направление** (long → short без обнуления) → `🔄 Перевернул позицию`

К каждому уведомлению прикрепляются inline-кнопки: открыть кошелёк в [Hypurrscan](https://hypurrscan.io), [Hyperdash](https://hyperdash.info), официальном explorer'е [Hyperliquid](https://app.hyperliquid.xyz) или [Coinmarketman](https://app.coinmarketman.com/) (кнопка ведёт на главную app — у CMM нет публичных страниц на отдельный адрес, навигация дальше внутри их UI).

## Архитектура

```
Hyperliquid REST  ──►  HyperliquidClient (asyncio + SDK)
                         │
                         ▼
                    Watcher loop  ──►  diff engine  ──►  asyncio.Queue
                         │                                   │
                         └──► position_snapshots (SQLite)    │
                                                             ▼
                                                    Notifier ──► aiogram bot ──► Telegram
                                                             ▲
                                                    /add /remove /list /status /lang
```

- **Polling:** в MVP опрос идёт через REST `info.user_state(addr)` с настраиваемым интервалом (по умолчанию 10 секунд). Hyperliquid REST позволяет ~600 запросов/мин с одного IP с весом 2 за запрос — этого хватает на десятки уникальных кошельков.
- **Дедупликация:** если 5 пользователей добавили один и тот же кошелёк, бот опрашивает его **один раз** и веером раздаёт уведомления подписчикам.
- **WebSocket:** в фазе 2 планируется подписка на `webData2` для мгновенных уведомлений (≤10 уникальных кошельков из-за лимита Hyperliquid).

### Структура проекта

```
src/hyperliquid_whale_bot/
├── __main__.py        # точка входа: python -m hyperliquid_whale_bot
├── config.py          # настройки из env / .env (pydantic-settings)
├── models.py          # Position, PositionEvent, WalletSnapshot, EventKind
├── diff.py            # чистая функция: (старый, новый) → [события]  ← покрыто тестами
├── service.py         # склейка watcher + bot + notifier под одним asyncio.TaskGroup
├── logging_setup.py   # конфигурация structlog
├── hl/
│   ├── client.py      # async-обёртка над hyperliquid-python-sdk (Info)
│   └── watcher.py     # цикл опроса позиций
├── storage/
│   ├── db.py          # SQLite-схема и менеджер соединений
│   └── repo.py        # CRUD: пользователи, кошельки, снапшоты
└── bot/
    ├── handlers.py    # обработчики команд (aiogram v3)
    ├── formatters.py  # форматирование сообщений (HTML)
    ├── keyboards.py   # inline-клавиатуры
    ├── i18n.py        # словари переводов RU/EN/UK
    └── main.py        # сборка Bot + Dispatcher

tests/
├── test_diff.py       # 14 тестов на diff-движок
└── test_models.py     # 4 теста на парсинг ответа Hyperliquid
```

## Быстрый старт (локально)

### 1. Клонировать репозиторий

```bash
git clone https://github.com/danysvnt/hyperliquid-whale-bot.git
cd hyperliquid-whale-bot
```

### 2. Установить Python 3.11+ и [uv](https://github.com/astral-sh/uv)

```bash
# uv — быстрый менеджер зависимостей для Python (рекомендуется проектом).
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Установить зависимости

```bash
uv sync --extra dev
```

### 4. Получить токен бота у @BotFather

1. В Telegram открой [@BotFather](https://t.me/BotFather).
2. Отправь `/newbot`, дай имя и username.
3. Скопируй токен.

### 5. Скопировать `.env.example` → `.env` и вставить токен

```bash
cp .env.example .env
# Открой .env и впиши TELEGRAM_BOT_TOKEN=<твой_токен>
```

### 6. Запустить

```bash
uv run python -m hyperliquid_whale_bot
```

Бот сразу начнёт `long-polling` Telegram. Открой его в Telegram и отправь `/start`.

## Конфигурация (`.env`)

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `TELEGRAM_BOT_TOKEN` | — | Обязательно. Токен от @BotFather. |
| `HL_NETWORK` | `mainnet` | `mainnet` (реальные позиции) или `testnet` (для разработки). |
| `WATCHER_POLL_INTERVAL_SECONDS` | `10` | Как часто опрашивать кошельки. Минимум 5. |
| `ALERT_PCT_THRESHOLD` | `5.0` | Минимальное изменение размера позиции в процентах для уведомления. |
| `ALERT_USD_THRESHOLD` | `5000` | Минимальное изменение в USD-нотионале для уведомления. |
| `MAX_WALLETS_PER_USER` | `10` | Сколько кошельков может отслеживать один Telegram-юзер. |
| `WHITELIST_CHAT_IDS` | пусто (публичный режим) | Если задан — только эти chat_id могут пользоваться ботом. CSV: `123,456`. |
| `DATABASE_PATH` | `data/whale_bot.db` | Путь к файлу SQLite. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` или `ERROR`. |

## Тесты, lint, типы

```bash
uv run pytest        # 18 тестов
uv run ruff check .  # линтер
uv run ruff format . # форматтер
uv run mypy src      # статическая типизация (strict)
```

## Деплой 24/7

Чтобы бот работал, даже когда твой компьютер выключен, его нужно поднять на сервере. Самые простые варианты:

### Railway (проще всего)

1. Зарегистрируйся на [railway.app](https://railway.app) (есть бесплатный тир).
2. Connect GitHub → выбери этот репозиторий.
3. В Variables добавь `TELEGRAM_BOT_TOKEN` (и любые другие переопределения из таблицы выше).
4. Railway автоматически использует `Dockerfile` из репо.

### Fly.io

1. Установи [flyctl](https://fly.io/docs/flyctl/install/).
2. `fly launch` (выбери Dockerfile, регион, бесплатный план).
3. `fly secrets set TELEGRAM_BOT_TOKEN=...`
4. `fly deploy`.

### Любой VPS (Hetzner, DigitalOcean, …)

```bash
# на сервере
git clone https://github.com/danysvnt/hyperliquid-whale-bot.git
cd hyperliquid-whale-bot
cp .env.example .env && nano .env   # вписать токен
docker build -t whale-bot .
docker run -d --restart=always --name whale-bot --env-file .env -v $(pwd)/data:/app/data whale-bot
```

## Лимиты и осторожность

- Hyperliquid REST API: 1200 weight/мин с одного IP. `clearinghouseState` (это и есть наш запрос) весит 2 → ~600 запросов/мин. При интервале 10 сек выдержим до **~100 уникальных кошельков** (если все юзеры разные кошельки).
- Hyperliquid WebSocket: максимум **10 уникальных user-specific подписок с одного IP** — это серьёзное ограничение для будущей фазы 2.
- Если нагрузка растёт — увеличивай `WATCHER_POLL_INTERVAL_SECONDS` или используй несколько IP / прокси.

## Дорожная карта

- [x] Polling по REST + diff-движок + multi-user
- [x] i18n RU / EN / UK
- [ ] Фаза 2: WebSocket `webData2` для мгновенных уведомлений (≤10 кошельков)
- [ ] Уведомления о начале / отмене TWAP-ордеров (через `userTwapSliceFills` + `historicalOrders`)
- [ ] Webhook-режим для Telegram (вместо long-polling) — для production
- [ ] Прометей-метрики и health-check

## Лицензия

MIT.

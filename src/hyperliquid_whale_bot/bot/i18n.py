"""Tiny i18n module — dict-based translations for RU / EN / UK.

Why a custom mini-implementation instead of gettext/Babel:
- We only need a small set of strings; no plural forms; no extraction tooling needed.
- Keeps the project dependency-light and easy to read for a beginner.
- Adding a new language = add a column to `_TRANSLATIONS`.
"""

from __future__ import annotations

from typing import Final

SUPPORTED_LANGS: Final[tuple[str, ...]] = ("ru", "en", "uk")
DEFAULT_LANG: Final[str] = "ru"

# Translation table. Keys are short, stable identifiers; values are dicts keyed by language.
_TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    # --- Welcome / help ---
    "welcome.title": {
        "ru": "👋 Привет! Я слежу за позициями кошельков на Hyperliquid и присылаю уведомления.",
        "en": "👋 Hi! I track Hyperliquid wallet positions and notify you when they change.",
        "uk": "👋 Привіт! Я стежу за позиціями гаманців на Hyperliquid і надсилаю сповіщення.",
    },
    "welcome.help_hint": {
        "ru": "Используй /help, чтобы увидеть список команд.",
        "en": "Use /help to see all commands.",
        "uk": "Використовуй /help, щоб побачити список команд.",
    },
    "help.title": {
        "ru": "<b>Команды:</b>",
        "en": "<b>Commands:</b>",
        "uk": "<b>Команди:</b>",
    },
    "help.add": {
        "ru": "<code>/add &lt;0x...адрес&gt; [метка]</code> — добавить кошелёк в слежение",
        "en": "<code>/add &lt;0x...address&gt; [label]</code> — start tracking a wallet",
        "uk": "<code>/add &lt;0x...адреса&gt; [мітка]</code> — додати гаманець у відстеження",
    },
    "help.remove": {
        "ru": "<code>/remove &lt;адрес или метка&gt;</code> — снять с мониторинга",
        "en": "<code>/remove &lt;address or label&gt;</code> — stop tracking",
        "uk": "<code>/remove &lt;адреса або мітка&gt;</code> — припинити стеження",
    },
    "help.list": {
        "ru": "/list — показать все отслеживаемые кошельки",
        "en": "/list — show all tracked wallets",
        "uk": "/list — показати всі відстежувані гаманці",
    },
    "help.status": {
        "ru": "<code>/status &lt;адрес или метка&gt;</code> — текущие открытые позиции",
        "en": "<code>/status &lt;address or label&gt;</code> — current open positions",
        "uk": "<code>/status &lt;адреса або мітка&gt;</code> — поточні відкриті позиції",
    },
    "help.lang": {
        "ru": "/lang — сменить язык интерфейса (ru / en / uk)",
        "en": "/lang — change interface language (ru / en / uk)",
        "uk": "/lang — змінити мову інтерфейсу (ru / en / uk)",
    },
    # --- /add ---
    "add.usage": {
        "ru": "Использование: <code>/add 0xADDRESS [метка]</code>",
        "en": "Usage: <code>/add 0xADDRESS [label]</code>",
        "uk": "Використання: <code>/add 0xADDRESS [мітка]</code>",
    },
    "add.invalid_address": {
        "ru": "❌ Неверный адрес. Должен начинаться с <code>0x</code> и состоять из 42 символов.",
        "en": "❌ Invalid address. Must start with <code>0x</code> and be 42 chars long.",
        "uk": "❌ Невірна адреса. Має починатися з <code>0x</code> і мати 42 символи.",
    },
    "add.limit_reached": {
        "ru": "❌ Достигнут лимит — ты уже отслеживаешь {limit} кошельков. Удали один через /remove.",
        "en": "❌ Limit reached — you're already tracking {limit} wallets. Remove one with /remove.",
        "uk": "❌ Досягнуто ліміт — ти вже стежиш за {limit} гаманцями. Видали один через /remove.",
    },
    "add.already_tracked": {
        "ru": "ℹ️ Этот кошелёк уже в твоём списке как «{label}».",
        "en": "ℹ️ This wallet is already in your list as “{label}”.",
        "uk": "ℹ️ Цей гаманець уже в твоєму списку як «{label}».",
    },
    "add.success": {
        "ru": "✅ Добавил <b>{label}</b>\n<code>{address}</code>\n\nПервое уведомление придёт при следующем изменении позиции.",
        "en": "✅ Added <b>{label}</b>\n<code>{address}</code>\n\nFirst notification will arrive on the next position change.",
        "uk": "✅ Додано <b>{label}</b>\n<code>{address}</code>\n\nПерше сповіщення прийде при наступній зміні позиції.",
    },
    # --- /remove ---
    "remove.usage": {
        "ru": "Использование: <code>/remove &lt;адрес или метка&gt;</code>",
        "en": "Usage: <code>/remove &lt;address or label&gt;</code>",
        "uk": "Використання: <code>/remove &lt;адреса або мітка&gt;</code>",
    },
    "remove.success": {
        "ru": "✅ Удалил из списка.",
        "en": "✅ Removed from your list.",
        "uk": "✅ Видалено зі списку.",
    },
    "remove.not_found": {
        "ru": "❌ Не нашёл такого кошелька в твоём списке.",
        "en": "❌ Couldn't find that wallet in your list.",
        "uk": "❌ Не знайшов такого гаманця у твоєму списку.",
    },
    # --- /list ---
    "list.empty": {
        "ru": "Список пуст. Добавь кошелёк через /add.",
        "en": "List is empty. Add a wallet with /add.",
        "uk": "Список порожній. Додай гаманець через /add.",
    },
    "list.title": {
        "ru": "<b>Отслеживаемые кошельки ({count}/{limit}):</b>",
        "en": "<b>Tracked wallets ({count}/{limit}):</b>",
        "uk": "<b>Відстежувані гаманці ({count}/{limit}):</b>",
    },
    # --- /status ---
    "status.usage": {
        "ru": "Использование: <code>/status &lt;адрес или метка&gt;</code>",
        "en": "Usage: <code>/status &lt;address or label&gt;</code>",
        "uk": "Використання: <code>/status &lt;адреса або мітка&gt;</code>",
    },
    "status.no_positions": {
        "ru": "ℹ️ У <b>{label}</b> сейчас нет открытых перп-позиций.",
        "en": "ℹ️ <b>{label}</b> has no open perp positions right now.",
        "uk": "ℹ️ У <b>{label}</b> зараз немає відкритих перп-позицій.",
    },
    "status.title": {
        "ru": "📊 <b>{label}</b> — открытые позиции:",
        "en": "📊 <b>{label}</b> — open positions:",
        "uk": "📊 <b>{label}</b> — відкриті позиції:",
    },
    "status.fetching": {
        "ru": "⏳ Запрашиваю данные…",
        "en": "⏳ Fetching data…",
        "uk": "⏳ Запитую дані…",
    },
    "status.error": {
        "ru": "❌ Не удалось получить данные. Попробуй ещё раз.",
        "en": "❌ Couldn't fetch data. Try again.",
        "uk": "❌ Не вдалося отримати дані. Спробуй ще раз.",
    },
    # --- /lang ---
    "lang.choose": {
        "ru": "Выбери язык:",
        "en": "Choose a language:",
        "uk": "Обери мову:",
    },
    "lang.changed": {
        "ru": "✅ Язык установлен: русский.",
        "en": "✅ Language set: English.",
        "uk": "✅ Мову встановлено: українська.",
    },
    # --- access control ---
    "access.denied": {
        "ru": "🚫 У тебя нет доступа к этому боту.",
        "en": "🚫 You don't have access to this bot.",
        "uk": "🚫 У тебе немає доступу до цього бота.",
    },
    # --- event labels ---
    "event.open": {"ru": "🟢 Открыл", "en": "🟢 Opened", "uk": "🟢 Відкрив"},
    "event.close": {"ru": "⚪ Закрыл", "en": "⚪ Closed", "uk": "⚪ Закрив"},
    "event.increase": {"ru": "➕ Увеличил", "en": "➕ Increased", "uk": "➕ Збільшив"},
    "event.decrease": {"ru": "➖ Уменьшил", "en": "➖ Decreased", "uk": "➖ Зменшив"},
    "event.leverage_change": {
        "ru": "⚙️ Сменил плечо",
        "en": "⚙️ Changed leverage",
        "uk": "⚙️ Змінив плече",
    },
    "event.side_flip": {
        "ru": "🔄 Перевернул позицию",
        "en": "🔄 Flipped side",
        "uk": "🔄 Перевернув позицію",
    },
    # --- field labels in event messages ---
    "field.long": {"ru": "🟩 LONG", "en": "🟩 LONG", "uk": "🟩 LONG"},
    "field.short": {"ru": "🟥 SHORT", "en": "🟥 SHORT", "uk": "🟥 SHORT"},
    "field.size": {"ru": "Размер", "en": "Size", "uk": "Розмір"},
    "field.notional": {"ru": "Ноционал", "en": "Notional", "uk": "Ноціонал"},
    "field.entry": {"ru": "Цена входа", "en": "Entry", "uk": "Ціна входу"},
    "field.leverage": {"ru": "Плечо", "en": "Leverage", "uk": "Плече"},
    "field.delta": {"ru": "Изменение", "en": "Change", "uk": "Зміна"},
    "field.pnl": {"ru": "PnL", "en": "PnL", "uk": "PnL"},
    "field.from_to": {"ru": "{a} → {b}", "en": "{a} → {b}", "uk": "{a} → {b}"},
    # --- explorer button labels ---
    "btn.hypurrscan": {"ru": "Hypurrscan", "en": "Hypurrscan", "uk": "Hypurrscan"},
    "btn.hyperdash": {"ru": "Hyperdash", "en": "Hyperdash", "uk": "Hyperdash"},
    "btn.hyperliquid": {"ru": "Hyperliquid", "en": "Hyperliquid", "uk": "Hyperliquid"},
}


def t(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
    """Translate `key` to `lang`, falling back to default lang and finally to the key.

    Supports {placeholder} substitution via kwargs.
    """
    table = _TRANSLATIONS.get(key)
    if table is None:
        return key
    template = table.get(lang) or table.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template

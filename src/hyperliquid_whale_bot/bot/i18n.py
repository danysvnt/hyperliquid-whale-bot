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


def button_texts(key: str) -> set[str]:
    """Return all localized variants of a translation key.

    Used to match incoming reply-keyboard taps against any of the supported
    languages (the user could be on RU and tap the persistent 'Wallets' button
    rendered in RU; another user on EN would see/tap the EN label).
    """
    return {v for v in _TRANSLATIONS.get(key, {}).values()}


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
        "ru": "<code>/add &lt;0x...адрес&gt;</code> — добавить кошелёк (имя спросит вторым шагом)",
        "en": "<code>/add &lt;0x...address&gt;</code> — add a wallet (label is asked next step)",
        "uk": "<code>/add &lt;0x...адреса&gt;</code> — додати гаманець (ім'я буде запитане наступним кроком)",
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
    "help.positions": {
        "ru": "/positions — позиции всех или одного кошелька (кнопки)",
        "en": "/positions — positions for all or one tracked wallet (buttons)",
        "uk": "/positions — позиції всіх або одного гаманця (кнопки)",
    },
    "help.lang": {
        "ru": "/lang — сменить язык интерфейса (ru / en / uk)",
        "en": "/lang — change interface language (ru / en / uk)",
        "uk": "/lang — змінити мову інтерфейсу (ru / en / uk)",
    },
    # --- /add ---
    "add.usage": {
        "ru": "Использование: <code>/add 0xADDRESS</code>\nМожно сразу с меткой: <code>/add 0xADDRESS метка</code>",
        "en": "Usage: <code>/add 0xADDRESS</code>\nOr inline with a label: <code>/add 0xADDRESS label</code>",
        "uk": "Використання: <code>/add 0xADDRESS</code>\nАбо відразу з міткою: <code>/add 0xADDRESS мітка</code>",
    },
    "add.ask_label": {
        "ru": "Введи имя для этого кошелька (или нажми «Пропустить» — назову по адресу).",
        "en": "Send a name for this wallet (or tap “Skip” to use a short address).",
        "uk": "Введи ім'я для цього гаманця (або натисни «Пропустити» — назову по адресі).",
    },
    "add.cancelled": {
        "ru": "❌ Добавление отменено.",
        "en": "❌ Add cancelled.",
        "uk": "❌ Додавання скасовано.",
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
    "add.ask_address": {
        "ru": "Пришли адрес кошелька (<code>0x…</code>, 42 символа).",
        "en": "Send the wallet address (<code>0x…</code>, 42 chars).",
        "uk": "Надішли адресу гаманця (<code>0x…</code>, 42 символи).",
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
    "field.amount": {"ru": "Сумма", "en": "Amount", "uk": "Сума"},
    "field.entry": {"ru": "Цена входа", "en": "Entry", "uk": "Ціна входу"},
    "field.leverage": {"ru": "Плечо", "en": "Leverage", "uk": "Плече"},
    "field.delta": {"ru": "Изменение", "en": "Change", "uk": "Зміна"},
    "field.pnl": {"ru": "PnL", "en": "PnL", "uk": "PnL"},
    "field.from_to": {"ru": "{a} → {b}", "en": "{a} → {b}", "uk": "{a} → {b}"},
    # --- explorer button labels ---
    "btn.hypurrscan": {"ru": "Hypurrscan", "en": "Hypurrscan", "uk": "Hypurrscan"},
    "btn.hyperdash": {"ru": "Hyperdash", "en": "Hyperdash", "uk": "Hyperdash"},
    "btn.hyperliquid": {"ru": "Hyperliquid", "en": "Hyperliquid", "uk": "Hyperliquid"},
    "btn.cmm": {"ru": "Coinmarketman", "en": "Coinmarketman", "uk": "Coinmarketman"},
    # --- main reply keyboard (persistent buttons under input field) ---
    "kb.wallets": {"ru": "🐳 Кошельки", "en": "🐳 Wallets", "uk": "🐳 Гаманці"},
    "kb.positions": {"ru": "📊 Позиции", "en": "📊 Positions", "uk": "📊 Позиції"},
    "kb.help": {"ru": "❔ Помощь", "en": "❔ Help", "uk": "❔ Допомога"},
    "kb.lang": {"ru": "🌐 Язык", "en": "🌐 Language", "uk": "🌐 Мова"},
    # --- positions menu (after tapping the 'Positions' button) ---
    "positions.choose": {
        "ru": "Что показать?",
        "en": "What to show?",
        "uk": "Що показати?",
    },
    "positions.btn_all": {
        "ru": "📋 Все кошельки",
        "en": "📋 All wallets",
        "uk": "📋 Всі гаманці",
    },
    "positions.btn_pick": {
        "ru": "🎯 Один кошелёк",
        "en": "🎯 Pick one",
        "uk": "🎯 Один гаманець",
    },
    "positions.pick_prompt": {
        "ru": "Выбери кошелёк:",
        "en": "Pick a wallet:",
        "uk": "Обери гаманець:",
    },
    "positions.empty": {
        "ru": "Список кошельков пуст — добавь хотя бы один через /add.",
        "en": "You don't have any wallets yet — add one with /add first.",
        "uk": "Список гаманців порожній — додай хоча б один через /add.",
    },
    "positions.not_found": {
        "ru": "Этот кошелёк больше не в твоём списке.",
        "en": "That wallet is no longer in your list.",
        "uk": "Цього гаманця більше немає в твоєму списку.",
    },
    # --- wallet list (🐳 Кошельки) ---
    "wlist.title": {
        "ru": "🐳 <b>Твои кошельки</b> · {count}/{limit}\n<i>Тапни по кошельку, чтобы настроить.</i>",
        "en": "🐳 <b>Your wallets</b> · {count}/{limit}\n<i>Tap a wallet to configure it.</i>",
        "uk": "🐳 <b>Твої гаманці</b> · {count}/{limit}\n<i>Тапни на гаманець, щоб налаштувати.</i>",
    },
    "wlist.empty": {
        "ru": "🐳 Список пуст. Нажми «➕ Добавить» или отправь адрес через /add.",
        "en": "🐳 No wallets yet. Tap “➕ Add” or send an address via /add.",
        "uk": "🐳 Список порожній. Натисни «➕ Додати» або надішли адресу через /add.",
    },
    "wlist.add_btn": {
        "ru": "➕ Добавить кошелёк",
        "en": "➕ Add wallet",
        "uk": "➕ Додати гаманець",
    },
    # --- wallet settings (per-wallet screen) ---
    "wset.title": {
        "ru": "⚙️ <b>Настройки кошелька</b> · {label}\n<code>{address}</code>\n<i>Включите/выключите типы уведомлений:</i>",
        "en": "⚙️ <b>Wallet settings</b> · {label}\n<code>{address}</code>\n<i>Toggle notification types on/off:</i>",
        "uk": "⚙️ <b>Налаштування гаманця</b> · {label}\n<code>{address}</code>\n<i>Увімкни/вимкни типи сповіщень:</i>",
    },
    "wset.toggle.positions.on": {
        "ru": "Позиции: ✅ ВКЛ",
        "en": "Positions: ✅ ON",
        "uk": "Позиції: ✅ УВІМК.",
    },
    "wset.toggle.positions.off": {
        "ru": "Позиции: ⬜ ВЫКЛ",
        "en": "Positions: ⬜ OFF",
        "uk": "Позиції: ⬜ ВИМК.",
    },
    "wset.toggle.twap.on": {
        "ru": "TWAP-ордера: ✅ ВКЛ · скоро",
        "en": "TWAP orders: ✅ ON · soon",
        "uk": "TWAP-ордери: ✅ УВІМК. · скоро",
    },
    "wset.toggle.twap.off": {
        "ru": "TWAP-ордера: ⬜ ВЫКЛ · скоро",
        "en": "TWAP orders: ⬜ OFF · soon",
        "uk": "TWAP-ордери: ⬜ ВИМК. · скоро",
    },
    "wset.toggle.limit.on": {
        "ru": "Лимитные ордера: ✅ ВКЛ · скоро",
        "en": "Limit orders: ✅ ON · soon",
        "uk": "Лімітні ордери: ✅ УВІМК. · скоро",
    },
    "wset.toggle.limit.off": {
        "ru": "Лимитные ордера: ⬜ ВЫКЛ · скоро",
        "en": "Limit orders: ⬜ OFF · soon",
        "uk": "Лімітні ордери: ⬜ ВИМК. · скоро",
    },
    "wset.edit_name": {
        "ru": "✏️ Сменить имя",
        "en": "✏️ Edit name",
        "uk": "✏️ Змінити ім'я",
    },
    "wset.delete": {
        "ru": "🗑 Удалить кошелёк",
        "en": "🗑 Delete wallet",
        "uk": "🗑 Видалити гаманець",
    },
    "wset.back": {
        "ru": "◀ К списку кошельков",
        "en": "◀ Back to wallets",
        "uk": "◀ До списку гаманців",
    },
    "wset.deleted": {
        "ru": "✅ Кошелёк удалён.",
        "en": "✅ Wallet deleted.",
        "uk": "✅ Гаманець видалено.",
    },
    "wset.gone": {
        "ru": "Этот кошелёк больше не в твоём списке.",
        "en": "That wallet is no longer in your list.",
        "uk": "Цього гаманця більше немає в твоєму списку.",
    },
    # --- edit-name flow ---
    "edit.ask_new_label": {
        "ru": "Пришли новое имя для <b>{label}</b>\n<code>{address}</code>",
        "en": "Send a new name for <b>{label}</b>\n<code>{address}</code>",
        "uk": "Надішли нове ім'я для <b>{label}</b>\n<code>{address}</code>",
    },
    "edit.too_long": {
        "ru": "❌ Имя слишком длинное (макс {max} символов). Попробуй короче.",
        "en": "❌ Name is too long (max {max} chars). Try a shorter one.",
        "uk": "❌ Ім'я занадто довге (макс {max} символів). Спробуй коротше.",
    },
    "edit.empty": {
        "ru": "❌ Пустое имя. Пришли хотя бы один символ.",
        "en": "❌ Empty name. Send at least one character.",
        "uk": "❌ Порожнє ім'я. Надішли хоча один символ.",
    },
    "edit.cancelled": {
        "ru": "❌ Изменение имени отменено.",
        "en": "❌ Rename cancelled.",
        "uk": "❌ Зміну імені скасовано.",
    },
    "edit.success": {
        "ru": "✅ Новое имя: <b>{label}</b>",
        "en": "✅ Renamed to <b>{label}</b>",
        "uk": "✅ Нове ім'я: <b>{label}</b>",
    },
    "edit.skip": {
        "ru": "⏭ Пропустить",
        "en": "⏭ Skip",
        "uk": "⏭ Пропустити",
    },
    "common.cancel": {
        "ru": "✖ Отменить",
        "en": "✖ Cancel",
        "uk": "✖ Скасувати",
    },
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

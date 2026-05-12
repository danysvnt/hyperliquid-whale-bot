"""Format `PositionEvent`s and snapshots into Telegram-friendly HTML messages."""

from __future__ import annotations

from html import escape

from ..models import (
    EventKind,
    Position,
    PositionEvent,
    Side,
    TwapEvent,
    TwapEventKind,
    TwapState,
    WalletSnapshot,
)
from .i18n import t


def format_event(event: PositionEvent | TwapEvent, label: str, lang: str) -> str:
    """Render an event as an HTML-formatted Telegram message.

    Dispatches on event type: position events use the existing perp-position
    layout; TWAP events use a TWAP-specific layout. Both share the same
    address-on-its-own-line convention so users can copy-tap the address.
    """
    if isinstance(event, TwapEvent):
        return _format_twap_event(event, label, lang)
    header = _event_header(event, label, lang)
    address_line = f"<code>{event.address.lower()}</code>"
    body = _event_body(event, lang)
    return f"{header}\n{address_line}\n\n{body}"


def format_snapshot(snapshot: WalletSnapshot, label: str, lang: str) -> str:
    """Render the current open positions of a wallet (used by /status)."""
    address_line = f"<code>{snapshot.address.lower()}</code>"
    if not snapshot.positions:
        return f"{t('status.no_positions', lang, label=escape(label))}\n{address_line}"

    title = t("status.title", lang, label=escape(label))
    lines = [title, address_line]
    for pos in snapshot.positions:
        lines.append("")
        lines.append(_pos_block(pos, lang))
    return "\n".join(lines)


# Telegram message limit is 4096 chars; leave headroom for HTML overhead.
_TG_MSG_SOFT_LIMIT = 3900


def format_multi_snapshot(
    items: list[tuple[str, WalletSnapshot]], lang: str
) -> list[str]:
    """Render the open positions of multiple wallets into one or more messages.

    Returns a list of HTML strings; each fits within `_TG_MSG_SOFT_LIMIT`. The
    title is repeated on every chunk so a user who only sees the second message
    still gets context.
    """
    title = t("positions.summary_title", lang)
    chunks: list[str] = []
    current = [title]
    current_len = len(title)

    for label, snap in items:
        block = _wallet_block(label, snap, lang)
        # +2 for the blank-line separator we insert before each wallet block.
        if current_len + len(block) + 2 > _TG_MSG_SOFT_LIMIT and len(current) > 1:
            chunks.append("\n".join(current))
            current = [title, "", block]
            current_len = len(title) + 2 + len(block)
        else:
            current.append("")
            current.append(block)
            current_len += 2 + len(block)

    chunks.append("\n".join(current))
    return chunks


def _wallet_block(label: str, snap: WalletSnapshot, lang: str) -> str:
    header = f"🐳 <b>{escape(label)}</b>"
    address_line = f"<code>{snap.address.lower()}</code>"
    if not snap.positions:
        return "\n".join([header, address_line, t("positions.empty_wallet", lang)])
    lines = [header, address_line]
    for pos in snap.positions:
        lines.append("")
        lines.append(_pos_block(pos, lang))
    return "\n".join(lines)


# --- internal helpers ------------------------------------------------------


def _event_header(event: PositionEvent, label: str, lang: str) -> str:
    """First line of the message: action + side + coin + label."""
    action = t(f"event.{event.kind.value}", lang)
    side_label = _side_label(event.position.side, lang)
    coin = escape(event.position.coin)
    label_html = f"<b>{escape(label)}</b>"
    return f"{action} {side_label} <b>{coin}</b> · {label_html}"


def _event_body(event: PositionEvent, lang: str) -> str:
    """Body lines depend on event kind."""
    pos = event.position
    prev = event.previous

    if event.kind == EventKind.OPEN:
        return "\n".join(
            [
                _kv(t("field.size", lang), _fmt_size(pos.size, pos.coin)),
                _kv(t("field.amount", lang), _fmt_usd(pos.notional_usd)),
                _kv(t("field.entry", lang), _fmt_usd(pos.entry_price)),
                _kv(t("field.leverage", lang), _fmt_leverage(pos)),
            ]
        )

    if event.kind == EventKind.CLOSE and prev is not None:
        return "\n".join(
            [
                _kv(t("field.size", lang), _fmt_size(prev.size, prev.coin)),
                _kv(t("field.amount", lang), _fmt_usd(prev.notional_usd)),
                _kv(t("field.entry", lang), _fmt_usd(prev.entry_price)),
                _kv(t("field.pnl", lang), _fmt_pnl(prev.unrealized_pnl)),
            ]
        )

    if event.kind in (EventKind.INCREASE, EventKind.DECREASE) and prev is not None:
        delta_str = _fmt_signed_usd(event.notional_delta_usd)
        pct_str = f"{event.pct_change:+.1f}%"
        return "\n".join(
            [
                _kv(
                    t("field.size", lang),
                    t(
                        "field.from_to",
                        lang,
                        a=_fmt_size(prev.size, prev.coin),
                        b=_fmt_size(pos.size, pos.coin),
                    ),
                ),
                _kv(t("field.amount", lang), _fmt_usd(pos.notional_usd)),
                _kv(t("field.delta", lang), f"{delta_str} ({pct_str})"),
                _kv(t("field.leverage", lang), _fmt_leverage(pos)),
            ]
        )

    if event.kind == EventKind.LEVERAGE_CHANGE and prev is not None:
        return _kv(
            t("field.leverage", lang),
            t(
                "field.from_to",
                lang,
                a=_fmt_leverage(prev),
                b=_fmt_leverage(pos),
            ),
        )

    if event.kind == EventKind.SIDE_FLIP and prev is not None:
        return "\n".join(
            [
                _kv(
                    t("field.size", lang),
                    t(
                        "field.from_to",
                        lang,
                        a=f"{_side_label(prev.side, lang)} {_fmt_size(prev.size, prev.coin)}",
                        b=f"{_side_label(pos.side, lang)} {_fmt_size(pos.size, pos.coin)}",
                    ),
                ),
                _kv(t("field.amount", lang), _fmt_usd(pos.notional_usd)),
                _kv(t("field.leverage", lang), _fmt_leverage(pos)),
            ]
        )

    # Fallback (shouldn't happen).
    return _pos_block(pos, lang)


def _pos_block(pos: Position, lang: str) -> str:
    side_label = _side_label(pos.side, lang)
    return "\n".join(
        [
            f"<b>{escape(pos.coin)}</b> · {side_label}",
            _kv(t("field.size", lang), _fmt_size(pos.size, pos.coin)),
            _kv(t("field.amount", lang), _fmt_usd(pos.notional_usd)),
            _kv(t("field.entry", lang), _fmt_usd(pos.entry_price)),
            _kv(t("field.leverage", lang), _fmt_leverage(pos)),
            _kv(t("field.pnl", lang), _fmt_pnl(pos.unrealized_pnl)),
        ]
    )


def _kv(key: str, value: str) -> str:
    return f"<b>{key}:</b> {value}"


def _side_label(side: Side, lang: str) -> str:
    return t("field.long" if side == Side.LONG else "field.short", lang)


def _fmt_leverage(pos: Position) -> str:
    return f"{pos.leverage:g}x ({pos.leverage_type})"


def _fmt_size(amount: float, coin: str) -> str:
    coin_html = escape(coin)
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M {coin_html}"
    if amount >= 1_000:
        return f"{amount / 1_000:.2f}K {coin_html}"
    # For sub-1000 amounts, show up to 4 significant decimals and strip trailing zeros.
    if amount >= 1:
        return f"{_strip_zeros(f'{amount:.4f}')} {coin_html}"
    if amount >= 0.001:
        return f"{_strip_zeros(f'{amount:.6f}')} {coin_html}"
    return f"{amount:.8g} {coin_html}"


def _strip_zeros(s: str) -> str:
    """Strip trailing zeros from a fixed-point number string. '0.5000' -> '0.5'."""
    if "." not in s:
        return s
    return s.rstrip("0").rstrip(".")


def _fmt_usd(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.2f}K"
    return f"${amount:,.2f}"


def _fmt_signed_usd(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{_fmt_usd(abs(amount))}"


def _format_twap_event(event: TwapEvent, label: str, lang: str) -> str:
    """Render a TWAP lifecycle event."""
    action = t(f"event.{event.kind.value}", lang)
    side_label = _side_label(event.twap.side, lang)
    coin = escape(event.twap.coin)
    label_html = f"<b>{escape(label)}</b>"
    header = f"{action} {side_label} <b>{coin}</b> · {label_html}"
    address_line = f"<code>{event.address.lower()}</code>"
    body = _twap_event_body(event, lang)
    return f"{header}\n{address_line}\n\n{body}"


def _twap_event_body(event: TwapEvent, lang: str) -> str:
    twap = event.twap

    if event.kind == TwapEventKind.STARTED:
        return "\n".join(
            [
                _kv(t("twap.field.total", lang), _fmt_size(twap.total_size, twap.coin)),
                _kv(t("twap.field.duration", lang), _fmt_minutes(twap.minutes, lang)),
                _kv(t("twap.field.kind", lang), _twap_flags(twap, lang)),
            ]
        )

    if event.kind == TwapEventKind.SLICE:
        progress_str = f"{event.bucket_pct}%"
        return "\n".join(
            [
                _kv(t("twap.field.progress", lang), progress_str),
                _kv(
                    t("twap.field.executed", lang),
                    t(
                        "field.from_to",
                        lang,
                        a=_fmt_size(twap.executed_size, twap.coin),
                        b=_fmt_size(twap.total_size, twap.coin),
                    ),
                ),
                _kv(t("twap.field.executed_usd", lang), _fmt_usd(twap.executed_notional_usd)),
            ]
        )

    if event.kind == TwapEventKind.FINISHED:
        return "\n".join(
            [
                _kv(t("twap.field.executed", lang), _fmt_size(twap.executed_size, twap.coin)),
                _kv(t("twap.field.executed_usd", lang), _fmt_usd(twap.executed_notional_usd)),
                _kv(t("twap.field.duration", lang), _fmt_minutes(twap.minutes, lang)),
            ]
        )

    if event.kind == TwapEventKind.CANCELLED:
        return "\n".join(
            [
                _kv(
                    t("twap.field.executed", lang),
                    t(
                        "field.from_to",
                        lang,
                        a=_fmt_size(twap.executed_size, twap.coin),
                        b=_fmt_size(twap.total_size, twap.coin),
                    ),
                ),
                _kv(t("twap.field.executed_usd", lang), _fmt_usd(twap.executed_notional_usd)),
                _kv(t("twap.field.progress", lang), f"{twap.progress_pct:.1f}%"),
            ]
        )

    # Fallback — should not happen.
    return _kv(t("twap.field.total", lang), _fmt_size(twap.total_size, twap.coin))


def _twap_flags(twap: TwapState, lang: str) -> str:
    """Compact label for randomize / reduce-only flags. Falls back to 'TWAP'."""
    parts: list[str] = ["TWAP"]
    if twap.reduce_only:
        parts.append(t("twap.flag.reduce_only", lang))
    if twap.randomize:
        parts.append(t("twap.flag.randomize", lang))
    return " · ".join(parts)


def _fmt_minutes(minutes: int, lang: str) -> str:
    """Render duration in minutes — used by TWAP messages."""
    return t("twap.field.minutes_value", lang, n=minutes)


def _fmt_pnl(amount: float) -> str:
    """Format PnL with a colored indicator emoji so positive / negative is obvious at a glance."""
    if amount > 0:
        marker = "\U0001f7e2"  # 🟢
    elif amount < 0:
        marker = "\U0001f534"  # 🔴
    else:
        marker = "\u26aa"  # ⚪
    return f"{marker} {_fmt_signed_usd(amount)}"

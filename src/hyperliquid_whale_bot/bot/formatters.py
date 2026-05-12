"""Format `PositionEvent`s and snapshots into Telegram-friendly HTML messages."""

from __future__ import annotations

from datetime import datetime, timedelta
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
    footer = _twap_footer(event.address, lang)
    return f"{header}\n{address_line}\n\n{body}\n\n{footer}"


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
    """Render a TWAP lifecycle event.

    Layout (all kinds share it):
        {header verb}  —  #{label}
        <code>{address}</code>

        <body — kind-specific>

        🔍 Проводник  •  By @danyseventeen
    """
    action = t(f"event.{event.kind.value}", lang)
    label_html = f"#{escape(label)}"
    header = f"{action} — {label_html}"
    address_line = f"<code>{event.address.lower()}</code>"
    body = _twap_event_body(event, lang)
    footer = _twap_footer(event.address, lang)
    return f"{header}\n{address_line}\n\n{body}\n\n{footer}"


def _twap_event_body(event: TwapEvent, lang: str) -> str:
    twap = event.twap

    if event.kind == TwapEventKind.STARTED:
        return _twap_started_body(event, lang)
    if event.kind == TwapEventKind.SLICE:
        return _twap_slice_body(event, lang)
    if event.kind == TwapEventKind.FINISHED:
        return _twap_finished_body(twap, lang)
    if event.kind in (
        TwapEventKind.CANCELLED,
        TwapEventKind.TERMINATED,
        TwapEventKind.ERROR,
    ):
        return _twap_terminal_body(event, lang)

    # Defensive fallback — only here if a new kind is added without updating this dispatch.
    return _kv(t("twap.label.total_size", lang), _fmt_size(twap.total_size, twap.coin))


# --- TWAP body builders ----------------------------------------------------


def _twap_started_body(event: TwapEvent, lang: str) -> str:
    twap = event.twap
    coin = escape(twap.coin)
    side_value = t(
        "twap.value.long_side" if twap.side == Side.LONG else "twap.value.short_side",
        lang,
    )

    # Headline: "🔴 ~$214K SHORT BTC" (USD prefix when mark price is known).
    usd_prefix = ""
    if event.mark_price_usd is not None and event.mark_price_usd > 0:
        approx_usd = _fmt_usd(twap.total_size * event.mark_price_usd)
        usd_prefix = t("twap.value.usd_approx", lang, usd=approx_usd) + " "
    headline = f"{usd_prefix}{side_value} {coin}"

    end_at = twap.started_at + timedelta(minutes=twap.minutes)
    slice_count = max(1, twap.minutes * 2)
    per_slice = twap.total_size / slice_count if slice_count else twap.total_size
    frequency_value = f"{_fmt_size(per_slice, twap.coin)} / 30s ({slice_count})"
    reduce_only_val = t(
        "twap.value.yes" if twap.reduce_only else "twap.value.no", lang
    )

    return "\n".join(
        [
            headline,
            "",
            _kv(t("twap.label.total_size", lang), _fmt_size(twap.total_size, twap.coin)),
            _kv(t("twap.label.price", lang), t("twap.label.market", lang)),
            _kv(t("twap.label.frequency", lang), frequency_value),
            _kv(t("twap.label.start", lang), _fmt_time_short(twap.started_at)),
            _kv(t("twap.label.end", lang), _fmt_time_short(end_at)),
            _kv(t("twap.label.reduce_only", lang), reduce_only_val),
            _kv(t("twap.label.twap_id", lang), str(twap.twap_id)),
        ]
    )


def _twap_slice_body(event: TwapEvent, lang: str) -> str:
    twap = event.twap
    coin = escape(twap.coin)
    side_value = t(
        "twap.value.long_side" if twap.side == Side.LONG else "twap.value.short_side",
        lang,
    )
    pinned = f"📌 ${coin} {side_value}"

    avg_price = (
        twap.executed_notional_usd / twap.executed_size if twap.executed_size > 0 else 0.0
    )
    filled_label = t("twap.label.executed_short", lang)
    filled_value = (
        f"{_fmt_size(twap.executed_size, twap.coin)} @ "
        f"${_fmt_price(avg_price)} ({_fmt_usd(twap.executed_notional_usd)})"
    )

    progress_value = (
        f"{event.bucket_pct or int(twap.progress_pct)}% "
        f"({_fmt_usd(twap.executed_notional_usd)} / {_fmt_usd(_total_usd_estimate(twap, event))})"
    )
    bar = _progress_bar(event.bucket_pct or twap.progress_pct)

    timestamp = event.captured_at if event.captured_at is not None else twap.started_at

    return "\n".join(
        [
            pinned,
            f"{filled_label}: {filled_value}",
            f"{t('twap.label.progress_short', lang)}: {progress_value}",
            bar,
            _kv(t("twap.label.time", lang), _fmt_time_long(timestamp)),
        ]
    )


def _twap_finished_body(twap: TwapState, lang: str) -> str:
    coin = escape(twap.coin)
    side_value = t(
        "twap.value.long_side" if twap.side == Side.LONG else "twap.value.short_side",
        lang,
    )
    pinned = f"📌 ${coin} {side_value}"
    return "\n".join(
        [
            pinned,
            _kv(t("twap.label.executed_full", lang), _fmt_size(twap.executed_size, twap.coin)),
            _kv(t("twap.label.executed_amount", lang), _fmt_usd(twap.executed_notional_usd)),
            _kv(t("twap.label.duration", lang), _fmt_minutes(twap.minutes, lang)),
            _kv(
                t("twap.label.finished_at", lang),
                _fmt_time_long(twap.started_at + timedelta(minutes=twap.minutes)),
            ),
        ]
    )


def _twap_terminal_body(event: TwapEvent, lang: str) -> str:
    twap = event.twap
    coin = escape(twap.coin)
    side_value = t(
        "twap.value.long_side" if twap.side == Side.LONG else "twap.value.short_side",
        lang,
    )
    pinned = f"📌 ${coin} {side_value}"

    if event.kind == TwapEventKind.TERMINATED:
        exec_label = t("twap.label.executed_stopped", lang)
        progress_label = t("twap.label.progress_at_stop", lang)
        time_label = t("twap.label.terminated_at", lang)
    elif event.kind == TwapEventKind.ERROR:
        exec_label = t("twap.label.executed_stopped", lang)
        progress_label = t("twap.label.progress_at_error", lang)
        time_label = t("twap.label.error_at", lang)
    else:  # CANCELLED
        exec_label = t("twap.label.executed_stopped", lang)
        progress_label = t("twap.label.progress_at_cancel", lang)
        time_label = t("twap.label.cancelled_at", lang)

    exec_value = (
        f"{_fmt_size(twap.executed_size, twap.coin)} / "
        f"{_fmt_size(twap.total_size, twap.coin)}"
    )
    progress_value = f"{twap.progress_pct:.1f}%"
    bar = _progress_bar(twap.progress_pct)
    timestamp = event.captured_at if event.captured_at is not None else twap.started_at

    return "\n".join(
        [
            pinned,
            f"{exec_label}: {exec_value}",
            _kv(t("twap.label.executed_amount", lang), _fmt_usd(twap.executed_notional_usd)),
            f"{progress_label}: {progress_value}",
            bar,
            _kv(time_label, _fmt_time_long(timestamp)),
        ]
    )


# --- TWAP helpers ----------------------------------------------------------


def _twap_footer(address: str, lang: str) -> str:
    explorer = t(
        "footer.explorer",
        lang,
        url=f"https://hypurrscan.io/address/{address.lower()}",
    )
    author = t("footer.author", lang)
    return f"{explorer}  •  {author}"


def _progress_bar(pct: float | int, slots: int = 10) -> str:
    """10-slot Unicode progress bar. 35% -> '███░░░░░░░'."""
    filled = max(0, min(slots, round(float(pct) / 100.0 * slots)))
    return "█" * filled + "░" * (slots - filled)


def _total_usd_estimate(twap: TwapState, event: TwapEvent) -> float:
    """Estimate total TWAP USD for a SLICE message.

    Prefer mark_price * total_size when we have a price; otherwise extrapolate
    from current executed average price.
    """
    if event.mark_price_usd is not None and event.mark_price_usd > 0:
        return twap.total_size * event.mark_price_usd
    if twap.executed_size > 0:
        avg = twap.executed_notional_usd / twap.executed_size
        return twap.total_size * avg
    return twap.executed_notional_usd


def _fmt_minutes(minutes: int, lang: str) -> str:
    """Render duration in minutes — used by TWAP messages."""
    return t("twap.field.minutes_value", lang, n=minutes)


def _fmt_time_short(dt: datetime) -> str:
    """Short UTC clock used in TWAP STARTED start/end fields."""
    return dt.strftime("%H:%M:%S UTC")


def _fmt_time_long(dt: datetime) -> str:
    """Long UTC stamp used in TWAP slice / terminal messages."""
    return dt.strftime("%d.%m.%Y %H:%M UTC")


def _fmt_price(value: float) -> str:
    """Format a per-unit price. Avoid the K/M abbreviations used for sizes."""
    if value == 0:
        return "0"
    if value >= 1:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _fmt_pnl(amount: float) -> str:
    """Format PnL with a colored indicator emoji so positive / negative is obvious at a glance."""
    if amount > 0:
        marker = "\U0001f7e2"  # 🟢
    elif amount < 0:
        marker = "\U0001f534"  # 🔴
    else:
        marker = "\u26aa"  # ⚪
    return f"{marker} {_fmt_signed_usd(amount)}"

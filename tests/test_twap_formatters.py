"""Unit tests for TWAP event formatting."""

from __future__ import annotations

from datetime import UTC, datetime

from hyperliquid_whale_bot.bot.formatters import format_event
from hyperliquid_whale_bot.models import (
    Side,
    TwapEvent,
    TwapEventKind,
    TwapState,
    TwapStatus,
)

ADDR = "0x" + "ab" * 20
LABEL = "alpha"


def _twap(
    *,
    coin: str = "BTC",
    total: float = 1.5,
    executed: float = 0.0,
    executed_usd: float = 0.0,
    status: TwapStatus = TwapStatus.ACTIVATED,
    minutes: int = 30,
    side: Side = Side.LONG,
) -> TwapState:
    return TwapState(
        twap_id=42,
        coin=coin,
        side=side,
        total_size=total,
        executed_size=executed,
        executed_notional_usd=executed_usd,
        minutes=minutes,
        status=status,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _event(kind: TwapEventKind, twap: TwapState, bucket_pct: int = 0) -> TwapEvent:
    return TwapEvent(
        kind=kind,
        address=ADDR,
        twap=twap,
        progress_pct=twap.progress_pct,
        captured_at=datetime.now(UTC),
        bucket_pct=bucket_pct,
    )


def test_format_twap_started_has_copyable_address_and_coin() -> None:
    """STARTED event renders the address copy-on-tap, includes the coin, and shows TwapId."""
    event = _event(TwapEventKind.STARTED, _twap())
    text = format_event(event, label=LABEL, lang="en")
    assert f"<code>{ADDR.lower()}</code>" in text
    assert "BTC" in text
    assert "TWAP started" in text  # EN header per new format
    assert "TwapId" in text  # new mockup surfaces the twap_id
    # Slice count is minutes * 2 per HL protocol; check we render it.
    assert "(60)" in text  # 30 minutes -> 60 slices


def test_format_twap_started_with_mark_price_shows_usd_estimate() -> None:
    """When mark_price_usd is provided, STARTED headline carries the ~$USD approximation."""
    twap = _twap(total=2.0)  # 2 BTC * 50000 = $100K
    event = TwapEvent(
        kind=TwapEventKind.STARTED,
        address=ADDR,
        twap=twap,
        progress_pct=0.0,
        captured_at=datetime.now(UTC),
        mark_price_usd=50_000.0,
    )
    text = format_event(event, label=LABEL, lang="en")
    assert "~$100.00K" in text


def test_format_twap_started_without_mark_price_omits_usd_estimate() -> None:
    """Without mark_price_usd, STARTED headline must NOT show a ~$ value."""
    event = _event(TwapEventKind.STARTED, _twap())  # mark_price_usd=None by default
    text = format_event(event, label=LABEL, lang="en")
    assert "~$" not in text


def test_format_twap_slice_shows_bucket_percent_and_progress_bar() -> None:
    """SLICE event shows the bucket_pct value (e.g. '30%') and renders a progress bar."""
    twap = _twap(total=10.0, executed=3.0, executed_usd=30_000.0)
    event = _event(TwapEventKind.SLICE, twap, bucket_pct=30)
    text = format_event(event, label=LABEL, lang="ru")
    assert "30%" in text
    assert "🔸" in text  # new slice header emoji
    # The progress bar is 10 unicode block slots, 30% filled.
    assert "███░░░░░░░" in text


def test_format_twap_finished_uses_filled_label_and_shows_amount() -> None:
    """FINISHED renders the localized 'filled' label and the executed USD amount."""
    twap = _twap(executed=1.5, executed_usd=150_000.0, status=TwapStatus.FINISHED)
    event = _event(TwapEventKind.FINISHED, twap)
    for lang, expected_header, expected_field in (
        ("en", "TWAP filled", "Filled:"),
        ("ru", "TWAP исполнен", "Исполнено:"),
        ("uk", "TWAP виконано", "Виконано:"),
    ):
        text = format_event(event, label=LABEL, lang=lang)
        assert expected_header in text, f"missing header for {lang!r}"
        assert expected_field in text, f"missing field label for {lang!r}"
        assert "$150.00K" in text


def test_format_twap_cancelled_shows_progress_percent() -> None:
    """CANCELLED reports how much was already executed before cancellation."""
    twap = _twap(
        total=10.0,
        executed=3.5,
        executed_usd=10_000.0,
        status=TwapStatus.TERMINATED,
    )
    event = _event(TwapEventKind.CANCELLED, twap)
    text = format_event(event, label=LABEL, lang="en")
    assert "TWAP cancelled" in text
    assert "35.0%" in text  # progress = 3.5 / 10 * 100


def test_format_twap_event_html_escapes_coin() -> None:
    """User-controlled coin name (spot, e.g. '@151') gets HTML-escaped."""
    twap = _twap(coin="<bad>")
    event = _event(TwapEventKind.STARTED, twap)
    text = format_event(event, label=LABEL, lang="en")
    assert "&lt;bad&gt;" in text
    assert "<bad>" not in text.replace("&lt;bad&gt;", "")


def test_format_twap_terminated_uses_terminated_header() -> None:
    """TERMINATED renders the localized 'terminated' header — distinct from CANCELLED."""
    twap = _twap(total=10.0, executed=3.5, executed_usd=10_000.0, status=TwapStatus.TERMINATED)
    event = _event(TwapEventKind.TERMINATED, twap)
    for lang, expected_header in (
        ("en", "TWAP terminated"),
        ("ru", "TWAP остановлен"),
        ("uk", "TWAP зупинено"),
    ):
        text = format_event(event, label=LABEL, lang=lang)
        assert expected_header in text, f"missing TERMINATED header for {lang!r}"


def test_format_twap_error_uses_error_header() -> None:
    """ERROR renders the localized 'error' header — distinct from TERMINATED and CANCELLED."""
    twap = _twap(total=10.0, executed=0.0, executed_usd=0.0, status=TwapStatus.ERROR)
    event = _event(TwapEventKind.ERROR, twap)
    for lang, expected_header in (
        ("en", "TWAP error"),
        ("ru", "TWAP — ошибка"),
        ("uk", "TWAP — помилка"),
    ):
        text = format_event(event, label=LABEL, lang=lang)
        assert expected_header in text, f"missing ERROR header for {lang!r}"


def test_format_twap_event_footer_links_to_explorer_and_author() -> None:
    """All TWAP messages carry the explorer + author footer."""
    event = _event(TwapEventKind.STARTED, _twap())
    text = format_event(event, label=LABEL, lang="en")
    assert "hypurrscan.io/address/" in text
    assert "danyseventeen" in text

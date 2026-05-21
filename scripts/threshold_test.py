"""Flow B — dual-threshold filter actually suppresses noise.

Adversarial test: this is the headline anti-spam guarantee from PR #1. If the
threshold logic were broken, the rest of the test suite would still pass — this
script targets it specifically.

Pure-function test: no Telegram, no DB, no Hyperliquid; just the diff engine
and the formatter, called directly.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hyperliquid_whale_bot.bot.formatters import format_event
from hyperliquid_whale_bot.diff import diff_snapshots
from hyperliquid_whale_bot.models import EventKind, Position, Side, WalletSnapshot


ADDR = "0x" + "ab" * 20


def make_snapshot(size: float, notional: float, entry: float, leverage: float) -> WalletSnapshot:
    pos = Position(
        coin="BTC",
        side=Side.LONG,
        size=size,
        entry_price=entry,
        notional_usd=notional,
        unrealized_pnl=0.0,
        leverage=leverage,
        leverage_type="cross",
        liquidation_price=None,
    )
    return WalletSnapshot(
        address=ADDR,
        positions=(pos,),
        captured_at=datetime.now(UTC),
    )


def main() -> int:
    print("=" * 78)
    print("Flow B — dual-threshold filter")
    print("=" * 78)

    previous = make_snapshot(size=1.0, notional=50_000.0, entry=50_000.0, leverage=5.0)
    current_small = make_snapshot(size=1.02, notional=51_000.0, entry=50_000.0, leverage=5.0)
    current_big = make_snapshot(size=1.20, notional=60_000.0, entry=50_000.0, leverage=5.0)

    failures: list[str] = []

    # --- Case 1: small change (+2%, +$1000) below both thresholds -----------
    print("\nCase 1: previous=1.0 BTC ($50k) -> current=1.02 BTC ($51k); thresholds 5% / $5000")
    events_small = diff_snapshots(
        previous=previous,
        current=current_small,
        pct_threshold=5.0,
        usd_threshold=5_000.0,
    )
    if events_small == []:
        print(f"  [PASS] no events emitted (got {len(events_small)})")
    else:
        kinds = [e.kind.value for e in events_small]
        print(f"  [FAIL] expected 0 events, got {len(events_small)}: {kinds}")
        failures.append(f"small-change suppression: emitted {kinds}")

    # --- Case 2: large change (+20%, +$10000) above both thresholds ---------
    print("\nCase 2: previous=1.0 BTC ($50k) -> current=1.20 BTC ($60k); thresholds 5% / $5000")
    events_big = diff_snapshots(
        previous=previous,
        current=current_big,
        pct_threshold=5.0,
        usd_threshold=5_000.0,
    )
    if len(events_big) == 1:
        print(f"  [PASS] exactly 1 event emitted: {events_big[0].kind.value}")
    else:
        print(f"  [FAIL] expected exactly 1 event, got {len(events_big)}")
        failures.append(f"big-change emission count: {len(events_big)}")
        return 1

    ev = events_big[0]
    if ev.kind == EventKind.INCREASE:
        print(f"  [PASS] event kind == INCREASE (got {ev.kind.value})")
    else:
        print(f"  [FAIL] event kind != INCREASE (got {ev.kind.value})")
        failures.append(f"big-change kind: {ev.kind.value}")

    # pct_change should be +20.0
    if abs(ev.pct_change - 20.0) < 0.001:
        print(f"  [PASS] pct_change == 20.0 (got {ev.pct_change})")
    else:
        print(f"  [FAIL] pct_change expected 20.0, got {ev.pct_change}")
        failures.append(f"pct_change: {ev.pct_change}")

    # notional_delta_usd should be +10000
    if abs(ev.notional_delta_usd - 10_000.0) < 0.001:
        print(f"  [PASS] notional_delta_usd == 10000 (got {ev.notional_delta_usd})")
    else:
        print(f"  [FAIL] notional_delta_usd expected 10000, got {ev.notional_delta_usd}")
        failures.append(f"notional_delta_usd: {ev.notional_delta_usd}")

    # --- Case 3: formatted message contains the right tokens -----------------
    print("\nCase 3: format_event in RU")
    text_ru = format_event(ev, label="whale", lang="ru")
    print(f"  formatted RU:\n    {text_ru.replace(chr(10), chr(10) + '    ')}")
    for needle in ("Увеличил", "BTC", "+20", "$10", "whale"):
        if needle in text_ru:
            print(f"  [PASS] RU output contains {needle!r}")
        else:
            print(f"  [FAIL] RU output missing {needle!r}")
            failures.append(f"format RU missing: {needle}")

    print("\nCase 3 (cont): format_event in EN")
    text_en = format_event(ev, label="whale", lang="en")
    print(f"  formatted EN:\n    {text_en.replace(chr(10), chr(10) + '    ')}")
    for needle in ("Increased", "BTC", "+20", "$10", "whale"):
        if needle in text_en:
            print(f"  [PASS] EN output contains {needle!r}")
        else:
            print(f"  [FAIL] EN output missing {needle!r}")
            failures.append(f"format EN missing: {needle}")

    # --- Case 4: just one threshold exceeded — still suppressed --------------
    print("\nCase 4: +20% but only +$1000 ($50k -> $51k with size 1.20 same coin)")
    # Construct an artificial 'big pct but small USD' snapshot: pretend price
    # dropped so the new notional is only 51k despite size growing 20%.
    odd_current = make_snapshot(size=1.20, notional=51_000.0, entry=50_000.0, leverage=5.0)
    events_odd = diff_snapshots(
        previous=previous,
        current=odd_current,
        pct_threshold=5.0,
        usd_threshold=5_000.0,
    )
    if events_odd == []:
        print("  [PASS] one-threshold-only change suppressed (no events)")
    else:
        kinds = [e.kind.value for e in events_odd]
        print(f"  [FAIL] expected 0 events, got {kinds}")
        failures.append(f"one-threshold suppression: {kinds}")

    print("\n" + "=" * 78)
    if not failures:
        print("Flow B: ALL PASS")
        return 0
    print(f"Flow B: {len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

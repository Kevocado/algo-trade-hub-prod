"""Read-only health of the hourly timers and the journal's per-family freeze rate.

This module is PURE: it turns already-fetched timestamps and counts into a report, so every rule is
testable without a database, a network, or a filesystem. `collect_health` at the bottom is the one
place that reads, and it does nothing but fetch.

What it reports, and why each fact exists:
  * When each hourly timer last succeeded (scan, settle, journal, orderbooks). A timer that ran and
    found nothing is different from a timer that did not run; only the second is a fault, and this
    reports the fact that separates them (a last-success timestamp) rather than guessing from output.
  * Forecasts frozen in the last 24h per family. A daily family that froze nothing is a fault; a
    monthly family that froze nothing in a given 24h window is Tuesday. `expected_daily` is the rule
    that tells those two apart, and it is deliberately narrow (daily/hourly only).
  * The age of the newest order-book file. `None` means "no file at all", which is NOT zero: zero
    would be a measurement of a search that found nothing, and nothing was searched.

**A missing figure is never 0.** Every absence is `None` and every zero is a real count. A family that
froze nothing in the window has `frozen_24h == 0` (that is what "froze nothing" means) while the
order-book file that was never written is `None` (we do not know if a search happened).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# The hourly timers this product runs. The names match the VPS `tradehub-*` jobs.
TIMERS: tuple[str, ...] = ("scan", "settle", "journal", "orderbooks")

# An hourly timer is expected to succeed at least this often. Two hours tolerates one missed tick.
STALE_AFTER_HOURS = 2
# An order-book file is written hourly; same tolerance.
ORDERBOOK_STALE_AFTER_HOURS = 3
# The window "froze in the last 24h" counts over.
FROZEN_WINDOW_HOURS = 24

# The cadences that should produce a freeze on (almost) every calendar day. A monthly or meeting
# cadence legitimately has quiet days and is never flagged as silent.
DAILY_CADENCES = frozenset({"daily", "hourly"})

# The order-book recorder's root, same env var it writes under (record_orderbooks.py). Read here so
# the health page and the writer can never disagree about where the files live.
ORDERBOOK_ROOT_ENV = "TRADEHUB_ORDERBOOK_DIR"
DEFAULT_ORDERBOOK_ROOT = "/cache/orderbooks"


def expected_daily(cadence: str | None) -> bool:
    """True when a family of this cadence is expected to freeze on a given day."""
    return (cadence or "").strip().lower() in DAILY_CADENCES


def timer_status(last_success: datetime | None, now: datetime, *, stale_after_hours: int = STALE_AFTER_HOURS) -> str:
    """`ok` if it succeeded recently, `stale` if it succeeded but not recently, `never` if it never has.

    `never` is its own word rather than a special case of `stale`: "has not run since we started
    watching" and "ran but has been quiet" are different facts, and an operator needs to tell them.
    """
    if last_success is None:
        return "never"
    age = (now - last_success).total_seconds()
    return "stale" if age >= stale_after_hours * 3600 else "ok"


def _age_seconds(now: datetime, when: datetime | None) -> float | None:
    return None if when is None else (now - when).total_seconds()


def build_health_report(
    *,
    timers: Mapping[str, datetime | None],
    frozen_by_family: Mapping[str, int],
    cadences: Mapping[str, str | None],
    orderbook_age_seconds: float | None,
    now: datetime,
) -> dict[str, Any]:
    """Assemble the whole read-only report. Pure: `timers`/`frozen_by_family` are already fetched."""
    problems: list[str] = []

    timer_payload: dict[str, Any] = {}
    for name in TIMERS:
        last = timers.get(name)
        status = timer_status(last, now)
        timer_payload[name] = {
            "last_success": last.isoformat() if last else None,
            "age_seconds": _age_seconds(now, last),
            "status": status,
        }
        if status != "ok":
            problems.append(f"timer {name} is {status}")

    family_payload: dict[str, Any] = {}
    for family, count in frozen_by_family.items():
        cadence = cadences.get(family)
        silent = expected_daily(cadence) and count == 0
        family_payload[family] = {
            "frozen_24h": count,
            "cadence": cadence,
            "expected_daily": expected_daily(cadence),
            "silent": silent,
        }
        if silent:
            problems.append(f"family {family} is daily but froze nothing in the last {FROZEN_WINDOW_HOURS}h")

    if orderbook_age_seconds is None:
        orderbook_status = "missing"
        problems.append("no order-book file has ever been written")
    elif orderbook_age_seconds >= ORDERBOOK_STALE_AFTER_HOURS * 3600:
        orderbook_status = "stale"
        problems.append("the newest order-book file is older than its staleness window")
    else:
        orderbook_status = "ok"

    return {
        "status": "degraded" if problems else "ok",
        "generated_at": now.isoformat(),
        "frozen_window_hours": FROZEN_WINDOW_HOURS,
        "stale_after_hours": STALE_AFTER_HOURS,
        "timers": timer_payload,
        "families": family_payload,
        "orderbook": {
            "newest_file_age_seconds": orderbook_age_seconds,
            "status": orderbook_status,
        },
        "problems": problems,
    }


# ─── the one place that reads ──────────────────────────────────────────────────


def _latest(supa, table: str, column: str) -> datetime | None:
    """The newest value of `column` in `table`, or None when the table is empty/unreadable.

    Supabase orders descending and returns the head, so this is one row, not a scan.
    """
    try:
        result = supa.table(table).select(column).order(column, desc=True).limit(1).execute()
    except Exception:  # noqa: BLE001 - health must never 500 on a missing table
        return None
    rows = getattr(result, "data", None) or []
    if not rows or rows[0].get(column) is None:
        return None
    value = rows[0][column]
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _frozen_counts(supa, since: datetime) -> dict[str, int]:
    """Forecasts frozen at/after `since`, grouped by forecaster."""
    try:
        result = (
            supa.table("journal_forecasts")
            .select("forecaster")
            .gte("frozen_at", since.isoformat())
            .execute()
        )
    except Exception:  # noqa: BLE001 - health must never 500 on a missing table
        return {}
    counts: dict[str, int] = {}
    for row in getattr(result, "data", None) or []:
        name = row.get("forecaster")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def orderbook_root() -> Path:
    return Path(os.getenv(ORDERBOOK_ROOT_ENV, DEFAULT_ORDERBOOK_ROOT))


def newest_orderbook_age_seconds(root: Path | None = None, now: datetime | None = None) -> float | None:
    """Age of the newest order-book file under `root`, or None when there is no file at all."""
    now = now or datetime.now(timezone.utc)
    base = root or orderbook_root()
    newest: float | None = None
    if not base.exists():
        return None
    for path in base.rglob("*.jsonl.gz"):
        try:
            age = (now - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds()
        except OSError:
            continue
        newest = age if newest is None else min(newest, age)
    return newest


def _expected_cadences() -> dict[str, str | None]:
    """Family -> cadence, from the journal registry, excluding baselines and market pseudo-forecasters.

    The registry is imported lazily so this module stays importable without credentials (registry
    builds clients at import time). A family missing from the registry is simply not listed.
    """
    from tradehub.journal.registry import FORECASTERS

    out: dict[str, str | None] = {}
    for fc in FORECASTERS:
        name = fc.name
        if name.startswith("baseline_") or name.startswith("kalshi_implied_"):
            continue
        out[name] = getattr(fc, "cadence", None)
    return out


def collect_health(supa, *, now: datetime | None = None, orderbook_dir: Path | None = None) -> dict[str, Any]:
    """Read every input and assemble the report. Read-only; never raises."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=FROZEN_WINDOW_HOURS)

    timers = {
        # The journal's last scorecard write is written every run, frozen or not, so it is the
        # honest "the journal ran" signal.
        "journal": _latest(supa, "journal_scores", "computed_at"),
        "scan": _latest(supa, "scanner_runs", "created_at"),
        "settle": _latest(supa, "predictions", "settled_at"),
        "orderbooks": None,  # derived from the filesystem below, not from a table
    }
    orderbook_age = newest_orderbook_age_seconds(orderbook_dir, now)
    if orderbook_age is not None:
        timers["orderbooks"] = now - timedelta(seconds=orderbook_age)

    frozen = _frozen_counts(supa, since)
    cadences = _expected_cadences()

    return build_health_report(
        timers=timers,
        frozen_by_family=frozen,
        cadences=cadences,
        orderbook_age_seconds=orderbook_age,
        now=now,
    )

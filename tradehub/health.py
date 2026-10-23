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

# The timers whose last success we CANNOT read, and why each one specifically. This is a fact about
# what the jobs write, not a guess, and it is the whole reason the page once cried wolf:
#
#   scan    `scanner_runs` exists and `start_run`/`complete_run` exist to fill it, but nothing calls
#           them -- the scan job writes `kalshi_edges` only, so the table stays empty forever.
#   settle  `predictions.settled_at` IS written, but only when a contract actually settles. A healthy
#           hourly run with nothing to settle leaves it untouched, so it answers "when did something
#           last settle", not "when did the job last run".
#
# Both jobs run fine; there is simply no row that records the run. So they are `not_tracked`: shown on
# the page as a known gap, and excluded from the fault count. They are deliberately NOT marked `ok`
# (we did not measure them) and NOT marked `never` (they are not broken).
#
# To track them for real: wire `complete_run` into `tradehub/scripts/scan.py` for `scan`, and give
# `settle` a row written every pass -- which needs a new table, i.e. a migration. See
# docs/superpowers/plans/migrations-applied.md for the record-keeping rule that applies.
UNTRACKED_TIMERS: frozenset[str] = frozenset({"scan", "settle"})

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


def is_game_driven(family: str) -> bool:
    """True for families that only freeze when a game is calendared (`sports_*`).

    Only these may be quiet on a day with no game. Every other daily family (weather, gas, ERCOT, FX)
    is expected every day, so a missing calendar entry there is the failure, not a day off.
    """
    return family.startswith("sports_")


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
    frozen_by_family: Mapping[str, int] | None,
    cadences: Mapping[str, str | None],
    orderbook_age_seconds: float | None,
    now: datetime,
    untracked: frozenset[str] | None = None,
    calendar_by_family: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Assemble the whole read-only report. Pure: `timers`/`frozen_by_family` are already fetched.

    `frozen_by_family` is `None` when the count query itself failed, which is NOT the same as an empty
    dict: empty means "the table was read and it held no rows", and `None` means "we do not know". A
    family absent from a successfully-read mapping therefore froze 0 rows (and a daily one is silent),
    while a family under a `None` mapping is reported as unknown (`frozen_24h: None`, not silent) so an
    unreadable table can never raise a false "froze nothing" alert.

    `untracked` names timers with no last-success marker (see UNTRACKED_TIMERS). They read
    `not_tracked` and raise no problem. It defaults to `None` meaning "track them all", deliberately:
    if a caller forgets to pass it, a timer with no marker is loudly `never` rather than quietly
    unmeasured. Opting out of tracking has to be explicit; opting in must not be.

    `calendar_by_family` maps family -> list of calendar entries (each with at least "target",
    "family", "cadence", "cutoff_at", "market_linked"). A daily family is only expected to freeze
    when it has at least one calendar entry whose cutoff is still ahead, inside (now, now+24h]. A game
    that already started was frozen before it started, usually more than 24h ago, so it says nothing about today.
    If the calendar read fails (None), fall back to cadence-only expected_daily. If the calendar
    returns entries but none fall in the window, the family is not expected to freeze that day
    (expected_daily=False, silent=False, reason="no_game_window").
    """
    problems: list[str] = []
    untracked = untracked or frozenset()

    timer_payload: dict[str, Any] = {}
    untracked_seen: list[str] = []
    for name in TIMERS:
        if name in untracked:
            # Unmeasured is not a measurement. `last_success` and `age_seconds` stay None exactly as
            # they do for a missing order-book file -- there is nothing to report, not a zero.
            untracked_seen.append(name)
            timer_payload[name] = {
                "last_success": None,
                "age_seconds": None,
                "status": "not_tracked",
                "tracked": False,
            }
            continue
        last = timers.get(name)
        # The order-book timer has its own window: a file every 3h is not stale at 2h.
        window = ORDERBOOK_STALE_AFTER_HOURS if name == "orderbooks" else STALE_AFTER_HOURS
        status = timer_status(last, now, stale_after_hours=window)
        timer_payload[name] = {
            "last_success": last.isoformat() if last else None,
            "age_seconds": _age_seconds(now, last),
            "status": status,
            "tracked": True,
        }
        if status != "ok":
            problems.append(f"timer {name} is {status}")

    known_counts = frozen_by_family or {}
    counts_known = frozen_by_family is not None
    family_payload: dict[str, Any] = {}
    # A daily game-driven family is expected to freeze when a game is still ahead: a cutoff in
    # (now, now + FROZEN_WINDOW_HOURS]. A game that already started was frozen before it started,
    # usually more than 24h ago, so counting it would flag a quiet day as a fault.
    calendar_window_start = now
    calendar_window_end = now + timedelta(hours=FROZEN_WINDOW_HOURS)

    # The union: every family the registry knows, plus any only the count read saw.
    for family in sorted(set(cadences) | set(known_counts)):
        cadence = cadences.get(family)
        if family in known_counts:
            count: int | None = known_counts[family]
        else:
            count = 0 if counts_known else None

        # Determine if this daily family is expected to freeze today.
        # A family is expected to freeze if:
        # 1. It has a daily/hourly cadence, AND
        # 2. Either calendar read failed (None) -> fall back to cadence, OR
        #    calendar has entries in the window, OR
        #    calendar has no entries in the window -> not expected (no_game_window) BUT ONLY FOR SPORTS_* FAMILIES
        base_expected = expected_daily(cadence)
        has_calendar_in_window = False
        reason: str | None = None
        if base_expected and is_game_driven(family):
            cal = calendar_by_family
            if cal is None:
                # Calendar read failed: fall back to old behavior (cadence-based)
                has_calendar_in_window = True  # treat as if it had entries
            else:
                entries = cal.get(family, [])
                for entry in entries:
                    cutoff = _as_datetime(entry.get("cutoff_at"))
                    if cutoff is None:
                        continue
                    if calendar_window_start <= cutoff <= calendar_window_end:
                        has_calendar_in_window = True
                        break
                if not has_calendar_in_window:
                    reason = "no_game_window"
        expected = base_expected and (not is_game_driven(family) or has_calendar_in_window)
        silent = expected and count == 0
        family_payload[family] = {
            "frozen_24h": count,
            "cadence": cadence,
            "expected_daily": expected,
            "silent": silent,
        }
        if reason:
            family_payload[family]["reason"] = reason
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
        # Carried so a reader can tell "2 of 4 timers fresh" apart from "2 of the 2 timers we
        # actually measure are fresh". The untracked ones stay in `timers` too -- a known gap shown
        # on the page, not one quietly left out of the denominator and the list both.
        "untracked_timers": untracked_seen,
        "tracked_timer_count": len(TIMERS) - len(untracked_seen),
        "families": family_payload,
        "orderbook": {
            "newest_file_age_seconds": orderbook_age_seconds,
            "status": orderbook_status,
        },
        "problems": problems,
    }


# ─── the one place that reads ──────────────────────────────────────────────────


def _as_datetime(value: Any) -> datetime | None:
    """Coerce a column value to an aware datetime, or None when it is not one.

    Supabase returns timestamptz as either a `datetime` or an ISO string depending on the driver. A
    naive value is assumed UTC (the database's own storage zone) rather than local, because a health
    figure read as local time is a wrong number that still looks like a number.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _latest(supa, table: str, column: str) -> datetime | None:
    """The newest value of `column` in `table`, or None when the table is empty/unreadable.

    Supabase orders descending and returns the head, so this is one row, not a scan.
    """
    try:
        result = supa.table(table).select(column).order(column, desc=True).limit(1).execute()
    except Exception:  # noqa: BLE001 - health must never 500 on a missing table
        return None
    rows = getattr(result, "data", None) or []
    if not rows:
        return None
    return _as_datetime(rows[0].get(column))


def _frozen_counts(supa, since: datetime) -> dict[str, int] | None:
    """Forecasts frozen at/after `since`, grouped by forecaster.

    `None` (not `{}`) when the query FAILS: an unreadable table means "we do not know how many froze",
    which must not be reported as zero, because zero is a measurement of a search nobody performed.
    An empty dict here means the table WAS read and genuinely held no rows in the window.
    """
    try:
        result = (
            supa.table("journal_forecasts")
            .select("forecaster")
            .gte("frozen_at", since.isoformat())
            .execute()
        )
    except Exception:  # noqa: BLE001 - health must never 500 on a missing table
        return None
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
        # scan and settle have no marker to read; see UNTRACKED_TIMERS. `scanner_runs` is left empty
        # rather than queried, because an always-empty table reads as a permanently failed job and
        # `predictions.settled_at` reads as "when something last settled". Both are lies of omission
        # that this report must not tell.
        "orderbooks": None,  # derived from the filesystem below, not from a table
    }
    orderbook_age = newest_orderbook_age_seconds(orderbook_dir, now)
    if orderbook_age is not None:
        timers["orderbooks"] = now - timedelta(seconds=orderbook_age)

    frozen = _frozen_counts(supa, since)
    cadences = _expected_cadences()

    # Fetch all calendar entries to determine which daily families have targets in the window
    # (now, now+24h]. If the calendar read fails, fall back to cadence-only behavior.
    calendar_by_family = _fetch_calendar_by_family(supa, now)

    return build_health_report(
        timers=timers,
        frozen_by_family=frozen,
        cadences=cadences,
        orderbook_age_seconds=orderbook_age,
        now=now,
        untracked=UNTRACKED_TIMERS,
        calendar_by_family=calendar_by_family,
    )


def _fetch_calendar_by_family(supa, now: datetime) -> dict[str, list[dict[str, Any]]] | None:
    """Read all calendar entries and group by family, filtered to the (now, now+24h] window.
    Returns None on failure."""
    try:
        # Use select_all pattern from journal/store.py to page through all entries
        from tradehub.journal.store import select_all
        lo = now.isoformat()
        hi = (now + timedelta(hours=FROZEN_WINDOW_HOURS)).isoformat()
        rows = select_all(
            supa, "journal_calendars", lambda q: q.gte("cutoff_at", lo).lte("cutoff_at", hi), ("target",)
        )
        by_family: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            family = row.get("family")
            if family:
                by_family.setdefault(family, []).append(row)
        return by_family
    except Exception:  # noqa: BLE001 - health must never 500 on a missing table
        return None

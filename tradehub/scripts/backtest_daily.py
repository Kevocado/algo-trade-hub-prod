"""Replay the daily-direction models over history and store the result as context (plan 16).

    python -m tradehub.scripts.backtest_daily --years 3 --dry-run     # print only
    python -m tradehub.scripts.backtest_daily --years 3               # also write `journal_backtests`

Never touches the journal tables. Each run adds one row per forecaster, so the page can show how the answer
moves over time; nothing here is counted toward a gate. Each stored row carries the Brier gap and its
standard error beside the skill, because a skill printed with no interval reads as a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.daily import closed_only
from tradehub.journal.forecasters.daily_direction import eurusd_source, gold_source, vix_source
from tradehub.journal.nyse import is_session
from tradehub.journal.replay import replay
from tradehub.journal.spx import HISTORY_DAYS, SPX_SERIES

BACKTESTS = "journal_backtests"

# (forecaster, version) exactly as the live journal names them, and how to fetch each family's closes.
SOURCES: dict[tuple[str, str], Callable[[date], tuple[Mapping[date, float], str]]] = {
    ("spy_quant", "spy-wf-v1"): lambda start: (fetch_fred_daily(SPX_SERIES, start), "America/New_York"),
    ("vix_direction", "vix-wf-v1"): vix_source().fetch,
    ("gold_direction", "gold-wf-v1"): gold_source().fetch,
    ("eurusd_direction", "eurusd-wf-v1"): eurusd_source().fetch,
}

# The calendar each family is scored on, taken from the live forecaster's own source rather than
# invented here: NYSE sessions for SPX, VIX and gold, TARGET days for EUR/USD. Replaying every date a
# feed happens to publish is NOT a replay of the live journal -- VIXCLS carries a print forward across
# market holidays, so ungated it scored 775 days against 754 real sessions, and the extra days are ones
# the live forecaster would never have traded. SPX's fetcher is a lambda, so its predicate is the
# module's own `is_session` rather than a source attribute.
CALENDARS: dict[tuple[str, str], tuple[Any, Callable[[date], bool]]] = {
    ("spy_quant", "spy-wf-v1"): (SOURCES[("spy_quant", "spy-wf-v1")], is_session),
    ("vix_direction", "vix-wf-v1"): (SOURCES[("vix_direction", "vix-wf-v1")], vix_source().is_session),
    ("gold_direction", "gold-wf-v1"): (SOURCES[("gold_direction", "gold-wf-v1")], gold_source().is_session),
    ("eurusd_direction", "eurusd-wf-v1"): (SOURCES[("eurusd_direction", "eurusd-wf-v1")], eurusd_source().is_session),
}


def run(now: datetime, years: int, *, sources=None, calendars=None) -> list[dict]:
    """Replay every family on ITS OWN calendar.

    A `sources` entry may be a bare `fetch`, or a `(fetch, is_target)` pair. A bare fetch takes its
    predicate from `CALENDARS` (the live forecaster's own), so a caller that swaps in a fake series
    without a predicate still replays every published day -- which is what the plain-fake tests want,
    and never silently applies one family's calendar to another.
    """
    if calendars is None:
        calendars = {}
        for key, value in (sources or SOURCES).items():
            if isinstance(value, tuple):
                calendars[key] = value
            elif key in CALENDARS:
                calendars[key] = (value, CALENDARS[key][1])
            else:
                calendars[key] = (value, None)
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=365 * years)
    out = []
    for (forecaster, version), (fetch, is_target) in calendars.items():
        try:
            closes, tz = fetch(now.date() - timedelta(days=HISTORY_DAYS))
            result = replay(closed_only(closes, tz, now), start=start, end=end, is_target=is_target)
        except Exception as exc:  # noqa: BLE001 - one family failing must not hide the others
            out.append({"forecaster": forecaster, "forecaster_version": version,
                        "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"forecaster": forecaster, "forecaster_version": version, **result})
    return out


def record(supa, results: list[dict], now: datetime) -> int:
    # `brier_diff`/`brier_diff_se` are written, not recomputed here and not left to be inferred from the
    # Brier pair: the interval is the point of the row (see journal/replay.py), and a stored point
    # estimate with no error bar would be the same defect one column along. `by_year` already carries its
    # own per-year summaries, jsonb, so it needs no column of its own here.
    #
    # This write needs migration 20260428000017 applied -- it names the two columns, and PostgREST refuses
    # an insert that mentions a column the table does not have. That is the direction we want: a loud
    # failure rather than a row that quietly stores a gap with no way to tell how sure anyone is of it.
    rows = [{"forecaster": r["forecaster"], "forecaster_version": r["forecaster_version"],
             "date_from": r["date_from"], "date_to": r["date_to"], "n": r["n"], "brier": r["brier"],
             "brier_baseline": r["brier_baseline"], "bss": r["bss"], "brier_diff": r["brier_diff"],
             "brier_diff_se": r["brier_diff_se"], "by_year": r["by_year"],
             "created_at": now.isoformat()} for r in results if "error" not in r and r["n"]]
    if rows:
        supa.table(BACKTESTS).insert(rows).execute()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_local_env()
    now = datetime.now(UTC)
    results = run(now, args.years)
    written = 0
    if not args.dry_run:
        from tradehub.core.supabase_client import get_client

        written = record(get_client(), results, now)
    print(json.dumps({"as_of": now.isoformat(), "written": written, "results": results}, default=str))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
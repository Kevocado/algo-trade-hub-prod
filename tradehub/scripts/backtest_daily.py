"""Replay the daily-direction models over history and store the result as context (plan 16).

    python -m tradehub.scripts.backtest_daily --years 3 --dry-run     # print only
    python -m tradehub.scripts.backtest_daily --years 3               # also write `journal_backtests`

Never touches the journal tables. Each run adds one row per forecaster, so the page can show how the answer
moves over time; nothing here is counted toward a gate. Each stored row carries the Brier gap and its
standard error beside the skill, because a skill printed with no interval reads as a result.

The sentiment meter joins the four here, and it is not replayed the same way: its inputs are FRED series,
and reading their CURRENT vintage would score the meter on revisions it never had (v2 spec §6). It goes
through `journal.meter_replay`, which asks ALFRED for each input's vintage as of the forecast's own date
and records a gap -- never a substituted value -- where there is none. It shares the table, the summary
and the "not counted" label; it does not share the `SOURCES` shape, because a point-in-time read is not a
single fetchable series.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.data.alfred_vintages import DEFAULT_CACHE_DIR, fetch_vintages
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.daily import closed_only
from tradehub.journal.forecasters.daily_direction import eurusd_source, gold_source, vix_source
from tradehub.journal.meter_replay import (
    FORECASTER,
    SETTLEMENT_LAG,
    VERSION,
    read_vintages,
    replay_meter,
)
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


def replay_meter_window(now: datetime, years: int, *,
                        fetch: Callable[..., Mapping[date, Any]] = fetch_vintages,
                        cache_dir: Path | None = DEFAULT_CACHE_DIR,
                        today: date | None = None,
                        deadline: float | None = None) -> dict[str, Any]:
    """The sentiment meter's replay over [now - years, now), read at FRED vintages.

    The window is trimmed to sessions whose settlement vintage can still exist: `fetch_vintages` drops
    `v >= today`, so asking for one would return nothing and report a gap that is really an artefact of
    the arithmetic. That is why the last day `date_to` can name is the one before the last session.
    """
    today = today or now.date()
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=365 * years)
    span = (end - start).days + 1
    days = [start + timedelta(days=i) for i in range(span)]
    days = [d for d in days if is_session(d) and d + SETTLEMENT_LAG < today]
    return replay_meter(days, read_vintages(days, fetch=fetch, cache_dir=cache_dir, today=today,
                                            deadline=deadline))


def run(now: datetime, years: int, *, sources=None, calendars=None, meter=None) -> list[dict]:
    """Replay every family on ITS OWN calendar, plus the sentiment meter when `meter` is given.

    A `sources` entry may be a bare `fetch`, or a `(fetch, is_target)` pair. A bare fetch takes its
    predicate from `CALENDARS` (the live forecaster's own), so a caller that swaps in a fake series
    without a predicate still replays every published day -- which is what the plain-fake tests want,
    and never silently applies one family's calendar to another.

    `meter` is `replay_meter_window`, passed in rather than called here because it reaches the network
    and the four families above do not: a test that replays fakes must not start an ALFRED crawl. `main`
    passes it, which is what keeps the meter's row on the page.
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
    # Fetch back far enough for the REQUESTED window plus the training and climatology history the
    # replay needs. `HISTORY_DAYS` alone covers `--years 3`; a larger `--years` would otherwise start
    # before the fetched data, and the replay would score only the part it has while still storing the
    # full requested window -- claiming history that was never scored.
    history_days = max(HISTORY_DAYS, (end - start).days + HISTORY_DAYS)
    out = []
    for (forecaster, version), (fetch, is_target) in calendars.items():
        try:
            closes, tz = fetch(now.date() - timedelta(days=history_days))
            result = replay(closed_only(closes, tz, now), start=start, end=end, is_target=is_target)
        except Exception as exc:  # noqa: BLE001 - one family failing must not hide the others
            out.append({"forecaster": forecaster, "forecaster_version": version,
                        "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"forecaster": forecaster, "forecaster_version": version, **result})
    if meter is not None:
        # Same treatment as any other family: a meter replay that cannot be read point-in-time is an
        # error, not a row. `record` writes nothing for it, which is the honest outcome -- a number from
        # a current-vintage read would be the leak, so there is no number to store.
        try:
            out.append(meter(now, years))
        except Exception as exc:  # noqa: BLE001
            out.append({"forecaster": FORECASTER, "forecaster_version": VERSION,
                        "error": f"{type(exc).__name__}: {exc}"})
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
    results = run(now, args.years, meter=replay_meter_window)
    written = 0
    if not args.dry_run:
        from tradehub.core.supabase_client import get_client

        written = record(get_client(), results, now)
    print(json.dumps({"as_of": now.isoformat(), "written": written, "results": results}, default=str))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
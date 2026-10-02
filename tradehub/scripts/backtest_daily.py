"""Replay the daily-direction models over history and store the result as context (plan 16).

    python -m tradehub.scripts.backtest_daily --years 3 --dry-run     # print only
    python -m tradehub.scripts.backtest_daily --years 3               # also write `journal_backtests`

Never touches the journal tables. Each run adds one row per forecaster, so the page can show how the answer
moves over time; nothing here is counted toward a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta

from tradehub.core.env import load_local_env
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.daily import closed_only
from tradehub.journal.forecasters.daily_direction import eurusd_source, gold_source, vix_source
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


def run(now: datetime, years: int, *, sources=SOURCES) -> list[dict]:
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=365 * years)
    out = []
    for (forecaster, version), fetch in sources.items():
        try:
            closes, tz = fetch(now.date() - timedelta(days=HISTORY_DAYS))
            result = replay(closed_only(closes, tz, now), start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - one family failing must not hide the others
            out.append({"forecaster": forecaster, "forecaster_version": version, "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"forecaster": forecaster, "forecaster_version": version, **result})
    return out


def record(supa, results: list[dict], now: datetime) -> int:
    rows = [{"forecaster": r["forecaster"], "forecaster_version": r["forecaster_version"],
             "date_from": r["date_from"], "date_to": r["date_to"], "n": r["n"], "brier": r["brier"],
             "brier_baseline": r["brier_baseline"], "bss": r["bss"], "by_year": r["by_year"],
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
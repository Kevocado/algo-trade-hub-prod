"""Cron entrypoint: one prediction-journal run (freeze -> settle -> score for every forecaster).

Run hourly by the VPS `tradehub-journal.timer` (vps-stack). Each forecaster decides from its own
calendar whether anything is due, so an hourly run is cheap when nothing is.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.health import collect_health
from tradehub.health_alerts import alert_on_failures
from tradehub.journal.registry import FORECASTERS
from tradehub.journal.runner import run_journal


def main() -> int:
    load_local_env()
    supa = get_client()
    summary = run_journal(supa, FORECASTERS, datetime.now(UTC))

    # Failure notifier, scoped to the two things this job is asked to alert on: the run itself failing,
    # and a daily family freezing nothing for 24h. Timer staleness and the order-book file are on the
    # /health page but are NOT alerts here -- a scan that has not run for 3h is a fact about the scan
    # job, and paging about it from the journal cron would report someone else's outage under our name.
    report = collect_health(supa)
    alertable = [p for p in report["problems"] if "froze nothing" in p]
    if summary["failures"]:
        alertable.append(f"journal run failed for: {', '.join(summary['failures'])}")
    alert_on_failures({**report, "problems": alertable})

    print(json.dumps(summary, default=str))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())

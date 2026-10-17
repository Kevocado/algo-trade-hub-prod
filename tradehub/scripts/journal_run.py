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

    # Failure notifier. The health report already knows the timers and the silent daily families; the
    # one thing only this function knows is whether THIS run failed, so it is added to the problems
    # before the report is rendered. `alert_on_failures` is a no-op when Telegram is not configured
    # and never raises, so a cron run is never taken down by the notifier.
    report = collect_health(supa)
    if summary["failures"]:
        report = {
            **report,
            "problems": [*report["problems"], f"journal run failed for: {', '.join(summary['failures'])}"],
        }
    alert_on_failures(report)

    print(json.dumps(summary, default=str))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())

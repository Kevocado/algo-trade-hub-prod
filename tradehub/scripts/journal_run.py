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
from tradehub.journal.registry import FORECASTERS
from tradehub.journal.runner import run_journal


def main() -> int:
    load_local_env()
    summary = run_journal(get_client(), FORECASTERS, datetime.now(UTC))
    print(json.dumps(summary, default=str))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())

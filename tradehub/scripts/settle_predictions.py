"""Cron entrypoint: settle open predictions against Kalshi market results.

Runs one settlement pass and refreshes each engine's track record, then
exits. Run hourly by the VPS `tradehub-settle.timer` — there is no
polling loop here. Simulated P&L wiring (spec section 4.5's fees+spread
term) lands with the paper-trading work; until then the gate receives
None and promotion stays blocked on that criterion.
"""

from __future__ import annotations

import json
import sys

from tradehub.core.kalshi_feed import fetch_market
from tradehub.core.supabase_client import get_client
from tradehub.settlement import run_settlement_pass
from tradehub.track_record import refresh_track_record

# (engine, cadence) pairs the cron refreshes — the spec's engine set (section
# 3.1). Cadence sets the gate's contract minimum: daily engines need 200
# settled contracts, monthly-release engines 50. `engine` values must match
# what each engine writes into predictions.engine.
ENGINES = [
    ("weather", "daily"),
    ("gas", "daily"),
    ("cpi_nowcast", "monthly"),
    ("labor_nowcast", "monthly"),
    ("crypto", "daily"),
]


def main() -> int:
    supa = get_client()
    summary = run_settlement_pass(supa, fetch_market)
    refreshed = []
    for engine, cadence in ENGINES:
        payloads = refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
        refreshed.extend(f"{engine}@{p['engine_version']}" for p in payloads)
    summary["track_record_refreshed"] = refreshed
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

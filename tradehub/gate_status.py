"""Promotion-gate lookup, shared by the scan and the API.

The gate is keyed on `(engine, engine_version)`: an engine is PROMOTED only when its latest
backtest AND its track record both say so, for that exact version. Keying on the engine alone
would let one version's promotion leak to another, and two copies of this lookup is how the
scan and the API would start disagreeing about whether an edge is tradable.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# The answer when the gate has promoted nothing, named once so there is one place to change it.
#
# It is the fail-closed direction -- it cannot make a non-tradable edge look tradable -- and it was
# written out as a bare `"SHADOW"` at four call sites across three modules. All four failed closed, so
# the duplication was harmless, but "harmless" is how a default starts disagreeing with itself: a
# reader comparing `scoreboard.py`'s default against this function's return can no longer tell a
# deliberate agreement from a coincidence, and there was no name to grep for.
#
# This module owns the concept -- `latest_gate_statuses` is what decides the value -- so the constant
# lives here and the callers import it rather than restating it.
DEFAULT_GATE_STATUS = "SHADOW"


def latest_gate_statuses(supa, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """{pair: "PROMOTED" | "SHADOW"} for every requested (engine, engine_version) pair.

    A pair with no rows, or with rows that are not both PROMOTED, is `DEFAULT_GATE_STATUS`. Failing
    closed matters: an unmatched version must not inherit another version's promotion.
    """
    statuses: dict[tuple[str, str], str] = {}
    for engine, version in pairs:
        backtest = supa.table("backtest_runs") \
            .select("engine,engine_version,gate_status,created_at") \
            .eq("engine", engine).eq("engine_version", version) \
            .order("created_at", desc=True).limit(1).execute()
        rows = list(backtest.data or [])
        if not rows or rows[0].get("gate_status") != "PROMOTED":
            statuses[(engine, version)] = DEFAULT_GATE_STATUS
            continue
        track = supa.table("track_record").select("gate_status") \
            .eq("engine", engine).eq("engine_version", version).limit(1).execute()
        track_rows = list(track.data or [])
        statuses[(engine, version)] = (
            "PROMOTED" if track_rows and track_rows[0].get("gate_status") == "PROMOTED"
            else DEFAULT_GATE_STATUS
        )
    return statuses

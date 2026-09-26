"""Promotion-gate lookup, shared by the scan and the API.

The gate is keyed on `(engine, engine_version)`: an engine is PROMOTED only when its latest
backtest AND its track record both say so, for that exact version. Keying on the engine alone
would let one version's promotion leak to another, and two copies of this lookup is how the
scan and the API would start disagreeing about whether an edge is tradable.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def latest_gate_statuses(supa, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """{pair: "PROMOTED" | "SHADOW"} for every requested (engine, engine_version) pair.

    A pair with no rows, or with rows that are not both PROMOTED, is SHADOW. Failing closed
    matters: an unmatched version must not inherit another version's promotion.
    """
    statuses: dict[tuple[str, str], str] = {}
    for engine, version in pairs:
        backtest = supa.table("backtest_runs") \
            .select("engine,engine_version,gate_status,created_at") \
            .eq("engine", engine).eq("engine_version", version) \
            .order("created_at", desc=True).limit(1).execute()
        rows = list(backtest.data or [])
        if not rows or rows[0].get("gate_status") != "PROMOTED":
            statuses[(engine, version)] = "SHADOW"
            continue
        track = supa.table("track_record").select("gate_status") \
            .eq("engine", engine).eq("engine_version", version).limit(1).execute()
        track_rows = list(track.data or [])
        statuses[(engine, version)] = (
            "PROMOTED" if track_rows and track_rows[0].get("gate_status") == "PROMOTED" else "SHADOW"
        )
    return statuses

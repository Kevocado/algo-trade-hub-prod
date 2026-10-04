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


def table_missing(exc: Exception, table: str) -> bool:
    """True when `exc` says `table` does not exist -- the table itself, not one of its columns.

    The distinction is load-bearing. Callers use this to decide "this feature has not been deployed yet",
    and fall back to legacy behaviour when it is True. A table that EXISTS but lacks a queried column
    produces its own message -- "column journal_scores.forecaster does not exist" -- which contains both
    the table name and "does not exist". Matching on those alone reported a half-migrated table as absent,
    so the read fell through to legacy records and served them as current: silent wrong data rather than
    a visible failure. So a `column ... does not exist` message is explicitly NOT a missing table.
    """
    text = str(exc)
    if "column " in text and "does not exist" in text:
        return False
    return table in text and ("schema cache" in text or "does not exist" in text or "PGRST205" in text)


def _journal_rows(supa, engine: str, version: str) -> list[dict]:
    """The journal scorecard row for this pair, or [] when the journal table does not exist yet.

    Deploy order: code can reach production before migration 20260428000014 is applied. A missing
    `journal_scores` table then means "no forecaster has moved onto the journal yet", which is
    exactly what falling through to the legacy tables says. Any other error propagates, and callers
    already treat a failed lookup as SHADOW.
    """
    try:
        result = supa.table("journal_scores").select("gate_status") \
            .eq("forecaster", engine).eq("forecaster_version", version).limit(1).execute()
    except Exception as exc:
        if table_missing(exc, "journal_scores"):
            log.info("gate: journal_scores not present yet; using the legacy gate tables")
            return []
        raise
    return list(result.data or [])


def latest_gate_statuses(supa, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """{pair: "PROMOTED" | "SHADOW"} for every requested (engine, engine_version) pair.

    A pair with no rows, or with rows that are not both PROMOTED, is `DEFAULT_GATE_STATUS`. Failing
    closed matters: an unmatched version must not inherit another version's promotion.
    """
    statuses: dict[tuple[str, str], str] = {}
    for engine, version in pairs:
        # One ledger of record (v2 spec §4): a forecaster that publishes through the journal is
        # gated by its journal scorecard alone. Its old `backtest_runs`/`track_record` rows are
        # pre-journal history and must not be able to promote it.
        journal_rows = _journal_rows(supa, engine, version)
        if journal_rows:
            statuses[(engine, version)] = (
                "PROMOTED" if journal_rows[0].get("gate_status") == "PROMOTED" else DEFAULT_GATE_STATUS
            )
            continue
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

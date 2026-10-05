"""Journal I/O against Supabase (service role). The freeze guarantees live in the database triggers
(migration 20260428000014); this module only reads, inserts, and reports what the database refused.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement

log = logging.getLogger(__name__)

CALENDARS = "journal_calendars"
FORECASTS = "journal_forecasts"
SETTLEMENTS = "journal_settlements"
SCORES = "journal_scores"
PAGE = 1000  # PostgREST returns at most 1000 rows per request, so reads page explicitly.
IN_CHUNK = 200  # keep `in.(...)` filters well under URL length limits


def select_all(supa, table: str, build: Callable[[Any], Any], order: tuple[str, ...]) -> list[dict[str, Any]]:
    """Read every matching row through ordered `.range()` pages (see api/main.py `_fetch_all`)."""
    rows: list[dict[str, Any]] = []
    lo = 0
    while True:
        query = build(supa.table(table).select("*"))
        for col in order:  # postgrest-py's order() takes ONE column per call
            query = query.order(col)
        chunk = query.range(lo, lo + PAGE - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        lo += PAGE


def _chunks(items: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(items), IN_CHUNK):
        yield items[i:i + IN_CHUNK]


def fetch_calendar(supa, targets: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(sorted(set(targets))):
        for row in select_all(supa, CALENDARS, lambda q, c=chunk: q.in_("target", c), ("target",)):
            out[row["target"]] = row
    return out


def register_calendar(supa, entries: list[CalendarEntry], now: datetime) -> int:
    """Insert calendar rows that do not exist yet and whose cutoff is still ahead. Returns the count."""
    existing = fetch_calendar(supa, [e.target for e in entries])
    fresh = [e for e in entries if e.target not in existing and e.cutoff_at > now]
    for entry in fresh:
        supa.table(CALENDARS).insert({
            "target": entry.target, "family": entry.family, "cadence": entry.cadence,
            "cutoff_at": entry.cutoff_at.isoformat(), "market_linked": entry.market_linked,
            "climatology_prob": entry.climatology_prob,
        }).execute()
    return len(fresh)


def fetch_forecasts(supa, forecaster: str, version: str, targets: list[str] | None = None) -> list[dict[str, Any]]:
    """Every frozen row for one (forecaster, version), or only `targets` when the caller names them.

    `targets` is the same filter `fetch_settlements` and `fetch_calendar` already push into the
    database, with the same chunking: a caller that wants to know about twenty of a forecaster's
    hundred thousand frozen rows should not pay for the other ninety-nine thousand and eighty. `None`
    (the default) means every target and keeps the scoring read whole; `[]` means none of them, which
    is not the same thing and is a real state -- a forecaster with no targets in this run.
    """
    def base(q):
        return q.eq("forecaster", forecaster).eq("forecaster_version", version)

    if targets is None:
        return select_all(supa, FORECASTS, base, ("id",))
    return [row for chunk in _chunks(sorted(set(targets)))
            for row in select_all(supa, FORECASTS, lambda q, c=chunk: base(q).in_("target", c), ("id",))]


# Whether `journal_forecasts.horizon_seconds` exists. `None` means "not asked yet"; the first freeze
# settles it and the answer is cached, because probing costs a round trip per run otherwise.
_HORIZON_DEPLOYED: bool | None = None


def _missing_horizon_column(exc: Exception) -> bool:
    """True when `exc` is PostgREST (or Postgres) saying the horizon column is not there.

    Both wordings matter, and the PostgREST one is the one that actually occurs. PostgREST does not
    usually say "does not exist": it answers an unknown column with `PGRST204` and a JSON body naming
    it ("Could not find the 'horizon_seconds' column of 'journal_forecasts' in the schema cache").
    Matching only the Postgres wording left the fallback unreachable in production -- the one branch
    standing between an unapplied migration and a ledger that records nothing.
    """
    text = str(exc)
    if "horizon_seconds" not in text:
        return False
    return "PGRST204" in text or "does not exist" in text or "schema cache" in text


# SQLSTATEs the `journal_calendar_guard` trigger raises with (migration 20260428000014). These are
# genuine refusals: the cutoff has passed, the target has no calendar row, or the row is immutable.
# No retry will change any of them, so they are the ONLY errors that may become a permanent gap.
_REFUSAL_CODES = frozenset({"23514", "42501", "23503"})
# Every message the trigger raises is prefixed `journal:`, which catches a refusal whose SQLSTATE did
# not survive the trip through PostgREST's JSON body.
_REFUSAL_PREFIX = "journal:"


def _is_refusal(exc: Exception) -> bool:
    """True when `exc` is the DATABASE saying no, not the network failing.

    CodeRabbit, on #48, and it is the most consequential kind of bug this journal has: `freeze()`
    caught every exception and returned False, and `run_forecaster` counts False as a MISSED
    forecast, which is never backfilled. So a dropped connection or a 500 near cutoff silently and
    permanently lost a target the forecaster could have produced -- and if the next run started after
    cutoff, that target was skipped forever and excluded from scoring.

    A refusal and a transport failure are different claims: "the database said no" versus "we never
    got to ask". Only the first may become a gap. A 5xx is deliberately NOT a refusal -- the insert may
    have succeeded server-side, and retrying is safe because the trigger refuses a duplicate target.
    """
    code = str(getattr(exc, "code", "") or "")
    if code in _REFUSAL_CODES:
        return True
    text = str(exc)
    return _REFUSAL_PREFIX in text


def freeze(supa, forecast: Forecast) -> bool:
    """Insert one frozen forecast. False when the database refused it: a gap, never a backfill.

    `horizon_seconds` arrived with migration 20260428000018, and code reaches production before
    migrations do. PostgREST rejects the WHOLE insert when it names an unknown column, and this
    function treats any insert error as "the trigger refused" -- so without the branch below, an
    unapplied migration would make the journal record NOTHING, log one warning, and report every
    target as missed. A new column would silently switch off the entire ledger.

    So a missing horizon column degrades to "the horizon was not recorded" and never to "the
    forecast was not recorded". The first is an honest gap; the second would be a lie, and the
    reader downstream could not tell the difference.
    """
    global _HORIZON_DEPLOYED
    row = {
        "forecaster": forecast.forecaster, "forecaster_version": forecast.forecaster_version,
        "target": forecast.target, "probability": round(forecast.probability, 5),
        "market_prob": round(forecast.market_prob, 5) if forecast.market_prob is not None else None,
        "source_hash": forecast.source_hash, "payload": forecast.payload,
    }
    if _HORIZON_DEPLOYED is not False:
        row["horizon_seconds"] = forecast.horizon_seconds
    try:
        supa.table(FORECASTS).insert(row).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - the trigger's refusal is the expected failure mode
        if _HORIZON_DEPLOYED is not False and _missing_horizon_column(exc):
            # Pre-migration. Retry without the column, and remember so we stop paying for the failure.
            _HORIZON_DEPLOYED = False
            log.warning("journal: horizon_seconds is not deployed yet (migration 20260428000018); "
                        "forecasts will record no horizon until it is applied")
            try:
                supa.table(FORECASTS).insert({k: v for k, v in row.items() if k != "horizon_seconds"}).execute()
                return True
            except Exception as retry_exc:  # noqa: BLE001 - fall through to the ordinary refusal path
                log.warning("journal: freeze refused for %s/%s %s: %s", forecast.forecaster,
                            forecast.forecaster_version, forecast.target, retry_exc)
                return False
        if not _is_refusal(exc):
            # Not the database saying no. Propagate so `run_journal` records the forecaster as FAILED
            # and a later run can retry while the target is still open -- rather than this becoming a
            # permanent, silent gap that scoring then excludes.
            log.exception("journal: freeze FAILED (not refused) for %s/%s %s; propagating so the run "
                          "can retry before cutoff", forecast.forecaster, forecast.forecaster_version,
                          forecast.target)
            raise
        log.warning("journal: freeze refused for %s/%s %s: %s", forecast.forecaster, forecast.forecaster_version,
                    forecast.target, exc)
        return False


def fetch_settlements(supa, targets: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for chunk in _chunks(sorted(set(targets))):
        for row in select_all(supa, SETTLEMENTS, lambda q, c=chunk: q.in_("target", c), ("target",)):
            out[row["target"]] = int(row["outcome"])
    return out


def settle(supa, settlement: Settlement) -> bool:
    try:
        supa.table(SETTLEMENTS).insert({
            "target": settlement.target, "outcome": settlement.outcome,
            "realized_value": settlement.realized_value, "source": settlement.source,
        }).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - e.g. a race with another run; retried next run
        log.warning("journal: settlement refused for %s: %s", settlement.target, exc)
        return False


# Columns added by migration 20260428000020, and whether they are deployed. `None` = not asked yet.
# Same reasoning as `_HORIZON_DEPLOYED`, and the same reason it exists: `upsert_score` spreads the whole
# card into one PostgREST upsert, so a single unknown column name rejects the ENTIRE write.
_PAIRED_BRIER_COLUMNS = ("brier_on_baseline", "n_baseline")
_PAIRED_BRIER_DEPLOYED: bool | None = None


def _missing_paired_brier(exc: Exception) -> bool:
    text = str(exc)
    if not any(col in text for col in _PAIRED_BRIER_COLUMNS):
        return False
    return "PGRST204" in text or "does not exist" in text or "schema cache" in text


def upsert_score(supa, forecaster: str, version: str, card: dict[str, Any], now: datetime) -> None:
    """Write one scorecard.

    A missing paired-Brier column degrades to "the paired figures are not recorded", never to "the
    scorecard is not written". The distinction is the whole reason this branch exists: `upsert_score` is
    the last statement in `run_forecaster`, so a rejected upsert leaves freezes and settlements
    committed while every score silently freezes at its last written value. Nothing would look broken --
    the ledger would keep filling and every scorecard would be stale, which is the worst failure shape
    in this repo. An absent figure is visible; a stale one is not.
    """
    global _PAIRED_BRIER_DEPLOYED
    row = {"forecaster": forecaster, "forecaster_version": version,
           **card, "computed_at": now.isoformat()}

    def _write(payload: dict[str, Any]) -> None:
        supa.table(SCORES).upsert(payload, on_conflict="forecaster,forecaster_version").execute()

    if _PAIRED_BRIER_DEPLOYED is False:
        row = {k: v for k, v in row.items() if k not in _PAIRED_BRIER_COLUMNS}
    try:
        _write(row)
        return
    except Exception as exc:  # noqa: BLE001 - classified below, or propagated as a real failure
        if _PAIRED_BRIER_DEPLOYED is False or not _missing_paired_brier(exc):
            raise
        _PAIRED_BRIER_DEPLOYED = False
        log.warning("journal: paired Brier columns are not deployed yet (migration 20260428000020); "
                    "scorecards will record no paired figures until it is applied")
        _write({k: v for k, v in row.items() if k not in _PAIRED_BRIER_COLUMNS})

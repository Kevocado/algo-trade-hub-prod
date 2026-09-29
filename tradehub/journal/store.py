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
        chunk = build(supa.table(table).select("*")).order(*order).range(lo, lo + PAGE - 1).execute().data or []
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


def fetch_forecasts(supa, forecaster: str, version: str) -> list[dict[str, Any]]:
    return select_all(supa, FORECASTS,
                      lambda q: q.eq("forecaster", forecaster).eq("forecaster_version", version), ("id",))


def freeze(supa, forecast: Forecast) -> bool:
    """Insert one frozen forecast. False when the database refused it: a gap, never a backfill."""
    try:
        supa.table(FORECASTS).insert({
            "forecaster": forecast.forecaster, "forecaster_version": forecast.forecaster_version,
            "target": forecast.target, "probability": round(forecast.probability, 5),
            "market_prob": round(forecast.market_prob, 5) if forecast.market_prob is not None else None,
            "source_hash": forecast.source_hash, "payload": forecast.payload,
        }).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - the trigger's refusal is the expected failure mode
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


def upsert_score(supa, forecaster: str, version: str, card: dict[str, Any], now: datetime) -> None:
    supa.table(SCORES).upsert({"forecaster": forecaster, "forecaster_version": version,
                               **card, "computed_at": now.isoformat()},
                              on_conflict="forecaster,forecaster_version").execute()

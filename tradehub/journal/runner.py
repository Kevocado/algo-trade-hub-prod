"""One journal run: for every registered forecaster, freeze -> settle -> score, isolated per forecaster.

Failure rules (spec §4): a missed freeze is a gap that is logged and never backfilled; an unsettled
target is retried on the next run; scoring is an idempotent recompute.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from tradehub.journal import store
from tradehub.journal.contract import Forecaster, require_aware
from tradehub.journal.scoring import score

log = logging.getLogger(__name__)


def run_forecaster(supa, fc: Forecaster, now: datetime) -> dict[str, Any]:
    # A wrapper that reads the store (MarketShrunk) must read THIS run's client, not the singleton its
    # constructor was wired to. Optional, so a plain forecaster is unaffected.
    bind = getattr(fc, "bind_store", None)
    if callable(bind):
        bind(supa)
    summary: dict[str, Any] = {"registered": 0, "frozen": 0, "missed": 0, "settled": 0, "gate_status": None}
    entries = [e for e in fc.targets(now) if e.cadence == fc.cadence]
    summary["registered"] = store.register_calendar(supa, entries, now)

    existing = store.fetch_forecasts(supa, fc.name, fc.version)
    frozen = {row["target"] for row in existing}
    for entry in entries:
        if entry.target in frozen or entry.cutoff_at <= now:
            continue
        forecast = fc.forecast(entry, now)
        if forecast is None:
            summary["missed"] += 1
            log.info("journal: %s/%s has no forecast for %s (gap, not backfilled)", fc.name, fc.version, entry.target)
            continue
        if forecast.forecaster != fc.name or forecast.forecaster_version != fc.version or forecast.target != entry.target:
            raise ValueError(f"{fc.name}: forecast identity does not match its forecaster/target")
        # Spec §3's `horizon`, derived here because the calendar entry is in hand and no forecaster
        # should have to compute it. Whole seconds, floored at 0: the runner has already skipped any
        # entry whose cutoff has passed, but a sub-second straddle must not write a negative horizon.
        # `Forecast` is a frozen dataclass, so this is a new value rather than a mutation.
        forecast = replace(forecast, horizon_seconds=max(0, int((entry.cutoff_at - now).total_seconds())))
        if store.freeze(supa, forecast):
            summary["frozen"] += 1
        else:
            summary["missed"] += 1

    rows = store.fetch_forecasts(supa, fc.name, fc.version)
    targets = [r["target"] for r in rows]
    calendar = store.fetch_calendar(supa, targets)
    settled = store.fetch_settlements(supa, targets)
    for target in targets:
        cutoff = calendar.get(target, {}).get("cutoff_at")
        if target in settled or cutoff is None or datetime.fromisoformat(str(cutoff)) > now:
            continue
        result = fc.settle(target, now)
        if result is not None and store.settle(supa, result):
            settled[target] = result.outcome
            summary["settled"] += 1

    card = score(rows, settled, calendar, fc.cadence)
    store.upsert_score(supa, fc.name, fc.version, card, now)
    summary["gate_status"] = card["gate_status"]
    return summary


def run_journal(supa, forecasters: list[Forecaster], now: datetime) -> dict[str, Any]:
    require_aware(now, "now")
    out: dict[str, Any] = {"as_of": now.isoformat(), "forecasters": {}, "failures": []}
    for fc in forecasters:
        key = f"{fc.name}@{fc.version}"
        try:
            out["forecasters"][key] = run_forecaster(supa, fc, now)
        except Exception as exc:
            log.exception("journal: %s failed", key)
            out["forecasters"][key] = {"error": f"{type(exc).__name__}: {exc}"}
            out["failures"].append(key)
    return out

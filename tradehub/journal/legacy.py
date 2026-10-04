"""One record per engine (v2 spec §4): the journal's scorecard replaces the legacy track record.

`predictions` is now a per-scan telemetry table (the CPI display and the sports hub calibration still
read its latest rows), not a ledger. For an engine that has a journal scorecard, the legacy
`track_record` rollup is no longer refreshed and no longer served: two live rollups with two headline
numbers for one engine is the failure this module prevents. Engines with no journal scorecard (weather,
gas, crypto) keep their legacy rollup untouched.

An engine is "on the journal" when any journal scorecard carries its name as `forecaster`, whatever the
version: the legacy versions (`cpi-v1`, `feed:ridge@...`) and the journal's are separate keys.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tradehub.journal.store import select_all
from tradehub.gate_status import table_missing


def journal_scores(supa) -> list[dict[str, Any]]:
    """Every journal scorecard, or [] when the journal table has not been deployed yet.

    Paged, because `journal_engines` built from this decides which engines are journal-backed: an
    unpaged read stops at PostgREST's 1,000-row default, so every scorecard past the cap was invisible
    and its engine fell back to the legacy tables as if it had never moved onto the journal.
    """
    try:
        # Both keys, not just `forecaster`: the pair is the table's PRIMARY KEY, so it is a TOTAL order.
        # One key is not -- two versions of one forecaster have undefined relative order, and
        # `select_all` pages with a separate `.range()` per page, so a version could be duplicated
        # across pages or dropped, and a dropped version vanishes from `merge_track_record()`.
        return select_all(supa, "journal_scores", lambda q: q.select("*"),
                          ("forecaster", "forecaster_version"))
    except Exception as exc:
        if table_missing(exc, "journal_scores"):
            return []
        raise


def journal_engines(scores: Iterable[dict[str, Any]]) -> set[str]:
    return {str(s["forecaster"]) for s in scores}


def journal_track_row(score: dict[str, Any]) -> dict[str, Any]:
    """One scorecard in the legacy `track_record` row shape, tagged so the reader knows where it came from.

    `n_settled`, `brier_ours` and `brier_market` are ONE comparison here, and they are one sample: the
    baseline-matched one (`brier_on_baseline`/`n_baseline`, migration 20260428000020), which is also the
    sample `bss` was computed from. So `1 - brier_ours/brier_market` is this row's own `bss`. They used to
    be `n_settled`/`brier` -- every settled target -- beside `brier_baseline`, which covers only the
    targets that HAVE a baseline, so the ratio every reader of this shape computes was an all-targets
    mean over a matched mean and was not the `bss` carried in the same row. Three denominators in one row.

    The wider sample is still here, under names that say what they cover, because dropping it would lose
    the settled count a caller may want. A scorecard written before the matched columns existed has no
    matched pair at all: it falls back to the all-settled pair, which is consistent with itself, rather
    than reporting `n_settled: null` for a card with hundreds of settled targets.
    """
    market = score.get("baseline") == "market"
    matched = score.get("n_baseline") is not None
    return {
        "engine": score["forecaster"],
        "engine_version": score["forecaster_version"],
        "n_settled": score.get("n_baseline") if matched else score.get("n_settled"),
        "brier_ours": score.get("brier_on_baseline") if matched else score.get("brier"),
        "brier_market": score.get("brier_baseline") if market else None,
        "cal_buckets": score.get("reliability") or [],
        "max_cal_dev": None,
        "gate_status": score.get("gate_status"),
        "updated_at": score.get("computed_at"),
        "source": "journal",
        "baseline": score.get("baseline"),
        "bss": score.get("bss"),
        "calibration_ready": score.get("calibration_ready"),
        # The all-settled figures, labelled: `brier_ours`/`n_settled` above are the matched sample.
        "n_settled_all": score.get("n_settled"),
        "brier_all": score.get("brier"),
    }


def merge_track_record(legacy_rows: Iterable[dict[str, Any]], scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy rows for engines NOT on the journal, plus a row per journal scorecard, ordered by engine."""
    on_journal = journal_engines(scores)
    rows = [{**r, "source": "legacy"} for r in legacy_rows if r.get("engine") not in on_journal]
    rows += [journal_track_row(s) for s in scores]
    return sorted(rows, key=lambda r: (str(r["engine"]), str(r.get("engine_version"))))

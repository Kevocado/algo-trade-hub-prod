"""Reduce `backtest_runs` to one honest row per engine, for the scoreboard.

Pure on purpose: no I/O, so every rule below is testable without a database, and
so a reviewer can check the arithmetic rather than the plumbing.

The rule that matters: a run whose `engine_version` carries a decision lead is an
EXPERIMENT, not the engine's record. Gas is 4.29x behind the market at the
production 2h and 2.16x behind at 12h (#24), so the two runs disagree about the
engine, and this page exists to answer whether to trust an engine. Presenting the
12h run as the record would make the page wrong in the direction that flatters the
engine. Experiments are therefore excluded rather than footnoted: a footnote is
something a reader skips, an absent row is something they cannot misread. The runs
stay in `backtest_runs` and stay reproducible from the CLI.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from tradehub.sports.scorecard import MIN_SETTLED

# Any occurrence of the marker, NOT the anchored `-lead<number>h` form.
#
# The anchored version was tried first and has a hole: a malformed `gas-v1-lead` (missing the
# number and the h) does not match it and so reads as the production engine -- which is exactly the
# direction that must not fail. Unanchored is safe because no real production version contains
# "lead": they are gas-v1, weather-v1, cpi-v1, cpi-core-v1, labor-v1
# (`tests/test_scoreboard_reduction.py::TestBacktestRunsProvenance` pins that list to the
# two CLI writers rather than to this comment).
EXPERIMENT_VERSION = re.compile(r"-lead")

# The gate's own words. `check_promotion_gate` (`tradehub/track_record.py:144`) writes
#
#     "only {n_settled} settled contracts, need {min_contracts} ({cadence})"
#
# so the number FOLLOWS "need" and is NOT itself followed by "settled". The plan this task was
# written from matched `need (\d+) settled`, which never matches the string the gate really emits,
# so every engine would have rendered as having no stated bar and no distance to it at all.
# `\b` rather than a literal word reads both the real wording and the "... need 200 settled (daily)"
# phrasing the plan assumed, without matching the gate's other four reasons (none of which contain
# "need" followed by a number).
_REQUIRED_IN_REASON = re.compile(r"need\s+(\d+)\b", re.IGNORECASE)


def is_experiment_version(engine_version: Any) -> bool:
    """True for anything that is not plainly the production version.

    Fails safe: an absent, empty or unrecognised version is treated as an
    experiment, so a new tagging scheme cannot silently start being presented as
    an engine's record.
    """
    if not isinstance(engine_version, str) or not engine_version:
        return True
    return bool(EXPERIMENT_VERSION.search(engine_version))


def brier_ratio(brier_ours: Any, brier_market: Any) -> float | None:
    """How many times worse our Brier is than the market's. `None` when undefined.

    A zero or absent market Brier has no defined ratio, and returning a number
    there would be inventing one. Below 1.0 is a real answer -- an engine better
    than the market -- and is passed through unchanged.
    """
    if not isinstance(brier_ours, (int, float)) or not isinstance(brier_market, (int, float)):
        return None
    if brier_market <= 0:
        return None
    return round(float(brier_ours) / float(brier_market), 4)


def required_settled(gate_reasons: Iterable[Any] | None, min_settled: int | None) -> int | None:
    """The settled count this engine's gate requires, or `None` if it does not say.

    The gate already states its own requirement in `gate_reasons`, so it is read
    from there rather than hardcoded per engine -- the bars genuinely differ (200
    for a daily engine, 50 for a monthly one, `MIN_CONTRACTS`), and duplicating
    them here would be a second place to get wrong.

    `min_settled` is the floor to fall back on when the gate states no bar; it is
    a floor, never a ceiling, so a stated bar always wins. `None` is returned when
    there is nothing to compare against -- never 0, which would render as "0 of 0"
    and so read as having met the gate.
    """
    for reason in gate_reasons or []:
        if not isinstance(reason, str):
            continue
        match = _REQUIRED_IN_REASON.search(reason)
        if match:
            return int(match.group(1))
    if isinstance(min_settled, int) and min_settled > 0:
        return min_settled
    return None


def settled_distance(n_settled: Any, required: int | None) -> dict[str, Any] | None:
    """How much settled evidence is still needed, or `None` if the bar is unknown.

    `pct` is capped at 100 and floored at 0: a run past the bar is "met", not
    "312% of the way to a gate it cleared", and a nonsense count cannot render as
    a negative fraction of a bar.
    """
    if required is None or not isinstance(n_settled, (int, float)):
        return None
    required = int(required)
    if required <= 0:
        return None
    met = int(n_settled) >= required
    return {
        "n_settled": int(n_settled),
        "required": required,
        "remaining": max(0, required - int(n_settled)),
        "met": met,
        "pct": min(100.0, max(0.0, round(100.0 * int(n_settled) / required, 1))),
    }


def _recency(run: Mapping[str, Any]) -> tuple[int, float, str]:
    """Sort key for "which run is newer". Bigger wins.

    `created_at` is a `timestamptz` (`market_sentiment_tool/supabase/migrations/
    20260416000004_backtest_runs.sql:28`), which PostgREST renders in the
    response's own offset -- so `2026-09-19T20:00:00-05:00` is later than the
    `2026-09-20T00:00:00+00:00` it sorts before as a string. It is compared as an
    instant. A run whose timestamp cannot be read still gets a row: it simply
    sorts below any run whose timestamp can, rather than crashing the page.

    On an exact tie the earlier run in the input wins, matching the strict `>`
    comparison and leaving the choice visible in the caller's ordering.
    """
    raw = run.get("created_at")
    if not isinstance(raw, str) or not raw:
        return (0, 0.0, "")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return (0, 0.0, raw)
    if moment.tzinfo is None:  # the column is timestamptz; assume UTC rather than local time
        moment = moment.replace(tzinfo=UTC)
    return (1, moment.timestamp(), raw)


def current_runs(runs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per (engine, mode), from the newest production run.

    `mode` is part of the key: taker and maker are different fills and different
    economics, so collapsing them would blend two experiments into a number that
    means neither.

    Nothing else filters a run out. A losing engine, an engine with no Brier, an
    engine whose gate is failing -- all of them are what the page is for, and an
    absent row is a claim the page cannot then make honestly. Only experiments are
    excluded, and they are excluded because presenting one as the engine's record
    would be a false claim, not because it is unflattering.
    """
    best: dict[tuple[str, str], Mapping[str, Any]] = {}
    for run in runs or []:
        engine = run.get("engine")
        if not engine or is_experiment_version(run.get("engine_version")):
            continue
        key = (str(engine), str(run.get("mode") or ""))
        seen = best.get(key)
        if seen is None or _recency(run) > _recency(seen):
            best[key] = run

    out: list[dict[str, Any]] = []
    for (engine, mode), run in sorted(best.items()):
        reasons = run.get("gate_reasons") or []
        out.append({
            "engine": engine,
            "engine_version": run.get("engine_version"),
            "mode": mode,
            "date_from": run.get("date_from"),
            "date_to": run.get("date_to"),
            "created_at": run.get("created_at"),
            "n_decisions": run.get("n_decisions"),
            "n_fills": run.get("n_fills"),
            "n_settled": run.get("n_settled"),
            "brier_ours": run.get("brier_ours"),
            "brier_market": run.get("brier_market"),
            "brier_ratio": brier_ratio(run.get("brier_ours"), run.get("brier_market")),
            "pnl_after_fees": run.get("pnl_after_fees"),
            "max_drawdown": run.get("max_drawdown"),
            "gate_status": run.get("gate_status") or "SHADOW",
            "gate_reasons": reasons,
            "settled_distance": settled_distance(
                # The gate's own bar when it states one; the product's settled-evidence floor
                # when it does not. `MIN_SETTLED` is imported, never written out.
                #
                # Known and accepted: a monthly-cadence engine (bar 50, `MIN_CONTRACTS`) holding
                # 50-99 settled contracts has already met its own bar, so the gate states nothing
                # and this reports it against the 100 floor. The row's own `gate_reasons` carries
                # what is actually blocking it, so the row is not silently wrong -- but the settled
                # cell reads stricter than the gate. Flagged in task-1-report.md for a ruling.
                run.get("n_settled"), required_settled(reasons, MIN_SETTLED)
            ),
        })
    return out

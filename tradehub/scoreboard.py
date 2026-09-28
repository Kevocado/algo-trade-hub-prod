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

The second rule: TWO bars, never one. The gate states its own settled requirement, and it
differs by cadence (200 daily, 50 monthly, `MIN_CONTRACTS`); the reviewer has a separate, flat
evidence floor (`MIN_SETTLED`). A monthly engine holding 70 settled contracts has met its own 50
bar, so reporting it as 70/100 with met=False is a verdict against a number that was never its
bar. So `settled_distance` carries both bars and `required_source` says which one the verdict is
made against. The floor is reported on every row, on its own fields, because the reviewer is the
component that will eventually make the keep-or-drop call.

The third rule, added with the endpoint: the page's headline is computed HERE, not in the route.
"Is this engine ahead of the market" has a threshold in it -- ratio > 1.0 -- and the moment the
route answers that as well as this module, the API and the page hold two copies of the same
verdict and nothing downstream can tell which one drifted. `market_comparison` is that threshold,
in one place, pure and tested.

The fourth rule, added with the page: `market_verdict` puts the same threshold ON THE ROW, so the
browser renders a word rather than comparing ratios in TypeScript. `market_comparison` buckets on
it too, which is what makes "the row says behind" and "the headline counts it behind" the same
statement. The headline is a claim about ENGINES and the buckets count ROWS, so `headline_kind`
and `caveat` travel with it: the page is obliged to render the caveat beside the headline, and it
cannot do that from a value it had to compose itself.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from tradehub.gate_status import DEFAULT_GATE_STATUS
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

# Which bar `settled_distance`'s verdict is against, reported as `required_source` so a reader
# never has to infer it from the number alone.
#
# There are two bars and they are not the same bar. The gate states its own requirement, which
# differs by cadence (200 daily, 50 monthly -- `MIN_CONTRACTS`). The reviewer's settled-evidence
# floor is a flat `MIN_SETTLED`. The defect these three names exist to prevent is a RIGHT NUMBER
# UNDER THE WRONG LABEL: a monthly engine holding 70 settled contracts has met its own 50 bar,
# and reporting that as 70/100 -- unmet -- is a verdict against a number that was never its bar.
#
#   SOURCE_GATE     the gate named a bar, so the engine is short of it and that bar is authoritative
#   SOURCE_ENGINE   the gate ran and named none, so the engine has met its own (unstateable) bar
#   SOURCE_UNKNOWN  nothing in the row shows the gate ran, so nothing is claimed
SOURCE_GATE = "gate"
SOURCE_ENGINE = "engine"
SOURCE_UNKNOWN = "unknown"

# The four sentences the page's headline can be. Four, not two, because "no engine beats the
# market" is a claim about ENGINES and there are two states in which making it would be a lie:
#
#   nothing was recorded      there is no run to make a claim about
#   nothing was comparable    the market Brier was never recorded, so we measured nothing
#
# and one in which it is true but incomplete:
#
#   some rows comparable, none ahead   true as a universal statement, and `rows_not_comparable`
#                                      rides beside it as the number that says how much of the
#                                      board it actually covers
#
# The wording lives here, in the data, rather than in a note the page renders, because prose is
# what nobody re-reads when the number is what they look at. "on Brier", not "after fees": a
# Brier ratio is a comparison of forecast accuracy and carries no fee adjustment at all, so
# "after fees" attributes to the number a meaning it does not have.
HEADLINE_NO_RUNS = "No backtest runs are recorded yet, so no engine has a record to show."
HEADLINE_NOT_COMPARABLE = "No engine run could be compared: no market Brier was recorded at decision time."
HEADLINE_BEHIND = "No engine beats the market on Brier."
HEADLINE_AHEAD = (
    "At least one engine beats the market on Brier. Check the settled count before reading that "
    "as an edge."
)

# Above this the model is behind the market. 1.0 exactly is LEVEL -- neither behind nor ahead.
# Rounding a tie into a loss would be a claim the numbers do not make, and it is the same
# direction of error as a losing engine being dropped: a number that is more flattering than the
# data.
BEHIND_THE_MARKET = 1.0

# The four verdicts one row can carry against the market. `VERDICT_NOT_COMPARABLE` is the load-
# bearing one: an unrecorded `brier_market` is a measurement nobody made, never a defeat, and it
# is a separate state rather than a fifth flavour of "behind" so that no count can quietly absorb
# it.
VERDICT_AHEAD = "ahead"
VERDICT_BEHIND = "behind"
VERDICT_LEVEL = "level"
VERDICT_NOT_COMPARABLE = "not_comparable"


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


def stated_settled_bar(gate_reasons: Iterable[Any] | None) -> int | None:
    """The settled count the gate names in its own reasons, or `None` if it names none.

    This is the primitive behind the two bars, and it deliberately does NOT fall back to a
    floor: "the gate named 50" and "the gate named nothing" are different facts about the
    engine, and collapsing them is what made a cleared monthly engine render as failing.

    A bar of zero is not a bar -- the same rule `required_settled` applies to a floor of zero --
    so a "need 0" reading counts as silence rather than as a bar met at zero.
    """
    for reason in gate_reasons or []:
        if not isinstance(reason, str):
            continue
        match = _REQUIRED_IN_REASON.search(reason)
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def required_settled(gate_reasons: Iterable[Any] | None, min_settled: int | None) -> int | None:
    """The settled count to fall back on: the gate's own bar if it stated one, else `min_settled`.

    Kept as the flat answer for callers that only want a number to compare against. Callers
    that care WHICH bar they are comparing against -- the scoreboard row does -- must use
    `stated_settled_bar`, because this function's answer cannot say where it came from.

    `min_settled` is a floor, never a ceiling, so a stated bar always wins. `None` is returned
    when there is nothing to compare against -- never 0, which would render as "0 of 0" and so
    read as having met the gate.
    """
    stated = stated_settled_bar(gate_reasons)
    if stated is not None:
        return stated
    if isinstance(min_settled, int) and min_settled > 0:
        return min_settled
    return None


def settled_distance(
    n_settled: Any,
    required: int | None = None,
    *,
    required_source: str = SOURCE_GATE,
    floor: int | None = None,
) -> dict[str, Any] | None:
    """Both bars, and which one the verdict is against.

    `required` is the bar `met` is a verdict ON, and `required_source` says where that bar came
    from, so the number and its attribution cannot be read apart:

    - `SOURCE_GATE`: the gate named a bar in its reasons. That bar is authoritative, and
      `met`/`remaining`/`pct` are measured against it.
    - `SOURCE_ENGINE`: the gate ran and named no bar, so the engine has met its own bar
      (`check_promotion_gate` names a bar only when `n_settled < min_contracts`,
      `tradehub/track_record.py:143`). The bar is unstateable from a `backtest_runs` row --
      `cadence` is not a column -- so `required` is `None` and `met` is `True`. That is the
      whole point: a monthly engine holding 70 settled has cleared its 50 bar, and reporting
      it as 70/100 would be a verdict against a number that was never its bar.
    - `SOURCE_UNKNOWN`: nothing in the row shows the gate ran, so `met` stays `None`. Silence
      is not a pass, which is the same fail-closed direction as the `SHADOW` default on the row.

    `floor` is `MIN_SETTLED`, the reviewer's own settled-evidence bar, reported on its own
    `floor_*` fields and reported ALWAYS -- including when the gate states its own bar, because
    "distance to the gate" is half the approval and the reviewer is the component that will
    eventually make the keep-or-drop call. It is never the bar `met` is judged against.

    `None` rather than a guess: an unreadable count, a non-positive bar, an unrecognised
    `required_source`, or a `required` that disagrees with its own `required_source` all yield
    `None` instead of a number nobody downstream can attribute.

    `pct` is capped at 100 and floored at 0: a run past a bar is "met", not "312% of the way to
    a gate it cleared", and a nonsense count cannot render as a negative fraction of a bar.
    """
    if not isinstance(n_settled, (int, float)) or required_source not in (
        SOURCE_GATE, SOURCE_ENGINE, SOURCE_UNKNOWN
    ):
        return None
    count = int(n_settled)

    # A `required` is only ever believed when it is attributed to the gate. A bar filed under
    # any other source is the mislabel this shape exists to prevent, so it is refused rather
    # than rendered -- and the caller's disagreement is not silently corrected either.
    if required_source == SOURCE_GATE:
        if not isinstance(required, (int, float)) or int(required) <= 0:
            return None
        bar: int | None = int(required)
    elif required is not None:
        return None
    else:
        bar = None

    floor_bar = int(floor) if isinstance(floor, (int, float)) and int(floor) > 0 else None

    out: dict[str, Any] = {
        "n_settled": count,
        "required": bar,
        "required_source": required_source,
        "remaining": None,
        "met": None,
        "pct": None,
        "floor": floor_bar,
        "floor_remaining": None,
        "floor_met": None,
        "floor_pct": None,
    }

    if bar is not None:
        out["remaining"] = max(0, bar - count)
        out["met"] = count >= bar
        out["pct"] = min(100.0, max(0.0, round(100.0 * count / bar, 1)))
    elif required_source == SOURCE_ENGINE:
        out["remaining"] = 0
        out["met"] = True

    if floor_bar is not None:
        out["floor_remaining"] = max(0, floor_bar - count)
        out["floor_met"] = count >= floor_bar
        out["floor_pct"] = min(100.0, max(0.0, round(100.0 * count / floor_bar, 1)))

    return out


def market_verdict(ratio: Any) -> str:
    """Where one row stands against the market, as one of the four `VERDICT_*` values.

    The single application of `BEHIND_THE_MARKET`, and it exists because the PAGE has to say the
    same thing per row. Without it the browser would hold `ratio > 1.0` in TypeScript and this
    module would hold it in Python, and the two would drift with nothing downstream able to tell
    which one the reader was shown. `market_comparison` buckets on this function rather than
    re-implementing it, so a row's own verdict and the headline's counts cannot disagree.

    The parameter is `ratio`, not `brier_ratio`: the latter is this module's own function, and a
    parameter that shadows it inside a module about having ONE copy of everything is a trap for the
    next reader -- the obvious next edit is `ratio = brier_ratio(ratio)`, which is `brier_ratio` of
    itself and a TypeError.

    `bool` is refused because `bool` is an `int`: a stray `True` would otherwise be a measured
    1.0, which is a tie invented out of a value that is not a measurement. Absent and
    non-numeric are the same fact -- the market Brier was not recorded, so nothing was compared.
    """
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        return VERDICT_NOT_COMPARABLE
    if ratio != ratio:  # NaN: the one float that compares false to itself
        return VERDICT_NOT_COMPARABLE
    if ratio > BEHIND_THE_MARKET:
        return VERDICT_BEHIND
    if ratio < BEHIND_THE_MARKET:
        return VERDICT_AHEAD
    return VERDICT_LEVEL


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
        raw_reasons = run.get("gate_reasons")
        reasons = raw_reasons or []
        status = run.get("gate_status") or DEFAULT_GATE_STATUS

        # Which bar the settled verdict is against. `check_promotion_gate` names a bar only
        # when n_settled < min_contracts (tradehub/track_record.py:143), so a gate that ran and
        # named no bar is positive evidence the engine met its own -- measured against the live
        # gate in tests::TestTwoBars::test_the_gate_names_a_bar_only_when_the_engine_is_short.
        # Silence is only that evidence if the gate demonstrably ran, hence the two branches.
        stated = stated_settled_bar(reasons)
        if stated is not None:
            required, required_source = stated, SOURCE_GATE
        elif isinstance(raw_reasons, list) or status == "PROMOTED":
            required, required_source = None, SOURCE_ENGINE
        else:
            # No reasons at all and not promoted: nothing here shows the gate ran, so this claims
            # nothing rather than reading absence of a complaint as a pass.
            required, required_source = None, SOURCE_UNKNOWN

        ratio = brier_ratio(run.get("brier_ours"), run.get("brier_market"))

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
            "brier_ratio": ratio,
            # The page renders this rather than re-deriving it: `BEHIND_THE_MARKET` is a threshold,
            # and a second copy of it in the browser is a second thing to keep wrong.
            "market_verdict": market_verdict(ratio),
            "pnl_after_fees": run.get("pnl_after_fees"),
            "max_drawdown": run.get("max_drawdown"),
            "gate_status": status,
            "gate_reasons": reasons,
            # `MIN_SETTLED` is the reviewer's floor, imported and never written out. It rides
            # along on its own fields whether or not the gate states a bar, and is never the
            # bar `met` is judged against -- see `settled_distance`.
            "settled_distance": settled_distance(
                run.get("n_settled"),
                required,
                required_source=required_source,
                floor=MIN_SETTLED,
            ),
        })
    return out


def market_comparison(rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """How the scoreboard's rows stand against the market, and the sentence to take away.

    Consumes the row shape `current_runs` produces -- so it reads the `brier_ratio` that
    `brier_ratio()` already computed, and never re-derives a ratio of its own.

    **Every row lands in exactly one bucket, and the four counts sum to `rows_total`.** A row
    that is silently uncounted is how "3 of 5 engines are behind" becomes true of a board of
    five; `test_every_row_lands_in_exactly_one_bucket` pins the sum for that reason.

    The buckets are named `rows_*` and not `engines_*` because they count ROWS, and a row is one
    (engine, mode) pair: weather in both taker and maker is two rows and one engine. The old
    name would have made "1 of 3 engines behind" a sentence about a board that had two engines in
    it, which is the right-number-wrong-label defect this module keeps refusing.

    `headline` is a universal claim about ENGINES, which is why `rows_not_comparable` does not
    make it false -- no engine beat the market is still true when some engines were never
    compared. It does make it incomplete, so the count travels beside it as a number rather than
    being folded into the sentence. An absent `brier_ratio` is a row we could not measure, never
    a row that lost.

    `headline_kind` and `caveat` are the same argument made machine-readable, for the page:

    - `headline_kind` names which of the four headlines this is. The page cannot infer it, because
      `any_beats_market` is False for BEHIND and for NOT_COMPARABLE alike, so a page that styled
      off that flag would colour a board nobody measured as though it had lost.
    - `caveat` is the sentence qualifying the headline, present exactly when some row was not
      comparable, and it names the count and the size of the board. The page is obliged to render
      it beside the headline, and a value it can only pass through is one it cannot quietly drop.
    """
    behind = ahead = level = missing = 0
    for row in rows or []:
        # Routed through `market_verdict` so the count and the per-row verdict the page renders are
        # the same application of the same threshold, not two implementations of it. A dict rather
        # than a `match`: the `VERDICT_*` values are bare names, which a `case` arm would read as
        # a capture pattern and shadow.
        verdict = market_verdict(row.get("brier_ratio"))
        if verdict == VERDICT_BEHIND:
            behind += 1
        elif verdict == VERDICT_AHEAD:
            ahead += 1
        elif verdict == VERDICT_LEVEL:
            level += 1
        else:
            missing += 1

    total = behind + ahead + level + missing
    if total == 0:
        headline, kind = HEADLINE_NO_RUNS, "no_runs"
    elif behind + ahead + level == 0:
        headline, kind = HEADLINE_NOT_COMPARABLE, "not_comparable"
    elif ahead:
        headline, kind = HEADLINE_AHEAD, "ahead"
    else:
        headline, kind = HEADLINE_BEHIND, "behind"
    return {
        "rows_total": total,
        "rows_behind_market": behind,
        "rows_ahead_of_market": ahead,
        "rows_level_with_market": level,
        "rows_not_comparable": missing,
        "any_beats_market": ahead > 0,
        "headline": headline,
        "headline_kind": kind,
        "caveat": (
            None if not missing else
            f"{missing} of {total} rows could not be compared: no market Brier was recorded for "
            f"them, so the headline does not rest on those rows."
        ),
    }

"""What every engine in this product CLAIMS to predict, joined to what it actually scored.

Pure, like `tradehub/scoreboard.py`, so every rule below is testable without a database.

**Why this module exists.** The product had a War Room, a Prediction Lab, a shadow backtester, a
sports-edges page, a jobs scorecard, a CPI display and an engine scoreboard, and no page that
answered the owner's question: *what are the models, what are they doing, and how did they do?*
Every page is downstream of that answer and none of them gives it. This module is the answer's
data half; `market_sentiment_tool/src/lib/models.ts` words it and `src/pages/Models.tsx` draws it.

**Why the claims live here and not in the React component.** A claim is a statement about what an
engine predicts, and it is checkable against the engine that makes the prediction -- the same
sentence has to survive next to the code in `tradehub/engines/gas.py` that does the predicting.
Written in a component, it drifts silently: the engine's target changes, the page does not, and
nothing in CI can tell, because a string in JSX has no test that can fail. So the claim is data
here, in the same language as the engine that has to honour it.

**The rule that matters, and it is the same one the scoreboard already keeps.** An engine with no
backtest run is ABSENT from `backtest_runs`, and an absent engine reads as "this engine has nothing
to show", which is a claim about the engine that nobody made. So the catalogue is authoritative
about which engines EXIST and the scoreboard is authoritative about what was MEASURED, and this
module joins them so every engine appears either way. `engines_not_measured` is the number that
makes the gap countable rather than invisible, and `not_measured` is a status of its own, never a
zero and never a row of dashes.

**Nothing here re-derives anything the scoreboard already decided.** The Brier ratio, the
`market_verdict`, the settled distance and both bars all arrive on the row and ride out untouched.
This module only adds three things the row cannot carry: WHICH engines exist, what each one claims,
and one status word rolling up that engine's rows -- and that roll-up is a roll-up of the
`VERDICT_*` words `market_verdict` already returned, never a second application of
`BEHIND_THE_MARKET`.

**The roll-up is pessimistic on purpose.** An engine can have more than one row (taker and maker are
different fills), and its rows can disagree. `behind` beats `ahead` beats `level` beats
`not_comparable`, so a mixed engine is reported at its worst row. The alternative is choosing which
row to lead with, and that is a choice made in a component, silently, in whichever direction the
person writing it happened to prefer. Every row is still carried on the entry, so the worst row is
never the only figure a reader can see -- it is the one the summary line is built from.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from tradehub.scoreboard import (
    VERDICT_AHEAD,
    VERDICT_BEHIND,
    VERDICT_LEVEL,
    VERDICT_NOT_COMPARABLE,
    market_verdict,
)

# An engine that has a row but was never measured against a market, and an engine with no row at
# all, are DIFFERENT facts and are not collapsed:
#
#   not_comparable   the run exists; no market Brier was recorded at decision time, so nothing was
#                    compared. We know what was decided and we cannot say whether it was good.
#   not_measured     there is no backtest run for this engine. We know nothing about its accuracy,
#                    which is not the same as knowing it is bad -- or good.
#
# `not_measured` is NOT a `VERDICT_*` value and is not a verdict on the engine at all: it is the
# absence of a verdict. It lives here rather than in `tradehub/scoreboard.py` because it is a
# statement about the CATALOGUE meeting the scoreboard, which is this module's whole job.
STATUS_NOT_MEASURED = "not_measured"

# A deleted engine does not vanish from the page: it leaves a tombstone (v2 spec §9), so the
# truthfulness story survives the deletion. `retired` is a sixth status and, like `not_measured`, it is
# not a verdict on the engine's accuracy. Its backtest history, if any, stays attached and visible.
STATUS_RETIRED = "retired"

# One dict per deleted engine: {"engine", "label", "removed" (ISO date), "reason", "replaced_by"}.
# `replaced_by` names what took over, or is None when nothing did. Add an entry in the SAME PR that
# deletes the engine; `tests/test_engine_catalogue.py` checks the shape. Empty today: nothing with a
# scoreboard row has been deleted yet (the wave-1 cuts removed a page and a helper, not an engine).
ENGINE_TOMBSTONES: tuple[dict[str, Any], ...] = ()

# The four words a row can carry, as a set, so a hand-built or older row whose `market_verdict` is
# missing does not silently fall through to a verdict nobody resolved. `market_verdict()` is the
# fallback and is the SAME function the reducer used, so this stays one threshold.
ROW_VERDICTS = frozenset({VERDICT_AHEAD, VERDICT_BEHIND, VERDICT_LEVEL, VERDICT_NOT_COMPARABLE})

# Why an engine with a backtest run but no catalogue entry says no claim. Not an empty string and
# not a plausible-sounding guess: an engine the catalogue does not describe is a gap in the
# catalogue, and the honest rendering of a gap is that it is one.
CLAIM_UNLISTED = (
    "Not described. This engine has a backtest run but no entry in the engine catalogue, so "
    "nothing here claims what it predicts. It is on this page anyway: an engine nobody has "
    "written down is a gap in the catalogue, not a reason for the engine to disappear."
)


# The catalogue itself. `engine` is the value `backtest_runs.engine` and `predictions.engine`
# carry, so this is a key into the data rather than a display name.
#
# `claim` is deliberately the sentence a reader can CHECK -- it names the market series, the
# decision time and the inputs -- rather than a category ("a macro engine", "a sports model"),
# because a category is the thing Kevin said he did not understand. Where a figure is quoted it is
# quoted from the module that computes it: the 2h gas lead is `GAS_DECISION_LEAD`
# (`tradehub/scripts/backtest_engines.py`), the 25-minute CPI lead is `CPI_DECISION_LEAD` in the
# same file, and the 23:30 weather decision is `WEATHER_DECISION_TIME`
# (`tradehub/data/weather.py`).
#
# `cadence` is the gate's own word, and it is why the two bars on the page differ per engine
# (`MIN_CONTRACTS`: 200 daily, 50 monthly). It is pinned to `settle_predictions.ENGINES` by test
# rather than imported from it: that module pulls the settlement and track-record stacks in at
# import time, and a catalogue that cannot be imported without a client is a catalogue that will be
# duplicated instead.
ENGINE_CATALOGUE: tuple[dict[str, Any], ...] = (
    {
        "engine": "gas",
        "label": "Gasoline — AAA US average, day over day",
        "cadence": "daily",
        "claim": (
            "Whether the AAA US average gasoline price will finish the day above or below a "
            "strike, on KXAAAGASD. It reads the last AAA print plus the change in front-month "
            "RBOB over the last five closes -- retail follows wholesale with a lag -- and is "
            "decided about two hours before the market closes."
        ),
    },
    {
        "engine": "weather",
        "label": "Daily high temperature — Chicago, New York, Miami",
        "cadence": "daily",
        "claim": (
            "Whether a city's daily high reaches a strike, on KXHIGHCHI, KXHIGHNY and KXHIGHMIA. "
            "It blends the overnight model forecasts for the city, and is decided at 23:30 local "
            "time the day before, against that city's settlement station."
        ),
    },
    {
        "engine": "cpi_nowcast",
        "label": "CPI — first print, month over month (headline and core)",
        "cadence": "monthly",
        "claim": (
            "Whether the BLS first print of month-over-month CPI is more than a strike above the "
            "contract, on KXCPI for headline and KXCPICORE for core -- two markets, one engine, "
            "two versions so their records stay separate. It reads the Cleveland Fed nowcast for "
            "that month, and is decided 25 minutes before the market closes, five minutes before "
            "the print is published."
        ),
    },
    {
        "engine": "labor_nowcast",
        "label": "Non-farm payrolls — BLS first print",
        "cadence": "monthly",
        "claim": (
            "Whether the BLS first print of the change in non-farm payrolls is above a strike, on "
            "KXPAYROLLS. Kalshi settles on the FIRST print, so the model is trained on ALFRED "
            "first-release vintages and never on revised history; it regresses on inputs that were "
            "public by the end of the reference month."
        ),
    },
    {
        "engine": "crypto",
        "label": "Crypto — BTC and ETH, next hourly close",
        "cadence": "daily",
        "claim": (
            "Whether an asset's next hourly close resolves YES against a fixed threshold, from an "
            "hourly-bar model over price, volume, RSI and moving-average distance. It is scored on "
            "the shadow timeline rather than against a market price, so it has no market Brier and "
            "cannot be ranked beside the others on this page."
        ),
    },
    {
        "engine": "sports_nfl",
        "label": "NFL game markets — winner, spread, total",
        "cadence": "daily",
        "claim": (
            "The probability that one side of an NFL market resolves as claimed, for winner, "
            "spread and total. The number is the predictor feed's own frozen pre-game snapshot and "
            "an LLM reviewer judges it; the reviewer never changes the probability."
        ),
    },
    {
        "engine": "sports_cfb",
        "label": "College football game markets — winner, spread, total",
        "cadence": "daily",
        "claim": (
            "The probability that one side of a college-football market resolves as claimed, for "
            "winner, spread and total. The number is the predictor feed's own frozen pre-game "
            "snapshot and an LLM reviewer judges it; the reviewer never changes the probability."
        ),
    },
)

# The engine names the catalogue declares, for the membership tests.
CATALOGUE_ENGINES: frozenset[str] = frozenset(
    entry["engine"] for entry in ENGINE_CATALOGUE if isinstance(entry.get("engine"), str)
)


def catalogue_entry(engine: Any) -> dict[str, Any] | None:
    """The catalogue's own record for one engine, or `None` when it declares none.

    `None` rather than a synthesised entry: an absent catalogue record and a present one with
    empty fields are different facts, and this function is called from a page that must be able to
    say which it is.
    """
    if not isinstance(engine, str):
        return None
    for entry in ENGINE_CATALOGUE:
        if entry["engine"] == engine:
            return dict(entry)
    return None


def row_verdict(row: Mapping[str, Any]) -> str:
    """One row's verdict, as one of the four words -- never re-decided here.

    Reads `market_verdict` when the row carries a word this module knows, and otherwise asks
    `market_verdict()` -- the reducer's own function, so still exactly one copy of
    `BEHIND_THE_MARKET` -- about the row's own ratio. The fallback is what keeps a hand-built or
    older row from falling through to a verdict nobody resolved, and it can only ever agree with
    the row's own field: `tests/test_scoreboard_reduction.py::TestMarketVerdict` already pins the
    two to the same application of the same threshold.
    """
    stated = row.get("market_verdict")
    if isinstance(stated, str) and stated in ROW_VERDICTS:
        return stated
    return market_verdict(row.get("brier_ratio"))


def engine_status(rows: Sequence[Mapping[str, Any]] | None) -> str:
    """One word for an engine across all of its rows.

    Pessimistic on purpose, and the order is the whole argument: `behind` beats `ahead` beats
    `level` beats `not_comparable`. Taker and maker are different fills and can disagree, and an
    engine that won one and lost the other is reported at the loss -- because the alternative is
    picking which row to lead with, and a component that picks is a component deciding the
    verdict. `not_measured` when there are no rows at all, which is the one case where there is no
    evidence to be pessimistic about.

    Every row is still carried on the entry this produces, so the word is a summary of what the
    reader can already see, not a substitute for it.
    """
    verdicts = [row_verdict(row) for row in rows or []]
    if not verdicts:
        return STATUS_NOT_MEASURED
    for verdict in (VERDICT_BEHIND, VERDICT_AHEAD, VERDICT_LEVEL):
        if verdict in verdicts:
            return verdict
    return VERDICT_NOT_COMPARABLE


def worst_brier_ratio(rows: Sequence[Mapping[str, Any]] | None) -> float | None:
    """The LARGEST comparable ratio among an engine's rows, or `None` where none was comparable.

    The largest is the furthest behind the market, which is the direction this product reports
    losses in: 4.29x must not be summarised as 2.16x because a different fill mode did better.
    `None` rather than `0` where nothing was compared, because a ratio of zero is a model that
    never misses and the absence of a comparison is not that.

    A non-numeric, boolean or NaN ratio is skipped rather than compared, for the reasons
    `market_verdict` gives for refusing them: `bool` is an `int`, and NaN compares false to
    itself. Both would otherwise become `max()`'s answer.
    """
    ratios = [
        row["brier_ratio"]
        for row in rows or []
        if isinstance(row.get("brier_ratio"), (int, float))
        and not isinstance(row.get("brier_ratio"), bool)
        and row["brier_ratio"] == row["brier_ratio"]  # NaN is the one float that is not itself
    ]
    return max(ratios) if ratios else None


def engine_catalogue(
    rows: Iterable[Mapping[str, Any]] | None,
    tombstones: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Every engine this product has, each joined to the scoreboard rows that measured it.

    Takes the rows `current_runs` produced and adds no measurement of its own. Three things come
    out, and the order is the design:

    - **every catalogue engine, always.** An engine with no backtest run is in the response with
      `measured: false` and `status: "not_measured"`. Absent is not zero: an engine rendered as an
      empty row of dashes is an engine a reader concludes has nothing to show, which is a claim
      nobody made about it.
    - **every engine that HAS a row, even one the catalogue does not declare.** A new engine is
      not a reason to leave the page; it is a reason to notice the catalogue is behind. It arrives
      with `claim: null` and `claim_note` saying exactly that, and `engines_unlisted` counts it.
    - **conservation.** Every input row lands in exactly one entry and every entry is a real
      engine. A row quietly uncounted is how "7 engines" becomes true of a board of five, so
      `tests/test_engine_catalogue.py` pins the sum.

    The counts are here rather than computed by the page because they are arithmetic on a set:
    `engines_measured` is the number of engines with at least one row, and `engines_not_measured`
    is the difference, which is the single most important number on the page and must not be a
    subtraction a component does at render time.
    """
    by_engine: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows or []:
        engine = row.get("engine")
        # A row with no engine name cannot be told apart from another such row, and
        # `current_runs` never produces one -- it skips a run with no engine before this point.
        # The guard is here so a hand-built row degrades to "not on the page" rather than raising.
        if not isinstance(engine, str) or not engine:
            continue
        by_engine.setdefault(engine, []).append(row)

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for declared in ENGINE_CATALOGUE:
        engine = declared["engine"]
        seen.add(engine)
        entries.append(_entry(declared, by_engine.get(engine, []), in_catalogue=True))
    retired = {str(ts["engine"]): ts for ts in (ENGINE_TOMBSTONES if tombstones is None else tombstones)}
    # Anything with a run that the catalogue does not name, in the order the board produced it.
    for engine, engine_rows in by_engine.items():
        if engine not in seen and engine not in retired:
            entries.append(_entry(None, engine_rows, in_catalogue=False))

    measured = sum(1 for entry in entries if entry["measured"])
    live_total = len(entries)
    # Tombstones come last and are NOT live engines: they leave `engines_total` and the measured
    # counts alone, and are counted in their own number. A retired engine with history keeps its rows.
    for tombstone in retired.values():
        entries.append(_tombstone_entry(tombstone, by_engine.get(str(tombstone["engine"]), [])))
    return {
        "engines_total": live_total,
        "engines_measured": measured,
        "engines_not_measured": live_total - measured,
        "engines_unlisted": sum(1 for entry in entries if entry["status"] != STATUS_RETIRED and not entry["in_catalogue"]),
        "engines_retired": len(retired),
        "entries": entries,
    }


def _tombstone_entry(tombstone: Mapping[str, Any], engine_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """A deleted engine: what it was, when and why it went, what replaced it, and any history it left."""
    engine = str(tombstone["engine"])
    return {
        "engine": engine,
        "label": str(tombstone["label"]),
        "claim": None,
        "claim_note": "Retired: " + str(tombstone["reason"]),
        "in_catalogue": False,
        "cadence": None,
        "measured": bool(engine_rows),
        "measured_rows": len(engine_rows),
        "status": STATUS_RETIRED,
        "worst_brier_ratio": worst_brier_ratio(engine_rows),
        "rows": list(engine_rows),
        "retired": {"removed": str(tombstone["removed"]), "reason": str(tombstone["reason"]),
                    "replaced_by": tombstone.get("replaced_by")},
    }


def _entry(
    declared: Mapping[str, Any] | None,
    engine_rows: list[Mapping[str, Any]],
    *,
    in_catalogue: bool,
) -> dict[str, Any]:
    """One engine's entry. The rows ride out by reference, unmodified and un-copied in value."""
    engine = declared["engine"] if declared else str(engine_rows[0]["engine"])
    return {
        "engine": engine,
        # An undeclared engine is labelled by its own key. Anything richer would be invented.
        "label": declared["label"] if declared else engine,
        "claim": declared["claim"] if declared else None,
        "claim_note": "" if declared else CLAIM_UNLISTED,
        "in_catalogue": in_catalogue,
        "cadence": declared["cadence"] if declared else None,
        "measured": bool(engine_rows),
        "measured_rows": len(engine_rows),
        "status": engine_status(engine_rows),
        "worst_brier_ratio": worst_brier_ratio(engine_rows),
        # The scoreboard's rows, whole and untouched. The page reads the ratio, the verdict and
        # both bars off these rather than re-deriving any of them, which is why they are carried
        # here rather than a list of indices: a self-contained entry cannot be mis-joined.
        "rows": list(engine_rows),
    }

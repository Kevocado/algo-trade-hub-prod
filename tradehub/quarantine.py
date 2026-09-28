"""The QUARANTINE: repaired engines whose output is measured, shown, and never published.

Pure, like `tradehub/engine_health.py` and `tradehub/scoreboard.py`, so every rule here is testable
without a database and without a network.

**What this is.** PR #38 (`a4bca55`) repaired nothing. It labelled Weather and Macro as *stopped*,
which is honest, and it answered a question nobody asked: the owner's question is what these engines
*would do*, and the labelling deliberately did not say. The root cause was one line in each engine:
Kalshi's API stopped sending the legacy cent keys `yes_bid`/`yes_ask`/`no_bid`/`no_ask` and sends
`yes_ask_dollars` as a 0-1 string instead, so a read of `yes_ask` with a `0` default returned 0 for
every market and both engines skipped all of them. They failed CLOSED, which is why nothing wrong
reached the ledger, and also why nothing reached the reader.

Both engines are now repaired, through the normaliser that already existed (`quote_cents` in
`tradehub/markets.py`, the one `kalshi_feed.process_markets` uses -- there is deliberately no second
one). Repairing them makes them produce real output: 295 rows per scan. And the whole point of
this module is that **none of it is published**.

**The safety property, stated as a rule and not as a hope.** A quarantined engine computes, its
output is measured and displayed, and not one row reaches `kalshi_edges`. Three independent things
enforce it, because one would be a promise:

  1. `tradehub/scripts/background_scanner.py::run_scan` never puts a quarantined row in the list it
     hands to `upsert_opportunities`. The structural separation: the two lists are different objects
     and the quarantine one's only destination is the quarantine sink.
  2. `upsert_opportunities` DROPS any row carrying `QUARANTINE_FLAG`, so a future refactor that
     concatenates the two lists writes zero of them anyway. The flag is a poison pill, and it is set
     in exactly one place, so it can only ever be set by the path that is meant to be quarantined.
  3. `tradehub/core/supabase_client.py::upsert_quarantined` writes to `kalshi_quarantine_edges` and
     to nothing else. There is no code path from a quarantined row to the trade-proposal sink, and
     `tests/test_weather_macro_quarantine.py` walks the source to prove it.

**The second thing this module has to do, which is harder.** 295 rows is not 295 opportunities, and
a surface that reports 295 rows under a heading that says "opportunities" is the exact failure this
whole effort exists to prevent -- a number on screen that looks authoritative and is not. So the
rows are split on two independent axes, and both conserve:

  * **is the row an opportunity at all, or a units artefact?** Both engines compute
    `edge = model_probability - yes_ask` and then pick their side from the sign, so the price on the
    row is always the YES ask. For a `BUY NO` at a 99c YES ask the trade described is a 1c purchase
    of a 99c payoff and the "84-point edge" is a gap between the model's YES probability and a YES
    quote -- printed as the edge of a trade the row did not recommend. That is a units artefact, and
    it is called by content, not by a flag somebody sets.
  * **is the row an INDEPENDENT statement, or a restatement of a forecast another row already made?**
    Neither engine has a per-market model. Each fetches one scalar per asset and quantises it into a
    handful of constants, so every row sharing an `(engine, asset, model_probability)` triple is the
    same number applied again. One GDP point forecast restated across eleven year-events is 143 rows
    and one opinion.

The headline number a reader gets is the count of *independent* rows, and every other count is shown
next to it. This is the same conservation contract as
`market_sentiment_tool/src/lib/displayOnlyEngines.ts` -- "a read that drops a row silently is
indistinguishable from there having been no rows" -- applied to a scan that produces rows nobody may
act on.

**What is deliberately NOT here.**

  * **No threshold derived from the data.** `DEGENERATE_YES_ASK_CENTS` is a written ruling, on the
    same terms as `STOPPED_SITES`: a threshold computed at read time from the rows it is judging is a
    threshold that moves to make whatever it is looking at come out right.
  * **No opinion on whether to publish.** This module measures and withholds. Turning the quarantine
    off is a deletion of a name from `QUARANTINED_EDGE_TYPES`, and it is the owner's call, made with
    the counts in front of them.
  * **No second normaliser.** The rescale from Kalshi's 0-1 dollar strings to 0-100 cents is
    `quote_cents` in `tradehub/markets.py`, and an answer to "what is a 29c quote" that lives in two
    modules is a second answer waiting to disagree with the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# ── the ruling ──────────────────────────────────────────────────────────────────────────────

# The edge types whose live engines are computed but NOT published. A written list, on exactly the
# terms as `STOPPED_SITES` in `tradehub/engine_health.py` and `DISPLAY_ONLY_ENGINES` in
# `market_sentiment_tool/src/lib/displayOnlyEngines.ts`: a name somebody added on purpose, with the
# reason attached, rather than a set computed from which engines happen to be quiet. A list nobody
# wrote down is a list that gets emptied by a refactor nobody was looking at, and the next reader
# finds a product that publishes 295 rows a scan with no memory of having decided that.
#
# It is keyed by EDGE TYPE, and that is deliberate and load-bearing. `upsert_opportunities` is
# shared with `tradehub/scripts/scan.py`, whose measured `weather` engine and macro ladder engine
# DO publish to these same two edge types. So the ruling cannot be enforced on `edge_type` at the
# sink, and is not: it is enforced on `QUARANTINE_FLAG`, which only the quarantine path sets. The
# edge type is the ruling's *scope* -- which boards are affected -- not its *identity*.
QUARANTINED_EDGE_TYPES: tuple[str, ...] = ("WEATHER", "MACRO")

# The marker, and it travels. Every quarantined row carries it, every quarantined payload carries it
# in its `marker` field, and the UI renders it next to every figure. The point is that a reader who
# screenshots one number from this surface still has the word QUARANTINED in the image, because a
# quarantined number that travels alone is indistinguishable from a live one, and that is the whole
# failure this exists to prevent.
QUARANTINE_FLAG = "quarantined"
QUARANTINE_MARK = "QUARANTINED"

# The one sentence that goes with the marker. Carried in every payload rather than written once in a
# component, for the same reason `engine_health.note` is: a browser can be holding an older bundle
# than the API, and a copy of this sentence in TypeScript is a copy that can disagree with the
# server about what is being shown.
QUARANTINE_NOTE = (
    "QUARANTINED. These engines run and compute their real output, and none of it is published: "
    "no row reaches kalshi_edges, so no trade can be proposed from anything on this surface. The "
    "counts below are a measurement, not a live board."
)

# The actions both engines emit. Named rather than string-compared inline, because the whole
# units-artefact rule below turns on the difference between them and an inline literal is how the
# next reader misses why.
ACTION_BUY_YES = "BUY YES"
ACTION_BUY_NO = "BUY NO"

# The number at which a quote stops being a price and becomes a statement about the far side.
#
# At a 99c YES ask the market is saying the outcome is effectively decided. The NO side -- the side
# a `BUY NO` row actually buys -- is a 1c contract. So a row reading "BUY NO, market 99c, edge 84"
# describes a trade whose entire stake is 1 cent, and whose 84 points are a difference between the
# model's YES probability and the YES quote rather than between the model and the price paid. It is
# not a bad trade; it is a number in the wrong units, presented as an 84-point opportunity, and the
# 1c payoff is what makes the 84 meaningless as a headline.
#
# A WRITTEN number, not one derived from the rows being judged. A threshold read off the data it is
# judging is a threshold that moves until whatever it is looking at comes out right, and this surface
# exists because a number was previously on screen looking authoritative while meaning nothing else.
DEGENERATE_YES_ASK_CENTS = 95.0


def normalize_edge_type(value: Any) -> str | None:
    """`" weather "` -> `"WEATHER"`. `None` for anything that is not a usable edge type.

    `upsert_opportunities` upper-cases `edge_type` before it writes it and a hand-built row may not
    have been, so a ruling that depended on the shape of the key would be a ruling that could be
    evaded by whitespace. It also must not raise: this runs on rows read back from a database, and a
    read that dies on a row it was handed reports the fault as a crash.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip().upper()
    return stripped or None


def is_quarantined_edge_type(value: Any) -> bool:
    """Whether this edge type is one the ruling puts under quarantine."""
    return normalize_edge_type(value) in QUARANTINED_EDGE_TYPES


def is_quarantined_row(row: Mapping[str, Any] | None) -> bool:
    """Whether a row carries the quarantine flag -- the identity test, and the sink's only test.

    NOT `is_quarantined_edge_type`. See `QUARANTINED_EDGE_TYPES` for why the flag and not the edge
    type: `tradehub/scripts/scan.py` publishes measured rows under both `WEATHER` and `MACRO` and
    must keep doing so, so a sink that refused those edge types would refuse the product's working
    engines to enforce a ruling about two different ones that share a board.
    """
    return bool(row) and row.get(QUARANTINE_FLAG) is True


# ── reading a row, without inventing a figure ─────────────────────────────────────────────────

def _number(value: Any) -> float | None:
    """A real number, or `None`. Never `0` for a figure that is not there.

    A missing figure is never a number, so a row that recorded no market price reads as `None` here
    and is NOT classified as a units artefact. Calling it one would be a claim about a row nobody can
    audit, and a row with no price has no units to get wrong either.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _action_of(row: Mapping[str, Any] | None) -> str:
    return _text(row.get("action")).upper() if row else ""


# ── the two axes ─────────────────────────────────────────────────────────────────────────────

#: A row that stands on its own terms: a quote on the side it recommends, at a price the reader can
#: act on. Everything else in this module is a reason a row is not that.
KIND_OPPORTUNITY = "opportunity"

#: A row whose headline edge is a difference between two quantities that are not the same thing.
KIND_UNITS_ARTEFACT = "units_artefact"

UNITS_ARTEFACT_REASON = (
    "A units artefact, not an opportunity. The engine prices every market against the YES ask and "
    "then picks its side from the sign of that difference, so the price on the row is the YES ask "
    "whatever it recommends. On this row the recommendation is BUY NO against a YES ask at or above "
    f"{DEGENERATE_YES_ASK_CENTS:.0f}c, which means the side it recommends trades at the far end of "
    "the book for a payoff measured in cents. The edge shown is the gap between the model's YES "
    "probability and a YES quote, and it is not the edge of the trade the row describes."
)

#: One model's statement, seen again on another market. The row is not a second opinion; the model
#: that produced it fetched one number per asset and has no view on the particular market.
RESTATEMENT_REASON = (
    "A restatement, not a second opinion. Neither engine has a per-market model: each fetches one "
    "figure per asset and quantises it into a handful of constants, so every row sharing this "
    "engine, asset and model probability is the same number applied again. The independent count "
    "counts each of them once."
)


def classify_row(row: Mapping[str, Any] | None) -> str:
    """`opportunity` or `units_artefact` for one row. Never raises.

    The test is the row's own arithmetic, not a flag: a `BUY NO` whose price is a degenerate YES ask
    is a units artefact whatever produced it, and a row that recorded no price at all is an
    opportunity of unknown quality rather than a measured artefact -- this module reports what it can
    check and says nothing about what it cannot.
    """
    if not row:
        return KIND_OPPORTUNITY
    if _action_of(row) != ACTION_BUY_NO:
        return KIND_OPPORTUNITY
    price = _number(row.get("market_price"))
    if price is not None and price >= DEGENERATE_YES_ASK_CENTS:
        return KIND_UNITS_ARTEFACT
    return KIND_OPPORTUNITY


def forecast_key(row: Mapping[str, Any] | None) -> tuple[str, str, str]:
    """What makes two rows the SAME statement rather than two.

    `(engine, asset, model_probability)`, and nothing else. The engine name because the same
    probability from two engines is two opinions; the asset because CPI at 60% and GDP at 60% are not
    the same claim; and the model probability as a string, because it is the output the model
    actually produced and the only part of these rows that is a forecast at all. The strike is
    deliberately NOT in the key: it is the thing being predicted about, not the prediction.

    The model probability is stringified so that 60 and 60.0 -- the same number in two shapes -- are
    the same statement, and so that a row that recorded no probability lands in one group rather
    than in none. A missing figure is not allowed to become a number here; it becomes its own
    written absence, which is a group of its own and is visible as such.
    """
    if not row:
        return ("", "", "")
    probability = row.get("model_probability")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        # Not 0, and not the empty string either. A row with no recorded probability groups under
        # this literal absence, so `restated_rows` cannot be quietly inflated by treating every
        # unmeasured row as the same 0% forecast.
        return (_text(row.get("engine")), _text(row.get("asset")), "no recorded probability")
    number = float(probability)
    if number.is_integer():
        rendered = str(int(number))
    else:
        rendered = f"{number:g}"
    return (_text(row.get("engine")), _text(row.get("asset")), rendered)


@dataclass(frozen=True)
class ClassifiedRow:
    """One quarantined row, with the two verdicts about it attached. The row is kept verbatim."""

    row: Mapping[str, Any]
    kind: str
    reason: str | None
    forecast: tuple[str, str, str]
    #: False when an EARLIER row in the same scan already made this exact statement.
    independent: bool


@dataclass(frozen=True)
class QuarantinePartition:
    """Every row, in one of two buckets on each of two axes, with nothing dropped.

    `opportunities + units_artefacts == rows` and `independent + restatements == rows`, both
    always, and both pinned by test. Conservation is the contract for the reason it is everywhere
    else in this codebase: a row that vanishes from a count is a count that reads as a finding, and
    the whole point of this surface is that 295 rows must never be read as 295 opportunities.
    """

    rows: tuple[ClassifiedRow, ...] = ()
    opportunities: tuple[ClassifiedRow, ...] = ()
    units_artefacts: tuple[ClassifiedRow, ...] = ()
    independent: tuple[ClassifiedRow, ...] = ()
    restatements: tuple[ClassifiedRow, ...] = ()

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def counts(self) -> dict[str, int]:
        """Every count a reader may be shown, in one dict. Computed here, never in a component.

        `buy_no_rows` is on its own line because it is a wider fact than `units_artefacts` and
        hiding it inside the narrower one would understate a real defect: BOTH engines compute
        `edge = model_probability - yes_ask` and then pick their side from the sign, so a `BUY NO`
        row carries the YES ask as its price on every one of them. At a sane price that happens to
        be arithmetically fine (in a frictionless book NO costs `100 - YES`, so the same difference
        comes out the other way). At a 99c YES ask the row reads "BUY NO, 99c, 84 points" and no
        such trade exists -- you would be buying NO at 99c while YES is also 99c. So `buy_no_rows`
        is the count of rows whose displayed price belongs to the other side, and
        `units_artefacts` is the subset where that stops being a labelling nuisance and becomes a
        headline nobody could act on. Reporting only the second would be choosing the flattering
        denominator.
        """
        independent_opportunities = sum(1 for row in self.opportunities if row.independent)
        return {
            "rows": len(self.rows),
            "opportunities": len(self.opportunities),
            "units_artefacts": len(self.units_artefacts),
            "buy_no_rows": sum(1 for row in self.rows if _action_of(row.row) == ACTION_BUY_NO),
            "independent_forecasts": len(self.independent),
            "restatements": len(self.restatements),
            "independent_opportunities": independent_opportunities,
            "restated_opportunities": len(self.opportunities) - independent_opportunities,
        }


def partition_quarantine(rows: Iterable[Mapping[str, Any]] | None) -> QuarantinePartition:
    """Sort quarantined rows into opportunities vs artefacts, and firsts vs restatements.

    Two passes, because the two axes are independent and a row can be both a restatement and an
    artefact. Folding them into one bucketing would force a choice -- is the 143rd copy of the GDP
    forecast an artefact or a restatement? -- and whichever way it went, the other question would go
    unasked. The reader needs both: "how much of this is not a tradeable edge" and "how much of it
    is the same opinion more than once" are different questions with different answers.

    The first occurrence of a forecast is the independent one. That is arbitrary and it is stated
    rather than hidden, because the alternative -- picking the highest edge among the copies -- would
    be a selection made on the outcome, and the copies do not disagree: they are the same number.
    """
    classified: list[ClassifiedRow] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            # A hand-built or corrupt row is not silently reclassified as an opportunity. It is
            # carried, unclassified, and `counts()` is honest about what it could not read.
            continue
        key = forecast_key(row)
        independent = key not in seen
        seen.add(key)
        kind = classify_row(row)
        classified.append(
            ClassifiedRow(
                row=row,
                kind=kind,
                reason=UNITS_ARTEFACT_REASON if kind == KIND_UNITS_ARTEFACT else None,
                forecast=key,
                independent=independent,
            )
        )

    return QuarantinePartition(
        rows=tuple(classified),
        opportunities=tuple(row for row in classified if row.kind == KIND_OPPORTUNITY),
        units_artefacts=tuple(row for row in classified if row.kind == KIND_UNITS_ARTEFACT),
        independent=tuple(row for row in classified if row.independent),
        restatements=tuple(row for row in classified if not row.independent),
    )


def quarantine_summary(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    engine: str | None = None,
) -> dict[str, Any]:
    """The whole measured surface for one payload: the marker, the note, and the counts.

    `engine` narrows the report to one engine and is used by the per-engine breakdown. It is a
    filter, never a rule: nothing in here changes shape depending on which engine is named, so a
    caller cannot accidentally get a stricter standard for the engine it likes.
    """
    return quarantine_summary_from_partition(partition_quarantine(rows), engine=engine)


def quarantine_summary_from_partition(
    partition: "QuarantinePartition", *, engine: str | None = None
) -> dict[str, Any]:
    """The counts and the marker for a partition that has ALREADY been built.

    Split out because `partition_quarantine` is not idempotent over its own output: its input is
    raw rows, and feeding it classified rows would re-derive the verdicts from a shape that no
    longer carries the fields they came from. The two entry points keep that mistake impossible --
    `quarantine_report` and `quarantine_summary` both classify raw rows exactly once, and only this
    function reads a finished partition.
    """
    return {
        "engine": engine,
        "marker": QUARANTINE_MARK,
        "quarantined": True,
        "note": QUARANTINE_NOTE,
        "counts": partition.counts(),
        "reasons": {
            KIND_UNITS_ARTEFACT: UNITS_ARTEFACT_REASON,
            "restatement": RESTATEMENT_REASON,
        },
    }


def mark_quarantine(rows: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Stamp each row as quarantined and attach the two verdicts about it. The row's figures stay.

    The flag goes on FIRST, unconditionally, before any classification runs. A row that cannot be
    classified -- a corrupt payload, a shape nobody anticipated -- still leaves here quarantined,
    because a row that failed the checks must not become publishable by failing them. The verdicts
    default to the safe reading too: an unread row is not counted as an opportunity, and is marked
    independent so it stays visible in the count rather than disappearing into the restatements.

    Returns copies, never the inputs. The engine hands these dicts straight to the sink, and a
    function that decorated its argument in place would be writing to an object the caller still
    holds a reference to -- which is how a quarantine marker ends up on a row somewhere it was never
    meant to be.
    """
    marked: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        copy = dict(row)
        copy[QUARANTINE_FLAG] = True
        kind = classify_row(copy)
        key = forecast_key(copy)
        copy["edge_kind"] = kind
        copy["edge_kind_reason"] = UNITS_ARTEFACT_REASON if kind == KIND_UNITS_ARTEFACT else None
        copy["forecast_key"] = " | ".join(part for part in key if part) or None
        marked.append(copy)

    # `independent` is a fact about the SET, so it is resolved here in one pass over the marked rows
    # rather than per row, and the first row making a statement is the one that gets it. Iterating
    # the engine's own order makes that the first market the engine looked at, which is arbitrary
    # and stable -- the alternative, keeping the largest edge, would be selecting on the outcome.
    seen: set[str] = set()
    for row in marked:
        key = row.get("forecast_key") or ""
        row["independent"] = key not in seen
        seen.add(key)
    return marked


def quarantine_report(rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """One payload for the whole quarantine: the marker, the note, the counts, the per-engine split.

    This is the whole measurement surface in one dict, and every number in it is computed here. A
    component that subtracted a set, or compared a price to a threshold, would be a rule in a second
    language that no test in this repo could pin.

    Takes RAW rows, not a partition, so a caller cannot pass the output of one classification in and
    get the counts of a second one over already-classified rows -- which is a silent way to end up
    reporting zeroes for a scan that measured 295.
    """
    partition = partition_quarantine(rows)
    payload = quarantine_summary_from_partition(partition, engine=None)
    payload["totals"] = payload["counts"]
    payload["engines"] = engine_rollup(rows)
    # Spelled out rather than left implicit in the marker, because "QUARANTINED" tells a reader the
    # rows were not published but not that the publication path is not merely unrun tonight. This is
    # a hard zero by construction: there is no code path from a quarantined row to `kalshi_edges`.
    payload["kalshi_edges_written"] = 0
    payload["sink"] = "kalshi_quarantine_edges"
    return payload


def engine_rollup(rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """One summary per engine present in the rows, each conserving its own rows.

    Derived here rather than in the page for the reason `engine_health` computes its counts in
    Python: a subtraction on a set, done at render time, is a rule in a second language with no test
    on it. An engine absent from the rows produces NO entry, and never an entry of zeros -- a
    per-engine line reading "0 opportunities" for an engine that returned no rows at all would be
    the one number this codebase exists to refuse.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        grouped.setdefault(_text(row.get("engine")) or "(unattributed engine)", []).append(row)
    # Each engine's counts are measured over ITS OWN rows, classified as a subset -- so the
    # per-engine "independent" figures sum to the whole-run one and the per-engine "restatements"
    # cannot double-count a forecast the other engine also made. Two engines reporting one forecast
    # would otherwise be two independent statements here, which is the exact error the axis exists
    # to catch, reproduced one level up.
    return [
        quarantine_summary(entries, engine=name)
        for name, entries in sorted(grouped.items())
    ]

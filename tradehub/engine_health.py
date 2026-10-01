"""Which engines ran, which are QUARANTINED, and the rule that keeps a stopped engine off the board.

Pure, like `tradehub/engine_catalogue.py`, `tradehub/scoreboard.py` and `tradehub/quarantine.py`, so
every rule below is testable without a database and without a network.

**Why this module exists.** Kalshi's API stopped sending the legacy cent fields `yes_bid` /
`yes_ask` / `no_bid` / `no_ask` and now sends `yes_ask_dollars` and its siblings as 0-1 *strings*.
The product's Tier-1 real-edge engines read the legacy names with a `0` default, so every market they
fetch read as a 0c quote, got skipped, and was never published. The scan logged "Found 0 weather
opportunities" and exited cleanly. Nothing wrong was written anywhere -- these engines failed CLOSED,
which is why the defect survived -- and nothing anywhere said so either. The Weather tab of the
Prediction Lab rendered "No high-confidence edges detected in weather", which is a *finding*, and the
finding was fiction.

**The rule this module holds.** An engine that could not run must never be rendered as an engine with
nothing to say, and an engine that is quarantined must never be rendered as one that published. Three
facts, and no two of them are the same fact:

    ran               the engine ran, looked, and no opportunity qualified. This is a measurement,
                      and the board is right to be empty.
    quarantined       the engine RAN and computed real opportunities, and none of them were
                      published, by ruling rather than by defect. Something was measured; it is
                      visible on its own surface, and it is marked.
    could_not_run     the engine did not run at all. Nothing was measured, so nothing may be
                      reported about the market it would have looked at.

The second state is the one that is easy to get wrong in both directions, and it is the newest.
Calling it `could_not_run` would be a lie -- these engines measured 295 rows -- and calling it `ran`
would be a different one, because a reader shown `ran` beside an empty board concludes the market was
quiet. So it is a third state, and the UI has to be able to say which of the three it is looking at.

**What changed from the version that preceded it, and why this module is not simply reverted.** That
version repaired nothing and recorded the drift instead, on the grounds that fixing the two live sites
would start these engines publishing hundreds of rows per scan into `kalshi_edges` and whether to
publish them is the owner's decision. That reasoning still holds and it is still load-bearing: the
engines are still not published, and the ruling that keeps them unpublished is in
`tradehub/quarantine.py`. What changed is that the two call sites were repaired through the shared
normaliser (`quote_cents` in `tradehub/markets.py` -- there is no second one) and their output routed
to a quarantine sink, so the owner can make the decision against real output rather than against
unseen code. So the drift at those two sites is HISTORICAL, and the sites stay on this list with
`disposition = repaired_quarantined` and the repaired read pinned in their place. Removing them
because the bug is fixed would delete the record of what the bug was, and a ruling that only remembers
the present cannot explain why a board is empty.

**The prior art, followed rather than reinvented.** `market_sentiment_tool/src/lib/displayOnlyEngines.ts`
records the identical defect on the sports path, where a display-only engine's rows must not be
dropped silently: "A READ THAT DROPS A ROW SILENTLY IS INDISTINGUISHABLE FROM THERE HAVING BEEN NO
ROWS." That module is the ruling for CPI. This one is the ruling for the engines that cannot produce a
row at all, and it keeps the two things that make that idiom work:

  * **a written ruling, not an inference.** `STOPPED_SITES` is a list somebody added on purpose,
    with the site, the cause and the disposition attached. Nothing here decides at read time that an
    engine "looks quiet" -- a heuristic like that would label an engine dead because a market was
    thin, which is the same fabrication wearing a different hat.
  * **conservation.** `partition_edge_types` puts every input in exactly ONE of three buckets and the
    test pins `ran + quarantined + could_not_run == len(input)`. A state that quietly drops an engine
    is how "no edge today" becomes true of a board nobody looked at.

**What is deliberately NOT here.**

  * No quote, and still not after the repair. Nothing in this module normalises `yes_ask_dollars`;
    the shared rescale already exists and it is `quote_cents` in `tradehub/markets.py`, which
    `kalshi_feed.process_markets` and the portfolio path use. A second normaliser here would be a
    second answer to "what is a 29c quote" in a module whose entire job is to say which engines are
    switched off.
  * No count of opportunities. An engine that did not run has no opportunity count, and `0` is the one
    number that would be a lie here. And a quarantined engine's count does not belong here either --
    it IS measured, but it is measured somewhere else, in `kalshi_quarantine_edges`, and publishing it
    on this endpoint would put two numbers for one fact on one screen. See
    `OPPORTUNITIES_NOT_COUNTED`, `OPPORTUNITIES_NOT_MEASURED` and `OPPORTUNITIES_QUARANTINED`.
  * No claim about any engine that is not in the ruling. A quiet engine is quiet until somebody
    writes down that it is not, which is what keeps this from becoming a machine for labelling every
    unfashionable engine broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

# The three words an edge type can carry. Deliberately three, and deliberately NOT the scoreboard's
# `VERDICT_*` family: those are verdicts on a MEASUREMENT (`tradehub/scoreboard.py`), and an engine
# that never ran has no measurement to be ahead or behind on. Reusing that vocabulary here would
# imply a comparison nobody made. These words are about whether the engine ran, and whether what it
# measured was published -- questions asked before any comparison is possible.
STATE_RAN = "ran"
STATE_COULD_NOT_RUN = "could_not_run"

# The third state, added when the two live sites were repaired. Not a synonym for `ran`: the engine
# DID run and DID measure, and a reader shown `ran` beside an empty board would conclude the market
# was quiet. Not a synonym for `could_not_run` either: it measured 295 rows, and a reader told it
# could not run would learn the opposite of the truth. It is a measurement that was deliberately not
# published, and the product has to be able to say that in those words.
STATE_QUARANTINED = "quarantined"

# The set of states, so a hand-built or older entry whose `state` is missing cannot fall through to a
# state nobody resolved -- the same defensive move `ROW_VERDICTS` makes in the catalogue.
EDGE_TYPE_STATES: frozenset[str] = frozenset({STATE_RAN, STATE_QUARANTINED, STATE_COULD_NOT_RUN})

# The edge types this product's edge ledger carries, with the label a reader already uses for them
# in the UI. The SET is the board's own vocabulary, and it is pinned to
# `tradehub/core/supabase_client.py::upsert_opportunities` by test rather than imported from it:
# that module builds a Supabase client at import time, and a ruling that cannot be imported without
# credentials is a ruling that will be duplicated instead -- which is the whole failure mode of the
# CPI ruling, just with the evidence left out of it.
#
# Conservation needs an authoritative set, because the count of "how much of the board cannot run"
# is meaningless unless every board is in it. An edge type nobody declared would be a board with
# no state at all, and a board with no state is a board that reads as a finding.
EDGE_TYPES: tuple[tuple[str, str], ...] = (
    ("WEATHER", "Weather"),
    ("MACRO", "Macro"),
    ("SPORTS", "Sports"),
    ("CRYPTO", "Crypto"),
    ("ENERGY", "Energy"),
)

EDGE_TYPE_LABELS: dict[str, str] = dict(EDGE_TYPES)


@dataclass(frozen=True)
class StoppedSite:
    """One place in the code that reads a Kalshi quote field the API no longer sends.

    `name` is the class or function, because that is the one identity a reader can grep for. It is
    NOT the `kalshi_edges.engine` value and must not be turned into one: `WeatherEngine` writes
    `engine: "Weather"`, which `upsert_opportunities` lower-cases to `weather` -- the SAME key the
    measured, working `weather` engine writes from `tradehub/scripts/scan.py`. Labelling the
    catalogue's `weather` entry "stopped" on the strength of a row that engine would one day
    publish would be a false claim about an engine that runs, so the two are never joined on that
    column. `module` and `site` are the unambiguous join, and a test pins that every module here
    exists and still contains the line this ruling names.
    """

    name: str
    module: str
    site: str
    reason: str
    # The edge type this site's engine would publish under, or None when it feeds no board. Used
    # to group the ruling under a tab a reader can actually select, and `None` is honest for
    # `clean_market_data`, which is a helper in the shared feed rather than an engine.
    edge_type: str | None
    # Whether anything actually CALLS it on a scan. This is the difference between "this engine is
    # switched off and its tab is empty for that reason" and "this code is not on the scan path at
    # all", and the two must not be collapsed: a helper no scanner calls cannot be the reason a tab
    # is empty, and saying it was would blame a dead branch for a live board.
    wired_to_a_scanner: bool
    # What was DONE about it, which is what lets one list carry a live defect and a repaired one
    # side by side. `repaired_quarantined` means the call site now reads the quote correctly and the
    # engine's output is routed to a quarantine sink rather than the trade-proposal table.
    # `unrepaired` means the drift is still there. Both kinds stay on the list: a ruling that only
    # remembers the present cannot explain why a board is empty, and dropping a fixed site would
    # erase the record of what the defect was.
    disposition: str = "unrepaired"


# The ruling. Add to it only with a written reason -- the same terms as
# `DISPLAY_ONLY_ENGINES` in `market_sentiment_tool/src/lib/displayOnlyEngines.ts`, and for the same
# reason: a list of names with no reason attached is a list of names somebody will quietly delete
# from, and the reader is left with an empty tab and no way to know whether the engine is quiet or
# gone.
#
# The shape of the defect is identical at every site, so the reason is stated once here and quoted
# at each: a legacy cent key read with a `0` default. Kalshi sends `yes_ask_dollars` ("0.6200") and
# does not send `yes_ask` at all -- verified across 156 markets in 5 series, 0 legacy keys, 100%
# `_dollars`. So the read returned 0, the 0 was indistinguishable from a 0c quote, and every
# consumer of this ruling skipped the market rather than pricing an edge against a fabricated zero.
# That last part is why the defect was invisible rather than loud: the engines failed CLOSED, so
# nothing wrong reached the ledger. It is also why they were stopped rather than deleted -- the
# failure mode here is silence, and silence is exactly what deleting a module would look like.
_THE_API_MOVED = (
    "Kalshi's API no longer sends the legacy cent field `yes_ask`. It sends `yes_ask_dollars` as a "
    "0-1 string (\"0.6200\") and omits the old key entirely, so a read of `yes_ask` with a `0` "
    "default returned 0 for a market that was quoting right now. The engine treated that 0 as an "
    "unpriceable market and skipped it, so it looked at every market it fetched and found nothing, "
    "published nothing, and raised nothing."
)

_REPAIRED_AND_QUARANTINED = (
    " It is now REPAIRED and it is QUARANTINED. The call site reads the quote through `quote_cents`, "
    "the shared normaliser, so the engine runs and computes its real opportunities. None of them are "
    "published: the output is measured and shown on its own surface (`kalshi_quarantine_edges`, read "
    "by /api/quarantine) and no row reaches `kalshi_edges`, so nothing it produces can become a trade "
    "proposal. It is quarantined rather than switched on because whether to publish it is a decision "
    "that has not been made -- and because most of what it produces is not an opportunity, which is "
    "what /api/quarantine measures."
)

STOPPED_SITES: tuple[StoppedSite, ...] = (
    StoppedSite(
        name="WeatherEngine",
        module="tradehub/engines/weather_engine.py",
        site="tradehub/engines/weather_engine.py:220",
        edge_type="WEATHER",
        # False since the legacy daemon (`background_scanner.py`) was deleted: the only scanner that ran
        # this class is gone, so it cannot be the reason the Weather board is empty or quarantined. The
        # board is fed by `tradehub/scripts/scan.py` (the pure `engines/weather.py`). The class is still
        # listed because `scripts/weather_auto_sell.py` calls it and it still prices against `yes_ask`.
        wired_to_a_scanner=False,
        disposition="repaired_quarantined",
        reason=(
            "This is the Tier-1 real-edge weather engine, and it prices every market against "
            "`yes_ask`. " + _THE_API_MOVED + _REPAIRED_AND_QUARANTINED
        ),
    ),
    StoppedSite(
        name="WeatherMaker",
        module="tradehub/engines/weather_maker.py",
        site="tradehub/engines/weather_maker.py:258",
        edge_type="WEATHER",
        # Deliberately False. No scanner calls this class, so it is not why the Weather tab is
        # empty, and an engine that is not on the scan path must not be reported as the reason a
        # live board has nothing on it. It is on the ruling because it carries the same drift and a
        # maintainer needs to see all four sites at once, not because it is holding up a board.
        wired_to_a_scanner=False,
        disposition="unrepaired",
        reason=(
            "Not running, and not wired to any scanner. It measures its edge as the distance between "
            "its own fair value and `market.get('price', 50)` on dicts that carry no `price` key, "
            "so its 'edge' is the distance from a hardcoded 50c default rather than from a quote. "
            "It is listed because it is a fourth site of the same drift and a reader has to be able "
            "to see it; it is not the reason any tab is empty, because nothing calls it."
        ),
    ),
    StoppedSite(
        name="clean_market_data",
        module="tradehub/core/kalshi_feed.py",
        site="tradehub/core/kalshi_feed.py:284",
        # No edge type: this is a helper in the shared feed, not an engine, and it belongs to no
        # board. Saying it feeds the Macro tab would be inventing a caller.
        edge_type=None,
        wired_to_a_scanner=False,
        disposition="unrepaired",
        reason=(
            "Not running, and not called by anything. `clean_market_data` drops every market whose "
            "`yes_ask` is 0, which is now every market, so it would return an empty list rather "
            "than a mispriced one. The live readers of the same API are already fixed -- "
            "`kalshi_feed.process_markets` and the portfolio path both go through `quote_cents` -- "
            "so this is the last unfixed reader of the moved field, left alone rather than quietly "
            "made into a second normaliser."
        ),
    ),
)

# Every site's name, for membership tests. Derived rather than restated, because a second list is a
# second thing to forget to add to.
STOPPED_SITE_NAMES: frozenset[str] = frozenset(site.name for site in STOPPED_SITES)

# The sites that can actually empty a board, and the sites that are merely unfixed. Two lists for
# one distinction, because the distinction IS the point of `wired_to_a_scanner`: a helper no
# scanner calls cannot explain an empty tab, and a ruling that let it try would be blaming a dead
# branch for a live board.
WIRED_STOPPED_SITES: tuple[StoppedSite, ...] = tuple(s for s in STOPPED_SITES if s.wired_to_a_scanner)
UNWIRED_STOPPED_SITES: tuple[StoppedSite, ...] = tuple(s for s in STOPPED_SITES if not s.wired_to_a_scanner)


# Why `opportunities_found` is not a number. Two sentences, one per state, and neither of them is
# "0" -- because an engine that did not run has no opportunity count, and a count of zero is a
# measurement of a search nobody performed.
OPPORTUNITIES_NOT_MEASURED = (
    "No count, because nothing ran. The engine did not execute, so there is no opportunity count to "
    "report -- not a count of zero. A zero here would be a measurement of a search that never "
    "happened."
)
OPPORTUNITIES_NOT_COUNTED = (
    "Not counted here. This endpoint reports which engines are stopped, not what the board found; "
    "the rows on the board are read separately and are not the same read as this response."
)

# The third reason, and the one that had to be written rather than reused. A quarantined engine DID
# measure, so the other two reasons would each be a lie: "nothing ran" is false, and "not counted
# here" would send a reader to a ledger that deliberately has none of these rows on it. The figure
# exists -- 295 rows on the measured run -- and it is on /api/quarantine with the split between real
# opportunities and units artefacts, which is the number worth having.
OPPORTUNITIES_QUARANTINED = (
    "Counted elsewhere, and withheld here on purpose. This engine ran and computed real "
    "opportunities, and none of them were published. The rows are in kalshi_quarantine_edges and the "
    "measured split -- how many are genuine, how many are units artefacts, how many are restatements "
    "of one forecast -- is served by /api/quarantine. This endpoint reports only that the engine ran "
    "and that nothing reached kalshi_edges."
)


def stopped_sites_for(edge_type: Any) -> tuple[StoppedSite, ...]:
    """The ruled-against sites that name this edge type, wired or not. Never empty for a stopped one.

    Both kinds are returned, with their own `wired_to_a_scanner` flag, because dropping the unwired
    ones would hide a real defect from a maintainer and the flag alone is enough to stop them being
    blamed for a board. A hand-built edge type that is not a string returns nothing rather than
    raising: this is called from a read, and a read must not die on a row it was handed.
    """
    if not isinstance(edge_type, str):
        return ()
    normalized = edge_type.strip().upper()
    return tuple(site for site in STOPPED_SITES if site.edge_type is not None and site.edge_type == normalized)


def repaired_sites_for(edge_type: Any) -> tuple[StoppedSite, ...]:
    """The wired sites for this edge type whose drift has been REPAIRED.

    Split from `stopped_sites_for` because the two kinds answer different questions and the UI has to
    ask both: "what was wrong here" (every site) and "is it wrong NOW" (`disposition`). A list that
    only carried unrepaired sites would quietly become a list of live defects, and a list that only
    carried repaired ones would go empty the moment everything was fixed and take the history with it.
    """
    return tuple(
        site for site in stopped_sites_for(edge_type)
        if site.wired_to_a_scanner and site.disposition == "repaired_quarantined"
    )


def edge_type_state(edge_type: Any) -> str:
    """`quarantined` if a wired site was repaired, `could_not_run` if one is still drifting, else `ran`.

    The unwired sites cannot move this, which is the whole content of `wired_to_a_scanner`: the
    question is not "is there unfixed code for this tab" but "did the thing that runs against this
    tab run at all".

    `ran` here means exactly "nothing on the ruling stops it", NOT "it found something" and not even
    "it definitely ran". The copy that draws the distinction lives in the reader, and it is allowed
    to say only what this can support.

    The two stopped states are distinguished, not merged, and the reason is the whole reason this
    module grew a third word. A repaired engine produced 295 rows: it RAN, and it measured. Calling
    that `could_not_run` tells the reader the opposite of the truth. Calling it `ran` beside an empty
    board tells them the market was quiet, which is the original defect wearing a new coat. So a
    repaired site resolves to `quarantined`, and the copy for that state has to say what it is:
    measured, counted, and deliberately not published.
    """
    sites = [site for site in stopped_sites_for(edge_type) if site.wired_to_a_scanner]
    if not sites:
        return STATE_RAN
    if any(site.disposition == "repaired_quarantined" for site in sites):
        return STATE_QUARANTINED
    return STATE_COULD_NOT_RUN


def stopped_reason(edge_type: Any) -> str | None:
    """The wired reasons for this edge type, joined. `None` when nothing stopped it.

    Only the wired sites are quoted into this, because this is the sentence that will be read as
    the explanation for an empty board. Quoting an unwired site there would be answering a
    question the reader did not ask with a cause that did not apply.
    """
    reasons = [site.reason for site in stopped_sites_for(edge_type) if site.wired_to_a_scanner]
    return " ".join(reasons) if reasons else None


class PartitionedEdgeTypes:
    """Every edge type handed in, in exactly one of three buckets. `len(ran) + len(quarantined) +
    len(could_not_run)` is the length of the input, always, and `tests/test_engine_health.py` pins it.

    Conservation is the contract for the same reason it is in `partitionDisplayOnly`: a state that
    silently drops an edge type produces a board that looks quieter than it is, and a reader
    concludes an engine was retired. The ruling relabels; it never removes.
    """

    __slots__ = ("ran", "quarantined", "could_not_run")

    def __init__(
        self,
        ran: Sequence[str],
        could_not_run: Sequence[str],
        quarantined: Sequence[str] = (),
    ) -> None:
        self.ran = tuple(ran)
        self.could_not_run = tuple(could_not_run)
        self.quarantined = tuple(quarantined)

    def __len__(self) -> int:
        return len(self.ran) + len(self.quarantined) + len(self.could_not_run)

    def __iter__(self):
        return iter(self.ran + self.quarantined + self.could_not_run)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PartitionedEdgeTypes):
            return NotImplemented
        return (
            self.ran == other.ran
            and self.could_not_run == other.could_not_run
            and self.quarantined == other.quarantined
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PartitionedEdgeTypes(ran={self.ran!r}, quarantined={self.quarantined!r}, "
            f"could_not_run={self.could_not_run!r})"
        )


def partition_edge_types(edge_types: Iterable[Any] | None) -> PartitionedEdgeTypes:
    """Split edge types into ran / quarantined / could-not-run, conserving every input.

    Order is preserved inside each bucket and every input appears exactly once, duplicates included:
    a set operation would quietly collapse a repeated edge type into one, and the caller is entitled
    to know it was given two.

    Three buckets, and the middle one is the newest. It exists because "ran and measured, and the
    measurement was withheld on purpose" is a real state these boards are in RIGHT NOW, and folding
    it into either neighbour would tell a reader something false: into `ran` it would imply a quiet
    market, into `could_not_run` it would imply nothing was looked at.
    """
    ran: list[str] = []
    could_not_run: list[str] = []
    quarantined: list[str] = []
    for edge_type in edge_types or ():
        state = edge_type_state(edge_type)
        if state == STATE_COULD_NOT_RUN:
            bucket = could_not_run
        elif state == STATE_QUARANTINED:
            bucket = quarantined
        else:
            bucket = ran
        bucket.append(edge_type if isinstance(edge_type, str) else str(edge_type))
    return PartitionedEdgeTypes(ran, could_not_run, quarantined)


def _site_payload(site: StoppedSite) -> dict[str, Any]:
    return {
        "name": site.name,
        "module": site.module,
        "site": site.site,
        "edge_type": site.edge_type,
        # Travels so a reader can tell a stopped scan path from dead code, and so nobody has to
        # guess which of the two emptied a board. The flag, not the count, is what carries it.
        "wired_to_a_scanner": site.wired_to_a_scanner,
        # Whether the drift is still there. Travels for the same reason `wired_to_a_scanner` does: a
        # site with no disposition is indistinguishable from a live defect, and this list holds both.
        "disposition": site.disposition,
        "reason": site.reason,
    }


def edge_type_entry(edge_type: str) -> dict[str, Any]:
    """One edge type's live state, as the API hands it over.

    `opportunities_found` is `None` on ALL THREE states, and that is deliberate rather than
    unfinished. This endpoint's subject is whether an engine ran; a count of what it found belongs to
    the read of the ledger -- or, for a quarantined engine, to `/api/quarantine`, which is a different
    read over a different table. Publishing a count here would put two numbers for one fact on one
    screen.

    The QUARANTINED case is the one that needed the most care, because it is the one where a count
    genuinely exists. It has 295 rows. It still reports `null`, for two reasons that are both load-
    bearing: `0` is the one value that would turn a search nobody ran into a measurement, and the
    figure that IS true lives in `kalshi_quarantine_edges` and is reported there -- with the split
    between real opportunities and units artefacts, which a bare total would throw away. So this
    endpoint says "this ran, and what it measured is withheld, and here is where that is" and the
    other one carries the number.
    """
    state = edge_type_state(edge_type)
    return {
        "edge_type": edge_type,
        "label": EDGE_TYPE_LABELS.get(edge_type, edge_type),
        "state": state,
        # Never empty and never a bare flag: a reader shown "could_not_run" learns nothing, and a
        # reader shown a reason learns that the emptiness is a fact about the engine rather than
        # about the market. `None` when nothing stopped it, so the two states cannot look alike.
        "reason": stopped_reason(edge_type),
        # Every ruled-against site naming this edge type, wired or not, each with its own flag and
        # its own disposition. The list is never truncated: a defect the reader cannot see is the
        # defect this module exists to remove.
        "stopped_sites": [_site_payload(site) for site in stopped_sites_for(edge_type)],
        # Where this edge type's measurement lives, when it has one. `None` for the two states with
        # no measurement to point at, so the three cannot be read as the same shape.
        "quarantine_sink": "kalshi_quarantine_edges" if state == STATE_QUARANTINED else None,
        "opportunities_found": None,
        "opportunities_found_reason": (
            OPPORTUNITIES_NOT_MEASURED
            if state == STATE_COULD_NOT_RUN
            else OPPORTUNITIES_QUARANTINED
            if state == STATE_QUARANTINED
            else OPPORTUNITIES_NOT_COUNTED
        ),
    }


def engine_health() -> dict[str, Any]:
    """The whole ruling, as `/api/engine-health` serves it.

    Everything is counted here rather than in the page, on the same terms as `engine_catalogue`:
    `edge_types_could_not_run` is a subtraction on a set, and a subtraction a component does at
    render time is a rule that exists in two languages and is tested in neither. The counts are
    also how a reader can tell a product with one stopped engine from a product with a broken feed,
    which is not a distinction anyone can make by looking at two tabs.
    """
    entries = [edge_type_entry(edge_type) for edge_type, _label in EDGE_TYPES]
    could_not_run = [entry["edge_type"] for entry in entries if entry["state"] == STATE_COULD_NOT_RUN]
    quarantined = [entry["edge_type"] for entry in entries if entry["state"] == STATE_QUARANTINED]
    # The state of the WHOLE board, which is the state of the unfiltered view a reader lands on
    # first. It is derived here rather than in the page for the same reason the counts are: a
    # component that asks "is any of these stopped" is a rule in a second language, and the answer
    # it would give is the answer the whole product turns on. A board with one stopped engine out of
    # five is not a working board, and this is where that is said once rather than re-derived.
    #
    # `could_not_run` outranks `quarantined` for the whole-board state, and deliberately: the
    # unfiltered view cannot say "measured but withheld" without also saying what was not measured at
    # all, and a reader who is told only the first is being told a board is in better shape than it
    # is. A quarantined board is a board with a question open; a broken one has no data at all.
    if could_not_run:
        board_state = STATE_COULD_NOT_RUN
    elif quarantined:
        board_state = STATE_QUARANTINED
    else:
        board_state = STATE_RAN
    return {
        "edge_types": entries,
        "edge_types_total": len(entries),
        "edge_types_could_not_run": len(could_not_run),
        "edge_types_quarantined": len(quarantined),
        "edge_types_ran": len(entries) - len(could_not_run) - len(quarantined),
        # The unfiltered view's own state, so a reader who has not picked a tab gets the truth
        # about the board rather than a copy of one tab's copy.
        "board_state": board_state,
        "board_reason": (
            " ".join(entry["reason"] for entry in entries if entry["reason"])
            if could_not_run or quarantined
            else None
        ),
        # The ruling itself, in full, including the two sites that feed no board. They are in the
        # payload rather than only in this file so the reason travels with the data: a browser can
        # hold an older bundle than the API, and a copy of this list in TypeScript would be a copy
        # that could disagree with the server about which engines are switched off.
        "sites": [_site_payload(site) for site in STOPPED_SITES],
        "sites_total": len(STOPPED_SITES),
        "sites_wired": len(WIRED_STOPPED_SITES),
        "sites_unwired": len(UNWIRED_STOPPED_SITES),
        # How many of the wired sites are still drifting, and how many were repaired. Two numbers
        # rather than one, because "3 sites" answers neither question a reader has: is anything
        # broken, and what was fixed.
        "sites_repaired": sum(1 for s in STOPPED_SITES if s.disposition == "repaired_quarantined"),
        "sites_unrepaired": sum(1 for s in STOPPED_SITES if s.disposition != "repaired_quarantined"),
        "note": (
            "An engine on this list either did not run, or ran and had its output quarantined rather "
            "than published. An empty board for it is not a finding about the market, and it is never "
            "reported as a count of zero."
        ),
    }

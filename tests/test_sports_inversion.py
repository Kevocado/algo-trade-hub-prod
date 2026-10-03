"""The inversion: the predictor's published calibration first, the hub's ledger once it has enough.

Approved 2026-09-27. The reasoning: the predictor publishes its own reliability record, so it is
available immediately and it is the model's own view of itself. The hub's settled ledger reflects what
the hub actually graded and priced against, so once it has enough settled results it becomes the
authority. Below that, the hub has no record to offer and deferring to it would be deferring to
nothing.

The threshold is `HUB_LEDGER_MIN_SETTLED = 100` -- the same number as the reviewer's `MIN_SETTLED`
(`sports/scorecard.py`), because 100 is the settled count this product has consistently meant (spec 3
and 5b). It is a named constant rather than a literal so a later ruling changes one place, and one
test ties it to the reviewer's own constant so the two cannot drift apart silently.

Three things this file also pins, because each was a live hole rather than a decision:

- **The ledger speaks for all three kinds, per engine.** `sports/scan.py` writes `"kind": kind` into
  every sports `predictions` row's own `raw_payload`, so the kind is a fact the hub itself recorded.
  Publishing only winners does not narrow the record, it makes every spread and total edge
  `calibration_insufficient` on the day the hub crosses the threshold. And one ledger shared across
  both sports would put NFL's rows into CFB's bands: different models, different records.
- **`choose_calibration` counts only the kind it is judging.** The threshold is about evidence for
  the band being looked up, and that band belongs to one kind. CFB's live ledger is 42 winner / 33
  spread / 32 total: an aggregate of 107 would hand the hub authority on a winner bucket holding 42
  settled rows.
- **`n_buckets` is read off the feed, not assumed here**, and the hub's bands carry
  `orientation: "raw"` so the fact that they are cut on un-normalised side-oriented probabilities
  travels in the data rather than living in a docstring someone has to go looking for.

And three more, from the second fix round, each the same shape of hole found one increment later:

- **One list of kinds, and the names it cannot hold are reported.** The triple was written twice --
  `hub_calibration.KINDS` and an inlined copy in `parse_feed` -- and a settled-ledger reader FILTERS
  rows down to it, so a second copy is not a second view of the list, it is a filter whose exclusions
  were silent. A fourth kind would have deleted every settled row of itself with nothing logged.
- **The review cache key names the calibration source.** The same market is judged on the
  predictor's record until the hub has enough settled rows of its kind and on the hub's own record
  from then on; one key for both would serve a cached verdict reasoned over the other band.
- **`None` is "not measured", for both diagnostic keys, and nothing else is.** `unrecognised_kinds`
  chose `{}` deliberately -- an empty tally is the POSITIVE answer -- and the failed read was
  returning a bare `HubLedger()`, so a run that read nothing published the reassuring value for a
  question it never asked. One sentinel with one meaning, shared with `too_far`'s "this sport never
  scanned", is what stops that: a reader must never see a value that reads as a completed
  measurement for a measurement that did not happen.
"""
import inspect
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.edges import EdgeSuggestion, Quote
from tradehub.markets import parse_market
from tradehub.sports import feed as feed_mod
from tradehub.sports import hub_calibration as hub_calibration_mod
from tradehub.sports import kinds as kinds_mod
from tradehub.sports import scan as scan_mod
from tradehub.sports.candidates import HUB_LEDGER_MIN_SETTLED, check_candidate, choose_calibration
from tradehub.sports.feed import FeedGame, parse_feed
from tradehub.sports.hub_calibration import HUB_ORIENTATION, KINDS, settled_buckets
from tradehub.sports.journal_ledger import journal_settled_ledger
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame
from tradehub.sports.reviewer import SYSTEM_PROMPT, MemoryReviewStore, Review, cache_key
from tradehub.sports.scorecard import MIN_SETTLED

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

PARAMS = {"max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000, "min_hours_to_start": 1,
          "max_hours_to_start": 72, "calibration_max_dev": 0.10, "calibration_min_n": 20}

PREDICTOR = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 3, "mean_prob": 0.65, "hit_rate": 0.66}]}
HUB = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 120, "mean_prob": 0.65, "hit_rate": 0.70}]}

# What `parse_feed` returns for a payload that published no calibration at all. NOT `{}`: the
# comprehension is `{k: calibration.get(k) or [] for k in KINDS}`, so the mapping always has three
# keys and is always truthy, and every test that hand-built `{}` to mean "no predictor" was testing
# an input production cannot produce. That is what made the `return {}, "none"` branch unreachable,
# and what let a feed with nothing to say be recorded as `calibration_source: "predictor"` -- the
# predictor's own record rejecting the edge, when the predictor published no record at all.
NO_PREDICTOR_RECORD = {kind: [] for kind in KINDS}


def test_the_predictors_own_calibration_is_used_while_the_hub_has_too_little():
    calibration, source = choose_calibration(PREDICTOR, {"winner": []}, {}, "winner")

    assert source == "predictor"
    assert calibration is PREDICTOR


def test_the_hubs_ledger_takes_over_once_it_has_enough():
    calibration, source = choose_calibration(PREDICTOR, HUB, {}, "winner")

    assert source == "hub_ledger"
    assert calibration is HUB


def test_the_threshold_is_the_reviewers_own_number():
    """100 is what this product means by 'enough settled'. The reviewer's MIN_SETTLED is the same
    number for the same reason, and two thresholds for one concept is how they drift."""
    assert HUB_LEDGER_MIN_SETTLED == 100
    assert HUB_LEDGER_MIN_SETTLED == MIN_SETTLED, (
        "the candidate filter and the reviewer must not disagree about how much settled evidence "
        "is enough -- see tests/test_gate_threshold_coherence.py for the arithmetic that made this "
        "coherence a problem"
    )


def test_one_short_of_the_threshold_stays_with_the_predictor():
    short = {"winner": [{"lo": 0.6, "hi": 0.7, "n": HUB_LEDGER_MIN_SETTLED - 1,
                         "mean_prob": 0.65, "hit_rate": 0.70}]}
    _, source = choose_calibration(PREDICTOR, short, {}, "winner")

    assert source == "predictor"


def test_no_hub_calibration_at_all_stays_with_the_predictor():
    _, source = choose_calibration(PREDICTOR, None, {}, "winner")

    assert source == "predictor"


def test_the_hubs_own_settled_rows_do_not_count_towards_another_kinds_bands():
    """The threshold is about evidence for the band being looked up, and that band belongs to one
    kind. Summing `n` across kinds is safe only while the hub published one kind, which was true
    under the superseded winner-only ruling and is false now that all three are published.

    The numbers are CFB's live ledger as read on 2026-09-27: 42 winner / 33 spread / 32 total. The
    aggregate clears 100, so an aggregate count would put the hub in charge of a WINNER bucket
    holding 42 settled rows -- under half the evidence this threshold is asking for -- and every
    winner edge would be judged on it. A kind borrows no other kind's evidence.
    """
    cfb_ledger = {"winner": [{"lo": 0.0, "hi": 1.0, "n": 42}],
                  "spread": [{"lo": 0.0, "hi": 1.0, "n": 33}],
                  "total": [{"lo": 0.0, "hi": 1.0, "n": 32}]}

    assert sum(b["n"] for bands in cfb_ledger.values() for b in bands) >= HUB_LEDGER_MIN_SETTLED, (
        "this test only bites while the aggregate clears the threshold"
    )
    calibration, source = choose_calibration(PREDICTOR, cfb_ledger, {}, "winner")

    assert source == "predictor", "a winner edge must be gated on WINNER evidence"
    assert calibration is PREDICTOR


def test_the_count_is_per_kind_so_one_thin_kind_cannot_speak_for_another():
    """The complement of the test above, so the per-kind count is pinned from both sides: spread and
    total both stay on the predictor when only the winner bands are thick, and the winner bands
    alone are enough to switch a spread edge. Without a per-kind count every one of these returns
    `hub_ledger`."""
    thick_winner = {"winner": [{"lo": 0.0, "hi": 1.0, "n": 300}],
                    "spread": [{"lo": 0.0, "hi": 1.0, "n": 4}],
                    "total": [{"lo": 0.0, "hi": 1.0, "n": 0}]}

    assert choose_calibration(PREDICTOR, thick_winner, {}, "winner")[1] == "hub_ledger"
    for thin in ("spread", "total"):
        calibration, source = choose_calibration(PREDICTOR, thick_winner, {}, thin)
        assert source == "predictor", f"a {thin} band judged on the winner model's 300 rows"
        assert calibration is PREDICTOR


def test_no_predictor_calibration_and_no_hub_falls_through_to_the_hub_rather_than_nothing():
    # A missing predictor payload must not leave the filter with no calibration at all, which would
    # read as "no bucket" and reject every edge for a reason that looks like bad luck.
    calibration, source = choose_calibration(NO_PREDICTOR_RECORD, HUB, {}, "winner")

    assert source == "hub_ledger"
    assert calibration is HUB


def test_a_thin_hub_with_no_predictor_at_all_reaches_the_fall_through_rather_than_the_first_branch():
    """The fall-through branch, reached on purpose. `HUB` above holds `n: 120`, so that test exits on
    the FIRST branch and the third is never exercised: delete the third branch and the whole suite
    still passes.

    5 settled is under the threshold, so this can only return the hub by falling through, and
    returning nothing would leave `check_candidate` with an empty calibration -- every edge rejected
    for "no bucket", which reads as bad luck rather than as an absent measurement.

    The predictor side is the shape `parse_feed` really produces for an absent calibration, not the
    `{}` this test used to hand-build. `{}` is falsy and skipped a branch; the real mapping is truthy
    with three empty lists, so under mapping truthiness it was taken -- and the fall-through below
    was dead code in production while this test passed against it.
    """
    thin = {"winner": [{"lo": 0.0, "hi": 1.0, "n": 5, "mean_prob": 0.65, "hit_rate": 0.6}]}
    assert sum(b["n"] for b in thin["winner"]) < HUB_LEDGER_MIN_SETTLED, "must not clear branch one"

    calibration, source = choose_calibration(NO_PREDICTOR_RECORD, thin, {}, "winner")

    assert source == "hub_ledger"
    assert calibration is thin


def test_a_predictor_that_published_no_bands_is_not_a_predictor_record():
    """The attribution defect, at the branch. A feed that published NO calibration at all was
    recorded on the edge row and in the reviewer's fact pack as `calibration_source: "predictor"` --
    which reads downstream as *the predictor's record rejected this* -- because the test was
    `if predictor_calibration:` on a mapping `parse_feed` always fills with three keys. Evaluated
    directly, which is the only way to see it:

        parse_feed({"calibration": {}}).calibration -> {'winner': [], 'spread': [], 'total': []}
        bool(that)                                 -> True
        choose_calibration(that, None, ...)        -> ('predictor' mapping, 'predictor')

    That is the same defect class this file already fixed once, in the fact pack's
    `predictor_calibration_in_bucket`: the numbers right, the label wrong, and nothing downstream
    knows to distrust it. The test is per bucket now -- did the predictor send any bands -- because
    that is the question the branch was written to ask.

    And it makes the `return {}, "none"` branch reachable in production, which it was not before:
    `parse_feed` never produced a falsy mapping, so the branch was only ever reached by a caller
    that passed `None`. A feed with nothing to say is exactly the case it exists for.
    """
    assert bool(NO_PREDICTOR_RECORD) is True, (
        "the dict-truthiness this replaced was true here, which is the whole finding"
    )
    calibration, source = choose_calibration(NO_PREDICTOR_RECORD, None, {}, "winner")

    assert source == "none", "the predictor published nothing, so it rejected nothing"
    assert calibration == {}
    # And the label it used to be given, so the fix is visibly about the attribution: a hub ledger
    # with a single band is a record, and a band set of `n: 0` is the hub's own record saying it has
    # settled nothing -- so the hub side keeps mapping truthiness and this is not a tidy-up of one
    # branch into another. `n: 0` on the predictor's side is not a record at all.
    unearned = {"winner": [{"lo": 0.0, "hi": 1.0, "n": 0, "mean_prob": None, "hit_rate": None}]}
    assert choose_calibration(NO_PREDICTOR_RECORD, unearned, {}, "winner") == (unearned, "hub_ledger")


def test_a_predictor_that_published_bands_for_another_kind_only_is_still_a_record():
    """The other side of the line, so the fix cannot be over-applied into "any empty band means no
    record". A predictor that published history for the spread bands and none for the winner bands
    HAS published a record, and a winner edge it rejects is rejected by a record rather than by
    nothing. Which is the whole difference between the two branches."""
    winner_only = {"winner": [], "spread": [{"lo": 0.0, "hi": 1.0, "n": 40, "mean_prob": 0.5,
                                             "hit_rate": 0.5}], "total": []}

    calibration, source = choose_calibration(winner_only, None, {}, "winner")

    assert source == "predictor"
    assert calibration is winner_only


def test_with_neither_source_the_filter_is_told_so_rather_than_left_guessing():
    calibration, source = choose_calibration(None, None, {}, "winner")

    assert source == "none"
    assert calibration == {}


def test_the_kind_is_required_rather_than_defaulted():
    """A default would be a silent wrong answer at a call site that forgot, and 'enough settled
    evidence' is precisely the thing that must not be guessed. `check_candidate` already has `kind`
    as its first positional argument, so it can pass it without a new parameter."""
    parameter = inspect.signature(choose_calibration).parameters["kind"]

    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        choose_calibration(PREDICTOR, HUB, {})


class TestSettledBuckets:
    def test_it_builds_the_same_shape_the_feed_publishes(self):
        """`bucket_for` in candidates.py indexes on lo/hi/n, so the shape must match or lookup misses
        and every edge fails calibration_insufficient for the wrong reason."""
        pairs = [(0.65, True)] * 8 + [(0.65, False)] * 2
        buckets = settled_buckets(pairs, n_buckets=10)

        assert "winner" in buckets
        target = buckets["winner"][6]  # 0.6-0.7
        assert target["lo"] == pytest.approx(0.6)
        assert target["hi"] == pytest.approx(0.7)
        assert target["n"] == 10
        assert target["mean_prob"] == pytest.approx(0.65)
        assert target["hit_rate"] == pytest.approx(0.8)

    def test_an_empty_pair_set_gives_buckets_that_are_visibly_unearned_not_none(self):
        """The feed's own shape for a band with no history: present, `n: 0`, no statistics. `None` for
        the whole key would read as 'no data at all' instead of 'nothing settled in this band'."""
        buckets = settled_buckets([], n_buckets=10)["winner"]

        assert len(buckets) == 10
        assert all(b["n"] == 0 and b["mean_prob"] is None and b["hit_rate"] is None for b in buckets)

    def test_the_bucket_count_is_the_callers_decision_and_is_required(self):
        """10 and 4 both work and both are used in practice: the predictors are moving to 4, so a
        default of 10 here would be a number this module has no business assuming -- which is what
        its own docstring says, in as many words."""
        assert len(settled_buckets([], n_buckets=4)["winner"]) == 4
        assert len(settled_buckets([], n_buckets=10)["winner"]) == 10
        with pytest.raises(TypeError):
            settled_buckets([(0.5, True)])

    def test_it_refuses_a_bucket_count_it_cannot_cut_on(self):
        with pytest.raises(ValueError):
            settled_buckets([(0.5, True)], n_buckets=0)

    def test_the_last_bucket_owns_a_probability_of_exactly_one(self):
        """`lo <= p < hi` drops 1.0 out of every band, and a certain call is the one probability a
        record must not lose."""
        assert settled_buckets([(1.0, True)], n_buckets=10)["winner"][9]["n"] == 1

    def test_every_kind_the_feed_publishes_is_published(self):
        """All three, against the DECLARED list rather than this module's own default argument.

        The old version of this test compared `settled_buckets`'s output to `KINDS`, which is the
        value it was called with as its default -- so it agreed with whatever the default was and
        proved nothing about any other site. The list that matters is the one `parse_feed` reads the
        payload against and `scan.py` filters settled rows by, and that is `sports.kinds.KINDS`:
        publishing fewer is not a narrower record, it is every spread and total edge becoming
        `calibration_insufficient` the day the hub crosses the threshold, plus every settled row of
        an unpublished kind deleted with nothing said.
        """
        buckets = settled_buckets([(0.65, True)] * 3, n_buckets=10)

        assert set(buckets) == set(kinds_mod.KINDS)

    def test_the_band_count_defaults_to_the_declared_list_and_not_a_copy_of_it(self):
        """`is`, not `==`. A fourth kind added to the declared list has to reach the publisher; a
        re-typed copy of the list in the signature would pass an equality check and keep the two
        apart, which is the drift this whole section exists to prevent."""
        assert inspect.signature(settled_buckets).parameters["kinds"].default is kinds_mod.KINDS

    def test_every_band_says_its_probabilities_are_not_home_oriented(self):
        """The limitation travels in the data. `our_prob` on a settled row is the probability for
        that market's SIDE while `bucket_for` is asked for a home-oriented one, so a band built from
        the ledger mixes orientations; NFL and CFB list a winner market for both teams of a game.
        A limitation that lives only in a docstring is invisible to whoever reads the numbers, and
        this is the kind that gets silently inherited."""
        buckets = settled_buckets([(0.65, True)] * 3, n_buckets=10)

        assert HUB_ORIENTATION == "raw"
        for bands in buckets.values():
            for band in bands:
                assert band["orientation"] == "raw"


# ── the filter, on real objects ──────────────────────────────────────────────────────────────

GAME = FeedGame(sport="nfl", game_id="2026_03_HOU_IND", home="IND", away="HOU",
                start_utc=NOW + timedelta(hours=29), p_home=0.35, margin_mu=-4.0, sigma=13.0,
                total_mu=45.0, total_sigma=12.0, model_version="ridge@t",
                snapshotted_at=NOW - timedelta(hours=10))
MARKET = SportsMarket(
    market=parse_market({"ticker": "KXNFLGAME-26SEP27HOUIND-IND", "event_ticker": "KXNFLGAME-26SEP27HOUIND",
                         "strike_type": "structured", "open_time": "2026-09-15T16:00:00Z",
                         "close_time": "2026-09-29T17:00:00Z", "title": "IND wins"}),
    quote=Quote(yes_bid=0.27, yes_ask=0.28, yes_bid_size=5000.0, yes_ask_size=4000.0),
    volume=50000.0, suffix="IND")
MG = MatchedGame(game=GAME, home_code="IND", away_code="HOU", suffix="26SEP27HOUIND", markets={})
EDGE = EdgeSuggestion("KXNFLGAME-26SEP27HOUIND-IND", "yes", 0.27, True, 7.5, 0.35, 0.275)


def _banded_buckets(counts, mean=0.35, hit=0.36):
    """Ten bands, with `n` settled in the bands named by `counts` and nothing anywhere else."""
    return [{"lo": i / 10, "hi": (i + 1) / 10, "n": counts.get(i, 0),
             "mean_prob": mean if counts.get(i) else None, "hit_rate": hit if counts.get(i) else None}
            for i in range(10)]


def _predictor_buckets():
    return _banded_buckets({3: 30}, hit=0.33)


def _hub_buckets():
    return _banded_buckets({3: 120})


def test_the_new_parameter_is_keyword_only_so_every_existing_caller_keeps_working():
    """`scan.py` and four existing test modules call this positionally with seven arguments. A
    positional-or-keyword parameter would also accept an eighth positional argument, which is exactly
    the shape that would let a future call site pass the hub's calibration where the timestamp
    belongs."""
    parameter = inspect.signature(check_candidate).parameters["hub_calibration"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    with pytest.raises(TypeError):
        check_candidate("winner", MARKET, MG, EDGE, {"winner": _predictor_buckets()}, PARAMS, NOW, HUB)


def test_a_filter_call_without_the_hub_reports_the_predictor():
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _predictor_buckets()}, PARAMS, NOW)

    assert check.calibration_source == "predictor"
    assert check.ok is True


def test_the_filter_actually_judges_against_the_hub_once_it_has_enough():
    """Not just the label. The bucket that comes back is the hub's, so `calibration_insufficient`
    would be read off the hub's settled record rather than the predictor's."""
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _predictor_buckets()}, PARAMS, NOW,
                            hub_calibration={"winner": _hub_buckets()})

    assert check.calibration_source == "hub_ledger"
    assert check.bucket["n"] == 120
    assert check.ok is True


def test_a_band_the_predictor_was_happy_with_can_still_reject_the_edge_under_the_hub():
    """The switch is not cosmetic: the hub is a different record, and it is allowed to disagree.
    Here the predictor has 30 settled in the band (enough) and the hub has 5, with its 100 elsewhere
    so it is in charge. The edge is rejected on the hub's band, which is the entire claim of the
    inversion -- and the honest failure mode, since the hub is the record of what the hub priced."""
    hub = _banded_buckets({3: 5, 7: HUB_LEDGER_MIN_SETTLED})
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _predictor_buckets()}, PARAMS, NOW,
                            hub_calibration={"winner": hub})

    assert check.calibration_source == "hub_ledger"
    assert check.bucket["n"] == 5
    assert check.reasons == ("calibration_insufficient",)


def test_the_filter_counts_only_the_kind_it_is_filtering():
    """`choose_calibration` reached through `check_candidate`, so the per-kind count is proven on the
    path that actually runs rather than only on the function. The winner bands hold 6 -- under the
    threshold -- and the spread bands hold 300, which is exactly the shape that would hand a winner
    edge another kind's record."""
    hub = {"winner": _banded_buckets({3: 6}), "spread": _banded_buckets({3: 300}),
           "total": _banded_buckets({3: 300})}

    winner = check_candidate("winner", MARKET, MG, EDGE, {"winner": _predictor_buckets()}, PARAMS, NOW,
                             hub_calibration=hub)

    assert winner.calibration_source == "predictor"
    assert winner.bucket["n"] == 30, "the predictor's own band, not the hub's 300"


# ── the threading, through the scan ───────────────────────────────────────────────────────────


def _rebands(buckets, count):
    """Re-cut a published band list into `count` bands of equal width, the same edges a predictor
    publishing `n_buckets: count` would send.

    Overwriting the `n_buckets` scalar while leaving ten bands in place is what the first version of
    the n_buckets test did, and it does not prove a 4-band feed works: the edges the hub would cut on
    would still be the ten the fixture happened to carry. The predictors are moving to four bands, so
    the four-band feed has to be a real one.
    """
    return ([{"lo": i / count, "hi": (i + 1) / count, "n": 0, "mean_prob": None, "hit_rate": None}
             for i in range(count)], count)


def _recorded_feed(sport="nfl", *, n_buckets=None, calibrated=True, bands=True, calibration=True):
    """The recorded feed, so `n_buckets` is the number a live predictor actually publishes."""
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    if not calibration:
        # A feed with no calibration KEY at all, which is not the same input as one that published
        # empty bands. `parse_feed` reads both to `n_buckets: 0`, so both are pinned below.
        raw["calibration"] = {}
    elif not bands:
        # A feed that published no bands at all: no count to read and no edges to cut on.
        raw["calibration"] = {"n_buckets": 0, "winner": [], "spread": [], "total": []}
    elif n_buckets is not None:
        for kind in ("winner", "spread", "total"):
            raw["calibration"][kind], raw["calibration"]["n_buckets"] = _rebands(
                raw["calibration"][kind], n_buckets
            )
    if calibrated:
        for kind in ("winner", "spread", "total"):
            for bucket in raw["calibration"].get(kind) or []:
                mid = round(bucket["lo"] + 0.05, 2)
                bucket.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


def _recorded_markets(sport="nfl"):
    from tradehub.sports.kalshi import parse_sports_market
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    return {series: [parse_sports_market(m) for m in markets] for series, markets in raw.items()}


# The home-oriented probability the recorded HOU@IND markets land on, per kind: winner 0.2954 (both
# sides of the game), spread 0.3637 (HOU3), total 0.5125 (46). 120 settled snapshots at each, 60 of
# the 120 right, so each kind's record is a real measurement rather than a flattering one, and each
# clears HUB_LEDGER_MIN_SETTLED on its OWN evidence -- which is the whole point of the corrected
# ruling, since a kind cannot borrow another's count.
HUB_LEDGER = {
    "winner": [(0.2954, True)] * 60 + [(0.2954, False)] * 60,
    "spread": [(0.3637, True)] * 60 + [(0.3637, False)] * 60,
    "total": [(0.5125, True)] * 60 + [(0.5125, False)] * 60,
}


def _scan(feed, **kwargs):
    from tradehub.sports.config import load_sport_config
    return scan_mod.scan_sport(load_sport_config("nfl"), _recorded_markets(), feed, NOW, **kwargs)


def _graded_winner_rows(result):
    """The winner rows the hub's settled ledger actually speaks about."""
    return [row for row in result.edges if row["kind"] == "winner" and row["calibration_bucket"]["n"] == 120]


def test_a_scan_with_no_hub_ledger_still_uses_the_predictors_calibration():
    result = _scan(_recorded_feed())

    assert result.edges
    assert {row["calibration_source"] for row in result.edges} == {"predictor"}


def test_the_hub_ledger_takes_over_the_scan_once_it_has_enough():
    result = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)

    assert {row["calibration_source"] for row in result.edges} == {"hub_ledger"}
    graded = _graded_winner_rows(result)
    assert len(graded) == 2, "the recorded HOU@IND winner markets, on both sides of one game"
    for row in graded:
        # 60/60 at 0.2954: the band the edge is admitted on is the hub's own record.
        assert row["calibration_bucket"]["hit_rate"] == pytest.approx(0.5)
        assert row["calibration_bucket"]["mean_prob"] == pytest.approx(0.2954)
        assert row["candidate"] is True, row["reject_reasons"]


def test_the_hub_ledger_judges_every_kind_on_its_own_settled_record():
    """The corrected ruling, end to end. The ledger speaks for all three kinds, so a spread edge and a
    total edge are each judged on the hub's settled SPREAD and TOTAL bands -- and the bands are found.

    Under the overturned winner-only version of this file, every row below was
    `calibration_insufficient` for the whole of the hub's authority: `calibration.get("spread")` and
    `calibration.get("total")` had no key at all, because the mapping only published `winner`. That is
    not a narrower record, it is the product losing every spread and total edge on the day the
    threshold is crossed -- the outcome the corrected ruling exists to prevent, and why this asserts a
    FOUND BAND rather than just a source label.

    Total is asserted on the band rather than on admission: the recorded total market whose home
    probability lands on the hub's total band (KXNFLTOTAL-26SEP27HOUIND-46) fails liquidity on its own
    merits, which is a different gate and is not what this test is about.

    The kind names are written out rather than imported from `hub_calibration.KINDS`: a test that
    loops over the constant it is supposed to be checking agrees with the constant, so shrinking
    `KINDS` to `("winner",)` would quietly skip the spread and total assertions instead of failing
    them. (It did, until this was written that way -- see the mutation table in the report.)
    """
    result = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)

    for kind in ("winner", "spread", "total"):
        rows = [row for row in result.edges if row["kind"] == kind]
        assert rows, f"the recorded feed has {kind} markets; this test needs one"
        graded = [row for row in rows
                  if row["calibration_source"] == "hub_ledger" and row["calibration_bucket"]["n"] == 120]
        assert graded, (
            f"no {kind} edge was judged on the hub's own {kind} bands: "
            f"{[(r['market_ticker'], r['calibration_bucket'], r['reject_reasons']) for r in rows]}"
        )
        for row in graded:
            assert "calibration_insufficient" not in row["reject_reasons"], row["market_ticker"]
            assert row["calibration_bucket"]["orientation"] == "raw"
    # And the switch is not cosmetic for the kinds either: a spread edge is ADMITTED on the hub's
    # spread record, where the winner-only version rejected it out of hand.
    assert [row for row in result.edges if row["kind"] == "spread" and row["candidate"]]


def test_a_kind_the_hub_has_not_settled_keeps_the_predictor_in_charge():
    """The other half of the corrected ruling, and the reason the per-kind count is not optional. A
    sport with no settled spread rows must not have its spread edges judged against the winner model's
    300 rows: the hub has no spread record to offer, so the published one stays in force.

    This is the failure an aggregate count invites. With `n` summed across kinds, 300 winner rows would
    switch every spread and total edge in the sport over to a record that has never seen one."""
    winner_only = {"winner": [(0.2954, True)] * 150 + [(0.2954, False)] * 150}
    result = _scan(_recorded_feed(), hub_pairs=winner_only)
    graded = [row for row in result.edges if row["kind"] in ("spread", "total")]

    assert graded, "the recorded feed has spread and total markets; this test needs one"
    for row in graded:
        assert row["calibration_source"] == "predictor", row["market_ticker"]
        assert row["calibration_bucket"]["n"] == 40, "the predictor's published band, not the hub's"
        assert "calibration_insufficient" not in row["reject_reasons"], row["market_ticker"]


def test_a_game_the_hub_has_never_settled_is_rejected_on_the_hubs_record():
    """The switch has teeth, and the direction matters. With the predictor in charge the recorded feed
    admits every matched market; once the hub's ledger is in charge, a game it has no settled history
    for finds an empty band and is rejected. That is the claim of the inversion -- the hub is the
    record of what the hub itself priced and graded -- but it is a real narrowing of the board rather
    than a relabelling, so it is pinned here rather than left to be discovered."""
    predicted = _scan(_recorded_feed())
    switched = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)

    ungraded = [row for row in switched.edges
                if row["kind"] == "winner" and row["calibration_bucket"]["n"] == 0]
    assert ungraded, "the recorded feed has a winner market outside the band the settled pairs are in"
    for row in ungraded:
        assert row["candidate"] is False, row["reject_reasons"]
        assert "calibration_insufficient" in row["reject_reasons"]
        was_admitted = next(r for r in predicted.edges if r["market_ticker"] == row["market_ticker"])
        assert was_admitted["candidate"] is True, (
            "the predictor's record admits this market, so the narrowing is the hub's doing"
        )
    # And it is a narrowing rather than a shutdown: the bands the hub has settled for stay admitted.
    assert [row for row in switched.edges if row["candidate"]]
    assert len([r for r in switched.edges if r["candidate"]]) < len([r for r in predicted.edges if r["candidate"]])


def test_the_hubs_bands_are_cut_on_the_number_of_buckets_the_feed_published():
    """The predictor's `n_buckets` is moving from 10 to 4, and this is why that number is read rather
    than assumed. A hub bucket set cut on different edges is not a replacement for the predictor's
    record, it is a different measurement wearing its name.

    Two halves, because neither earns the name alone: at 10 the band is 0.1 wide and a hardcoded 4
    fails it, and at 4 the band is 0.25 wide and a hardcoded 10 fails it.

    The 4-band feed is a REAL 4-band feed -- four published bands, re-cut on quarter edges -- not a
    ten-band feed with the scalar overwritten, which is the input the first version of this test used
    and which cannot tell a read from a hardcode.
    """
    for published, width in ((10, 0.1), (4, 0.25)):
        feed = _recorded_feed(n_buckets=published)
        assert feed.n_buckets == published
        for bands in feed.calibration.values():
            assert len(bands) == published, f"the feed must publish {published} bands per kind"
        result = _scan(feed, hub_pairs=HUB_LEDGER)
        bucket = _graded_winner_rows(result)[0]["calibration_bucket"]

        assert bucket["hi"] - bucket["lo"] == pytest.approx(width), (
            f"a feed publishing n_buckets={published} must produce bands {width} wide"
        )
        assert bucket["n"] == 120, "and the same settled pairs must land in the band the edge is in"


def test_the_hub_records_that_its_bands_are_not_home_oriented():
    """The orientation limitation, pinned where it is claimed: in the data. A stored edge row is what
    a future reader meets, and a `mean_prob` with no caveat is a number somebody will trust."""
    result = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)
    hub_rows = [row for row in result.edges if row["calibration_source"] == "hub_ledger"]

    assert hub_rows
    for row in hub_rows:
        assert row["calibration_bucket"]["orientation"] == HUB_ORIENTATION


def test_a_feed_that_published_no_bands_leaves_nobody_in_charge():
    """Nothing to cut against is not a reason to invent a cut. With 120 settled pairs in hand the scan
    still refuses the hub's bands, which is the behaviour before the inversion.

    And the source is `none` rather than `predictor`, which is the correction this test had to
    absorb. It used to read `== {"predictor"}` and passed, because `feed.calibration` is a dict of
    three keys whatever the payload held, so `if predictor_calibration:` was true for a predictor
    that had published no bands at all -- and a row labelled `calibration_source: "predictor"`
    tells every reader below that the predictor's own record rejected the edge, when the predictor
    had no record. Same shape as the fact pack's `predictor_calibration_in_bucket`, one module over.

    `none` is the branch that says so, and it is now REACHABLE in production: `_hub_calibration`
    returns `None` when the feed published no `n_buckets`, so the hub offers nothing, and the
    predictor published nothing, and `{}` is the only honest thing left. The board is unchanged
    either way -- every edge is rejected for `calibration_insufficient`, which is the gate failing
    closed -- so this is a change to the ATTRIBUTION and not to the gate.
    """
    result = _scan(_recorded_feed(bands=False), hub_pairs=HUB_LEDGER)

    assert result.edges
    assert {row["calibration_source"] for row in result.edges} == {"none"}
    assert all("calibration_insufficient" in row["reject_reasons"] for row in result.edges)
    assert all(row["calibration_bucket"] is None for row in result.edges)

    # And the other absent-calibration input, a payload with no `calibration` key at all, reaches the
    # same branch rather than a second way of saying `predictor`. Two inputs, one answer: "the
    # predictor sent nothing" is one fact, and `parse_feed` already normalises both shapes to the
    # same three empty lists, so the filter must not tell them apart either.
    absent = _scan(_recorded_feed(calibration=False), hub_pairs=HUB_LEDGER)
    assert {row["calibration_source"] for row in absent.edges} == {"none"}


class TestTheFeedsBucketCount:
    """`n_buckets` is read off the payload, so these pin the reading rather than the number."""

    def test_it_is_the_count_the_feed_published(self):
        assert _recorded_feed().n_buckets == 10, "the recorded NFL feed published ten bands"
        assert _recorded_feed(n_buckets=4).n_buckets == 4

    def test_a_payload_without_the_field_falls_back_to_the_bands_it_published(self):
        """The same fact read a different way: the length of the published bucket list. Defaulting to
        10 here instead would be a hub-side guess at the predictor's setting, which is the one thing
        this path exists to avoid."""
        raw = json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())
        raw["calibration"].pop("n_buckets")

        assert parse_feed(raw).n_buckets == 10

    def test_a_feed_with_no_calibration_key_publishes_no_count(self):
        """An ABSENT calibration, which is what the test's name says. Distinct input from the one
        below: a feed that published the key with no bands under it."""
        assert _recorded_feed(calibration=False).n_buckets == 0

    def test_a_feed_with_no_calibration_publishes_no_count(self):
        """The key present, every band list empty. Same answer, and both are pinned because the
        difference is the difference between "the predictor sent nothing" and "the predictor sent a
        calibration with no history in it"."""
        assert _recorded_feed(bands=False).n_buckets == 0


# ── the fact pack: which record the reviewer is being handed ─────────────────────────────────


def _fact_pack_for(result, market_ticker):
    return next(req.fact_pack for req in result.review_requests
                if req.market_ticker == market_ticker)


def test_the_fact_pack_does_not_misattribute_the_hubs_record_to_the_predictor():
    """The reviewer is the component this whole design defers the calibration judgement to, so
    handing it the hub's `mean_prob`/`hit_rate` under a key reading `predictor_calibration_in_bucket`
    is the exact failure the inversion exists to avoid: the numbers are right and the label is wrong,
    which is worse than a wrong number because nothing downstream knows to distrust it.

    The reviewer is given the fact pack verbatim as JSON, so the key IS the attribution."""
    result = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)
    ticker = _graded_winner_rows(result)[0]["market_ticker"]
    pack = _fact_pack_for(result, ticker)

    assert pack["calibration_source"] == "hub_ledger"
    assert pack["calibration_in_bucket"]["n"] == 120
    assert "predictor_calibration_in_bucket" not in pack, (
        "the old key still names the predictor whatever produced the band"
    )
    assert "predictor_calibration_in_bucket" not in json.dumps(pack)


def test_the_fact_pack_names_the_predictor_when_the_predictor_is_the_record():
    """The other side: renaming the key must not lose the source. Both cases carry it."""
    result = _scan(_recorded_feed())
    pack = _fact_pack_for(result, next(row["market_ticker"] for row in result.edges if row["candidate"]))

    assert pack["calibration_source"] == "predictor"
    assert "calibration_in_bucket" in pack
    assert "predictor_calibration_in_bucket" not in pack


# ── the prompt the reviewer reads that pack with ───────────────────────────────────────────
#
# The fact pack is only half of the attribution. `reviewer.SYSTEM_PROMPT` is the other half, and it
# is the half the reviewer REASONS OVER: it is the instruction, and the pack is the evidence. A pack
# that says `calibration_source: hub_ledger` under a prompt that calls the record the predictor's is
# a reviewer judging a record it has been told is the wrong one.
#
# These three pin the property rather than the wording, because the wording is a product decision
# that will be rewritten again and the misattribution is not. Each test locates the clause it cares
# about by what it talks ABOUT (calibration, point distribution) and then constrains only the
# attribution, so the prose can be reworded freely. An exact-string assertion would be satisfied by
# one rewrite and broken by the next, which is the opposite of what a guard is for.


def _clauses(prompt):
    """The prompt split into clauses -- a sentence end, or a top-level comma -- lowercased.

    A clause is the unit of attribution: every claim the prompt makes about WHOSE something is lives
    inside exactly one of these, and none of them span a boundary. Splitting on punctuation rather
    than on phrases is what makes the tests below robust -- a rewrite of any clause's words leaves the
    clause boundaries alone, so a rewording is free and a re-attribution is not.

    Two details the prompt's own shape forces. Commas inside brackets do not split, or the red-flag
    list runs a clause through the middle of itself and swallows the rest of the prompt with it. And a
    period only ends a clause when whitespace follows it, so a decimal inside a number does not
    become a boundary.
    """
    parts, current, depth = [], [], 0
    for index, char in enumerate(prompt):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        boundary = depth == 0 and (char == "," or (char == "." and prompt[index + 1:index + 2] in ("", " ")))
        if boundary:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip().lower() for part in parts if part.strip()]


def _calibration_clauses(prompt):
    """Only the clauses that talk about calibration."""
    return [clause for clause in _clauses(prompt) if "calibrat" in clause]


def test_the_system_prompt_never_says_the_calibration_is_the_predictors():
    """The ruling, as a property: no clause that talks about calibration may name the predictor.

    Checked per clause rather than as "the string 'calibrated the predictor' is absent", because the
    failure is an ATTRIBUTION and attributions move around inside sentences. A future rewrite that
    said "how well calibrated the model has been" or "the calibration of this band" passes; a rewrite
    that reintroduces the predictor -- in any phrasing -- does not.
    """
    calibration_clauses = _calibration_clauses(SYSTEM_PROMPT)

    assert calibration_clauses, (
        "the prompt has to say something about calibration: the fact pack publishes a band and a "
        "source, and a prompt that never mentions them is not a neutral prompt, it is a blind one"
    )
    for clause in calibration_clauses:
        assert "predictor" not in clause, (
            f"the prompt attributes the calibration to the predictor: {clause!r}. Under the "
            f"inversion that record is the hub's own settled ledger whenever "
            f"`calibration_source` says `hub_ledger`, so the reviewer would be judging a record it "
            f"has been told is the wrong one."
        )


def test_the_system_prompt_names_the_field_that_says_which_record_it_is():
    """Source-neutral is not the same as source-oblivious. A prompt that dropped the subject without
    naming the replacement would tell the reviewer to judge a band and not tell it whose it is."""
    calibration_clauses = _calibration_clauses(SYSTEM_PROMPT)

    assert any("calibration_source" in clause for clause in calibration_clauses), (
        f"the prompt must point the reviewer at the field that names the record: {calibration_clauses}"
    )


def test_the_system_prompt_still_calls_the_probability_and_distribution_the_predictors():
    """The half that must NOT move, pinned so the fix cannot be over-applied.

    The pre-game probability and the point distribution genuinely are the predictor's whichever
    record the calibration came from -- that is a fact about the pack, not an attribution, and it was
    never wrong. A test that only asserted the negative above would pass just as happily if someone
    had deleted every mention of the predictor from the whole prompt, which would be a second,
    different bug: the reviewer told to judge a gap it has not been told who computed.
    """
    distribution_clauses = [c for c in _clauses(SYSTEM_PROMPT) if "distribution" in c]

    assert distribution_clauses, "the prompt has to tell the reviewer what the point distribution is"
    for clause in distribution_clauses:
        assert "predictor" in clause, (
            f"the point distribution is the predictor's whichever calibration source is in force, so "
            f"the prompt should still say so: {clause!r}"
        )


def test_every_field_the_prompt_points_the_reviewer_at_is_in_the_fact_pack():
    """The prompt and the pack are written in different modules and are read in different messages,
    so they can drift apart silently -- and a prompt naming a field the pack does not carry is the
    same class of failure as the one this round fixed: the reviewer is told to read something and
    either finds the wrong thing or finds nothing.

    Rather than assert the prompt contains one hardcoded field name, this reads the calibration clause
    and checks every snake_case token in it against the pack the scan actually sends, so naming
    `calibration_source` is a fact about the data and not a fact about the prose. Checked for the
    HUB-sourced pack, because that is the case where the attribution is live and the one the
    predictor-sourced case gets right for free.
    """
    result = _scan(_recorded_feed(), hub_pairs=HUB_LEDGER)
    pack = _fact_pack_for(result, _graded_winner_rows(result)[0]["market_ticker"])
    pointed_at = {
        token for clause in _calibration_clauses(SYSTEM_PROMPT) for token in re.findall(r"[a-z_]+", clause)
        if "_" in token
    }

    assert pointed_at, "the calibration clause names no field, so there is nothing to check"
    assert pointed_at <= set(pack), (
        f"the prompt points at {sorted(pointed_at - set(pack))}, which the fact pack does not "
        f"publish. It publishes {sorted(pack)}."
    )


# ── the review cache: a verdict is only reusable for the record it was reasoned over ───────────
#
# The reviewer is the one component the whole design defers the calibration judgement to, and
# `SupabaseReviewStore` serves it the last `status='ok'` verdict filed under a key. So the key has
# to name every input the reasoning depended on. It named five: sport, game, market, side, price
# bucket -- which was complete while the predictor's published calibration was the only record there
# was. The inversion makes the source flip from `predictor` to `hub_ledger` the day the hub has
# `HUB_LEDGER_MIN_SETTLED` rows of that kind, so one key can now mean two different records and the
# store will hand back a verdict reasoned over the other band, at the other hit rate, and the edge
# will be tiered on a record nobody reviewed it against.


def _requests_by_ticker(result):
    return {req.market_ticker: req for req in result.review_requests}


def test_the_review_cache_key_changes_when_the_calibration_source_does():
    """The same market, the same side, the same price bucket, judged on a different record. Both
    halves matter: the keys must differ, and they must differ ONLY in the source -- otherwise a key
    that varied incidentally while still colliding on the real difference would satisfy the first
    half while the collision stood."""
    before = _requests_by_ticker(_scan(_recorded_feed()))
    after = _requests_by_ticker(_scan(_recorded_feed(), hub_pairs=HUB_LEDGER))

    shared = sorted(set(before) & set(after))
    assert shared, (
        "a market has to be a candidate under both records for this to mean anything; the recorded "
        "feed's HOU@IND winner markets are, one on the published bands and one on the hub's"
    )
    for ticker in shared:
        predictor, hub = before[ticker], after[ticker]
        assert predictor.fact_pack["calibration_source"] == "predictor", ticker
        assert hub.fact_pack["calibration_source"] == "hub_ledger", ticker
        assert predictor.key != hub.key, (
            f"{ticker} is filed under one cache key for two different calibration records: "
            f"{predictor.key!r} vs {hub.key!r}"
        )
        assert predictor.key.rsplit(":", 1)[0] == hub.key.rsplit(":", 1)[0], (
            f"{ticker}: the only difference may be the source, but {predictor.key!r} and "
            f"{hub.key!r} differ in more than that"
        )
        assert hub.key.endswith(":hub_ledger"), hub.key


def test_two_markets_differing_only_in_calibration_source_do_not_share_a_cache_key():
    """The unit, and the reason the parameter is required rather than defaulted: a default of
    `"predictor"` is a call site that quietly rebuilds the colliding key, which is the defect."""
    predictor = cache_key("nfl", "2026_03_HOU_IND", "KXNFLGAME-26SEP27HOUIND-IND", "yes", 5, "predictor")
    hub = cache_key("nfl", "2026_03_HOU_IND", "KXNFLGAME-26SEP27HOUIND-IND", "yes", 5, "hub_ledger")

    assert predictor != hub
    assert predictor.startswith("nfl:2026_03_HOU_IND:KXNFLGAME-26SEP27HOUIND-IND:yes:5:")
    assert predictor.endswith(":predictor") and hub.endswith(":hub_ledger")
    # Every other field is unchanged in both, so the source is demonstrably the only difference.
    assert predictor.rsplit(":", 1)[0] == hub.rsplit(":", 1)[0]
    # And the third source, the one `choose_calibration` returns when there is no record at all, is
    # a different key too -- otherwise "no record" would read as "the predictor's record".
    assert len({predictor, hub, cache_key("nfl", "2026_03_HOU_IND", "KXNFLGAME-26SEP27HOUIND-IND",
                                          "yes", 5, "none")}) == 3


def test_a_verdict_reasoned_over_the_predictor_is_not_served_for_the_hubs_record():
    """The consequence, through the store that serves it, rather than the string alone. A market
    reviewed on the published calibration and then re-scanned with the hub in charge asks the
    reviewer the same question about a different band; handing back the old verdict would tier the
    edge on a record the reviewer never saw, and the edge row's own `calibration_source` would
    disagree with the band behind the tier."""
    before = _requests_by_ticker(_scan(_recorded_feed()))
    after = _requests_by_ticker(_scan(_recorded_feed(), hub_pairs=HUB_LEDGER))
    ticker = sorted(set(before) & set(after))[0]
    cached, current = before[ticker], after[ticker]
    store = MemoryReviewStore()
    store.save(cached, Review(status="ok", explainable=True, drivers=("margin",), red_flags=(),
                              model="m"))

    assert store.cached(cached.key) is not None, "the verdict is still reusable for its own record"
    assert store.cached(current.key) is None, (
        f"the store served a verdict reasoned over {cached.fact_pack['calibration_source']}'s band "
        f"for an edge judged on {current.fact_pack['calibration_source']}'s"
    )


# ── the ledger the scan is handed ──────────────────────────────────────────────────────────────
#
# The `predictions`-table reader is gone; `journal_ledger.journal_settled_ledger` is the live one and
# `tests/test_sports_journal_ledger.py` proves it. What stays here is what is true of the ledger the
# scan is HANDED: a read that failed leaves the predictor's calibration in charge, and the two
# diagnostics in the run summary say "not measured" rather than the reassuring empty answer.


def _hub(pairs_by_engine, unrecognised_by_engine=None):
    """A `HubLedger` for the tests that hand one to `run_sports_scan` rather than reading one."""
    return scan_mod.HubLedger(pairs_by_engine, unrecognised_by_engine or {})


def test_a_ledger_read_that_fails_leaves_the_predictors_calibration_in_charge():
    """The ledger read is a failure mode on the sports path, and it must not be able to cost the
    scan: the pre-change behaviour is a working scan on the published calibration.

    Driven at `journal_ledger.journal_settled_ledger`, the reader the cron path uses. It used to be
    driven at the deleted `predictions` reader; the property is the scan's, not that reader's."""
    class Broken:
        def table(self, _name):
            raise RuntimeError("postgrest 500")

    ledger = journal_settled_ledger(Broken())

    # An empty ledger, not a `{}`-shaped one that happens to compare equal: the tally is empty too,
    # because a count taken from a read that failed is not a count. What it is NOT allowed to be is
    # indistinguishable from a healthy read that found nothing, so the expected value carries
    # `read_failed=True` and a bare `HubLedger()` -- the positive answer, "the read completed and
    # there is nothing" -- would fail this line.
    assert ledger == scan_mod.HubLedger(read_failed=True), ledger
    assert ledger != scan_mod.HubLedger(), (
        "a failed read must not be the same value as a completed one"
    )


# ── one list of kinds, and what happens to a kind that is not on it ────────────────────────────
#
# The triple was written down twice -- `hub_calibration.KINDS` and an inlined copy inside
# `parse_feed` -- and nothing tied the two together. It was not two views of one list, though. It was
# a list and a FILTER: a settled-ledger reader keeps only the kinds on it, so the inlined copy
# decided which settled evidence the hub was allowed to have. Add a fourth kind to the predictors
# and every settled row of that kind would have been deleted with nothing logged, while the feed's
# own band list for the same kind was read and judged -- the record on one side, the evidence on the
# other, and no word about the gap.
#
# So the list now lives in `tradehub/sports/kinds.py` and is imported by every site that has to
# agree with it, and a kind outside it is reported rather than dropped. Both reports reach a
# human as a `per_sport` key in the run summary, and NEITHER is a log line alone:
#
#   - `parse_feed` records the payload's unread names on `Feed.unrecognised_kinds`, and
#     `run_sports_scan` publishes them as `per_sport[sport]["feed_unrecognised_kinds"]`. A payload's
#     calibration keys are all in hand at once, so the answer is complete before the function
#     returns -- which used to be the argument for the log being the only place it could go. It is
#     not: the caller is handed the whole `Feed`, so the list rides along exactly as
#     `Feed.n_buckets` already did.
#   - a reader tallies what it could not file onto `HubLedger.unrecognised_by_engine`, and
#     `run_sports_scan` publishes it as `per_sport[sport]["unrecognised_kinds"]`. Its rows arrive one
#     at a time and it runs once in the cron entry point, so the report it has to reach is the one
#     the caller builds. A log line here would be evidence nobody reads -- this codebase upserts to
#     four tables that never existed, with bare `print()`s, for its whole life without anyone
#     noticing (the migration guard in PR #20). The live reader asks only for forecaster names it
#     composes itself, so in practice it tallies `{}`; the channel stays because `_unrecognised_for`
#     publishes whatever it is handed, and the tests below hand it a tally.
#
# The two are SEPARATE keys rather than one merged tally, because the consequences differ and a
# single number could not say which was which: a settled row this build cannot file is evidence
# lost, while a band list this build cannot read means the affected kinds are judged on NO band at
# all. Both are build gaps, both were silent, and a reader who saw one number could not tell which
# kind of gap they were looking at.
#
# What the reports have to do is name the kind, and where there is a count, the count, so that "this
# build cannot read that kind" is distinguishable from "nothing of that kind has settled": two facts
# every number downstream looks identical under, because both read as a band with `n: 0`.


def test_the_feed_client_the_publisher_and_the_ledger_filter_share_one_list():
    """`is`, not `==`. A fourth kind added to one of the two lists and not the other is exactly the
    bug, and two tuples that happen to compare equal are two tuples that can be edited apart."""
    assert kinds_mod.KINDS is feed_mod.KINDS is hub_calibration_mod.KINDS is scan_mod.KINDS


def test_the_list_is_the_three_kinds_the_predictors_publish():
    """The membership is the product's, so it is written out rather than read back: dropping a kind
    or renaming one changes what the hub can calibrate and is not a refactor."""
    assert KINDS == ("winner", "spread", "total")


def test_parse_feed_reads_exactly_the_kinds_this_build_declares():
    """`Feed.calibration`'s keys ARE the kinds `parse_feed` read, so the set it publishes is the
    observable for a second copy of the list being inlined back into the function -- where an
    identity check on the module attribute would go on passing while the payload and the code
    disagreed. It is compared against the declared list, not against a literal written here, because
    the claim is that the two are the same thing rather than that they are both three."""
    raw = json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())

    parsed = parse_feed(raw)

    assert set(parsed.calibration) == set(kinds_mod.KINDS)
    for kind in kinds_mod.KINDS:
        assert parsed.calibration[kind] == raw["calibration"][kind], (
            f"the payload's own {kind} bands are what the feed has to carry, not a default"
        )


def test_the_hub_publishes_a_band_set_for_every_declared_kind():
    """The other end of the same tie. `_hub_calibration` is the one place that decides which kinds
    the hub has a record for, so a copy of the list inlined into its comprehension shows up here as a
    published key that is not, or is not, a declared kind."""
    published = scan_mod._hub_calibration(_recorded_feed(), {"winner": [(0.5, True)]})

    assert published is not None
    assert set(published) == set(kinds_mod.KINDS)


def test_a_feed_that_publishes_a_kind_this_build_cannot_read_says_so(caplog):
    """The feed half of the report. A kind the payload published that this build does not know is
    not read, and the cost of not reading it is that its edges are judged on no band at all -- which
    reads downstream exactly like a predictor that published no history for them. The name has to
    reach the log or nobody can tell the two apart."""
    raw = json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())
    raw["calibration"]["prop"] = [{"lo": 0.0, "hi": 1.0, "n": 40, "mean_prob": 0.5, "hit_rate": 0.5}]

    with caplog.at_level(logging.WARNING, logger="tradehub.sports.feed"):
        parsed = parse_feed(raw)

    assert "prop" not in parsed.calibration, "an unread kind is not invented into the feed"
    assert "does not recognise" in caplog.text
    assert "prop" in caplog.text, caplog.text


def test_a_feed_that_publishes_no_unknown_kind_says_nothing(caplog):
    """The other half, and the reason the warning can be trusted. `n_buckets` is a scalar the
    payload publishes next to the band lists and is not a kind, so a check that treated it as one
    would warn on every single scan -- and a line that always fires is a line nobody reads."""
    with caplog.at_level(logging.WARNING, logger="tradehub.sports.feed"):
        parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))

    assert "recognise" not in caplog.text, caplog.text


# ── one ledger per sport, all the way through `run_sports_scan` ───────────────────────────────


class _Kalshi:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return self.markets.get(series, [])


# The CFB fixture's games are only in the 1-72h window at this time: its first game kicked off on
# 2026-09-25T20:00, and at NOW it is 32h past. The two-sport tests need CFB to produce edges at all,
# so they use their own clock rather than the NFL one.
BOTH_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _both_sports(ledger):
    """Run both sports' recorded feeds and markets through the orchestrator with one shared ledger."""
    return scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}),
        fetch=lambda url, **_kw: _recorded_feed("cfb" if url.startswith("https://cfb-") else "nfl"),
        hub_ledger=ledger, sports=("nfl", "cfb"),
    )


def _band_counts(run, sport):
    return {row["calibration_bucket"]["n"] for row in run.per_sport[sport]["edges"]
            if row["calibration_bucket"] is not None}


def test_each_scan_is_handed_only_its_own_sports_pairs(monkeypatch):
    """The plumbing, stated directly. Two sports, two ledgers, and each `scan_sport` must get its own --
    the same numbers in a shared ledger would be right while the attribution is wrong, and the numbers
    only disagree because the two recorded feeds happen to have different probabilities."""
    seen: dict = {}
    real = scan_mod.scan_sport

    def spy(cfg, markets, feed, now, **kwargs):
        seen[cfg.sport] = kwargs.get("hub_pairs")
        return real(cfg, markets, feed, now, **kwargs)

    monkeypatch.setattr(scan_mod, "scan_sport", spy)
    ledger = _hub({"sports_nfl": {"winner": [(0.29, True)] * 3},
                   "sports_cfb": {"winner": [(0.74, True)] * 4, "spread": [(0.5, True)] * 5}})
    _both_sports(ledger)

    assert seen["nfl"] == {"winner": [(0.29, True)] * 3}
    assert seen["cfb"] == {"winner": [(0.74, True)] * 4, "spread": [(0.5, True)] * 5}
    assert seen["nfl"] is not seen["cfb"]


def test_a_sports_ledger_never_reaches_the_other_sports_scan():
    """NFL and CFB are different models with different records, so one shared ledger would put NFL's
    rows into CFB's bands and the reverse. The two ledgers are sized differently on purpose (300 and
    700) and filed at the same probability, because the recorded feeds' probabilities are disjoint --
    without a deliberate collision a contaminated band is invisible.

    Correct: NFL's winner band holds 300 and CFB's holds 700. Shared: both hold 1000."""
    ledger = _hub({"sports_nfl": {"winner": [(0.2954, True)] * 150 + [(0.2954, False)] * 150},
                   "sports_cfb": {"winner": [(0.2954, True)] * 350 + [(0.2954, False)] * 350}})
    run = _both_sports(ledger)
    nfl, cfb = _band_counts(run, "nfl"), _band_counts(run, "cfb")

    # 0.2954 is inside NFL's HOU@IND winner band and inside CFB's Temple winner band, so each sport
    # reads a band the other sport's rows would also have landed in.
    assert 300 in nfl and 700 in cfb, f"each sport must read its own count: nfl={nfl} cfb={cfb}"
    assert 700 not in nfl, "NFL's bands hold CFB rows"
    assert 300 not in cfb, "CFB's bands hold NFL rows"
    assert 1000 not in nfl | cfb, "one shared ledger: both bands hold both sports' rows"


def test_a_sport_with_no_settled_rows_of_its_own_keeps_the_predictor_in_charge():
    """The other half, and the one a shared ledger would have got wrong in the dangerous direction:
    CFB has 300 settled winner rows and NFL has none, so a shared ledger would put the hub in charge
    of NFL's winner edges on CFB's history alone. 0.2633 is the home-oriented probability of the
    recorded CFB winner markets (`home_oriented` flips the away-team market, so both sides of the
    Temple/Army game read 0.2633), so CFB really is switched over rather than merely labelled."""
    ledger = _hub({"sports_cfb": {"winner": [(0.2633, True)] * 150 + [(0.2633, False)] * 150}})
    run = _both_sports(ledger)

    assert {row["calibration_source"] for row in run.per_sport["nfl"]["edges"]} == {"predictor"}
    assert {row["calibration_source"] for row in run.per_sport["cfb"]["edges"]} == {"hub_ledger"}
    assert 300 in _band_counts(run, "cfb")


def test_the_run_report_carries_a_settled_kind_this_build_cannot_read():
    """The property, end to end, and the one the finding is actually about.

    A settled row of a kind this build does not know is kept out of the record -- correctly, since
    filing it would be a wrong attribution -- and the cost of that is that the kind then has no band
    anywhere. Every number downstream reads "no record" and cannot say whether nothing of that kind
    has settled or this deployment cannot read it. So the run report has to say which of the two it
    is, in the data:

    - NFL has two settled `moneyline` rows it cannot place  -> the tally names them.
    - CFB has none                                         -> the key is present and empty.

    CFB is the control, and without it the first assertion would be satisfied by a key that is
    simply never empty. Both facts have to be readable, and neither is inferable from the other.

    Hand-built ledger rather than a read: the live reader (`journal_ledger`) asks only for forecaster
    names it composes itself, so it can never hand back a tally, and this is about what `run_sports_scan`
    does with one it is given.
    """
    ledger = _hub({"sports_nfl": {"winner": [(0.65, True)]},
                   "sports_cfb": {"total": [(0.72, True)]}},
                  {"sports_nfl": {"moneyline": 2}})
    run = _both_sports(ledger)

    # The gap, per sport, in the run summary beside the rest of the run's state.
    assert run.per_sport["nfl"]["unrecognised_kinds"] == {"moneyline": 2}, run.per_sport["nfl"]
    assert run.per_sport["cfb"]["unrecognised_kinds"] == {}, run.per_sport["cfb"]
    # Separate objects, so a consumer that edits one sport's report cannot reach the other's or the
    # measurement's -- the same reason the two scans are handed separate sub-ledgers.
    assert (run.per_sport["nfl"]["unrecognised_kinds"]
            is not run.per_sport["cfb"]["unrecognised_kinds"])
    assert (run.per_sport["nfl"]["unrecognised_kinds"]
            is not ledger.unrecognised_by_engine["sports_nfl"])

    # The rows are still not in the record, and the kind still has no band anywhere: that is the
    # whole reason the report carries the tally, because the numbers cannot.
    assert ledger.pairs_by_engine == {"sports_nfl": {"winner": [(0.65, True)]},
                                      "sports_cfb": {"total": [(0.72, True)]}}
    published = scan_mod._hub_calibration(_recorded_feed(), ledger.pairs_by_engine["sports_nfl"])
    assert published is not None and "moneyline" not in published, sorted(published)
    # And no scan invents one: three kinds in, three kinds out.
    for sport in ("nfl", "cfb"):
        assert {row["kind"] for row in run.per_sport[sport]["edges"]} <= set(KINDS), sport


def test_the_unrecognised_kinds_key_is_there_even_when_the_sport_never_scanned():
    """Why the key is on all four paths and not only the one that scanned. The tally is learned when
    the ledger is read, which happens before any of the exits in `run_sports_scan`, so it is a fact
    about the run rather than a fact about a scan. A key that only appears when a sport scanned is a
    key the reader has to wonder about on the runs where it is missing -- and the runs where a sport
    does not scan are exactly the runs somebody reads the report to find out why."""
    def no_feed(_url, **_kw):
        raise feed_mod.FeedUnavailable("404")

    run = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}), fetch=no_feed,
        hub_ledger=_hub({"sports_nfl": {"winner": []}}, {"sports_nfl": {"moneyline": 2}}),
        sports=("nfl", "cfb"),
    )

    assert run.per_sport["nfl"]["feed_ok"] is False, "the sport really did not scan"
    assert run.per_sport["nfl"]["unrecognised_kinds"] == {"moneyline": 2}, run.per_sport["nfl"]
    assert run.per_sport["cfb"]["unrecognised_kinds"] == {}, run.per_sport["cfb"]
    # And the feed's own key is `None` on this path rather than `[]`: the fetch raised, so no
    # payload was ever parsed. An empty list here would be the reassuring answer to a question this
    # run never asked -- the same collision `unrecognised_kinds` avoids by being `None` on a failed
    # ledger read.
    assert run.per_sport["nfl"]["feed_unrecognised_kinds"] is None, run.per_sport["nfl"]
    assert run.per_sport["cfb"]["feed_unrecognised_kinds"] is None, run.per_sport["cfb"]


# ── the FEED's unread names, which used to be a log line and nothing else ───────
#
# The ledger's side of this problem got a `per_sport` key because a log line in this codebase is
# demonstrably not an observed channel (see the block comment above). The feed's side did not, and it
# is the worse of the two: a payload publishing a name this build cannot read means every edge of
# that kind is judged on NO band at all, so the gap is not a missing statistic, it is a gate running
# without the input it exists to check. The only evidence was one `log.warning` per fetch.


def _feed_with_extra_calibration_key(sport, key):
    """The recorded feed with one extra key in `calibration`, parsed for real.

    Parsed through `parse_feed` rather than assembled as a `Feed`, because the whole point is that
    the parse is what records the name -- a hand-built `Feed` would satisfy this by construction,
    which is the defect the producer test in `test_sports_sigma_rank.py` was written against.
    """
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    raw["calibration"][key] = [{"lo": 0.0, "hi": 1.0, "n": 1, "mean_prob": 0.5, "hit_rate": 0.5}]
    return parse_feed(raw)


def test_a_payload_name_this_build_cannot_read_is_carried_as_data_not_only_logged(caplog):
    """The end of the feed-side chain: the name survives `parse_feed` on the object it returns.

    Before this, `extra` existed only as a `log.warning` argument, so the whole finding evaporated
    when the function returned. A `caplog` assertion alone would have passed on the version that had
    no data channel at all, which is why the assertion is on the RETURN VALUE.
    """
    feed = _feed_with_extra_calibration_key("cfb", "moneyline")

    assert feed.unrecognised_kinds == ["moneyline"], (
        "the payload published a band list this build cannot read and the Feed does not say so; "
        f"unrecognised_kinds={feed.unrecognised_kinds}"
    )
    # The gap is real: the band list is not read, so the kind has no bands anywhere. That is why the
    # name has to travel -- every number downstream reads `n: 0` and cannot tell this from a kind
    # with nothing settled.
    assert "moneyline" not in feed.calibration, sorted(feed.calibration)
    # And the log line is still there, as the immediate half of the same report.
    assert any("moneyline" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]


def test_a_feed_that_publishes_only_known_names_reports_an_empty_list_not_a_missing_key():
    """`[]` is the positive answer, and it has to be distinguishable from an absent key: absent reads
    as "not measured", and this WAS measured. Recorded payloads carry exactly
    `n_buckets, spread, total, winner`, so this is the state every real run is in today.
    """
    assert _recorded_feed("cfb").unrecognised_kinds == []
    # `n_buckets` is a published scalar, not a kind, and is not tallied as an unread name. Recorded
    # explicitly because the payload carrying it is the normal case and a regression here would make
    # every run report a build gap that does not exist.
    assert "n_buckets" in json.loads((FIXTURES / "cfb_kalshi_feed.json").read_text())["calibration"]


def test_a_new_published_scalar_is_reported_as_an_unread_name_not_silently_ignored():
    """Future-facing, and the reason the message wording matters.

    `_PUBLISHED_SCALARS` is exactly `{"n_buckets"}`, so the day the payload starts publishing a
    second scalar this build has not been taught to read, that scalar is reported as a name it
    cannot place. That is the honest report -- this build genuinely has not been told about it --
    and it arrives in the run summary rather than in a log, so the drift is visible without reading
    anything. The test asserts the behaviour rather than a future payload's contents.
    """
    assert feed_mod._PUBLISHED_SCALARS == frozenset({"n_buckets"}), (
        "the set of published scalars changed; if that is deliberate, the warning text and this "
        "test both need to say what is now known to be a scalar rather than a kind"
    )
    feed = _feed_with_extra_calibration_key("cfb", "n_buckets_v2")
    assert feed.unrecognised_kinds == ["n_buckets_v2"]


def test_the_run_summary_carries_the_feeds_unread_names_per_sport():
    """The property the whole block is for, end to end and in the summary a human reads.

    NFL's payload publishes a band list this build cannot read; CFB's does not. So the run summary
    names NFL's gap and reports CFB's as an empty list -- and both are separate values, so a reader
    can tell which sport has a build gap rather than that one of them does.
    """
    parsed: list = []

    def fetch(url, **_kw):
        sport = "cfb" if url.startswith("https://cfb-") else "nfl"
        if sport == "cfb":
            return _recorded_feed(sport)
        parsed.append(_feed_with_extra_calibration_key(sport, "moneyline"))
        return parsed[-1]

    run = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}), fetch=fetch,
        hub_ledger=_hub({}), sports=("nfl", "cfb"),
    )

    assert run.per_sport["nfl"]["feed_unrecognised_kinds"] == ["moneyline"], run.per_sport["nfl"]
    assert run.per_sport["cfb"]["feed_unrecognised_kinds"] == [], run.per_sport["cfb"]
    # Separate objects, so a consumer that edits one sport's report cannot reach the other's or the
    # measurement's -- the same reason `_unrecognised_for` copies.
    assert (run.per_sport["nfl"]["feed_unrecognised_kinds"]
            is not run.per_sport["cfb"]["feed_unrecognised_kinds"])
    # And a COPY, not the `Feed`'s own list: editing the report must not edit the measurement.
    assert run.per_sport["nfl"]["feed_unrecognised_kinds"] is not parsed[0].unrecognised_kinds

    published = scan_mod.sports_run_summary(run)
    assert published["nfl"]["feed_unrecognised_kinds"] == ["moneyline"], published["nfl"]
    assert published["cfb"]["feed_unrecognised_kinds"] == [], published["cfb"]
    # The two gaps are not one number. A settled row this build cannot file is evidence lost; a band
    # list it cannot read means those kinds are judged on no band at all. Merged, the reader could
    # not tell which kind of gap they were reading.
    assert published["nfl"]["unrecognised_kinds"] == {}, published["nfl"]


def test_the_feeds_gap_survives_a_run_where_the_ledger_read_failed():
    """The two diagnostics are INDEPENDENT measurements, and this is the run that proves it.

    A failed ledger read makes the ledger's two keys `None` -- "not measured" -- while the feed's
    key is still a real list from a payload that WAS parsed. Collapsing them into one shared
    measurement would have to choose, and either choice is a lie: reporting the feed's names as
    `None` loses a gap that was measured, and reporting the ledger's as a real value publishes a
    count nobody took.
    """
    run = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}),
        fetch=lambda url, **_kw: _feed_with_extra_calibration_key(
            "cfb" if url.startswith("https://cfb-") else "nfl", "moneyline"),
        hub_ledger=scan_mod.HubLedger(read_failed=True), sports=("nfl", "cfb"),
    )

    published = scan_mod.sports_run_summary(run)
    for sport in ("nfl", "cfb"):
        assert published[sport]["unrecognised_kinds"] is None, published[sport]
        assert published[sport]["settled_by_kind"] is None, published[sport]
        assert published[sport]["feed_unrecognised_kinds"] == ["moneyline"], published[sport]


def test_the_cron_path_actually_hands_the_ledger_to_the_scan(monkeypatch):
    """The last link in the chain, and the one most easily left disconnected: the read above proves
    the query, but nothing else would notice if the cron path stopped passing the result on, and the
    feature would simply never switch over with every test still green.

    Plan 12 moved the cron to `journal_ledger.journal_settled_ledger` (one frozen, Kalshi-settled
    forecast per game and kind). `tests/test_sports_journal_ledger.py` proves that reader; this test
    still owns the wiring, so it watches the journal reader be called with the cron entry point's own
    client and its exact result be passed through to the scan."""
    import tradehub.sports.journal_ledger as jl

    monkeypatch.setattr(scan_mod, "SportsKalshi", lambda **_kw: "kalshi")
    monkeypatch.setattr(scan_mod, "SupabaseReviewStore", lambda _supa: "store")
    monkeypatch.setattr(scan_mod, "OpenRouterReviewer", lambda *_a, **_kw: None)
    monkeypatch.setattr(scan_mod, "unrecorded", lambda _supa, rows: rows)
    seen: dict = {}
    journal = _hub({"sports_nfl": {"winner": [(0.28, True), (0.28, False)]}})
    called: list = []

    def fake_journal_ledger(supa):
        called.append(supa)
        return journal

    monkeypatch.setattr(jl, "journal_settled_ledger", fake_journal_ledger)

    def fake_scan(_now, _kalshi, **kwargs):
        seen.update(kwargs)
        return scan_mod.SportsRun([], [], {}, {})

    monkeypatch.setattr(scan_mod, "run_sports_scan", fake_scan)
    supa = object()
    scan_mod.run_sports_for_cron(NOW, supa)

    assert called == [supa] and seen["hub_ledger"] == journal


# ── the diagnostics a reader actually receives ────────────────────────────────────────────────
#
# The same gap has now appeared twice in this one place: a key is computed, filed in `per_sport`,
# and never read. `per_sport` is the run's own state; the cron entry point printed `run.reports`
# and kept `per_sport` only to decide pruning. So both of these facts were real, recorded, and
# invisible -- which is the `feed:unknown` shape: 100 live rows carrying a version nobody could see.
#
# The assertion that would have caught it reads the PRINTED summary, not `per_sport` and not even
# `sports_run_summary`. A test on either of those would stay green with the one line in
# `scripts/scan.py` deleted, which is the same gap a third time wearing a different hat.


def _cron_summary_for(monkeypatch, capsys, run):
    """Run `tradehub.scripts.scan.main()` with every engine but sports stubbed to nothing and `run`
    spliced in where `run_sports_for_cron` would have produced it; return the printed sports summary.

    `main()` writes the summary to stdout as JSON, so what comes back is the exact bytes an
    operator's `journalctl` shows, and there is no separate "is the summary wired up" question to
    ask. The stubs are not ceremony: sports is the last step, so stubbing the three other engines
    is what lets the assertion be about the sports summary instead of about weather data sources.

    The two writes are stubbed at their SOURCE modules, not on the scan module, because `main()`
    imports them inside its own body. `record_predictions` is not among `scripts/scan.py`'s
    top-level imports at all, so the `monkeypatch.setattr(scan_mod, "record_predictions", ...,
    raising=False)` that the existing deadline tests use adds a name `main` then rebinds over: the
    real function still runs, and it happens to be harmless there only because every row list in
    those tests is empty and it no-ops on an empty batch. Verified, not assumed.
    """
    from tradehub.core import supabase_client
    from tradehub.scripts import scan as cron
    import tradehub.predictions as predictions_mod

    monkeypatch.setattr(cron, "KalshiLive", lambda *_a, **_k: object())
    monkeypatch.setattr(cron, "scan_weather", lambda *_a, **_k: ([], []))
    monkeypatch.setattr(cron, "scan_gas", lambda *_a, **_k: ([], []))
    monkeypatch.setattr(cron, "cpi_scan_due", lambda _now: False)
    monkeypatch.setattr(cron, "labor_scan_due", lambda _now: False)
    monkeypatch.setattr(cron, "sports_due", lambda _now: True)
    monkeypatch.setattr(cron, "latest_gate_statuses", lambda *_a, **_k: {})
    monkeypatch.setattr(cron, "remove_closed_cpi_edges", lambda *_a, **_k: None)
    monkeypatch.setattr(cron, "remove_closed_labor_edges", lambda *_a, **_k: None)
    monkeypatch.setattr(cron, "remove_started_sports_edges", lambda *_a, **_k: [])
    monkeypatch.setattr(cron, "remove_stale_edges", lambda *_a, **_k: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda _rows: None)
    monkeypatch.setattr(predictions_mod, "record_predictions", lambda *_a, **_k: [])
    monkeypatch.setattr(cron, "run_sports_for_cron", lambda *_a, **_k: run)
    # `client=` is passed, so `get_client` is never reached; no Supabase call below goes anywhere.
    cron.main(now=NOW, live=object(), client=object())
    return json.loads(capsys.readouterr().out)["sports"]


def _cfb_run_three_days_early():
    """A real CFB scan in which both facts are true at once, three days before the recorded games.

    Temple@Army is then 56h out and priced; Stanford@Georgia Tech is 86.5h out, past
    `max_hours_to_start`, so exactly one game is dropped before it is ever priced -- which is what
    `too_far` counts, and what makes this run's short board different from a run that priced
    nothing. The ledger carries a tally naming a kind outside `sports.kinds.KINDS`, so that kind
    has no band anywhere and the run has to say the kind is one this build cannot read rather than
    one with nothing settled. Hand-built, because the live reader cannot produce a tally.
    """
    ledger = _hub({"sports_cfb": {"winner": [(0.72, True)]}}, {"sports_cfb": {"moneyline": 2}})
    return scan_mod.run_sports_scan(
        NOW - timedelta(days=3), _Kalshi(_recorded_markets("cfb")),
        fetch=lambda url, **_kw: _recorded_feed("cfb"), hub_ledger=ledger, sports=("cfb",),
    )


def test_the_summary_a_reader_receives_carries_both_diagnostic_facts(monkeypatch, capsys):
    """The property, end to end, through the surface a human actually reads.

    Both facts are real, not synthesised: the scan genuinely drops one game at the window's far
    bound, and the ledger carries two settled rows of a kind this build cannot file. And both are
    asserted on the cron entry point's printed JSON, because that print is the whole surface.
    """
    run = _cfb_run_three_days_early()
    # The facts exist, and they are the ones claimed: one game past the bound, two unreadable rows.
    # Without these the summary assertions could be satisfied by an empty tally and a zero count.
    assert run.per_sport["cfb"]["too_far"] == 1, run.per_sport["cfb"]
    assert run.per_sport["cfb"]["unrecognised_kinds"] == {"moneyline": 2}, run.per_sport["cfb"]
    assert run.reports["cfb"]["markets_priced"] == 2, "the 56h game must still be priced"

    printed = _cron_summary_for(monkeypatch, capsys, run)

    assert printed["cfb"]["too_far"] == 1, printed["cfb"]
    assert printed["cfb"]["unrecognised_kinds"] == {"moneyline": 2}, printed["cfb"]
    # The scan's own numbers survive: the diagnostics are folded IN, not substituted for the report.
    assert printed["cfb"]["markets_priced"] == 2, printed["cfb"]


def test_the_diagnostics_survive_for_a_sport_that_never_scanned(monkeypatch, capsys):
    """Why the fold is per sport and not a join against the reports that happened to be written.

    `unrecognised_kinds` is learned when the ledger is read, which happens before any of the exits
    in `run_sports_scan`, so a feed that is down still leaves the run with a build gap to report. A
    projection that iterated the reports and looked each sport up would drop exactly that, and the
    run where a sport did not scan is precisely the run somebody opens the summary to find out why.

    The `too_far` on this sport is `None`, not 0: there was no scan to count, and 0 would claim the
    window dropped nothing rather than that nothing was looked at.
    """
    def no_feed(_url, **_kw):
        raise feed_mod.FeedUnavailable("404")

    run = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}), fetch=no_feed,
        hub_ledger=_hub({"sports_cfb": {"winner": []}}, {"sports_cfb": {"moneyline": 3}}),
        sports=("nfl", "cfb"),
    )
    printed = _cron_summary_for(monkeypatch, capsys, run)

    assert printed["cfb"]["unrecognised_kinds"] == {"moneyline": 3}, printed["cfb"]
    assert printed["cfb"]["too_far"] is None, (
        "a sport that never scanned has no count, and 0 would be a claim it did not make"
    )
    # NFL is the control: it shares the run and has no gap, so the key is present and empty rather
    # than absent. Without it the assertion above would be satisfied by a key that is always full.
    assert printed["nfl"]["unrecognised_kinds"] == {}, printed["nfl"]


# `settled_by_kind`: how many settled rows the hub's own record holds, per kind.
#
# The threshold `choose_calibration` applies is PER KIND -- it sums only the kind it is judging, and
# the reason it does is right there in `test_the_hubs_own_settled_rows_do_not_count_towards_another_
# kinds_bands`: CFB's live ledger is 42 / 33 / 32, which sums to 107 and clears 100 while no single
# kind does. So the number that decides whether the hub is in charge of an edge is the largest count
# in this dict, and until this round it was not published anywhere: a reader had to open a band to
# find an `n` and then know how many bands the feed cut to make it comparable to 100. That is the
# diagnostic the four-bucket flip needs on the day it lands, and its absence is why the coherence
# gap in `tests/test_gate_threshold_coherence.py` could sit there unremarked -- both thresholds are
# the same number and only one of them is visible in the run report.


def test_the_run_report_counts_the_settled_rows_the_hub_holds_of_each_kind():
    """The values, from a real read of real rows, and per sport rather than pooled.

    NFL has winner and spread rows, CFB has total only, and one kind nothing in this build writes.
    So all four of the readings a reader needs are here at once, and none of them is inferable from
    another: CFB's one kind is present with its count, NFL's absent kind is absent, the unreadable
    kind is named by the other key, and each sport's numbers are its own.

    The ledger is hand-built: what this owns is what `run_sports_scan` publishes, and the live reader
    cannot hand back a tally."""
    ledger = _hub({"sports_nfl": {"winner": [(0.65, True), (0.64, False)], "spread": [(0.30, True)]},
                   "sports_cfb": {"total": [(0.72, True), (0.73, True)]}},
                  {"sports_nfl": {"moneyline": 1}})
    run = _both_sports(ledger)

    assert run.per_sport["nfl"]["settled_by_kind"] == {"winner": 2, "spread": 1}, run.per_sport["nfl"]
    assert run.per_sport["cfb"]["settled_by_kind"] == {"total": 2}, run.per_sport["cfb"]
    # The two halves of the ledger's story, side by side, which is the pairing that makes either
    # readable: a kind with no rows the hub can use, and a kind whose rows this build cannot place.
    assert run.per_sport["nfl"]["unrecognised_kinds"] == {"moneyline": 1}, run.per_sport["nfl"]
    # A separate object per sport, for the same reason `_unrecognised_for` copies: a consumer that
    # edits one sport's report must not be able to edit another's, or the measurement's.
    assert (run.per_sport["nfl"]["settled_by_kind"]
            is not run.per_sport["cfb"]["settled_by_kind"])
    assert (run.per_sport["nfl"]["settled_by_kind"]
            is not ledger.pairs_by_engine["sports_nfl"])
    # And the count is the ROWS, not the bands and not the total, because 100 is a row count. The
    # `_hub_calibration` cut publishes a band per `n_buckets` for every kind whether or not anything
    # settled, so the band count is a property of the feed and cannot be the measurement.
    published = scan_mod._hub_calibration(_recorded_feed(), ledger.pairs_by_engine["sports_nfl"])
    assert sum(band["n"] for bands in published.values() for band in bands) == 3
    assert run.per_sport["nfl"]["settled_by_kind"] == {"winner": 2, "spread": 1}


def test_a_kind_with_nothing_settled_is_absent_from_the_tally_rather_than_zero():
    """The shape is `unrecognised_kinds`'s, deliberately, so a reader learns one convention: a kind
    that is not in the dict has no hub record, and `{}` is a real measurement of a read that
    completed and found no settled row of any kind. `{"winner": 0}` would be the same information
    with a second thing to learn, and it would also invite summing the values to compare with a
    threshold -- a sum over a dict that omits its zeroes is not the number the threshold is measured
    in.

    The other reason not to enumerate: a `{"winner": .., "spread": .., "total": ..}` shape would be a
    second copy of `sports.kinds.KINDS` in this module, and a second copy of that triple is the exact
    defect `kinds.py` exists to end."""
    ledger = _hub({"sports_nfl": {"winner": [(0.65, True)]}})
    run = _both_sports(ledger)

    assert run.per_sport["nfl"]["settled_by_kind"] == {"winner": 1}, run.per_sport["nfl"]
    assert "spread" not in run.per_sport["nfl"]["settled_by_kind"]
    # A sport with nothing settled at all: the read happened and found nothing, so `{}` and not
    # `None`. Without this the `{}` above would be satisfied by a key that is simply never empty.
    assert run.per_sport["cfb"]["settled_by_kind"] == {}, run.per_sport["cfb"]
    assert run.per_sport["cfb"]["unrecognised_kinds"] == {}, run.per_sport["cfb"]


def test_the_per_kind_tally_shows_the_how_far_short_of_the_threshold_each_kind_is(monkeypatch, capsys):
    """Why this key exists, as a fact about the data rather than a claim in a comment: the number
    that decides whether the hub is in charge is the LARGEST per-kind count, and the aggregate a
    reader could compute from the bands crosses the threshold first. Here the read is EARNED -- the
    rows exist -- and the gap is stated, so the run says out loud what the gate is doing.

    This is the diagnostic the four-bucket flip would have been read through. Admitting an edge
    through the hub needs every bucket to clear `calibration_min_n`, so a wider band makes admission
    STRICTER, not looser, and a run that says "107 settled" while every kind is far short of 100 is
    exactly the run an operator has to be able to see through.

    The ledger is hand-built, and it has to be: `journal_ledger` reads winner rows only (see
    `HUB_LEDGER_KINDS`), so no read of the live reader can produce a three-kind tally like this one.
    What is asserted here is what `run_sports_scan` publishes and what the gate then does with it.
    """
    def settled(count, base):
        return [(base + i / 100, bool(i % 2)) for i in range(count)]

    ledger = _hub({"sports_cfb": {"winner": settled(42, 0.60),
                                  "spread": settled(33, 0.30),
                                  "total": settled(32, 0.50)}})
    run = scan_mod.run_sports_scan(
        NOW - timedelta(days=3), _Kalshi(_recorded_markets("cfb")),
        fetch=lambda url, **_kw: _recorded_feed("cfb"), hub_ledger=ledger, sports=("cfb",),
    )
    counts = run.per_sport["cfb"]["settled_by_kind"]

    # CFB's real numbers, so the test is about the shape that motivated the key.
    assert counts == {"winner": 42, "spread": 33, "total": 32}, counts
    assert sum(counts.values()) >= HUB_LEDGER_MIN_SETTLED, (
        "this test only bites while the aggregate clears the threshold the gate does NOT use"
    )
    assert max(counts.values()) < HUB_LEDGER_MIN_SETTLED, (
        "and while no single kind does, which is why the per-kind count is the one that matters"
    )
    # The consequence, through the gate: the predictor stays in charge, and the run report says why
    # in numbers rather than leaving it to be inferred.
    assert {row["calibration_source"] for row in run.per_sport["cfb"]["edges"]} == {"predictor"}
    printed = _cron_summary_for(monkeypatch, capsys, run)
    assert printed["cfb"]["settled_by_kind"] == {"winner": 42, "spread": 33, "total": 32}, printed["cfb"]


def test_the_per_kind_tally_reaches_a_sport_that_never_scanned():
    """Learned when the ledger is read, which is before any of the four paths in `run_sports_scan`
    -- so it is a fact about the run and not about a scan, and it belongs on the early exits for the
    same reason `unrecognised_kinds` does. A sport whose feed is down is exactly the sport whose
    settled record somebody opens the report to ask about."""
    def no_feed(_url, **_kw):
        raise feed_mod.FeedUnavailable("404")

    run = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}), fetch=no_feed,
        hub_ledger=_hub({"sports_cfb": {"winner": [(0.7, True)] * 2}}), sports=("nfl", "cfb"),
    )

    assert run.per_sport["cfb"]["feed_ok"] is False, "the sport really did not scan"
    assert run.per_sport["cfb"]["settled_by_kind"] == {"winner": 2}, run.per_sport["cfb"]
    assert run.per_sport["nfl"]["settled_by_kind"] == {}, run.per_sport["nfl"]


def test_a_sport_the_reports_never_mentioned_still_gets_its_facts():
    """The projection walks `per_sport`, not `reports`, and this is the case that says why.

    Every path in `run_sports_scan` today writes both, so the two dicts are in step and a projection
    could iterate either one and pass every test above -- including the two that read the printed
    summary. That is exactly why this is pinned separately rather than left as a comment: a join
    written the obvious way would drop a sport's diagnostics the first time a path forgot to write a
    report for it, and a dropped diagnostic is invisible in the one surface that exists.

    Two halves, and they fail for different reasons, which is why the hand-built one comes first and
    is parameterised off the list rather than repeating it:

    - the projection: a sport with state and no report gets exactly the diagnostics, with the values
      it was handed. Hand-built, so the shape really is that rather than whatever the orchestrator
      happens to produce today. Its keys come off the list, with the values set afterwards, so this
      half cannot go stale when a key is added -- and so a name in the list that nothing writes is
      reported by the contract half below, as the defect it is, rather than as a KeyError here.
      An assertion that has to be edited by hand is an assertion that will be edited wrongly or not
      at all, and this file is about hand-maintained invariants.
    - the CONTRACT: every key the list names is a key some path actually writes. See below.

    Ordering matters for the failure report. If a name in the list is written nowhere, the
    hand-built half fails first with a diff that reads like a fixture problem, and the actual defect
    -- a diagnostic that will be published as `None` forever -- is in the noise.
    """
    state = {"feed_ok": False, "edges": [], **{key: None for key in scan_mod.DIAGNOSTIC_KEYS}}
    state.update(unrecognised_kinds={"moneyline": 2}, settled_by_kind={"winner": 3})
    summary = scan_mod.sports_run_summary(scan_mod.SportsRun([], [], {}, {"cfb": state}))

    assert summary == {"cfb": {key: state[key] for key in scan_mod.DIAGNOSTIC_KEYS}}, summary
    # The keys it DID hand in and the keys the summary carries are the same set, so the projection
    # is reading the list rather than a second list of its own -- which is the drift this file keeps
    # finding, one level down.
    assert set(summary["cfb"]) == set(state) - {"feed_ok", "edges"}, summary["cfb"]

    # The contract half, and the half that was missing. `DIAGNOSTIC_KEYS` answers "how does a key
    # added to `per_sport` reach a reader", and it says nothing about the reverse: that the key it
    # names is a key `per_sport` actually writes. Its own docstring calls itself the answer to "the
    # next diagnostic key will not be carried either", and adding a third diagnostic to `per_sport`
    # without touching the list passed every test in the suite -- which is the same gap this list was
    # built to close, reintroduced in the list itself. A name carried that nothing writes publishes
    # `None` forever, and `None` is this summary's word for "not measured", so the reader is told a
    # measurement was not taken on a run that took it.
    #
    # REAL runs, not the hand-built entry above: a hand-built dict only proves the test author
    # updated their own fixture. These two cover the path that scanned and one of the three that did
    # not, and the union is taken over every entry of both -- the four paths write different subsets
    # (`too_far` exists only on the path that scanned), so a per-sport check would either fail on a
    # sport that never scanned or quietly check the one path a new key was added to.
    def no_feed(_url, **_kw):
        raise feed_mod.FeedUnavailable("404")

    scanned = _both_sports(_hub({"sports_cfb": {"winner": [(0.72, True)] * 3, "spread": [(0.5, True)]}}))
    unscanned = scan_mod.run_sports_scan(
        BOTH_NOW, _Kalshi({**_recorded_markets("nfl"), **_recorded_markets("cfb")}), fetch=no_feed,
        hub_ledger=_hub({"sports_cfb": {"winner": [(0.72, True)] * 3}}), sports=("nfl", "cfb"),
    )
    # Every entry of both runs, not a merge of them: the two runs use the same sport names, so a
    # `{**a, **b}` would keep only the second run's entries and quietly check one run's paths.
    states = [*scanned.per_sport.values(), *unscanned.per_sport.values()]
    written = {key for state in states for key in state}

    # The two runs really do cover the two kinds of path, so the union below is not one path twice.
    assert len(states) == 4, states
    assert any(s.get("series_ok") for s in states), "no path that scanned"
    assert any(s.get("too_far") is not None for s in states), "no path that scanned"
    assert any(s.get("too_far") is None for s in states), "no path that did not"
    # `too_soon` and `feed_unrecognised_kinds` are the two keys with a SPLIT value across the paths,
    # so the list membership above is not enough for them: `too_soon` is a real count only where the
    # window was applied, and `feed_unrecognised_kinds` is `None` on the two exits that never parsed
    # a payload. A key present on every path with one value everywhere would be published as a
    # measurement on runs that never took it.
    assert any(s.get("too_soon") is not None for s in states), "no path that scanned"
    assert any(s.get("too_soon") is None for s in states), "no path that did not"
    # The same split for the feed's key: a parsed payload gives a real list on the paths that got
    # one, and the 404 run above gives `None` on both of its sports because no payload was ever
    # read. `None` is this summary's word for "not measured", and an empty list there would tell a
    # reader the feed was checked and clean.
    assert [s.get("feed_unrecognised_kinds") for s in scanned.per_sport.values()] == [[], []]
    assert [s.get("feed_unrecognised_kinds") for s in unscanned.per_sport.values()] == [None, None]
    assert set(scan_mod.DIAGNOSTIC_KEYS) <= written, (
        f"DIAGNOSTIC_KEYS names {sorted(set(scan_mod.DIAGNOSTIC_KEYS) - written)}, which no path of "
        f"`run_sports_scan` writes. The list is how a diagnostic reaches the printed summary, so a "
        f"name nothing writes is published as None forever -- and None is this summary's word for "
        f"'not measured'."
    )
    # The converse is NOT asserted and must not be: `feed_ok`, `edges` and `series_ok` are read by
    # the prune path rather than carried to a reader, and a summary that grew all of them would be a
    # summary nobody reads.


# ── one sentinel, one meaning: `None` is "not measured" ─────────────────────────────────────────
#
# `unrecognised_kinds` chose `{}` deliberately: an empty tally is the POSITIVE answer, "the read
# completed and this sport has no settled row of a kind this build cannot place", and a reader has
# to be able to see that the distinction from "nothing of that kind has settled" is being made on
# purpose. But the settled-ledger reader returned a bare `HubLedger()` when the read FAILED -- empty
# mappings, because a partial record must not calibrate anything -- and so a failed read published
# the reassuring value for a measurement nobody took:
#
#     FAILED READ  -> {}
#     CLEAN READ   -> {}
#     GAPPED       -> {"moneyline": 2}
#
# Any Supabase error on any page gets there, the read has no retry, and on such a run the hub's
# calibration goes out of use for both sports so the board changes materially. `log.exception` was
# the only flag, in the channel an earlier round established nobody reads. That is the same false
# claim, at the same place, that `0` would have made for `too_far` on a feed-404 run and that this
# round already refused for the same reason.
#
# So both keys now share ONE sentinel with ONE meaning. `None` is "not measured"; an empty value is
# a real measurement. A reader never sees a value that reads as a completed measurement for a
# measurement that did not happen.


def _cfb_run_with(ledger, days_early: int = 3):
    """The same real CFB scan `_cfb_run_three_days_early` runs, but with the ledger supplied rather
    than read -- so two runs differ in exactly one input and the comparison is about that input."""
    return scan_mod.run_sports_scan(
        NOW - timedelta(days=days_early), _Kalshi(_recorded_markets("cfb")),
        fetch=lambda url, **_kw: _recorded_feed("cfb"), hub_ledger=ledger, sports=("cfb",),
    )


class _DeadSupabase:
    """Every call fails, which is what any Supabase outage on any page looks like from in here."""

    def table(self, _name):
        raise RuntimeError("postgrest 500")


def test_a_failed_ledger_read_publishes_not_measured_where_a_clean_one_publishes_a_count(
        monkeypatch, capsys):
    """The property, on the surface a reader reads, for the case that produced it.

    Two runs of the same real CFB scan, differing in one input: the ledger. One is measured, the other
    is the failed read. The assertion that matters is that the two summaries DIFFER, and that the
    failed one is not a value a reader would take as a completed measurement.

    The failed ledger is the LIVE reader's, off a client that fails: the property is that a real
    journal read going wrong cannot be told apart from a real journal read that found nothing. The
    measured one is hand-built, because the live reader reads winner rows only and this control needs
    a two-kind record (`HUB_LEDGER_KINDS`).
    """
    clean = _hub({"sports_cfb": {"winner": [(0.72, True)], "spread": [(0.51, False)]}})
    failed = journal_settled_ledger(_DeadSupabase())
    printed_clean = _cron_summary_for(monkeypatch, capsys, _cfb_run_with(clean))
    printed_failed = _cron_summary_for(monkeypatch, capsys, _cfb_run_with(failed))

    # The claim, first and on the reader's own bytes, so a regression is reported as the regression
    # rather than as its own setup. `None`, so the summary says the question was not asked on that
    # run; under the pre-fix code this is the line that fails, printing the `{}` it published.
    assert printed_failed["cfb"]["unrecognised_kinds"] is None, printed_failed["cfb"]
    # And the two runs are not interchangeable to a reader.
    assert (printed_failed["cfb"]["unrecognised_kinds"]
            != printed_clean["cfb"]["unrecognised_kinds"]), (
        "a failed read published the same value as a completed one, so nothing tells them apart"
    )

    # The guards that make those two claims mean something, after the claims.
    #
    # The control holds rows that exist, so its `{}` is EARNED -- "read it, this sport has no settled
    # row of a kind the build cannot place" -- and not the same nothing the failed read publishes.
    # Without this the difference asserted above could be a difference between "no rows" and "no
    # rows", which is what the bug was.
    assert clean.pairs_by_engine["sports_cfb"]["winner"], (
        "the control held real settled rows, so its empty tally is a measurement and not an absence"
    )
    assert clean.unrecognised_by_engine == {}, "the control has no build gap, by construction"
    assert failed.read_failed is True and clean.read_failed is False

    # The positive answer is untouched. A fix that made the key always `None` would pass the two
    # assertions above and destroy the diagnostic.
    assert printed_clean["cfb"]["unrecognised_kinds"] == {}, printed_clean["cfb"]

    # The other half of the finding: a failed read must not cost the scan either. Both runs price
    # the same two markets, so the fix is the diagnostic and not the board.
    assert printed_failed["cfb"]["markets_priced"] == printed_clean["cfb"]["markets_priced"] == 2, (
        f"{printed_failed['cfb']} vs {printed_clean['cfb']}"
    )
    # And `too_far` is a real count in BOTH runs, identically. The two keys are independent
    # measurements: one of them failing to be measured does not make the other one, and `None` is
    # not simply what this projection always emits.
    assert printed_failed["cfb"]["too_far"] == printed_clean["cfb"]["too_far"] == 1, (
        f"{printed_failed['cfb']} vs {printed_clean['cfb']}"
    )
    # So the same summary carries one key measured and one not, and `None` is the shared word for
    # "not measured" -- the same word `too_far` uses for a sport that never scanned.
    assert printed_failed["cfb"]["too_far"] is not None
    # The third key shares the sentinel, and is not measured on this run either: the read that
    # failed is the same read both of the ledger's keys are computed from, so there is no input one
    # of them could have been measured from.
    assert printed_failed["cfb"]["settled_by_kind"] is None, printed_failed["cfb"]
    assert printed_clean["cfb"]["settled_by_kind"] == {"winner": 1, "spread": 1}, printed_clean["cfb"]
    # The join publishes EVERY diagnostic key, including the ones this run never wrote into
    # `per_sport`. Derived from `DIAGNOSTIC_KEYS` rather than spelled out, so that adding a
    # diagnostic does not mean editing this assertion -- and so the assertion stays about the thing
    # it is for (a key in the list cannot be dropped by the join) rather than about today's list. It
    # still fails the moment a key in `DIAGNOSTIC_KEYS` is not published; what it no longer does is
    # fail the moment a key is added, which is the churn that would have trained a reader to
    # delete the assertion.
    joined = scan_mod.sports_run_summary(scan_mod.SportsRun(
        [], [], {}, {"cfb": {"too_far": None, "unrecognised_kinds": None, "settled_by_kind": None}}
    ))["cfb"]
    assert set(joined) == set(scan_mod.DIAGNOSTIC_KEYS), (
        f"the join published {sorted(joined)} for a sport whose per_sport entry carried none of "
        f"them; every key in DIAGNOSTIC_KEYS must be published as None"
    )
    assert set(joined.values()) == {None}, joined


def test_a_run_given_no_ledger_at_all_does_not_claim_the_read_found_nothing():
    """The same collision, second input: no ledger handed in rather than a failed one.

    `--dry-run` calls `run_sports_scan` with no `hub_ledger=` at all, so this is the shape the dry
    run actually produces. Nothing prints the diagnostics on that path today -- `main()` prints
    `run.reports` and neither key is in it -- so `{}` here is a false claim in the data structure
    rather than in front of a reader. It is worth the same fix for two reasons: a `per_sport` entry
    that says "no build gap" when nothing was read is the value the cron path would publish the day
    a caller is wired up without a ledger, and a `_unrecognised_for` that checked only
    `read_failed` would satisfy every other test here while leaving this input false.
    """
    run = scan_mod.run_sports_scan(
        NOW - timedelta(days=3), _Kalshi(_recorded_markets("cfb")),
        fetch=lambda url, **_kw: _recorded_feed("cfb"), sports=("cfb",),
    )

    assert run.per_sport["cfb"]["unrecognised_kinds"] is None, run.per_sport["cfb"]
    # The same for the third diagnostic, for the same reason and by the same predicate: `{}` here
    # would be the most reassuring wrong number on the run, because a reader seeing an empty per-kind
    # tally concludes nothing of that kind has settled, which is a statement about the sport's record
    # rather than about the fact that nobody asked.
    assert run.per_sport["cfb"]["settled_by_kind"] is None, run.per_sport["cfb"]
    # The scan is unaffected, as on a failed read: the predictor's calibration stays in charge.
    assert run.reports["cfb"]["markets_priced"] == 2, run.reports["cfb"]
    # And the dry run's own print carries NEITHER key, which is the settled ruling and the reason
    # the absence of a ledger cannot mislead anyone there today.
    assert scan_mod.sports_run_summary(run)["cfb"]["unrecognised_kinds"] is None
    assert scan_mod.sports_run_summary(run)["cfb"]["settled_by_kind"] is None


def test_the_two_ledger_diagnostics_never_disagree_about_whether_the_read_happened():
    """One predicate, one answer. `_unrecognised_for` and `_settled_by_kind_for` both reduce to
    `_ledger_measured`, and this is the test that says why they have to: they are two views of ONE
    read, computed from one `HubLedger`, so there is no input on which one could be measured and the
    other not. A copy of the `None` test written into one of them later would be invisible -- each
    key's own test would still pass -- and the run summary would then say "this sport has settled
    nothing" and "nobody looked" on the same line, which is the collision this sentinel exists to
    end, arriving in the other direction.

    `too_far` is in the same summary with the same sentinel and a third meaning ("this sport never
    scanned"), and it is deliberately NOT checked here: it is learned from the scan rather than from
    the read, so a scanned sport has one and a sport that did not has the other. `None` still means
    one thing across all three -- not measured -- which is the only property they share.
    """
    measured = _hub({"sports_cfb": {"winner": [(0.72, True)]}})
    for ledger in (measured, journal_settled_ledger(_DeadSupabase()), None):
        run = _cfb_run_with(ledger)
        state = run.per_sport["cfb"]
        # All three inputs, all three outcomes: a measured ledger, a failed read, and none at all.
        assert (state["unrecognised_kinds"] is None) == (state["settled_by_kind"] is None), (
            f"the two ledger diagnostics disagree about whether the read happened: {state}"
        )
    # And the measured one is a measurement rather than an absence, so the agreement above is not the
    # agreement of two `None`s.
    assert run.per_sport["cfb"]["settled_by_kind"] is None, "the last ledger handed in was None"
    assert _cfb_run_with(measured).per_sport["cfb"]["settled_by_kind"] == {"winner": 1}

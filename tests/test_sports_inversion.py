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

Two things this file also pins, because both were open questions rather than decisions:

- `n_buckets` is read off the feed, not assumed here. It is being changed from 10 to 4 in the
  predictors, and a hub bucket set cut on different edges is not a replacement for the predictor's
  record, it is a different measurement wearing its name.
- The hub's ledger is read as winner rows only, so a kind it does not cover finds no bucket and is
  rejected as `calibration_insufficient` rather than borrowing the winner model's numbers.
"""
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.edges import EdgeSuggestion, Quote
from tradehub.markets import parse_market
from tradehub.sports import scan as scan_mod
from tradehub.sports.candidates import HUB_LEDGER_MIN_SETTLED, check_candidate, choose_calibration
from tradehub.sports.feed import FeedGame, parse_feed
from tradehub.sports.hub_calibration import settled_buckets
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame
from tradehub.sports.scorecard import MIN_SETTLED

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

PARAMS = {"max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000, "min_hours_to_start": 1,
          "max_hours_to_start": 72, "calibration_max_dev": 0.10, "calibration_min_n": 20}

PREDICTOR = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 3, "mean_prob": 0.65, "hit_rate": 0.66}]}
HUB = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 120, "mean_prob": 0.65, "hit_rate": 0.70}]}


def test_the_predictors_own_calibration_is_used_while_the_hub_has_too_little():
    calibration, source = choose_calibration(PREDICTOR, {"winner": []}, {})

    assert source == "predictor"
    assert calibration is PREDICTOR


def test_the_hubs_ledger_takes_over_once_it_has_enough():
    calibration, source = choose_calibration(PREDICTOR, HUB, {})

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
    _, source = choose_calibration(PREDICTOR, short, {})

    assert source == "predictor"


def test_no_hub_calibration_at_all_stays_with_the_predictor():
    _, source = choose_calibration(PREDICTOR, None, {})

    assert source == "predictor"


def test_no_predictor_calibration_and_no_hub_falls_through_to_the_hub_rather_than_nothing():
    # A missing predictor payload must not leave the filter with no calibration at all, which would
    # read as "no bucket" and reject every edge for a reason that looks like bad luck.
    calibration, source = choose_calibration({}, HUB, {})

    assert source == "hub_ledger"
    assert calibration is HUB


def test_with_neither_source_the_filter_is_told_so_rather_than_left_guessing():
    calibration, source = choose_calibration(None, None, {})

    assert source == "none"
    assert calibration == {}


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

    def test_the_bucket_count_is_the_callers_decision(self):
        """10 and 4 both work and both are used in practice: the predictors are moving to 4."""
        assert len(settled_buckets([], n_buckets=4)["winner"]) == 4
        assert len(settled_buckets([], n_buckets=10)["winner"]) == 10

    def test_it_refuses_a_bucket_count_it_cannot_cut_on(self):
        with pytest.raises(ValueError):
            settled_buckets([(0.5, True)], n_buckets=0)

    def test_the_last_bucket_owns_a_probability_of_exactly_one(self):
        """`lo <= p < hi` drops 1.0 out of every band, and a certain call is the one probability a
        record must not lose."""
        assert settled_buckets([(1.0, True)], n_buckets=10)["winner"][9]["n"] == 1

    def test_a_kind_nobody_read_is_not_published(self):
        """Winner rows only. Publishing the same pairs under 'spread' and 'total' would be a kind
        attribution with no evidence behind it -- see hub_calibration.DEFAULT_KINDS."""
        buckets = settled_buckets([(0.65, True)] * 3, n_buckets=10)

        assert set(buckets) == {"winner"}


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


# ── the threading, through the scan ───────────────────────────────────────────────────────────


def _recorded_feed(sport="nfl", *, n_buckets=None, calibrated=True, bands=True):
    """The recorded feed, so `n_buckets` is the number a live predictor actually publishes."""
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    if n_buckets is not None:
        raw["calibration"]["n_buckets"] = n_buckets
    if not bands:
        # A feed that published no calibration at all: no count to read and no edges to cut on.
        raw["calibration"] = {"n_buckets": 0, "winner": [], "spread": [], "total": []}
    if calibrated:
        for kind in ("winner", "spread", "total"):
            for bucket in raw["calibration"][kind]:
                mid = round(bucket["lo"] + 0.05, 2)
                bucket.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


def _recorded_markets(sport="nfl"):
    from tradehub.sports.kalshi import parse_sports_market
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    return {series: [parse_sports_market(m) for m in markets] for series, markets in raw.items()}


# 120 settled winner snapshots at 0.28, which is the band the recorded HOU@IND winner markets land in
# (0.2954 home-oriented, on both sides of the same game). 60 of the 120 right, so the hub's record is
# a real measurement rather than a flattering one, and enough to clear HUB_LEDGER_MIN_SETTLED.
HUB_PAIRS = [(0.28, True)] * 60 + [(0.28, False)] * 60


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
    result = _scan(_recorded_feed(), hub_pairs=HUB_PAIRS)

    assert {row["calibration_source"] for row in result.edges} == {"hub_ledger"}
    graded = _graded_winner_rows(result)
    assert len(graded) == 2, "the recorded HOU@IND winner markets, on both sides of one game"
    for row in graded:
        # 60/60 at 0.28: the band the edge is admitted on is the hub's own record.
        assert row["calibration_bucket"]["hit_rate"] == pytest.approx(0.5)
        assert row["calibration_bucket"]["mean_prob"] == pytest.approx(0.28)
        assert row["candidate"] is True, row["reject_reasons"]


def test_a_game_the_hub_has_never_settled_is_rejected_on_the_hubs_record():
    """The switch has teeth, and the direction matters. With the predictor in charge the recorded feed
    admits every matched market; once the hub's ledger is in charge, a game it has no settled history
    for finds an empty band and is rejected. That is the claim of the inversion -- the hub is the
    record of what the hub itself priced and graded -- but it is a real narrowing of the board rather
    than a relabelling, so it is pinned here rather than left to be discovered."""
    predicted = _scan(_recorded_feed())
    switched = _scan(_recorded_feed(), hub_pairs=HUB_PAIRS)

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


def test_the_hubs_buckets_are_cut_on_the_number_of_buckets_the_feed_published():
    """The predictor's `n_buckets` is moving from 10 to 4, and this is why that number is read rather
    than assumed. A hub bucket set cut on different edges is not a replacement for the predictor's
    record, it is a different measurement wearing its name.

    Two halves, because neither earns the name alone: at 10 the band is 0.1 wide and a hardcoded 4
    fails it, and at 4 the band is 0.25 wide and a hardcoded 10 fails it.
    """
    for published, width in ((10, 0.1), (4, 0.25)):
        result = _scan(_recorded_feed(n_buckets=published), hub_pairs=HUB_PAIRS)
        bucket = _graded_winner_rows(result)[0]["calibration_bucket"]

        assert bucket["hi"] - bucket["lo"] == pytest.approx(width), (
            f"a feed publishing n_buckets={published} must produce bands {width} wide"
        )
        assert bucket["n"] == 120, "and the same settled pairs must land in the band the edge is in"


def test_a_kind_the_hubs_ledger_does_not_cover_is_not_borrowed_from_the_winner_bucket():
    """Winner rows only, and this is the consequence. A spread edge under hub authority finds no
    bucket and is rejected as `calibration_insufficient` -- a reason this codebase already knows how
    to read -- rather than being admitted against the winner model's record."""
    result = _scan(_recorded_feed(), hub_pairs=HUB_PAIRS)
    spread = [row for row in result.edges if row["kind"] != "winner"]

    assert spread, "the recorded feed has spread and total markets; this test needs one"
    for row in spread:
        assert row["calibration_source"] == "hub_ledger"
        assert row["calibration_bucket"] is None
        assert "calibration_insufficient" in row["reject_reasons"]
        assert row["candidate"] is False


def test_a_feed_that_published_no_bands_leaves_the_predictor_in_charge():
    """Nothing to cut against is not a reason to invent a cut. With 120 settled pairs in hand the scan
    still uses the published record, which is the behaviour before this change."""
    result = _scan(_recorded_feed(bands=False), hub_pairs=HUB_PAIRS)

    assert result.edges
    assert {row["calibration_source"] for row in result.edges} == {"predictor"}


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

    def test_a_feed_with_no_calibration_publishes_no_count(self):
        assert _recorded_feed(bands=False).n_buckets == 0


# ── reading the ledger, winner rows only ───────────────────────────────────────────────────────


class _Query:
    """A PostgREST-shaped builder that records what it was asked for, in the style of
    test_sports_scan.py's `unrecorded` fake."""

    def __init__(self, rows, asked):
        self.rows, self.asked = rows, asked

    def select(self, *columns):
        self.asked["select"] = [c.strip() for c in ",".join(columns).split(",")]
        return self

    def in_(self, column, values):
        self.asked["engine"] = (column, sorted(values))
        return self

    def eq(self, column, value):
        self.asked["eq"] = (column, value)
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, rows, asked):
        self.rows, self.asked = rows, asked

    def table(self, name):
        self.asked["table"] = name
        return _Query(self.rows, self.asked)


def _ledger(rows):
    asked: dict = {}
    return scan_mod._hub_settled_pairs(_Supa(rows, asked)), asked


def test_the_ledger_read_takes_winner_rows_and_leaves_the_rest_behind():
    rows = [
        {"engine": "sports_nfl", "our_prob": 0.65, "result": "yes", "raw_payload": {"kind": "winner"}},
        # No kind at all: what the scan has always written for a winner market, so it is a winner.
        {"engine": "sports_cfb", "our_prob": 0.40, "result": "no", "raw_payload": {}},
        {"engine": "sports_nfl", "our_prob": 0.30, "result": "no", "raw_payload": {"kind": "spread"}},
        {"engine": "sports_nfl", "our_prob": 0.30, "result": "no", "raw_payload": {"kind": "total"}},
        # Not settled, or not a graded binary: no win/loss signal to learn from.
        {"engine": "sports_nfl", "our_prob": 0.55, "result": None, "raw_payload": {"kind": "winner"}},
        {"engine": "sports_nfl", "our_prob": None, "result": "yes", "raw_payload": {"kind": "winner"}},
    ]
    pairs, asked = _ledger(rows)

    assert pairs == [(0.65, True), (0.40, False)]
    assert asked["table"] == "predictions"
    assert asked["eq"] == ("status", "SETTLED")
    assert asked["engine"] == ("engine", ["sports_cfb", "sports_nfl"])
    # Without raw_payload in the select there is no kind to honour, and the filter would be reading
    # a kind it never looked at.
    assert "raw_payload" in asked["select"]


def test_a_ledger_read_that_fails_leaves_the_predictors_calibration_in_charge():
    """The ledger read is a new failure mode on the sports path, and it must not be able to cost the
    scan: the pre-change behaviour is a working scan on the published calibration."""
    class Broken:
        def table(self, _name):
            raise RuntimeError("postgrest 500")

    assert scan_mod._hub_settled_pairs(Broken()) == []


def test_the_cron_path_actually_hands_the_ledger_to_the_scan(monkeypatch):
    """The last link in the chain, and the one most easily left disconnected: the read above proves
    the query, but nothing else would notice if the cron path stopped passing the result on, and the
    feature would simply never switch over with every test still green."""
    rows = [{"engine": "sports_nfl", "our_prob": 0.28, "result": "yes", "raw_payload": {"kind": "winner"}},
            {"engine": "sports_nfl", "our_prob": 0.28, "result": "no", "raw_payload": {"kind": "winner"}}]
    monkeypatch.setattr(scan_mod, "SportsKalshi", lambda **_kw: "kalshi")
    monkeypatch.setattr(scan_mod, "SupabaseReviewStore", lambda _supa: "store")
    monkeypatch.setattr(scan_mod, "OpenRouterReviewer", lambda *_a, **_kw: None)
    monkeypatch.setattr(scan_mod, "unrecorded", lambda _supa, rows: rows)
    seen: dict = {}

    def fake_scan(_now, _kalshi, **kwargs):
        seen.update(kwargs)
        return scan_mod.SportsRun([], [], {}, {})

    monkeypatch.setattr(scan_mod, "run_sports_scan", fake_scan)
    scan_mod.run_sports_for_cron(NOW, _Supa(rows, {}))

    assert seen["hub_pairs"] == [(0.28, True), (0.28, False)]

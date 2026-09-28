"""Rank by edge / sigma, and refuse to invent a sigma.

Two +10pp edges are not the same claim: at sigma 1.5pp the score is 6.7, at sigma 15pp it is 0.7.
Ranking on raw edge puts the vague one first.

**The producer comes first in this file, and that ordering is the correction.** Every other test here
built its own `raw_payload` with a `sigma` already in it, so 100% of the sigma coverage passed while
nothing in the codebase ever wrote one: `_edge_row` had no `sigma` key, `core/supabase_client.py`
stores `raw_payload = op` verbatim, and so `kalshi_edges.raw_payload["sigma"]` was ABSENT -- not
null, which is the distinction the whole defect hid behind. The feature was unreachable from real
data and the suite said it worked, because a hand-built payload is a statement about the test and not
about the code. `TestTheProducer` runs a real `scan_sport` and asserts on what it STORES. Read that
class first; the rest of this file is what happens to the number once it exists.

The refusals are three-valued, and telling them apart IS the test. A missing sigma is a real
possibility -- a feed that publishes none, a row written before the producer existed -- and it falls
back. A published ZERO is degenerate but real: a distribution with no width is a distribution that
was measured -- so it is floored and scored, and the response says `edge_sigma` because the sort
really did consume it. A NEGATIVE sigma is neither: it is corrupt input, and it is refused exactly as
a missing one is, because flooring it hands the row the cap and the top of the board. The third case
arrived on review (2026-09-27): a test named for a negative sigma was asserting a negative EDGE, so
the negative-sigma branch had a name, a docstring clause, and no coverage at all -- and the value it
was hiding was 20.0.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import _ranking_mode, _sports_rank, app
from tradehub.sports.scan import SIGMA_SCORE_CAP, edge_sigma_score, sigma_floor

FUTURE = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# THE PRODUCER. Everything below this block is downstream of one number existing.
# ════════════════════════════════════════════════════════════════════════════

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


class _Game:
    """A `feed.FeedGame` built field by field, because that is the contract `_edge_row` reads.

    The whole class exists because of the defect this block is named for. The earlier fakes in this
    suite omitted `sigma` and that was invisible while `_edge_row` never read it -- the first thing a
    real read of `game.sigma` did was turn three unrelated window tests into `AttributeError`s. So the
    fields are spelled out, and one of them (`SIGMA`, below) is the one the ranking is about.
    """

    def __init__(self, start_utc, *, sigma):
        self.sport = "cfb"
        self.game_id = "g1"
        self.home, self.away = "UConn", "Syracuse"
        self.start_utc = start_utc
        self.p_home = 0.55                 # what `price_market` reads for a winner market
        self.margin_mu = 3.0
        self.sigma = sigma
        self.total_mu, self.total_sigma = 55.0, 12.0
        self.model_version = "xgb@2026-09-04"
        self.snapshotted_at = start_utc - timedelta(hours=6)
        self.season, self.week = 2026, 5


class _Market:
    ticker = "KXNCAAFGAME-26SEP28SYRCONN-CONN"
    title = "UConn wins"
    event_ticker = "KXNCAAFGAME-26SEP28SYRCONN"
    close_time = NOW + timedelta(days=10)


class _Quote:
    yes_bid, yes_ask = 0.40, 0.44
    no_bid, no_ask = 0.56, 0.60
    yes_bid_size = yes_ask_size = no_bid_size = no_ask_size = 500


class _SportMarket:
    suffix = "CONN"          # `team_code` strips trailing digits off this
    volume = 5000.0

    def __init__(self):
        self.market = _Market()
        self.quote = _Quote()


class _Feed:
    sport = "cfb"
    generated_at = NOW
    n_buckets = 10
    calibration: dict = {}
    rejected: list = []
    games: list = []


def _cfg(**params):
    from tradehub.engine_config import EngineConfig
    from tradehub.sports.config import SportConfig

    p = {
        "max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000,
        "min_hours_to_start": 1, "max_hours_to_start": 72,
        "calibration_max_dev": 0.10, "calibration_min_n": 20,
    }
    p.update(params)
    return SportConfig(
        sport="cfb", engine="sports_cfb", base_url="http://x", site_url="http://y",
        series={"winner": "KXNCAAFGAME"}, series_titles={"KXNCAAFGAME": "NCAAF"},
        edge=EngineConfig(min_edge_pct=4.0, prefer_maker=True, params=p),
    )


def _stored_rows(*, sigma, monkeypatch, hours_out=24):
    """Run a REAL `scan_sport` and return what it would hand the database.

    The point of the helper is that it returns the scan's own output rather than a payload built to
    suit. `monkeypatch` rather than a bare assignment: `match_games` is a module global, and a
    permanent one leaks this fake into every later test in the session.
    """
    from tradehub.sports import scan as scan_mod
    from tradehub.sports.mapping import MatchedGame, MatchReport

    sm = _SportMarket()
    report = MatchReport(matched=[MatchedGame(
        game=_Game(NOW + timedelta(hours=hours_out), sigma=sigma),
        home_code="CONN", away_code="SYR", suffix="CONN", markets={"winner": [sm]},
    )])
    monkeypatch.setattr(scan_mod, "match_games", lambda *a, **k: report)
    result = scan_mod.scan_sport(_cfg(), {}, _Feed(), NOW)
    # `core.supabase_client.upsert_opportunities` stores `raw_payload = op` VERBATIM, so the op dict
    # the scan produced IS the stored row's payload. Shaped as the API reads it back so the ranking
    # assertions below run on the same shape the real handler gets, not on the scan's output alone.
    return [
        {"market_id": e["market_ticker"], "title": e["market_title"], "edge_type": "SPORTS",
         "engine": "sports_cfb", "gate_status": "SHADOW", "our_prob": e["model_probability"],
         "market_prob": e["market_price"], "edge_pct": round(e["edge"], 4), "expires_at": FUTURE,
         "raw_payload": dict(e)}
        for e in result.edges
    ], result


class TestTheProducer:
    """What actually writes `raw_payload["sigma"]`, asserted on what it writes.

    This is the class the defect slipped past. Every other test in this file, and the ones in
    `test_sports_api_range_paging.py`, constructed a `raw_payload` carrying a sigma by hand -- so the
    consumer was tested against an input no producer in the repository creates, and 100% of the
    sigma coverage was green on a feature that could not fire.
    """

    def test_a_real_scan_stores_the_games_own_sigma(self, monkeypatch):
        rows, result = _stored_rows(sigma=0.015, monkeypatch=monkeypatch)

        assert result.edges, "the fixture produced no edge, so nothing here is testing the producer"
        assert rows[0]["raw_payload"]["sigma"] == 0.015, (
            f"a scan of a game the feed gave sigma=0.015 stored no sigma: {sorted(rows[0]['raw_payload'])}"
        )

    def test_a_stored_sigma_is_what_the_ranking_mode_reads(self, monkeypatch):
        """The end of the line, and the only assertion here that is about the FEATURE rather than
        about one function: a real scan of a real sigma must make the API report `edge_sigma`.

        Before the producer existed this returned `raw_edge` over rows priced from a sigma of 0.015,
        and the page said "the feed reports no sigma yet" -- a false claim about a feed that was
        reporting one the whole time.
        """
        rows, _ = _stored_rows(sigma=0.015, monkeypatch=monkeypatch)

        assert rows, "no rows, so there is nothing for the ranking to read"
        assert _ranking_mode(rows) == "edge_sigma", (
            f"a real scan stored rows the API reads as unscored: {[r['raw_payload'].get('sigma') for r in rows]}"
        )

    def test_a_game_with_no_sigma_still_stores_the_key_and_reports_raw_edge(self, monkeypatch):
        """`None` is a real published value -- the feed said it has no width -- and it has to be
        STORED, not omitted, so that `raw_payload["sigma"]` means "what the feed published" rather
        than "whatever the writer remembered to add".

        This is the case the two are easy to confuse over, and the confusion is what hid the bug: a
        missing key and a null value read identically to `.get("sigma")`, so a test could not tell
        "the feed published nothing" from "nobody wrote a producer". Storing the key either way is
        what makes the difference observable.
        """
        rows, _ = _stored_rows(sigma=None, monkeypatch=monkeypatch)

        assert "sigma" in rows[0]["raw_payload"], (
            "a null sigma is a published value and must be stored; omitting the key is what made "
            "the missing producer indistinguishable from a feed that publishes no sigma"
        )
        assert rows[0]["raw_payload"]["sigma"] is None
        assert _ranking_mode(rows) == "raw_edge", (
            "a null sigma is not scorable, so the sort really did fall back and must say so"
        )

    def test_the_api_does_NOT_publish_sigma_to_the_page(self, monkeypatch):
        """The other half of the contract, and the half that must NOT be "fixed".

        `_edge_row` writes the sigma; `edge_row` deliberately withholds it from the served payload.
        That asymmetry is load-bearing: the server sorts and reports which ranking it used, and a
        per-row sigma in the page's hands is a second source of the ranking -- one the page could
        sort by and then have to describe, and which would let the client re-derive a mode the
        response already states. Publishing it would also mean the fully-scored and partly-scored
        boards stopped being one literal, and the `edge_sigma` sentence has to be true of both.
        """
        from tradehub.sports.scan import edge_row

        rows, _ = _stored_rows(sigma=0.015, monkeypatch=monkeypatch)
        served = [edge_row(r) for r in rows]

        assert served, "no served rows"
        for row in served:
            assert "sigma" not in row, (
                f"the page can now see a per-row sigma and could sort on it itself: {sorted(row)}"
            )

    def test_the_stored_sigma_is_a_width_the_pricer_reads_not_a_decoration(self):
        """On a SPREAD market, `price_market` computes the quoted probability with this exact sigma
        (`prob_in_interval(margin_mu, sigma, ...)`), so the row is ranked on the confidence of the
        number it carries. Two sigmas, two prices, so the width is demonstrably an input rather than
        a field copied in for show.

        Winner markets are the honest exception and are named rather than glossed: their price comes
        from `p_home` alone, so there the stored sigma is the game's published width rather than the
        width of that particular quote. That is the shape `edge / sigma` asks for -- ONE sigma per
        game, so spread and winner rows of a game stay comparable -- and it is why this test uses a
        spread market rather than asserting the winner case too.
        """
        from tradehub.sports.mapping import MatchedGame
        from tradehub.sports.pricing import price_market

        sm = _SportMarket()
        sm.market.floor_strike = 2.5
        sm.market.strike_type = "greater"

        def _price_at(sigma):
            game = _Game(NOW + timedelta(hours=24), sigma=sigma)
            return price_market("spread", sm, MatchedGame(
                game=game, home_code="CONN", away_code="SYR", suffix="CONN",
                markets={"spread": [sm]}))

        tight, vague = _price_at(0.015), _price_at(0.20)
        assert tight is not None and vague is not None, "the spread fixture priced to None"
        assert tight != vague, (
            "two different sigmas priced the same market identically, so the width is not an input "
            "to the price and storing it records a number nothing used"
        )
        assert 0.0 <= vague < tight <= 1.0, (tight, vague)


class TestScore:
    def test_a_confident_edge_scores_above_a_vague_one_at_the_same_size(self):
        confident = edge_sigma_score(0.10, 0.015)
        vague = edge_sigma_score(0.10, 0.15)

        assert confident > vague
        assert confident == pytest.approx(6.67, abs=0.01)
        assert vague == pytest.approx(0.67, abs=0.01)

    def test_a_MISSING_sigma_produces_no_score_at_all(self):
        """The important one, and it was wrong in the first draft of this plan.

        Flooring a missing sigma gives 0.10 / 0.005 = 20.0 -- the CAP, i.e. the highest score the
        feature can produce. So a row whose confidence is unknown would rank at the very top of its
        tier, which is the opposite of conservative, and the docstring claiming otherwise would have
        been false.

        Absent is not the same as degenerate. Absent means the feed said nothing, so there is no
        confidence to score and the row falls back to raw edge. The floor exists for a *published*
        sigma of zero, which is a real value that would otherwise divide by zero.
        """
        assert edge_sigma_score(0.10, None) is None

    def test_a_degenerate_published_sigma_is_floored_and_then_capped(self):
        assert edge_sigma_score(0.10, 0.0) == SIGMA_SCORE_CAP

    def test_a_missing_sigma_cannot_outrank_a_confident_one(self):
        missing = edge_sigma_score(0.10, None)
        confident = edge_sigma_score(0.10, 0.015)
        assert missing is None or missing < confident, (
            "an unknown confidence must never score above a known one"
        )

    def test_the_score_is_capped_so_one_absurd_ratio_cannot_own_the_top(self):
        assert edge_sigma_score(0.90, 0.0001) == SIGMA_SCORE_CAP

    def test_a_missing_edge_has_no_score(self):
        assert edge_sigma_score(None, 0.05) is None

    def test_the_floor_is_the_documented_value(self):
        """Pinned because the floor is the difference between 'degenerate' and 'confident'. Moved
        silently, it would change which rows are floored without any test saying so."""
        assert sigma_floor == 0.005

    def test_a_published_sigma_below_the_floor_is_floored_rather_than_divided_by(self):
        """A positive-but-absurd sigma is a real published value, so the floor applies to it exactly
        as it applies to zero. The floor is not a stand-in for a missing number."""
        assert edge_sigma_score(0.10, 0.0001) == pytest.approx(0.10 / sigma_floor, abs=0.001)

    def test_a_negative_EDGE_is_scored_negative_rather_than_as_a_large_disagreement(self):
        """A negative EDGE, which is a real value: the market disagrees with us, or we are on the
        wrong side of it.

        The market being MORE confident than we are is the opposite of a wide disagreement.
        `abs()` here would score -0.10 at a tight sigma as +6.7, and `_sports_rank` negates the
        score, so a row whose edge points the wrong way would lead its tier instead of trailing it.
        That is a change in what the sign means, not a rounding detail.

        (Named after its EDGE on purpose. This test used to be called `test_a_negative_sigma_...`
        while asserting a negative edge, which left a branch nothing covered: a negative SIGMA is a
        different value with the opposite answer, and it is pinned by the test below.)
        """
        assert edge_sigma_score(-0.10, 0.015) == pytest.approx(-6.667, abs=0.001)

    def test_a_NEGATIVE_sigma_is_refused_rather_than_floored_to_the_cap(self):
        """A negative sigma is corrupt input, not a degenerate real value, and it is the one thing
        this feature must not turn into a rank.

        Flooring it hands it the floor, so 0.10 / 0.005 = 20.0 -- SIGMA_SCORE_CAP, the highest score
        the feature can produce and the top of the board. A predictor that published a negative width
        would therefore lead its own tier, which is the same failure as flooring a MISSING sigma
        (see above) wearing a different hat, and it is worse: a missing sigma is today's normal
        state and visible to the reader, whereas a negative one only ever appears when something has
        already gone wrong upstream.

        There is no third option. Scoring it would mean inventing a confidence the feed never had,
        and this feature exists to refuse exactly that.
        """
        assert edge_sigma_score(0.10, -0.05) is None
        # Any negative width, not one magnitude: a tiny negative floors as hard as a large one.
        assert edge_sigma_score(0.10, -0.0001) is None
        # Including alongside an edge that is itself negative, so the two refusals are independent.
        assert edge_sigma_score(-0.10, -0.05) is None

    def test_a_zero_sigma_is_still_floored_so_the_refusal_above_is_not_just_the_floor(self):
        """The load-bearing half of the pair: -0.0 and 0.0 are the same number to `sigma < 0`, and
        the boundary is on the sign rather than on `sigma <= 0`."""
        assert edge_sigma_score(0.10, 0.0) == SIGMA_SCORE_CAP
        assert edge_sigma_score(0.10, -0.0) == SIGMA_SCORE_CAP


class TestBoolIsNotANumber:
    """`bool` is an `int` subclass and `float(True)` is 1.0, so the numeric checks have to exclude it
    explicitly. Unreachable from jsonb, so these are cosmetic guards -- which is exactly why they need
    a test, since a branch with no test is a branch nobody re-reads."""

    def test_a_bool_edge_is_not_a_one_pp_edge(self):
        """Without the guard this is 1.0 / 0.05 = 20.0: the cap, from a JSON `true` in the edge."""
        assert edge_sigma_score(True, 0.05) is None
        assert edge_sigma_score(False, 0.05) is None

    def test_a_bool_sigma_is_not_a_full_width_confident_forecast(self):
        """Without the guard this is 0.10 / 1.0 = 0.1 -- scored as though the predictor had published
        a 100pp-wide distribution and were therefore the most confident thing on the board."""
        assert edge_sigma_score(0.10, True) is None
        assert edge_sigma_score(0.10, False) is None


# ── the ranking, on real-shaped database rows ──────────────────────────────────────────────────
#
# `_sports_rank` sorts the rows read out of `kalshi_edges`, BEFORE `edge_row` is applied, so what it
# reads is the COLUMN `edge_pct` and `raw_payload`. `rank_edge_pct` is the name the served row
# carries for that same number (sports/scan.py `edge_row`), and it does not exist on the stored row
# at all -- so a fallback that read it would silently be the 0.0 fallback.

def _edge(market_id, *, edge_pct, sigma="absent", tier="top_pick", candidate=True):
    raw = {
        "sport": "nfl", "kind": "winner", "side": "yes", "entry_price": 0.25, "maker": True,
        "home": "IND", "away": "HOU", "start_utc": FUTURE, "tier": tier, "candidate": candidate,
        "reject_reasons": [], "game_id": "g", "engine_version": "feed:v1",
    }
    if sigma != "absent":
        raw["sigma"] = sigma
    return {
        "market_id": market_id, "title": market_id, "edge_type": "SPORTS", "engine": "sports_nfl",
        "gate_status": "SHADOW", "our_prob": 0.3, "market_prob": 0.25, "edge_pct": edge_pct,
        "expires_at": FUTURE, "market_url": "https://kalshi.com/markets/x",
        "source_url": "https://sports/x", "raw_payload": raw,
    }


class TestRankFallsBackToTheRawEdge:
    def test_within_a_tier_the_confident_edge_leads(self):
        confident = _edge("C", edge_pct=0.10, sigma=0.015)
        vague = _edge("V", edge_pct=0.10, sigma=0.15)

        assert _sports_rank(confident) < _sports_rank(vague), (
            "two equal edges at different confidences are not equal claims"
        )

    def test_a_row_with_no_sigma_is_ranked_by_its_own_edge(self):
        """The fallback, and it is the raw edge rather than 0.0.

        0.0 is not a neutral key: `_sports_rank` negates, so it would sort the row LAST within its
        tier, which reads as 'the least interesting pick here'. That is a claim about the row, and it
        is made by a fallback -- the row's confidence is unknown, which says nothing about how
        interesting it is.
        """
        small = _edge("S", edge_pct=0.02)
        big = _edge("B", edge_pct=0.40)
        # Deliberately the wrong way round: an equal-keyed sort is stable and would preserve this
        # order, so only a real edge comparison can fix it.
        assert _sports_rank(big) < _sports_rank(small)

    def test_a_row_with_no_sigma_ranks_beside_the_scored_ones_not_below_them(self):
        """The same decision, seen from the other side: a no-sigma row must not be pushed underneath
        a scored row on the strength of nothing."""
        scored = _edge("S", edge_pct=0.10, sigma=0.50)   # a wide distribution: score 0.2
        unknown = _edge("U", edge_pct=0.40)              # no sigma: falls back to 0.40
        assert scored["edge_pct"] / 0.50 < unknown["edge_pct"]
        assert _sports_rank(unknown) < _sports_rank(scored), (
            "a fallback of 0.0 would have sorted the unknown row last, as though it were the "
            "least interesting pick here"
        )

    def test_a_negative_edge_still_ranks_last_in_its_tier(self):
        wrong_way = _edge("N", edge_pct=-0.10, sigma=0.015)
        right_way = _edge("P", edge_pct=0.10, sigma=0.015)
        assert _sports_rank(right_way) < _sports_rank(wrong_way)

    def test_a_corrupt_sigma_cannot_lead_its_tier(self):
        """The negative sigma refused above, seen through the sort that consumes it.

        Floored, a -0.05 sigma scores this 2pp edge at 2.0 / 0.005 = 4.0, which is a HIGHER score
        than the honest 10pp edge below it -- so the row from the broken predictor leads. That is the
        whole failure in one line of test data: nothing about this edge is special, and the only
        reason it would lead is that its denominator was corrupt.

        The corrupt row falls back to its own 0.02 edge, so it ranks below the honest 0.10. Nothing
        else about the ranking changes: same group, same tier, same key shape.
        """
        corrupt = _edge("X", edge_pct=0.02, sigma=-0.05)   # refused -> falls back to 0.02
        honest = _edge("H", edge_pct=0.10, sigma=0.05)     # scored -> 2.0
        assert edge_sigma_score(corrupt["edge_pct"], corrupt["raw_payload"]["sigma"]) is None
        assert _sports_rank(honest) < _sports_rank(corrupt), (
            "a sigma that came from a broken predictor must not buy its row the top of the tier"
        )

    def test_tier_order_is_untouched_by_the_score(self):
        """The confidence score ranks WITHIN a tier. It must not let a filtered row with a huge
        score outrank a top pick, which is the one thing the group ordering exists to prevent."""
        rejected = _edge("F", edge_pct=0.90, sigma=0.001, tier="filtered", candidate=False)
        top_pick = _edge("T", edge_pct=0.01, sigma=0.50)
        assert _sports_rank(top_pick) < _sports_rank(rejected)


class TestRankingMode:
    def test_it_says_raw_edge_when_the_feed_publishes_no_sigma(self):
        rows = [_edge("A", edge_pct=0.10), _edge("B", edge_pct=0.05)]
        assert _ranking_mode(rows) == "raw_edge"

    def test_it_says_edge_sigma_once_a_real_sigma_is_published(self):
        rows = [_edge("A", edge_pct=0.10), _edge("B", edge_pct=0.05, sigma=0.02)]
        assert _ranking_mode(rows) == "edge_sigma"

    def test_a_degenerate_published_sigma_still_counts_as_edge_sigma(self):
        """Sigma 0 is floored and scored like any other published value, so the sort DID use the
        score. Reporting `raw_edge` here would be the mode disagreeing with the sort it describes."""
        assert _ranking_mode([_edge("A", edge_pct=0.10, sigma=0.0)]) == "edge_sigma"

    def test_a_partly_published_feed_says_edge_sigma(self):
        """The sort is per row: a row with a sigma is scored and one without falls back. The page's
        sentence is worded to be true in that state, so the mode only has to be right about whether
        the score was in play at all."""
        assert _ranking_mode([_edge("A", edge_pct=0.10, sigma=0.02), _edge("B", edge_pct=0.05)]) \
            == "edge_sigma"

    def test_an_empty_result_set_reports_raw_edge(self):
        """Nothing was ranked, so the conservative answer is the one that claims the least."""
        assert _ranking_mode([]) == "raw_edge"

    def test_a_set_whose_ONLY_sigma_is_corrupt_reports_raw_edge(self):
        """A negative sigma scores to `None`, so it did not decide anything -- and a page that says
        "ranked by edge over the predictor's own sigma" here is telling the reader the sort used a
        confidence it refused to use.

        The difference from `test_a_degenerate_published_sigma_still_counts_as_edge_sigma` above is the
        whole point of the pair: a published ZERO is a degenerate value the sort really did consume
        (floored), and a negative one is corrupt input it consumed not at all. Same literal field,
        opposite answers, and the page's sentence turns on the distinction.
        """
        assert _ranking_mode([_edge("A", edge_pct=0.10, sigma=-0.05)]) == "raw_edge"

    def test_a_corrupt_sigma_does_not_hide_a_real_one(self):
        """Mixed set, and the mode reports what the sort actually did: the honest row was scored, so
        the ranking is `edge_sigma`. The corrupt row falls back to its own edge and is still ranked,
        correctly, just not on a score."""
        rows = [_edge("A", edge_pct=0.10, sigma=-0.05), _edge("B", edge_pct=0.10, sigma=0.02)]
        assert _ranking_mode(rows) == "edge_sigma"


class _Q:
    def __init__(self, table, store):
        self.table, self.store, self.rows = table, store, list(store.tables[table])

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def gte(self, col, val):
        self.rows = [r for r in self.rows if str(r.get(col, "")) >= str(val)]
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def range(self, lo, hi):
        self.rows = self.rows[lo:hi + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(name, self)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(edges):
    app.dependency_overrides[get_supabase] = lambda: _Supa({
        "kalshi_edges": edges, "sports_reviews": [], "predictions": [],
    })
    return TestClient(app)


class TestTheResponseSaysWhichRankingItUsed:
    """A page that claims to rank by confidence while ranking by raw edge is worse than one that
    never claimed it, so the field has to be on the response and has to be right."""

    def test_the_response_reports_raw_edge_for_todays_rows(self):
        body = _client([_edge("A", edge_pct=0.10), _edge("B", edge_pct=0.05)]).get(
            "/api/sports-edges").json()
        assert body["ranking"] == "raw_edge", (
            f"the sort fell back to raw edge, so claiming edge_sigma would be a lie: {body['ranking']}"
        )

    def test_the_response_reports_edge_sigma_when_the_feed_publishes_one(self):
        body = _client([_edge("A", edge_pct=0.10, sigma=0.02)]).get("/api/sports-edges").json()
        assert body["ranking"] == "edge_sigma"

    def test_the_reported_ranking_matches_the_order_the_rows_are_actually_in(self):
        """The mode is not decoration beside the sort: it has to describe it. A confident and a vague
        edge of the same size are raw-edge INDISTINGUISHABLE, so this ordering can only come from the
        score."""
        rows = [_edge("vague", edge_pct=0.10, sigma=0.15), _edge("confident", edge_pct=0.10, sigma=0.015)]
        body = _client(rows).get("/api/sports-edges").json()
        assert body["ranking"] == "edge_sigma"
        assert [e["market_id"] for e in body["edges"]] == ["confident", "vague"], (
            "the page says it ranked by confidence, so confidence has to be what ordered it"
        )

    def test_the_ranking_is_reported_over_the_whole_set_not_just_this_page(self):
        """A sigma on page 3 is still a sigma the sort used, so a page-1-only count would report
        `raw_edge` while rows were being scored -- the exact claim the field exists to prevent."""
        edges = [_edge(f"P{i:03d}", edge_pct=0.01 * i) for i in range(150)]
        edges[149]["raw_payload"]["sigma"] = 0.02
        body = _client(edges).get("/api/sports-edges", params={"limit": 50, "offset": 0}).json()
        assert len(body["edges"]) == 50
        assert body["ranking"] == "edge_sigma"

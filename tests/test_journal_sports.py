import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.sports import (
    SportsFeedForecaster,
    SportsMarketImplied,
    SportsSnapshot,
    build_sports,
    one_per_game,
)
from tradehub.journal.runner import run_journal
from tradehub.sports import scan as sports_scan
from tradehub.sports.config import load_sport_config
from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.scan import run_sports_scan

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
PRE_GAME = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)  # the recorded NFL games kick off at 17:00Z: 15h out


class FakeKalshi:
    def __init__(self, sport):
        raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
        self.markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}

    def open_markets(self, series):
        return self.markets.get(series, [])


def _scan(sport, counter=None):
    feed = parse_feed(json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text()))

    def scan(now):
        if counter is not None:
            counter.append(now)
        return run_sports_scan(now, FakeKalshi(sport), fetch=lambda base_url, deadline=None: feed, sports=(sport,))
    return scan


def _final(ticker_result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": ticker_result}}


def test_one_target_per_game_winner_markets_only_first_ticker():
    rows = [
        {"market_ticker": "B-HOU", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "A-IND", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "S-IND8", "raw_payload": {"kind": "spread", "game_id": "g1"}},
        {"market_ticker": "T-O45", "raw_payload": {"kind": "total", "game_id": "g1"}},
        {"market_ticker": "C-KC", "raw_payload": {"kind": "winner", "game_id": "g2"}},
    ]
    assert set(one_per_game(rows)) == {"A-IND", "C-KC"}  # never looks at the forecast


def test_the_same_game_keeps_the_same_ticker_when_its_first_quote_goes_one_sided():
    """A walk-forward series is only a series if the same game is the same instrument every hour.

    CodeRabbit on #61: `one_per_game` chose from the quote-eligible rows, so the chosen ticker could
    change between two hourly snapshots of ONE game. `scan_sport` only emits a prediction row when the
    market has both a bid and an ask, so the minute `KXNFLGAME-26SEP27HOUIND-HOU` (the ASCII-first of
    that game's two winner markets) goes one-sided, it drops out of the input entirely and
    `…-IND` -- the exact complement, pointing the OTHER way -- is journaled under the same game_id.

    Nothing downstream can see it. Both are winner markets for one game, the calendar registers a
    fresh entry for the newcomer, and the settled count for the game goes to two: one target that
    resolved YES and one that resolved NO, in the same series. The scorecard averages them as
    independent evidence.

    The docstring already claims the rule this breaks ("of a game's two winner markets only the first
    in ASCII ticker order. The rule never looks at the forecast") -- it just does not hold when the
    set of candidates changes, which is exactly what a quote going one-sided does.

    Two snapshots of the same feed, one apart: same game, same ticker out. A test that asserted
    "one_per_game returns something" would pass against the bug, so the two sides must DIFFER.
    """
    import copy

    from tradehub.journal.forecasters.sports import one_per_game

    raw = json.loads((FIXTURES / "nfl_open_markets.json").read_text())
    feed_raw = json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())
    for kind in ("winner", "spread", "total"):
        for band in feed_raw["calibration"][kind]:   # the recorded feed has no graded history
            mid = round(band["lo"] + 0.05, 2)
            band.update(n=40, mean_prob=mid, hit_rate=mid)
    feed = parse_feed(feed_raw)
    cfg = load_sport_config("nfl")
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def picked(markets):
        rows = sports_scan.scan_sport(
            cfg, {s: [parse_sports_market(m) for m in ms] for s, ms in markets.items()}, feed, now)
        return one_per_game(rows.predictions)

    both_quoted = copy.deepcopy(raw)
    assert "KXNFLGAME-26SEP27HOUIND-HOU" in picked(both_quoted), picked(both_quoted)

    one_sided = copy.deepcopy(raw)
    for market in one_sided["KXNFLGAME"]:
        if market["ticker"] == "KXNFLGAME-26SEP27HOUIND-HOU":
            market["yes_ask_dollars"] = None   # the book thins; the row leaves the scan entirely
    thinned = next(m for m in one_sided["KXNFLGAME"] if m["ticker"] == "KXNFLGAME-26SEP27HOUIND-HOU")
    assert thinned["yes_bid_dollars"] and thinned["yes_ask_dollars"] is None, (
        "the market must still be listed and priced -- only its quote is one-sided")

    later = picked(one_sided)
    assert "KXNFLGAME-26SEP27HOUIND-IND" not in later, (
        "the complement was journaled for a game already journaled as its sibling, so one game enters "
        f"the series twice in both directions: {sorted(later)}")
    # A gap is the honest alternative and this is what the rule now produces: the game's ticker is
    # unchanged, it simply has no quote to freeze this hour. Either state is fine; a DIFFERENT ticker
    # is not, and that is the only thing this asserts.
    assert set(later) & set(picked(both_quoted)) == set(both_quoted := picked(both_quoted)) - {
        "KXNFLGAME-26SEP27HOUIND-HOU"}, (later, both_quoted)


def test_the_feed_forecaster_freezes_the_predictors_probability_and_the_quote():
    snapshot = SportsSnapshot("nfl", _scan("nfl"))
    fc = SportsFeedForecaster(snapshot, _final("yes"))
    entries = fc.targets(PRE_GAME)
    assert entries and all(e.market_linked and e.cadence == "daily" and e.target.startswith("kalshi:KXNFLGAME-")
                           for e in entries)
    assert all(e.cutoff_at == datetime(2026, 9, 27, 17, 0, tzinfo=UTC) or e.cutoff_at > PRE_GAME for e in entries)
    forecast = fc.forecast(entries[0], PRE_GAME)
    assert (fc.name, fc.version) == ("sports_nfl", "feed-v1")
    assert 0.0 < forecast.probability < 1.0 and forecast.market_prob is not None
    assert forecast.payload["game_id"] and forecast.payload["kind"] == "winner"
    assert forecast.payload["yes_bid"] is not None and forecast.payload["yes_ask"] is not None  # for cost netting
    assert forecast.payload["model_version"]  # the predictor's version rides in the row, not in the key


def test_a_game_outside_the_24h_lead_is_not_a_target_yet():
    fc = SportsFeedForecaster(SportsSnapshot("nfl", _scan("nfl")), _final("yes"))
    assert fc.targets(PRE_GAME - timedelta(hours=12)) == []  # the nearest game is 27h out
    after_sunday = datetime(2026, 9, 27, 17, 30, tzinfo=UTC)  # the 17:00Z games have kicked off
    assert all(e.cutoff_at > after_sunday for e in fc.targets(after_sunday))  # only the late game remains


def test_both_forecasters_share_one_scan_per_hour():
    calls = []
    snapshot = SportsSnapshot("nfl", _scan("nfl", calls))
    feed, implied = SportsFeedForecaster(snapshot, _final("yes")), SportsMarketImplied(snapshot, _final("yes"))
    feed.targets(PRE_GAME)
    implied.targets(PRE_GAME)
    feed.forecast(feed.targets(PRE_GAME)[0], PRE_GAME)
    assert len(calls) == 1
    feed.targets(PRE_GAME + timedelta(hours=1))
    assert len(calls) == 2


def test_end_to_end_freeze_before_kickoff_then_settle_on_kalshi_and_score_against_the_mid():
    clock = [PRE_GAME]
    db = FakeJournalDB(lambda: clock[0])
    snapshot = SportsSnapshot("nfl", _scan("nfl"))
    fcs = [SportsFeedForecaster(snapshot, _final("yes")), SportsMarketImplied(snapshot, _final("yes"))]
    out = run_journal(db, fcs, clock[0])
    frozen = out["forecasters"]["sports_nfl@feed-v1"]["frozen"]
    assert frozen >= 1 and out["forecasters"]["kalshi_implied_sports_nfl@v1"]["frozen"] == frozen
    clock[0] = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)  # after the games
    snapshot._hour = None
    out = run_journal(db, fcs, clock[0])
    started = [c for c in db.tables["journal_calendars"] if datetime.fromisoformat(c["cutoff_at"]) <= clock[0]]
    assert 0 < len(started) < frozen  # the late-Sunday game has not kicked off: it must not settle yet
    assert out["forecasters"]["sports_nfl@feed-v1"]["settled"] == len(started)
    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["sports_nfl"]["baseline"] == "market"
    assert cards["kalshi_implied_sports_nfl"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_both_sports_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for expected in (("sports_nfl", "feed-v1"), ("kalshi_implied_sports_nfl", "v1"),
                     ("sports_cfb", "feed-v1"), ("kalshi_implied_sports_cfb", "v1")):
        assert expected in keys
    assert len(set(keys)) == len(keys) and len(build_sports()) == 12

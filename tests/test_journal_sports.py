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
    assert len(set(keys)) == len(keys) and len(build_sports()) == 4

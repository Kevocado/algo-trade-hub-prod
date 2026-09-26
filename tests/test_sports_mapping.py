import json
from datetime import datetime, timezone
from pathlib import Path

from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.mapping import kalshi_date, load_aliases, match_games

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
SERIES = {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}


def _markets(sport):
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    return {series: [parse_sports_market(m) for m in ms] for series, ms in raw.items()}


def test_kalshi_date_is_the_eastern_date_of_kickoff():
    # Thursday night kickoff 00:15Z Friday is still Thursday in New York.
    assert kalshi_date(datetime(2026, 10, 2, 0, 15, tzinfo=timezone.utc)) == "26OCT01"
    assert kalshi_date(datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)) == "26SEP27"


def test_alias_tables_are_versioned_and_cover_known_code_mismatches():
    nfl, cfb = load_aliases("nfl"), load_aliases("cfb")
    assert nfl.version == "2026-09-25" and len(nfl.teams) == 32
    assert (nfl.teams["JAX"], nfl.teams["LA"]) == ("JAC", "LAR")
    assert len(cfb.teams) >= 233
    assert cfb.teams["Miami"] == "MIA" and cfb.teams["Miami (OH)"] == "MOH"
    assert cfb.teams["South Alabama"] == "USA" and cfb.teams["New Mexico State"] == "NMSU"


def test_match_nfl_fixture_games_including_the_rams_alias():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    report = match_games(feed.games, _markets("nfl"), SERIES, load_aliases("nfl"))
    assert {m.game.game_id: m.suffix for m in report.matched} == {
        "2026_03_CIN_PIT": "26SEP27CINPIT", "2026_03_HOU_IND": "26SEP27HOUIND", "2026_03_LA_DEN": "26SEP27LARDEN",
    }
    la = next(m for m in report.matched if m.game.game_id == "2026_03_LA_DEN")
    assert (la.home_code, la.away_code) == ("DEN", "LAR")
    hou = next(m for m in report.matched if m.game.game_id == "2026_03_HOU_IND")
    assert sorted(m.market.ticker for m in hou.markets["spread"]) == [
        "KXNFLSPREAD-26SEP27HOUIND-HOU3", "KXNFLSPREAD-26SEP27HOUIND-HOU7",
        "KXNFLSPREAD-26SEP27HOUIND-IND3", "KXNFLSPREAD-26SEP27HOUIND-IND8",
    ]
    assert len(hou.markets["total"]) == 3 and len(hou.markets["winner"]) == 2
    assert report.unmatched_games == []
    assert report.unmatched_events == ["KXNFLGAME-26SEP27KCMIA"]   # no feed game for it


def test_unknown_team_and_missing_event_are_reported_not_guessed():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    games = [g.__class__(**{**g.__dict__, "home": "XXX"}) if g.game_id == "2026_03_CIN_PIT" else g for g in feed.games]
    markets = _markets("nfl")
    markets["KXNFLGAME"] = [m for m in markets["KXNFLGAME"] if "LARDEN" not in m.market.ticker]
    report = match_games(games, markets, SERIES, load_aliases("nfl"))
    assert sorted(report.unmatched_games) == [
        ("2026_03_CIN_PIT", "no_alias:XXX"), ("2026_03_LA_DEN", "no_kalshi_event:26SEP27LARDEN"),
    ]
    assert [m.game.game_id for m in report.matched] == ["2026_03_HOU_IND"]


def test_match_cfb_fixture_by_full_school_names():
    feed = parse_feed(json.loads((FIXTURES / "cfb_kalshi_feed.json").read_text()))
    report = match_games(feed.games, _markets("cfb"),
                         {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
                         load_aliases("cfb"))
    assert {m.game.home: m.suffix for m in report.matched} == {"Stanford": "26SEP26GTSTAN", "Temple": "26SEP25ARMYTEM"}


def test_placeholder_kickoff_times_match_the_adjacent_kalshi_date():
    """ESPN lists TBD late kickoffs as 03:59Z (23:59 ET the day before); Kalshi dates the event by the
    real kickoff. The same two teams one day apart is the same game, so +-1 day is accepted and reported."""
    feed = parse_feed(json.loads((FIXTURES / "cfb_kalshi_feed.json").read_text()))
    stanford = next(g for g in feed.games if g.home == "Stanford")
    moved = stanford.__class__(**{**stanford.__dict__, "start_utc": datetime(2026, 9, 26, 3, 59, tzinfo=timezone.utc)})
    report = match_games([moved], _markets("cfb"),
                         {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
                         load_aliases("cfb"))
    assert [(m.suffix, m.date_shift_days) for m in report.matched] == [("26SEP26GTSTAN", 1)]

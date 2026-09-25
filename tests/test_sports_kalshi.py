import json
from pathlib import Path

import pytest

from tradehub.sports.kalshi import SportsKalshi, parse_sports_market, team_code

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
OPEN = json.loads((FIXTURES / "nfl_open_markets.json").read_text())


def test_parse_winner_market():
    raw = next(m for m in OPEN["KXNFLGAME"] if m["ticker"] == "KXNFLGAME-26SEP27LARDEN-LAR")
    sm = parse_sports_market(raw)
    assert sm.market.series_ticker == "KXNFLGAME"
    assert sm.suffix == "LAR"
    assert team_code(sm) == "LAR"
    assert sm.quote.yes_bid is not None and sm.quote.yes_ask is not None
    assert sm.volume > 0


def test_parse_spread_and_total_suffixes():
    spread = parse_sports_market(next(m for m in OPEN["KXNFLSPREAD"] if m["ticker"].endswith("-IND8")))
    total = parse_sports_market(OPEN["KXNFLTOTAL"][0])
    assert (spread.suffix, team_code(spread), spread.market.floor_strike) == ("IND8", "IND", 7.5)
    assert total.market.strike_type == "greater" and team_code(total) is None


def test_open_markets_pages_through_the_public_api():
    pages = {None: {"markets": OPEN["KXNFLGAME"][:2], "cursor": "c1"}, "c1": {"markets": OPEN["KXNFLGAME"][2:], "cursor": ""}}
    seen = []

    def get_json(url, params):
        seen.append((url, params.get("series_ticker"), params.get("status")))
        return pages[params.get("cursor")]

    markets = SportsKalshi(get_json=get_json).open_markets("KXNFLGAME")
    assert len(markets) == len(OPEN["KXNFLGAME"])
    assert seen[0] == ("https://api.elections.kalshi.com/trade-api/v2/markets", "KXNFLGAME", "open")


@pytest.mark.parametrize("suffix,expected", [("HOU10", "HOU"), ("M-OH", "M-OH"), ("67", None)])
def test_team_code_strips_the_strike(suffix, expected):
    sm = parse_sports_market(dict(OPEN["KXNFLTOTAL"][0], ticker=f"KXNFLTOTAL-26SEP27HOUIND-{suffix}"))
    assert team_code(sm) == expected

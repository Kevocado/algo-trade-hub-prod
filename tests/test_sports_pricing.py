import json
from pathlib import Path

import pytest

from tradehub.markets import prob_in_interval
from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.mapping import load_aliases, match_games
from tradehub.sports.pricing import home_oriented, price_market

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
SERIES = {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}


@pytest.fixture
def hou_ind():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    raw = json.loads((FIXTURES / "nfl_open_markets.json").read_text())
    markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}
    report = match_games(feed.games, markets, SERIES, load_aliases("nfl"))
    return next(m for m in report.matched if m.game.game_id == "2026_03_HOU_IND")


def _market(mg, kind, suffix):
    return next(m for m in mg.markets[kind] if m.suffix == suffix)


def test_winner_prices_are_the_predictors_own_probability(hou_ind):
    g = hou_ind.game
    assert price_market("winner", _market(hou_ind, "winner", "IND"), hou_ind) == pytest.approx(g.p_home)
    assert price_market("winner", _market(hou_ind, "winner", "HOU"), hou_ind) == pytest.approx(1 - g.p_home)


def test_spread_uses_the_margin_distribution_at_kalshis_strike(hou_ind):
    g = hou_ind.game   # IND home, margin_mu about -7.1
    ind8 = price_market("spread", _market(hou_ind, "spread", "IND8"), hou_ind)
    hou7 = price_market("spread", _market(hou_ind, "spread", "HOU7"), hou_ind)
    assert ind8 == pytest.approx(prob_in_interval(g.margin_mu, g.sigma, (7.5, float("inf"))))
    assert hou7 == pytest.approx(prob_in_interval(g.margin_mu, g.sigma, (float("-inf"), -6.5)))
    assert hou7 > 0.5 > ind8


def test_total_uses_the_total_distribution(hou_ind):
    g = hou_ind.game
    over46 = price_market("total", _market(hou_ind, "total", "46"), hou_ind)
    assert over46 == pytest.approx(prob_in_interval(g.total_mu, g.total_sigma, (45.5, float("inf"))))


def test_no_distribution_means_no_price(hou_ind):
    game = hou_ind.game.__class__(**{**hou_ind.game.__dict__, "sigma": None, "total_sigma": None})
    mg = hou_ind.__class__(**{**hou_ind.__dict__, "game": game})
    assert price_market("spread", _market(mg, "spread", "IND8"), mg) is None
    assert price_market("total", _market(mg, "total", "46"), mg) is None
    assert price_market("winner", _market(mg, "winner", "IND"), mg) == pytest.approx(game.p_home)


def test_home_oriented_flips_away_team_markets(hou_ind):
    assert home_oriented("winner", _market(hou_ind, "winner", "HOU"), hou_ind, 0.7) == pytest.approx(0.3)
    assert home_oriented("spread", _market(hou_ind, "spread", "IND8"), hou_ind, 0.2) == pytest.approx(0.2)
    assert home_oriented("total", _market(hou_ind, "total", "46"), hou_ind, 0.6) == pytest.approx(0.6)

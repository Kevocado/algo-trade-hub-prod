import json
import math

import pytest
from test_journal_sports import FIXTURES, PRE_GAME, _final, _scan

from tradehub.journal.forecasters.sports import (
    SportsFeedForecaster,
    SportsMarketImplied,
    SportsSnapshot,
    build_sports,
    one_rung,
)
from tradehub.markets import prob_in_interval


def _row(ticker, game, kind, our, mid):
    return {"market_ticker": ticker, "our_prob": our, "market_prob": mid,
            "raw_payload": {"kind": kind, "game_id": game}}


def test_one_rung_picks_the_strike_the_market_prices_nearest_a_coin_flip():
    rows = [_row("S-HOU7", "g1", "spread", 0.9, 0.20), _row("S-IND3", "g1", "spread", 0.1, 0.46),
            _row("S-HOU3", "g1", "spread", 0.2, 0.55), _row("T-43", "g1", "total", 0.5, 0.80),
            _row("T-46", "g1", "total", 0.5, 0.52), _row("S-X", "g2", "spread", 0.5, 0.50)]
    assert set(one_rung(rows, "spread")) == {"S-IND3", "S-X"}   # |.46-.5| beats |.55-.5|
    assert set(one_rung(rows, "total")) == {"T-46"}


def test_one_rung_never_looks_at_the_forecast_and_breaks_ties_by_ticker():
    a = [_row("S-B", "g", "spread", 0.01, 0.40), _row("S-A", "g", "spread", 0.99, 0.60)]
    b = [_row("S-B", "g", "spread", 0.99, 0.40), _row("S-A", "g", "spread", 0.01, 0.60)]
    assert set(one_rung(a, "spread")) == set(one_rung(b, "spread")) == {"S-A"}
    assert one_rung([_row("S-A", "g", "spread", 0.5, None)], "spread") == {}   # no mid, no baseline, no target


def _spread(sport="nfl", kind="spread"):
    snap = SportsSnapshot(sport, _scan(sport))
    return SportsFeedForecaster(snap, _final("yes"), kind=kind), SportsMarketImplied(snap, _final("yes"), kind=kind)


def test_names_and_families_keep_each_kind_on_its_own_scorecard():
    feed, implied = _spread()
    assert (feed.name, feed.family) == ("sports_nfl_spread", "sports_nfl_spread")
    assert implied.name == "kalshi_implied_sports_nfl_spread"
    winner = SportsFeedForecaster(SportsSnapshot("nfl", _scan("nfl")), _final("yes"))
    assert (winner.name, winner.family) == ("sports_nfl", "sports_nfl")   # existing keys unchanged


def test_a_spread_forecast_is_the_probability_of_the_side_the_market_names_never_sign_flipped():
    feed, _ = _spread()
    entries = feed.targets(PRE_GAME)
    assert entries and all(e.target.startswith("kalshi:KXNFLSPREAD-") for e in entries)
    game = next(g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]
                if g["game_id"].endswith("HOU_IND") or g["game_id"].endswith("IND_HOU"))
    seen = set()
    for entry in entries:
        f = feed.forecast(entry, PRE_GAME)
        p = f.payload
        assert p["kind"] == "spread" and p["team"] in (p["home"], p["away"]) and p["strike"] is not None
        mu, sigma = game["margin_mu"], game["sigma"]   # margin = home minus away
        want = (prob_in_interval(mu, sigma, (p["strike"], math.inf)) if p["team"] == p["home"]
                else prob_in_interval(mu, sigma, (-math.inf, -p["strike"])))
        assert f.probability == pytest.approx(want, abs=1e-4)
        assert p["yes_means"] == f"{p['team']} wins by more than {p['strike']:g}"
        seen.add(p["team"] == p["home"])
    assert seen   # at least one side exercised


def test_a_total_forecast_is_the_probability_of_the_over():
    feed, implied = _spread(kind="total")
    entry = feed.targets(PRE_GAME)[0]
    f, m = feed.forecast(entry, PRE_GAME), implied.forecast(entry, PRE_GAME)
    game = next(g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]
                if g["game_id"] == f.payload["game_id"])
    assert f.probability == pytest.approx(prob_in_interval(game["total_mu"], game["total_sigma"],
                                                           (f.payload["strike"], math.inf)), abs=1e-4)
    assert f.payload["yes_means"] == f"total points above {f.payload['strike']:g}"
    assert m.probability == pytest.approx(f.market_prob) and m.market_prob == f.market_prob   # same contract, the mid


def test_the_registry_adds_spread_and_total_for_both_sports_without_touching_the_winner_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for sport in ("nfl", "cfb"):
        for kind in ("spread", "total"):
            assert (f"sports_{sport}_{kind}", "feed-v1") in keys
            assert (f"kalshi_implied_sports_{sport}_{kind}", "v1") in keys
    assert ("sports_nfl", "feed-v1") in keys and len(set(keys)) == len(keys) and len(build_sports()) == 12


def test_every_spread_rung_the_scan_records_carries_an_orientation_that_reproduces_its_probability():
    run = _scan("nfl")(PRE_GAME)
    game = {g["game_id"]: g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]}
    rows = [r for r in run.predictions if r["raw_payload"]["kind"] == "spread"]
    assert {r["raw_payload"]["team"] == r["raw_payload"]["home"] for r in rows} == {True, False}  # both sides present
    for r in rows:
        p, g = r["raw_payload"], game[r["raw_payload"]["game_id"]]
        want = (prob_in_interval(g["margin_mu"], g["sigma"], (p["strike"], math.inf)) if p["team"] == p["home"]
                else prob_in_interval(g["margin_mu"], g["sigma"], (-math.inf, -p["strike"])))
        assert r["our_prob"] == pytest.approx(want, abs=1e-4), r["market_ticker"]

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tradehub.edges import EdgeSuggestion, Quote
from tradehub.markets import parse_market
from tradehub.sports.candidates import bucket_for, check_candidate
from tradehub.sports.feed import FeedGame
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
PARAMS = {"max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000, "min_hours_to_start": 1,
          "max_hours_to_start": 72, "calibration_max_dev": 0.10, "calibration_min_n": 20}


def _buckets(n=30, mean=0.35, hit=0.33):
    return [{"lo": i / 10, "hi": (i + 1) / 10, "n": n if i == 3 else 0,
             "mean_prob": mean if i == 3 else None, "hit_rate": hit if i == 3 else None} for i in range(10)]


GAME = FeedGame(sport="nfl", game_id="2026_03_HOU_IND", home="IND", away="HOU",
                start_utc=NOW + timedelta(hours=29), p_home=0.35, margin_mu=-4.0, sigma=13.0, total_mu=45.0,
                total_sigma=12.0, model_version="ridge@t", snapshotted_at=NOW - timedelta(hours=10))
MARKET = SportsMarket(
    market=parse_market({"ticker": "KXNFLGAME-26SEP27HOUIND-IND", "event_ticker": "KXNFLGAME-26SEP27HOUIND",
                         "strike_type": "structured", "open_time": "2026-09-15T16:00:00Z",
                         "close_time": "2026-09-29T17:00:00Z", "title": "IND wins"}),
    quote=Quote(yes_bid=0.27, yes_ask=0.28, yes_bid_size=5000.0, yes_ask_size=4000.0), volume=50000.0, suffix="IND")
MG = MatchedGame(game=GAME, home_code="IND", away_code="HOU", suffix="26SEP27HOUIND", markets={})
EDGE = EdgeSuggestion("KXNFLGAME-26SEP27HOUIND-IND", "yes", 0.27, True, 7.5, 0.35, 0.275)


def test_a_liquid_calibrated_market_is_a_candidate():
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _buckets()}, PARAMS, NOW)
    assert check.ok is True and check.reasons == ()
    assert check.bucket["lo"] == 0.3


def test_every_failed_rule_is_named():
    thin = replace(MARKET, quote=Quote(yes_bid=0.20, yes_ask=0.28, yes_bid_size=5.0, yes_ask_size=4000.0), volume=10.0)
    late = replace(MG, game=replace(GAME, start_utc=NOW + timedelta(minutes=30)))
    check = check_candidate("winner", thin, late, EDGE, {"winner": _buckets(mean=0.35, hit=0.20)}, PARAMS, NOW)
    assert check.ok is False
    assert check.reasons == ("wide_quote", "thin_book", "low_volume", "starts_too_soon", "calibration_off")


def test_too_few_graded_snapshots_is_not_calibrated():
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _buckets(n=5)}, PARAMS, NOW)
    assert check.reasons == ("calibration_insufficient",)


def test_away_team_market_uses_the_home_oriented_bucket():
    away = replace(MARKET, suffix="HOU")
    edge = replace(EDGE, our_prob=0.65)       # P(HOU wins) = 1 - 0.35
    check = check_candidate("winner", away, MG, edge, {"winner": _buckets()}, PARAMS, NOW)
    assert check.ok and check.bucket["lo"] == 0.3


def test_bucket_for_edges():
    buckets = _buckets()
    assert bucket_for(buckets, 1.0)["lo"] == 0.9
    assert bucket_for(buckets, 0.3)["lo"] == 0.3
    assert bucket_for([], 0.5) is None

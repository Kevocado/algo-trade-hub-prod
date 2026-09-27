"""The per-bucket `calibration_off` test is gone, and that is the point.

Ruled 2026-09-27. The reasoning is arithmetic rather than taste:

`check_candidate` ran two tests off one parameter, and the second was not meaningful at the first
one's sample size. With `calibration_min_n: 20` and `calibration_max_dev: 10pp`, a *correctly
calibrated* bucket trips the comparison about 37% of the time -- n=20 gives an 11.2pp standard error,
so 10pp is 0.89 SD. It is a coin flip wearing a threshold, and it was rejecting weather on a bucket
with n=23 and z=1.42.

Nor could it be tuned into shape, because the two demands are mutually exclusive: admission wants a
*small* `min_n` (the aggregate `n_buckets x min_n` must stay under the reviewer's 100), while a 10pp
comparison needs n >= 97 to fire on under 5% of well-calibrated buckets. At 10 buckets that asks for
`min_n <= 10` and `min_n >= 97` simultaneously.

So it is dropped rather than tuned, and the reviewer's keep-or-drop at n >= 100 makes the quality
call instead. `calibration_insufficient` STAYS: admitting an edge still needs a bucket, and a bucket
with n < 20 is an absence rather than a measurement.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tradehub.edges import EdgeSuggestion, Quote
from tradehub.markets import parse_market
from tradehub.sports.candidates import check_candidate
from tradehub.sports.feed import FeedGame
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
PARAMS = {"max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000, "min_hours_to_start": 1,
          "max_hours_to_start": 72, "calibration_max_dev": 0.10, "calibration_min_n": 20}

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


def _bucket(n, mean, hit):
    """One populated bucket in the 0.3-0.4 band, where the 0.27 edge's own probability lands."""
    return [{"lo": i / 10, "hi": (i + 1) / 10, "n": n if i == 3 else 0,
             "mean_prob": mean if i == 3 else None, "hit_rate": hit if i == 3 else None} for i in range(10)]


# 12.2pp apart, which is the miss that rejected weather (n=23, z=1.42).
MISALIGNED = _bucket(23, 0.35, 0.4722)
WELL_ALIGNED = _bucket(23, 0.35, 0.36)
THIN = _bucket(5, 0.35, 0.36)


def _check(buckets, market=None, mg=None):
    return check_candidate("winner", market or MARKET, mg or MG, EDGE,
                           {"winner": buckets}, PARAMS, NOW)


def test_a_misaligned_bucket_no_longer_rejects_the_edge():
    """The regression: this is the bucket that produced `calibration_off`."""
    check = _check(MISALIGNED)

    assert "calibration_off" not in check.reasons
    assert check.ok is True, check.reasons


def test_a_well_aligned_bucket_behaves_identically_to_a_misaligned_one():
    """If these two differ at all, the filter is still measuring something other than admission."""
    assert _check(MISALIGNED).reasons == _check(WELL_ALIGNED).reasons
    assert _check(MISALIGNED).ok == _check(WELL_ALIGNED).ok


def test_a_wildly_misaligned_bucket_still_does_not_reject():
    """Even a 40pp miss is not a rejection reason now. The reviewer judges quality; the admission
    filter judges tradeability and whether any settled history exists at all."""
    wild = _bucket(400, 0.35, 0.75)

    check = _check(wild)

    assert "calibration_off" not in check.reasons
    assert check.ok is True, check.reasons


def test_a_thin_bucket_still_rejects_as_insufficient():
    """The check that STAYS. n < min_n is a real absence, not a noisy comparison."""
    check = _check(THIN)

    assert "calibration_insufficient" in check.reasons
    assert check.ok is False


def test_a_bucket_with_no_mean_probability_still_rejects():
    empty = _bucket(30, 0.35, 0.36)
    empty[3]["mean_prob"] = None

    check = _check(empty)

    assert "calibration_insufficient" in check.reasons


def test_no_calibration_at_all_still_rejects():
    check = check_candidate("winner", MARKET, MG, EDGE, {}, PARAMS, NOW)

    assert "calibration_insufficient" in check.reasons


def test_the_other_rules_are_untouched():
    """Dropping one test must not have disturbed the rest."""
    thin = replace(MARKET, quote=Quote(yes_bid=0.20, yes_ask=0.28, yes_bid_size=5.0, yes_ask_size=4000.0),
                   volume=10.0)
    soon = replace(MG, game=replace(GAME, start_utc=NOW + timedelta(minutes=30)))
    wide = replace(MARKET, quote=Quote(yes_bid=0.10, yes_ask=0.40, yes_bid_size=5000.0, yes_ask_size=4000.0))

    # 0.20/0.28 is an 8-cent spread, so this fixture trips wide_quote as well as size and volume.
    assert _check(WELL_ALIGNED, market=thin).reasons == ("wide_quote", "thin_book", "low_volume")
    assert "starts_too_soon" in _check(WELL_ALIGNED, mg=soon).reasons
    assert "starts_too_late" in _check(
        WELL_ALIGNED, mg=replace(MG, game=replace(GAME, start_utc=NOW + timedelta(hours=200)))
    ).reasons
    assert "wide_quote" in _check(WELL_ALIGNED, market=wide).reasons
    assert "calibration_off" not in _check(WELL_ALIGNED, market=wide).reasons
    # 30 minutes out is inside min_hours_to_start=1, so `soon` trips starts_too_soon; the default
    # game is 29h out and clean.
    assert _check(WELL_ALIGNED, mg=soon).reasons == ("starts_too_soon",)
    assert _check(WELL_ALIGNED).ok is True

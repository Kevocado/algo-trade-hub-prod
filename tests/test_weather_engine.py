import math

import pytest

from tradehub.engines.weather import DEFAULT_ERROR, MIN_SIGMA, ErrorModel, fit_error_model, weather_prob
from tradehub.markets import prob_in_interval, parse_market

BASE = {"ticker": "KXHIGHNY-26SEP25-T74", "event_ticker": "KXHIGHNY-26SEP25", "strike_type": "greater",
        "floor_strike": 74, "cap_strike": None, "open_time": "2026-09-23T14:00:00Z",
        "close_time": "2026-09-26T05:00:00Z", "title": "NYC high"}


def test_fit_error_model_defaults_below_min_pairs():
    assert fit_error_model([(70.0, 71.0)] * 5) == DEFAULT_ERROR


def test_fit_error_model_bias_and_sigma():
    pairs = [(70.0, 71.0), (70.0, 73.0)] * 10  # errors +1/+3 -> bias 2, sample std ~1.026
    model = fit_error_model(pairs)
    assert model.bias == pytest.approx(2.0)
    assert model.sigma == pytest.approx(math.sqrt(sum((e - 2.0) ** 2 for e in [1.0, 3.0] * 10) / 19))


def test_fit_error_model_sigma_floor():
    assert fit_error_model([(70.0, 70.0)] * 30).sigma == pytest.approx(MIN_SIGMA)


def test_weather_prob_matches_normal_model():
    m = parse_market(BASE)
    p = weather_prob(m, [75.0, 75.0, 75.0], ErrorModel(bias=0.0, sigma=2.0))
    assert p == pytest.approx(prob_in_interval(75.0, 2.0, (74.5, math.inf)))


def test_weather_prob_bias_shifts_without_adding_model_spread_twice():
    m = parse_market(BASE)
    base = weather_prob(m, [75.0, 75.0], ErrorModel(0.0, 2.0))
    assert weather_prob(m, [75.0, 75.0], ErrorModel(2.0, 2.0)) > base
    # The fitted error sigma is the complete uncertainty term; forecast-model
    # disagreement must not be added to it a second time here.
    assert weather_prob(m, [70.0, 80.0], ErrorModel(0.0, 2.0)) == pytest.approx(base)


def test_weather_probability_is_clamped_away_from_zero_and_one():
    m = parse_market(BASE)
    assert weather_prob(m, [1000.0], ErrorModel(0.0, 1.0)) == pytest.approx(1.0 - 1e-4)
    assert weather_prob(m, [-1000.0], ErrorModel(0.0, 1.0)) == pytest.approx(1e-4)


def test_weather_prob_requires_highs():
    with pytest.raises(ValueError):
        weather_prob(parse_market(BASE), [], DEFAULT_ERROR)


def test_calibration_uses_each_past_days_own_decision_lead():
    """Past-day pairs must use the forecast its own decision would have seen (lead 2 at D-1 23:30
    LST, since lead 1 publishes ~D 05:00), not the lead-1 value that is only known later."""
    from datetime import date, datetime, timedelta, timezone

    from tradehub.backtest.pit import Observation
    from tradehub.data.weather import WEATHER_CITIES, weather_decision_time
    from tradehub.engines.weather import walk_forward_error_model

    city = WEATHER_CITIES["KXHIGHNY"]
    as_of = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    actuals, forecasts = [], {}
    for i in range(25):
        day = date(2026, 7, 1) + timedelta(days=i)
        decided = weather_decision_time(day, 1, city)
        actuals.append(Observation(f"KXHIGHNY-{day.strftime('%y%b%d').upper()}", 80.0,
                                   decided + timedelta(days=1)))
        forecasts[day] = [
            # lead 2: published before the day's decision; its error is exactly +2 or -2
            Observation(f"om:gfs:high:{day}:lead2", 78.0 if i % 2 else 82.0, decided - timedelta(hours=10)),
            # lead 1: published after the day's decision (but well before as_of); error 0
            Observation(f"om:gfs:high:{day}:lead1", 80.0, decided + timedelta(hours=6)),
        ]
    model = walk_forward_error_model(
        actuals, forecasts, as_of, decision_time_for=lambda d: weather_decision_time(d, 1, city),
    )
    assert model.sigma > 1.9  # lead-2 errors (+-2); lead-1 pairs would give sigma MIN_SIGMA

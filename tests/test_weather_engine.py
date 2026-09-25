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

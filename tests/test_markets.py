import math
from datetime import date, datetime, timezone

import pytest

from tradehub.markets import PROBABILITY_EPSILON, event_date, market_url, parse_market, prob_in_interval, yes_interval

RAW = {
    "ticker": "KXHIGHNY-26SEP25-T74", "event_ticker": "KXHIGHNY-26SEP25", "strike_type": "greater",
    "floor_strike": 74, "cap_strike": None, "open_time": "2026-09-23T14:00:00Z",
    "close_time": "2026-09-26T05:00:00Z", "title": "Highest temperature in NYC",
}


def test_parse_market():
    m = parse_market(RAW)
    assert m.series_ticker == "KXHIGHNY"
    assert m.floor_strike == 74.0 and m.cap_strike is None
    assert m.close_time == datetime(2026, 9, 26, 5, tzinfo=timezone.utc)
    assert m.open_time == datetime(2026, 9, 23, 14, tzinfo=timezone.utc)


def test_event_date():
    assert event_date("KXHIGHNY-26SEP25") == date(2026, 9, 25)
    assert event_date("KXAAAGASD-26JUL01") == date(2026, 7, 1)


def test_yes_interval_weather_integer_strikes():
    greater = parse_market(RAW)
    less = parse_market(dict(RAW, strike_type="less", floor_strike=None, cap_strike=67))
    between = parse_market(dict(RAW, strike_type="between", floor_strike=87, cap_strike=88))
    assert yes_interval(greater, 1.0) == (74.5, math.inf)     # YES iff high >= 75
    assert yes_interval(less, 1.0) == (-math.inf, 66.5)       # YES iff high <= 66
    assert yes_interval(between, 1.0) == (86.5, 88.5)         # YES iff high in {87, 88}


def test_yes_interval_gas_strictly_greater():
    gas = parse_market(dict(RAW, ticker="KXAAAGASD-26SEP25-4.5200", event_ticker="KXAAAGASD-26SEP25", floor_strike=4.52))
    lo, hi = yes_interval(gas, 0.0001)
    assert lo == pytest.approx(4.52005) and hi == math.inf


def test_yes_interval_rejects_unknown_strike_type():
    with pytest.raises(ValueError):
        yes_interval(parse_market(dict(RAW, strike_type="custom")), 1.0)


def test_prob_in_interval():
    assert prob_in_interval(70.0, 2.0, (70.0, math.inf)) == pytest.approx(0.5)
    assert prob_in_interval(70.0, 2.0, (-math.inf, math.inf)) == pytest.approx(1.0 - PROBABILITY_EPSILON)
    assert prob_in_interval(70.0, 2.0, (72.0, math.inf)) == pytest.approx(0.158655, abs=1e-5)
    with pytest.raises(ValueError):
        prob_in_interval(70.0, 0.0, (70.0, math.inf))


def test_market_url():
    assert market_url(parse_market(RAW)) == "https://kalshi.com/markets/kxhighny"

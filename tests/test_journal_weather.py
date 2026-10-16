from datetime import UTC, date, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.acis import parse_station
from tradehub.data.ensemble import day_members, parse_members
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.weather import (
    KERNEL_SIGMA,
    STATIONS,
    WeatherClimatology,
    WeatherEnsemble,
    WeatherInputs,
    build_weather,
    climatology_prob,
    ensemble_prob,
    station_for,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_market

CLOSE = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)  # end of the Oct 9 climate day in NYC (local standard time)
NOW = CLOSE - timedelta(hours=20)


def _lm(ticker, strike_type, floor=None, cap=None, bid=0.40, ask=0.44, close=CLOSE):
    event = ticker.rsplit("-", 1)[0]
    raw = {"ticker": ticker, "event_ticker": event, "strike_type": strike_type, "floor_strike": floor,
           "cap_strike": cap, "open_time": "2026-10-07T14:00:00Z", "close_time": close.isoformat(), "title": ticker}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _hourly(start, temps, rains):
    """An Open-Meteo ensemble payload: one row per hour from `start`, one column per member."""
    n = len(temps[0])
    hourly = {"time": [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]}
    for i, (t, r) in enumerate(zip(temps, rains, strict=True)):
        suffix = "ncep_gefs05" if i == 0 else f"member{i:02d}_ncep_gefs05"
        hourly[f"temperature_2m_{suffix}"] = t
        hourly[f"precipitation_{suffix}"] = r
    return {"hourly": hourly}


ACIS = {"meta": {"ll": [-73.96925, 40.77898], "name": "NY CITY CENTRAL PARK"},
        "data": [["2025-10-09", "70", "55", "0.00"], ["2024-10-09", "80", "60", "T"], ["2023-10-09", "72", "M", "0.20"],
                 ["2022-10-12", "65", "50", "0.05"], ["2022-10-30", "99", "90", "1.00"]]}


def test_acis_parses_trace_as_zero_and_missing_as_none():
    lat, lon, days = parse_station(ACIS)
    assert (lat, lon) == (40.77898, -73.96925)
    assert days[date(2024, 10, 9)] == {"high": 80.0, "low": 60.0, "rain": 0.0}   # trace settles as NO rain
    assert days[date(2023, 10, 9)]["low"] is None


def test_ensemble_members_are_the_climate_day_max_min_and_total():
    start = CLOSE - timedelta(hours=26)
    # hours 0-2 end at or before the climate day starts, 3-26 are inside it (the last ends at close), 27 is after
    temps = [[60.0] * 3 + [70.0] * 24 + [99.0], [61.0] * 3 + [75.0] * 12 + [65.0] * 12 + [99.0]]
    rains = [[0.5] * 3 + [0.0] * 25, [0.0] * 3 + [0.1] * 3 + [0.0] * 22]
    members = parse_members(_hourly(start, temps, rains))
    assert len(members) == 2
    assert day_members(members, CLOSE, "high") == [70.0, 75.0]        # the hours either side are outside
    assert day_members(members, CLOSE, "low") == [70.0, 65.0]
    assert day_members(members, CLOSE, "rain") == [0.0, pytest.approx(0.3)]


def test_a_temperature_probability_is_the_kernel_smoothed_share_of_members_in_the_yes_interval():
    m = _lm("KXHIGHNY-26OCT09-T76", "greater", floor=76).market   # YES = high of 77 or more
    assert ensemble_prob(m, "high", [90.0] * 10) > 0.99
    assert ensemble_prob(m, "high", [60.0] * 10) < 0.01
    assert ensemble_prob(m, "high", [76.5] * 10) == pytest.approx(0.5)  # on the boundary
    assert KERNEL_SIGMA == 2.0


def test_rain_is_the_share_of_members_with_measurable_rain_never_exactly_zero_or_one():
    m = _lm("KXRAIN-26OCT09-NYC", "greater", floor=0).market
    assert ensemble_prob(m, "rain", [0.0] * 9 + [0.2]) == pytest.approx((1 + 0.5) / (10 + 1))
    assert 0 < ensemble_prob(m, "rain", [0.0] * 10) < 0.05
    assert 0.95 < ensemble_prob(m, "rain", [1.0] * 10) < 1
    assert ensemble_prob(m, "rain", [0.004] * 10) < 0.05   # below a reportable 0.01 inch


def test_climatology_is_the_same_week_in_past_years_never_using_the_target_year():
    _lat, _lon, days = parse_station(ACIS)
    m = _lm("KXHIGHNY-26OCT09-T76", "greater", floor=76).market
    # 2025-10-09 (70), 2024-10-09 (80), 2023-10-09 (72), 2022-10-12 (65) are within +/-7 days; Oct 30 is not.
    assert climatology_prob(m, "high", days, date(2026, 10, 9)) == pytest.approx((1 + 0.5) / (4 + 1))
    rain = _lm("KXRAIN-26OCT09-NYC", "greater", floor=0).market
    assert climatology_prob(rain, "rain", days, date(2026, 10, 9)) == pytest.approx((2 + 0.5) / (4 + 1))
    assert climatology_prob(m, "high", {date(2026, 10, 8): {"high": 99.0}}, date(2026, 10, 9)) is None


def test_the_station_comes_from_the_series_and_the_rain_suffix():
    assert station_for(_lm("KXHIGHNY-26OCT09-T76", "greater", 76).market) == "NYC"
    assert station_for(_lm("KXRAIN-26OCT09-PHIL", "greater", 0).market) == "PHL"
    assert station_for(_lm("KXRAIN-26OCT09-TTN", "greater", 0).market) == "TTN"
    assert station_for(_lm("KXHIGHZZZ-26OCT09-T1", "greater", 1).market) is None
    assert STATIONS["KXLOWTAUS"] == ("low", "AUS")


class Inputs(WeatherInputs):
    def __init__(self, ensemble, acis):
        super().__init__(get_json=None)
        self.ens, self.acis, self.calls = ensemble, acis, []

    def _fetch_ensemble(self, lat, lon):
        self.calls.append(("ens", lat, lon))
        return self.ens

    def _fetch_station(self, sid, start, end):
        self.calls.append(("acis", sid))
        return self.acis


def _inputs():
    start = CLOSE - timedelta(hours=24)
    temps = [[80.0] * 24 for _ in range(10)]
    rains = [[0.0] * 24 for _ in range(10)]
    return Inputs(_hourly(start, temps, rains), ACIS)


def _final(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_the_forecaster_freezes_inside_24h_records_how_it_was_made_and_never_refetches_in_a_run():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76),
                     _lm("KXHIGHNY-26OCT11-T76", "greater", floor=76, close=CLOSE + timedelta(days=2))])
    inputs = _inputs()
    fc = WeatherEnsemble("high", live, _final("yes"), inputs)
    [entry] = fc.targets(NOW)                       # the Oct 11 market is not inside 24h yet
    assert (fc.name, fc.version, fc.family) == ("weather_high", "ens-v1", "weather_high")
    f = fc.forecast(entry, NOW)
    # every member at 80F against YES = 77 or more: Phi((80 - 76.5) / 2) = 0.96
    assert f.probability == pytest.approx(0.9599, abs=1e-4) and f.market_prob == pytest.approx(0.42)
    assert f.payload["station"] == "NYC" and f.payload["n_members"] == 10 and f.payload["kernel_sigma"] == 2.0
    assert f.payload["yes_bid"] == 0.40 and f.payload["ensemble_mean"] == pytest.approx(80.0)
    fc.forecast(entry, NOW)
    assert [c[0] for c in inputs.calls] == ["acis", "ens"]   # coordinates once, ensemble once


def test_a_market_already_part_way_through_its_climate_day_is_not_forecast():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    for cls in (WeatherEnsemble, WeatherClimatology):
        fc = cls("high", live, _final("yes"), _inputs())
        assert fc.targets(CLOSE - timedelta(hours=21)) and fc.targets(CLOSE - timedelta(hours=19)) == []


def test_no_members_in_the_window_is_a_gap_not_a_guess():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    inputs = Inputs({"hourly": {"time": []}}, ACIS)
    fc = WeatherEnsemble("high", live, _final("yes"), inputs)
    assert fc.forecast(fc.targets(NOW)[0], NOW) is None


def test_end_to_end_the_model_its_climatology_and_the_market_are_scored_on_the_same_contracts():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76), _lm("KXRAIN-26OCT09-NYC", "greater", floor=0)])
    fcs = build_weather(live, _final("no"), _inputs())
    run_journal(db, fcs, clock[0])
    clock[0] = CLOSE + timedelta(hours=1)
    out = run_journal(db, fcs, clock[0])
    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    for kind in ("high", "rain"):
        assert cards[f"weather_{kind}"]["n_settled"] == 1 and cards[f"weather_{kind}"]["baseline"] == "market"
        assert cards[f"baseline_climatology_weather_{kind}"]["n_settled"] == 1
        assert cards[f"kalshi_implied_weather_{kind}"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_every_weather_family_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for kind in ("high", "low", "rain"):
        for name in (f"weather_{kind}", f"kalshi_implied_weather_{kind}", f"baseline_climatology_weather_{kind}"):
            assert any(k[0] == name for k in keys), name
    assert len(set(keys)) == len(keys)
    assert not any(k[0].startswith("weather_") and k[0].endswith("_cautious") for k in keys)
    assert isinstance(WeatherClimatology, type)

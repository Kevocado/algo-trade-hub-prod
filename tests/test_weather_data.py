from datetime import date, datetime, timezone

import pytest

from tradehub.data.weather import (
    FORECAST_URL,
    WEATHER_CITIES,
    WEATHER_MODELS,
    historical_forecast_highs,
    historical_forecast_highs_range,
    live_forecast_highs,
)

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)


class Recorder:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.payload(params) if callable(self.payload) else self.payload


def test_cities_use_settlement_stations_and_standard_time_days():
    assert WEATHER_CITIES["KXHIGHNY"].cli_station == "CLINYC"
    assert WEATHER_CITIES["KXHIGHCHI"].cli_station == "CLIMDW"   # Midway, not O'Hare
    assert WEATHER_CITIES["KXHIGHMIA"].cli_station == "CLIMIA"
    assert WEATHER_CITIES["KXHIGHNY"].lst_timezone == "Etc/GMT+5"
    assert WEATHER_CITIES["KXHIGHCHI"].lst_timezone == "Etc/GMT+6"


def test_live_forecast_highs_one_per_model_max_over_lst_day():
    hourly = {"time": [f"2026-09-25T{h:02d}:00" for h in range(24)],
              "temperature_2m_gfs_seamless": [60.0] * 23 + [71.0],
              "temperature_2m_ecmwf_ifs025": [None] * 12 + [70.0] * 12,
              "temperature_2m_icon_seamless": [None] * 24}
    rec = Recorder({"hourly": hourly})
    obs = live_forecast_highs(WEATHER_CITIES["KXHIGHNY"], date(2026, 9, 25), NOW, get_json=rec)
    url, params = rec.calls[0]
    assert url == FORECAST_URL
    assert params["models"] == ",".join(WEATHER_MODELS)
    assert params["timezone"] == "Etc/GMT+5" and params["temperature_unit"] == "fahrenheit"
    assert params["start_date"] == params["end_date"] == "2026-09-25"
    assert [(o.name, o.value) for o in obs] == [
        ("openmeteo:gfs_seamless:high:2026-09-25:live", 71.0),
        ("openmeteo:ecmwf_ifs025:high:2026-09-25:live", 70.0),
    ]
    assert all(o.published_at == NOW for o in obs)


def test_historical_forecast_highs_range_makes_one_request_per_model():
    start = date(2026, 7, 1)
    end = date(2026, 7, 2)
    variables = tuple(f"temperature_2m_previous_day{lead}" for lead in range(1, 8))

    def payload(params):
        times = [
            f"{day}T{hour:02d}:00"
            for day in (start.isoformat(), end.isoformat())
            for hour in range(24)
        ]
        return {
            "hourly": {
                "time": times,
                **{variable: [70.0] * len(times) for variable in params["hourly"].split(",")},
            }
        }

    rec = Recorder(payload)
    observations = historical_forecast_highs_range(
        WEATHER_CITIES["KXHIGHNY"],
        start,
        end,
        get_json=rec,
    )

    assert len(rec.calls) == len(WEATHER_MODELS) == 3
    assert {params["models"] for _, params in rec.calls} == set(WEATHER_MODELS)
    assert all(params["start_date"] == "2026-07-01" and params["end_date"] == "2026-07-02" for _, params in rec.calls)
    assert all(params["hourly"] == ",".join(variables) for _, params in rec.calls)
    assert len(observations) == len(WEATHER_MODELS) * 2 * 7
    assert {observation.name.split(":")[3] for observation in observations} == {"2026-07-01", "2026-07-02"}


def test_historical_forecast_highs_skips_models_without_data():
    def payload(params):
        var = params["hourly"]
        values = [None] * 24 if params["models"] == "icon_seamless" else [80.0] * 24
        return {"hourly": {"time": [], var: values}}

    obs = historical_forecast_highs(WEATHER_CITIES["KXHIGHCHI"], date(2026, 7, 24), 1, get_json=Recorder(payload))
    assert [o.name.split(":")[1] for o in obs] == ["gfs_seamless", "ecmwf_ifs025"]
    assert all(o.value == pytest.approx(80.0) for o in obs)

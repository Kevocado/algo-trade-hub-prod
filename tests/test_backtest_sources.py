from datetime import date, datetime, timedelta, timezone

import pytest

from tradehub.backtest.sources.alfred import FRED_OBSERVATIONS_URL, AlfredSource
from tradehub.backtest.sources.open_meteo import PREVIOUS_RUNS_URL, forecast_daily_high


class Recorder:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.payload


def test_alfred_queries_previous_day_vintage_and_lags_publication():
    rec = Recorder({"observations": [
        {"realtime_start": "2026-09-04", "realtime_end": "2026-09-04", "date": "2026-08-01", "value": "159123"},
        {"realtime_start": "2026-08-07", "realtime_end": "2026-09-04", "date": "2026-07-01", "value": "158900"},
    ]})
    obs = AlfredSource("PAYEMS", "k", get_json=rec).latest_as_of(datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc))
    url, params = rec.calls[0]
    assert url == FRED_OBSERVATIONS_URL
    assert params["realtime_start"] == params["realtime_end"] == "2026-09-04"
    assert params["sort_order"] == "desc" and params["file_type"] == "json" and params["series_id"] == "PAYEMS"
    assert obs.value == pytest.approx(159123.0)
    assert obs.name == "PAYEMS:2026-08-01"
    assert obs.published_at == datetime(2026, 9, 5, tzinfo=timezone.utc)
    assert obs.published_at <= datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def test_alfred_skips_missing_values_and_handles_empty():
    rec = Recorder({"observations": [
        {"realtime_start": "2026-09-04", "realtime_end": "2026-09-04", "date": "2026-08-01", "value": "."},
        {"realtime_start": "2026-08-07", "realtime_end": "2026-09-04", "date": "2026-07-01", "value": "158900"},
    ]})
    obs = AlfredSource("PAYEMS", "k", get_json=rec).latest_as_of(datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert obs.value == pytest.approx(158900.0)
    assert obs.published_at == datetime(2026, 8, 8, tzinfo=timezone.utc)
    assert AlfredSource("X", "k", get_json=Recorder({"observations": []})).latest_as_of(
        datetime(2026, 9, 5, tzinfo=timezone.utc)) is None


def test_forecast_daily_high_max_of_previous_day_series_and_issue_time():
    hourly = [65.6, 65.3, 64.5] + [70.0] * 18 + [84.4, 80.0, 75.0]
    rec = Recorder({"hourly": {"time": [f"2026-07-24T{h:02d}:00" for h in range(24)],
                               "temperature_2m_previous_day1": hourly}})
    obs = forecast_daily_high(latitude=40.7794, longitude=-73.9692, target_date=date(2026, 7, 24), lead_days=1,
                              model="ncep_gfs_seamless", timezone_name="America/New_York", get_json=rec)
    url, params = rec.calls[0]
    assert url == PREVIOUS_RUNS_URL
    assert params["hourly"] == "temperature_2m_previous_day1"
    assert params["start_date"] == params["end_date"] == "2026-07-24"
    assert params["temperature_unit"] == "fahrenheit" and params["models"] == "ncep_gfs_seamless"
    assert obs.value == pytest.approx(84.4)
    # 23:00 EDT on Jul 24 minus 1 day and the default 6h availability lag
    # is Jul 23 21:00 UTC.
    assert obs.published_at == datetime(2026, 7, 23, 21, 0, tzinfo=timezone.utc)
    assert obs.name == "openmeteo:ncep_gfs_seamless:high:2026-07-24:lead1"


def test_forecast_daily_high_applies_default_lag_across_spring_forward():
    rec = Recorder({"hourly": {
        "time": [f"2026-03-08T{h:02d}:00" for h in range(24)],
        "temperature_2m_previous_day1": [70.0] * 24,
    }})

    obs = forecast_daily_high(
        latitude=40.7,
        longitude=-73.9,
        target_date=date(2026, 3, 8),
        lead_days=1,
        model="ncep_gfs_seamless",
        timezone_name="America/New_York",
        get_json=rec,
    )

    assert obs.published_at == datetime(2026, 3, 7, 21, 0, tzinfo=timezone.utc)


def test_forecast_daily_high_accepts_a_model_specific_availability_lag():
    rec = Recorder({"hourly": {
        "time": [f"2026-07-24T{h:02d}:00" for h in range(24)],
        "temperature_2m_previous_day1": [70.0] * 24,
    }})

    obs = forecast_daily_high(
        latitude=40.7,
        longitude=-73.9,
        target_date=date(2026, 7, 24),
        lead_days=1,
        model="slow_model",
        timezone_name="America/New_York",
        availability_lag=timedelta(hours=12),
        get_json=rec,
    )

    assert obs.published_at == datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)


    kwargs = dict(latitude=40.7, longitude=-73.9, target_date=date(2026, 7, 24),
                  model="ncep_gfs_seamless", timezone_name="America/New_York")
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=0, get_json=Recorder({}), **kwargs)
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=8, get_json=Recorder({}), **kwargs)
    empty = Recorder({"hourly": {"time": [], "temperature_2m_previous_day2": [None, None]}})
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=2, get_json=empty, **kwargs)


def test_forecast_daily_high_subtracts_lead_days_in_utc_across_fall_back():
    rec = Recorder({"hourly": {
        "time": [f"2026-11-01T{h:02d}:00" for h in range(24)],
        "temperature_2m_previous_day1": [70.0] * 24,
    }})
    obs = forecast_daily_high(
        latitude=40.7,
        longitude=-73.9,
        target_date=date(2026, 11, 1),
        lead_days=1,
        model="ncep_gfs_seamless",
        timezone_name="America/New_York",
        get_json=rec,
    )
    assert obs.published_at == datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)

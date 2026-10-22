"""Tests for the weather API: city grid of today's forecast vs Kalshi vs climatology.

Read from journal tables via the API. No new forecasting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _weather_target(day, strike="T76") -> str:
    """A journal target as it really looks: 'kalshi:KXHIGHNY-26OCT18-T76' (series, event day, strike).

    The endpoint decides 'today' from the Eastern-time clock, so fixtures are built from the real now in
    that zone and never from a hardcoded date.
    """
    return f"kalshi:KXHIGHNY-{day.strftime('%y%b%d').upper()}-{strike}"


_NOW_ET = datetime.now(ZoneInfo("America/New_York"))
# Relative to the real clock: never a hardcoded date, or the test goes stale the day it runs.
_TODAY = _weather_target(_NOW_ET)
_YESTERDAY = _weather_target(_NOW_ET - timedelta(days=1))
_LAST_MONTH = _weather_target(_NOW_ET - timedelta(days=40))


def _client(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def teardown_function(_fn):
    app.dependency_overrides.clear()


def _weather_forecast(forecaster, target, prob, market_prob=None, **over):
    row = {
        "forecaster": forecaster,
        "forecaster_version": "v1",
        "target": target,
        "probability": prob,
        "market_prob": market_prob,
        "frozen_at": T0.isoformat(),
        "source_hash": "h",
        "payload": {},
        "rebuilt": False,
    }
    row.update(over)
    return row


def test_weather_api_returns_today_and_settled():
    db = FakeJournalDB(lambda: T0)
    today = _TODAY
    yesterday = _YESTERDAY
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", today, 0.65, 0.60),
        _weather_forecast("baseline_climatology_weather_high", today, 0.55, 0.60),
        _weather_forecast("kalshi_implied_weather_high", today, 0.60, 0.60),
        _weather_forecast("weather_high", yesterday, 0.70, 0.72),
        _weather_forecast("baseline_climatology_weather_high", yesterday, 0.60, 0.72),
        _weather_forecast("kalshi_implied_weather_high", yesterday, 0.72, 0.72),
    ]
    db.tables["journal_settlements"] += [
        {"target": yesterday, "outcome": 1, "realized_value": 92.0, "source": "kalshi", "settled_at": T0.isoformat()},
    ]
    body = _client(db).get("/api/weather").json()
    assert "today" in body
    assert "settled" in body
    assert len(body["today"]) > 0
    assert len(body["settled"]) > 0


def test_weather_api_today_has_all_three_probabilities():
    db = FakeJournalDB(lambda: T0)
    today = _TODAY
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", today, 0.65, 0.60),
        _weather_forecast("baseline_climatology_weather_high", today, 0.55, 0.60),
        _weather_forecast("kalshi_implied_weather_high", today, 0.60, 0.60),
    ]
    body = _client(db).get("/api/weather").json()
    city = body["today"][0]
    assert "ensemble" in city
    assert "kalshi" in city
    assert "climatology" in city
    assert city["ensemble"] == 0.65
    assert city["kalshi"] == 0.60
    assert city["climatology"] == 0.55


def test_weather_api_settled_includes_outcome():
    db = FakeJournalDB(lambda: T0)
    yesterday = _YESTERDAY
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", yesterday, 0.70, 0.72),
        _weather_forecast("baseline_climatology_weather_high", yesterday, 0.60, 0.72),
        _weather_forecast("kalshi_implied_weather_high", yesterday, 0.72, 0.72),
    ]
    db.tables["journal_settlements"] += [
        {"target": yesterday, "outcome": 1, "realized_value": 92.0, "source": "kalshi", "settled_at": T0.isoformat()},
    ]
    body = _client(db).get("/api/weather").json()
    assert len(body["settled"]) == 1
    row = body["settled"][0]
    assert row["outcome"] == 1
    assert row["ensemble"] == 0.70
    assert row["kalshi"] == 0.72


def test_weather_api_excludes_non_weather_forecasters():
    db = FakeJournalDB(lambda: T0)
    today = _TODAY
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", today, 0.65, 0.60),
        _weather_forecast("gas", today, 0.50, 0.50),  # not weather
        _weather_forecast("sports_nfl", today, 0.55, 0.55),  # not weather
    ]
    body = _client(db).get("/api/weather").json()
    # Only weather forecasters should appear
    forecasters = {f for row in body["today"] for f in [row.get("forecaster", "")]}
    assert "gas" not in forecasters
    assert "sports_nfl" not in forecasters


def test_weather_api_503_without_supabase():
    app.dependency_overrides[get_supabase] = lambda: None
    assert TestClient(app).get("/api/weather").status_code == 503


def test_weather_api_empty_tables_returns_empty_lists():
    db = FakeJournalDB(lambda: T0)
    body = _client(db).get("/api/weather").json()
    assert body["today"] == []
    assert body["settled"] == []


def test_the_date_is_the_events_day_not_the_strike_and_history_is_newest_first_across_months():
    """Regression: the day was read from the LAST ticker part, so 'T75' was the date and months sorted as text."""
    db = FakeJournalDB(lambda: T0)
    for target in (_YESTERDAY, _LAST_MONTH):
        db.tables["journal_forecasts"].append(_weather_forecast("kalshi_implied_weather_high", target, 0.5, 0.5))
        db.tables["journal_settlements"].append(
            {"target": target, "outcome": 1, "realized_value": 70.0, "source": "kalshi", "settled_at": T0.isoformat()})
    settled = _client(db).get("/api/weather").json()["settled"]
    assert [r["target"] for r in settled] == [_YESTERDAY, _LAST_MONTH]
    assert all(len(r["date"]) == 10 and r["date"][4] == "-" for r in settled)        # an ISO date, never 'T76'
    assert settled[0]["date"] > settled[1]["date"]


def test_a_past_contract_with_no_settlement_is_not_history():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_forecasts"].append(_weather_forecast("weather_high", _YESTERDAY, 0.7, 0.7))
    body = _client(db).get("/api/weather").json()
    assert body["settled"] == [] and body["today"] == []

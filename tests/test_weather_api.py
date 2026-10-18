"""Tests for the weather API: city grid of today's forecast vs Kalshi vs climatology.

Read from journal tables via the API. No new forecasting.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


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
    today = "T-KXHIGHNY-26OCT18"
    yesterday = "T-KXHIGHNY-26OCT17"
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
    today = "T-KXHIGHNY-26OCT18"
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
    yesterday = "T-KXHIGHNY-26OCT17"
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
    today = "T-KXHIGHNY-26OCT18"
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

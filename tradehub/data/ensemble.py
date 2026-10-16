"""Ensemble weather forecasts from Open-Meteo (NOAA GEFS 0.5 and ECMWF IFS 0.25), keyless.

One request returns every member's hourly temperature and precipitation, in UTC. A member's value for a
Kalshi market is its max, min or total over the market's climate day, which is the 24 hours ending at the
market's close (Kalshi closes each daily weather market at midnight local standard time).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.backtest.http import default_get_json

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODELS = ("gfs05", "ecmwf_ifs025")
CLIMATE_DAY = timedelta(hours=24)
Members = list[tuple[list[datetime], list[float | None], list[float | None]]]


def fetch_ensemble(lat: float, lon: float, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    return get_json(ENSEMBLE_URL, {"latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation",
                                   "models": ",".join(MODELS), "temperature_unit": "fahrenheit",
                                   "precipitation_unit": "inch", "timezone": "GMT", "forecast_days": 3})


def parse_members(payload: dict[str, Any]) -> Members:
    """[(hours, temperatures, precipitation)] per member, control runs included."""
    hourly = payload.get("hourly") or {}
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly.get("time") or []]
    out = []
    for key in hourly:
        if key.startswith("temperature_2m_"):
            rain = hourly.get("precipitation_" + key.removeprefix("temperature_2m_")) or [None] * len(times)
            out.append((times, hourly[key], rain))
    return out


def day_members(members: Members, close: datetime, kind: str) -> list[float]:
    """Each member's high, low or rain total over (close - 24h, close]; members with no data drop out."""
    start = close - CLIMATE_DAY
    out = []
    for times, temps, rains in members:
        series = rains if kind == "rain" else temps
        values = [v for t, v in zip(times, series, strict=True) if start < t <= close and v is not None]
        if not values:
            continue
        out.append(sum(values) if kind == "rain" else max(values) if kind == "high" else min(values))
    return out

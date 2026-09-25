"""Open-Meteo Previous Runs: weather forecasts exactly as issued N days ahead."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
DEFAULT_AVAILABILITY_LAG = timedelta(hours=6)
# Callers can override a model's lag for a particular source/config; unknown
# models use the conservative default above.
MODEL_AVAILABILITY_LAGS: dict[str, timedelta] = {}


def forecast_daily_high(
    *,
    latitude: float,
    longitude: float,
    target_date: date,
    lead_days: int,
    model: str,
    timezone_name: str,
    availability_lag: timedelta | None = None,
    get_json: Callable[..., Any] = default_get_json,
) -> Observation:
    """Max hourly 2 m temperature (°F) for target_date as forecast `lead_days` earlier."""
    if not 1 <= lead_days <= 7:
        raise ValueError(f"lead_days must be 1..7, got {lead_days}")
    variable = f"temperature_2m_previous_day{lead_days}"
    day = target_date.isoformat()
    data = get_json(PREVIOUS_RUNS_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": variable,
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": timezone_name,
        "start_date": day,
        "end_date": day,
    })
    values = [v for v in (data.get("hourly") or {}).get(variable) or [] if v is not None]
    if not values:
        raise ValueError(f"no {variable} values for {day} ({model})")
    last_hour_local = datetime.combine(target_date, time(23, 0), ZoneInfo(timezone_name))
    lag = availability_lag if availability_lag is not None else MODEL_AVAILABILITY_LAGS.get(model, DEFAULT_AVAILABILITY_LAG)
    issued = last_hour_local.astimezone(timezone.utc) - timedelta(days=lead_days) + lag
    return Observation(name=f"openmeteo:{model}:high:{day}:lead{lead_days}", value=max(values), published_at=issued)

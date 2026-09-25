"""Open-Meteo Previous Runs: weather forecasts exactly as issued N days ahead."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from itertools import zip_longest
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
DEFAULT_AVAILABILITY_LAG = timedelta(hours=6)
# Callers can override a model's lag for a particular source/config; unknown
# models use the conservative default above.
MODEL_AVAILABILITY_LAGS: dict[str, timedelta] = {}


def forecast_daily_highs_range(
    *,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    model: str,
    timezone_name: str,
    lead_days: tuple[int, ...] = tuple(range(1, 8)),
    availability_lag: timedelta | None = None,
    get_json: Callable[..., Any] = default_get_json,
) -> list[Observation]:
    """Fetch all requested previous-run leads for a date range in one request."""
    if end_date < start_date:
        raise ValueError(f"end_date must not precede start_date, got {end_date!r} < {start_date!r}")
    if not lead_days or any(not 1 <= lead <= 7 for lead in lead_days):
        raise ValueError(f"lead_days must contain values in 1..7, got {lead_days!r}")
    variables = tuple(f"temperature_2m_previous_day{lead}" for lead in lead_days)
    data = get_json(PREVIOUS_RUNS_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(variables),
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": timezone_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    })
    hourly = data.get("hourly") or {}
    timestamps = hourly.get("time") or []
    lag = availability_lag if availability_lag is not None else MODEL_AVAILABILITY_LAGS.get(model, DEFAULT_AVAILABILITY_LAG)
    out: list[Observation] = []
    for lead, variable in zip(lead_days, variables, strict=True):
        by_day: dict[date, list[float]] = {}
        for stamp, value in zip_longest(timestamps, hourly.get(variable) or (), fillvalue=None):
            if stamp is None or value is None:
                continue
            try:
                target = date.fromisoformat(str(stamp)[:10])
            except ValueError:
                continue
            if start_date <= target <= end_date:
                by_day.setdefault(target, []).append(float(value))
        for target, values in sorted(by_day.items()):
            last_hour_local = datetime.combine(target, time(23, 0), ZoneInfo(timezone_name))
            issued = last_hour_local.astimezone(timezone.utc) - timedelta(days=lead) + lag
            out.append(Observation(
                name=f"openmeteo:{model}:high:{target.isoformat()}:lead{lead}",
                value=max(values),
                published_at=issued,
            ))
    return sorted(out, key=lambda observation: (observation.name.split(":")[3], observation.published_at, observation.name))


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

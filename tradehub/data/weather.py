"""Weather inputs for Kalshi daily-high markets, aggregated over the NWS climate day (LST)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation
from tradehub.backtest.sources.open_meteo import forecast_daily_high, forecast_daily_highs_range

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_MODELS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")
WEATHER_LEAD_DAYS = tuple(range(1, 8))


def forecast_target_date(observation: Observation) -> date:
    """Extract YYYY-MM-DD from an Open-Meteo observation name."""
    parts = observation.name.split(":")
    if len(parts) < 5 or parts[2] != "high":
        raise ValueError(f"not an Open-Meteo high observation: {observation.name!r}")
    return date.fromisoformat(parts[3])


@dataclass(frozen=True)
class City:
    name: str
    cli_station: str
    latitude: float
    longitude: float
    lst_timezone: str


# Settlement stations come from each market's rules text; climate days run in
# local STANDARD time all year, hence fixed-offset Etc/GMT+N zones.
WEATHER_CITIES: dict[str, City] = {
    "KXHIGHNY": City("New York City (Central Park)", "CLINYC", 40.7789, -73.9692, "Etc/GMT+5"),
    "KXHIGHCHI": City("Chicago (Midway)", "CLIMDW", 41.7868, -87.7522, "Etc/GMT+6"),
    "KXHIGHMIA": City("Miami (International)", "CLIMIA", 25.7906, -80.3164, "Etc/GMT+5"),
}


def live_forecast_highs(
    city: City, target_date: date, now: datetime, get_json: Callable[..., Any] = default_get_json
) -> list[Observation]:
    day = target_date.isoformat()
    data = get_json(FORECAST_URL, {
        "latitude": city.latitude,
        "longitude": city.longitude,
        "hourly": "temperature_2m",
        "models": ",".join(WEATHER_MODELS),
        "temperature_unit": "fahrenheit",
        "timezone": city.lst_timezone,
        "start_date": day,
        "end_date": day,
    })
    hourly = data.get("hourly") or {}
    out = []
    for model in WEATHER_MODELS:
        values = [v for v in hourly.get(f"temperature_2m_{model}") or [] if v is not None]
        if values:
            out.append(Observation(f"openmeteo:{model}:high:{day}:live", max(values), now))
    return out


def historical_forecast_highs_range(
    city: City,
    start_date: date,
    end_date: date,
    get_json: Callable[..., Any] = default_get_json,
) -> list[Observation]:
    """Fetch all seven leads for the date range with one request per model."""
    out: list[Observation] = []
    for model in WEATHER_MODELS:
        try:
            out.extend(forecast_daily_highs_range(
                latitude=city.latitude,
                longitude=city.longitude,
                start_date=start_date,
                end_date=end_date,
                model=model,
                timezone_name=city.lst_timezone,
                lead_days=WEATHER_LEAD_DAYS,
                get_json=get_json,
            ))
        except ValueError:
            continue
    return out


def historical_forecast_highs(
    city: City, target_date: date, lead_days: int, get_json: Callable[..., Any] = default_get_json
) -> list[Observation]:
    out = []
    for model in WEATHER_MODELS:
        try:
            out.append(forecast_daily_high(latitude=city.latitude, longitude=city.longitude, target_date=target_date,
                                           lead_days=lead_days, model=model, timezone_name=city.lst_timezone,
                                           get_json=get_json))
        except ValueError:
            continue
    return out

"""Daily station observations from NOAA's Applied Climate Information System (ACIS), keyless.

Kalshi's daily weather markets name an NWS climate station (CLINYC, CLIAUS, ...) and settle on its reported
high, low or precipitation. ACIS serves the same station's daily record back decades, plus its coordinates.
Checked 2026-10-08 against 3,996 settled Kalshi markets (highs, lows, rain): ACIS reproduced every outcome,
with a trace of rain ("T") settling NO, so trace is read as 0.0.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

ACIS_URL = "https://data.rcc-acis.org/StnData"
FIELDS = ("high", "low", "rain")


def _value(raw: str) -> float | None:
    if raw == "T":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):  # "M" (missing), "S"/"A" flags
        return None


def parse_station(payload: dict[str, Any]) -> tuple[float, float, dict[date, dict[str, float | None]]]:
    """(latitude, longitude, {day: {high, low, rain}}) from an ACIS StnData response."""
    lon, lat = payload["meta"]["ll"]
    days = {date.fromisoformat(row[0]): {f: _value(v) for f, v in zip(FIELDS, row[1:], strict=True)}
            for row in payload.get("data") or []}
    return lat, lon, days


def fetch_station(sid: str, start: date, end: date, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    return get_json(ACIS_URL, {"sid": sid, "sdate": start.isoformat(), "edate": end.isoformat(),
                               "elems": "maxt,mint,pcpn", "output": "json"})

"""ERCOT daily peak demand: the operating day's highest hourly TOTAL system load, keyless.

Kalshi's ``KXTXERCOTPEAKD`` settles on "the highest value in the TOTAL column of the first complete
'Actual System Load by Forecast Zone' report published by ERCOT for the operating day". That report is
one keyless HTML table per operating day (columns ``Oper Day | Hour Ending | NORTH | SOUTH | WEST |
HOUSTON | TOTAL``). The yearly ``Native_Load_<year>.zip`` archive is a *different* series -- eight
weather zones, not these four forecast zones -- and does not reproduce Kalshi's settlements, so it is
not used. Checked 2026-10-16 against the 49 settled KXTXERCOTPEAKD events: the TOTAL-column peak
reproduced the settled rung on every one.

The daily reports begin at 2024-05-07 (older dates 404). Fetched peaks are cached on disk keyed by
operating day, so the ~600-day backfill happens once and only new days are fetched after that.

Weather features use Open-Meteo (keyless). Live uses its forecast API; the historical replay uses the
"previous runs" forecast archive, which is the same model's forecast for past days, so the training and
live features come from the same kind of source. The ensemble API cannot serve a multi-year past (its
allowed window is about three months), so it is not used here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from tradehub.backtest.http import default_get_json, default_get_text

ZONE_URL = "https://www.ercot.com/content/cdr/html/{ymd}_actual_loads_of_forecast_zones.html"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORY_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FIRST_DAY = date(2024, 5, 7)
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "tradehub" / "ercot"
CACHE_ENV = "TRADEHUB_ERCOT_CACHE_DIR"

# Metro areas mapped to the four ERCOT forecast zones (HOUSTON->Houston, NORTH->Dallas,
# SOUTH->San Antonio, WEST->Austin), with approximate metro population in millions as the weight.
CITIES: dict[str, tuple[float, float, float]] = {
    "Dallas": (32.777, -96.797, 7.6),
    "Houston": (29.760, -95.369, 7.3),
    "Austin": (30.267, -97.743, 2.4),
    "San Antonio": (29.424, -98.494, 2.6),
}


def zone_url(day: date) -> str:
    return ZONE_URL.format(ymd=day.strftime("%Y%m%d"))


class _TableRows(HTMLParser):
    """Every ``<tr>`` as a list of its cell texts. Stdlib only: `pandas.read_html` needs lxml."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_daily_peak(html: str) -> float | None:
    """The day's peak hourly TOTAL MW, or None when the table is absent or unreadable."""
    parser = _TableRows()
    parser.feed(html or "")
    header = next((row for row in parser.rows if any(c.upper() == "TOTAL" for c in row)), None)
    if header is None:
        return None
    column = [c.upper() for c in header].index("TOTAL")
    peaks: list[float] = []
    for row in parser.rows:
        if len(row) <= column:
            continue
        try:
            peaks.append(float(row[column]))
        except ValueError:
            continue
    return max(peaks) if peaks else None


def cache_dir_from_env() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR)


def _days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def load_peaks(first: date, last: date, *, get_text: Callable[..., Any] = default_get_text,
               cache_dir: Path | None = None, today: date | None = None) -> dict[date, float]:
    """{operating day: peak MW} over [first, last], fetching only days not already cached.

    Only a COMPLETE operating day is trusted. ERCOT serves a partial report for the day in progress
    (at 13:00 CDT it held 12 of 24 rows), and the report for day D is published the following morning,
    so days on or after `today` are neither fetched nor kept from the cache. A day whose report is not
    published yet (404) is skipped. Only successful parses are cached, so a transient failure leaves a
    hole to retry, not a silent gap.
    """
    cache = Path(cache_dir) if cache_dir is not None else cache_dir_from_env()
    path = cache / "peaks.json"
    peaks: dict[date, float] = {}
    if path.exists():
        try:
            peaks = {date.fromisoformat(k): float(v) for k, v in json.loads(path.read_text()).items()}
        except (ValueError, OSError, TypeError):
            peaks = {}
    today = today or datetime.now(UTC).date()
    last_full = today - timedelta(days=1)
    complete = {d: v for d, v in peaks.items() if d <= last_full}
    changed = len(complete) != len(peaks)
    peaks = complete
    for day in _days(max(first, FIRST_DAY), min(last, last_full)):
        if day in peaks:
            continue
        try:
            html = get_text(zone_url(day))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        peak = parse_daily_peak(html)
        if peak is not None:
            peaks[day] = peak
            changed = True
    if changed:
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({d.isoformat(): v for d, v in sorted(peaks.items())}))
    return {d: v for d, v in peaks.items() if first <= d <= last}


def weighted_temp(by_city: dict[str, float]) -> float:
    """The population-weighted temperature over whichever cities are present."""
    known = {name: t for name, t in by_city.items() if name in CITIES}
    weight = sum(CITIES[name][2] for name in known)
    if not weight:
        raise ValueError("no known cities in temperature map")
    return sum(t * CITIES[name][2] for name, t in known.items()) / weight


def _city_daily(url: str, lat: float, lon: float, params: dict[str, Any],
                get_json: Callable[..., Any]) -> dict[date, float]:
    payload = get_json(url, {"latitude": lat, "longitude": lon, "daily": "temperature_2m_max",
                             "temperature_unit": "fahrenheit", "timezone": "America/Chicago", **params})
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    values = daily.get("temperature_2m_max") or []
    return {date.fromisoformat(t): v for t, v in zip(times, values, strict=True) if v is not None}


def _merge_cities(per_city: dict[str, dict[date, float]]) -> dict[date, float]:
    days = sorted({d for values in per_city.values() for d in values})
    return {d: weighted_temp({name: values[d] for name, values in per_city.items() if d in values})
            for d in days}


def fetch_forecast_temps(*, get_json: Callable[..., Any] = default_get_json,
                         forecast_days: int = 3) -> dict[date, float]:
    """Population-weighted daily max temp for the next few days, from the live forecast."""
    return _merge_cities({name: _city_daily(FORECAST_URL, lat, lon, {"forecast_days": forecast_days}, get_json)
                          for name, (lat, lon, _w) in CITIES.items()})


def fetch_historical_temps(first: date, last: date, *, get_json: Callable[..., Any] = default_get_json
                           ) -> dict[date, float]:
    """Population-weighted daily max temp over [first, last] from the archived forecast runs."""
    params = {"start_date": first.isoformat(), "end_date": last.isoformat()}
    return _merge_cities({name: _city_daily(HISTORY_URL, lat, lon, params, get_json)
                          for name, (lat, lon, _w) in CITIES.items()})

"""Cleveland Fed inflation nowcast (keyless) as point-in-time observations.

nowcast_month.json is a FusionCharts payload: one entry per target month
(chart.subcaption "2026-8"), daily "MM/DD" category labels without a year,
plus "vline" categories (release markers) that carry no data point. Each
series' data list lines up with the non-vline categories.

Timing rules (the publish time of each daily value is not documented):
- a nowcast labelled day L is treated as known from 00:00 ET on L+1;
- the "Actual" value sits on the BLS release day R and is known from 08:30 ET on R.

Revision policy: the "Actual" series is the BLS FIRST print for the month and the
chart does not restate history, so an old month keeps its first print even after BLS
revises the published number. The engine's error model is calibrated against first
prints, so this is load-bearing; `tests/test_cleveland_fed.py` pins it on December
2021, a month BLS revised by more than 0.2pp. The series is the seasonally adjusted
month-over-month percent change, not NSA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

NOWCAST_MONTH_URL = (
    "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en"
)
ET = ZoneInfo("America/New_York")
BLS_RELEASE_TIME = time(8, 30)
SERIES = {
    "headline": ("CPI", "CPI Inflation", "Actual CPI Inflation"),
    "core": ("CORECPI", "Core CPI Inflation", "Actual Core CPI Inflation"),
}


@dataclass(frozen=True)
class MonthNowcast:
    month: date
    path: tuple[Observation, ...]
    actual: Observation | None


def _label_date(label: str, month: date) -> date:
    mm, dd = (int(part) for part in label.split("/"))
    year = month.year if mm >= month.month else month.year + 1
    return date(year, mm, dd)


def _value(point: dict[str, Any]) -> float | None:
    raw = point.get("value")
    return None if raw in (None, "") else float(raw)


def parse_nowcast_month(payload: list[dict[str, Any]], kind: str = "headline") -> dict[date, MonthNowcast]:
    prefix, nowcast_name, actual_name = SERIES[kind]
    out: dict[date, MonthNowcast] = {}
    for entry in payload:
        year, mon = (int(part) for part in entry["chart"]["subcaption"].split("-"))
        month = date(year, mon, 1)
        labels = [c["label"] for c in entry["categories"][0]["category"] if not c.get("vline")]
        series = {s["seriesname"]: s["data"] for s in entry["dataset"]}
        tag = f"{prefix}:{month:%Y-%m}"
        path = []
        for label, point in zip(labels, series.get(nowcast_name, [])):
            value = _value(point)
            if value is None:
                continue
            day = _label_date(label, month)
            known = datetime.combine(day + timedelta(days=1), time(0), ET).astimezone(timezone.utc)
            path.append(Observation(f"{tag}@{day.isoformat()}", value, known))
        actual = None
        for label, point in zip(labels, series.get(actual_name, [])):
            value = _value(point)
            if value is not None:
                released = datetime.combine(_label_date(label, month), BLS_RELEASE_TIME, ET).astimezone(timezone.utc)
                actual = Observation(f"{tag}:actual", value, released)
                break
        out[month] = MonthNowcast(month, tuple(sorted(path, key=lambda o: o.published_at)), actual)
    return out


def fetch_nowcast_history(
    kind: str = "headline", get_json: Callable[..., Any] = default_get_json
) -> dict[date, MonthNowcast]:
    return parse_nowcast_month(get_json(NOWCAST_MONTH_URL), kind)

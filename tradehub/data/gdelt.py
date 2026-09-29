"""GDELT DOC 2.1 average news tone, one value per day (keyless; optional sentiment component).

GDELT computes the tone itself (`mode=timelinetone`), so no sentiment lexicon ships on the VPS. The
DOC API covers a rolling ~3 months and allows one request every 5 seconds; the meter makes one call
per daily freeze.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MARKET_QUERY = '"stock market" sourcelang:english'


def parse_tone_timeline(payload: dict[str, Any]) -> dict[date, float]:
    out: dict[date, float] = {}
    for series in payload.get("timeline") or []:
        if series.get("series") != "Average Tone":
            continue
        for point in series.get("data") or []:
            stamp = point["date"]  # "20260705T000000Z"
            out[date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))] = float(point["value"])
    return out


def fetch_market_tone(get_json: Callable[..., Any] = default_get_json) -> dict[date, float]:
    params = {"query": MARKET_QUERY, "mode": "timelinetone", "timespan": "3m", "format": "json"}
    return parse_tone_timeline(get_json(GDELT_DOC_URL, params))

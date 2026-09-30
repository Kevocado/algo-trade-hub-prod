"""Daily raw closes from Yahoo's chart JSON (keyless; the endpoint yfinance already uses).

Used for gold (the GLD ETF, see `forecasters/daily_direction.py`). Raw `close`, never `adjclose`: the
settlement is the price that printed, and adjusted history is restated after distributions.
Bars whose exchange-local date is None-priced are dropped, not zero-filled.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
# Yahoo answers 429 to the default python-requests agent and 200 to an honest, descriptive one. The
# journal identifies itself; it does not pretend to be a browser.
USER_AGENT = "tradehub-journal/1.0 (+https://github.com/Kevocado/algo-trade-hub-prod)"
TIMEOUT_SECONDS = 30


def default_get_json(url: str, params: dict | None = None) -> Any:
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def parse_chart(payload: dict[str, Any]) -> tuple[dict[date, float], str]:
    """({exchange-local date: close}, exchange timezone name) from one chart payload."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"no chart result in payload: {str(payload)[:120]}")
    zone_name = result["meta"].get("exchangeTimezoneName") or "UTC"
    zone = ZoneInfo(zone_name)
    closes = result["indicators"]["quote"][0]["close"]
    out: dict[date, float] = {}
    for stamp, close in zip(result.get("timestamp") or [], closes, strict=False):
        if close is not None:
            out[datetime.fromtimestamp(stamp, UTC).astimezone(zone).date()] = float(close)
    return out, zone_name


def fetch_chart(symbol: str, start: date, *, get_json: Callable[..., Any] = default_get_json
                ) -> tuple[dict[date, float], str]:
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
    params = {"period1": period1, "period2": int(datetime.now(UTC).timestamp()) + 86400, "interval": "1d"}
    return parse_chart(get_json(f"{CHART_URL}/{symbol}", params))

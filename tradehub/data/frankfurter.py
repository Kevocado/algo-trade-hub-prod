"""ECB euro foreign-exchange reference rates via Frankfurter (keyless, documented, daily).

The ECB publishes one EUR/USD reference rate per TARGET business day at about 16:00 CET. The wave-2
EUR/USD forecaster settles on this series because Stooq (the spec's source) now serves scripts a
JavaScript proof-of-work wall, which the journal does not bypass.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"


def parse_rates(payload: dict[str, Any], quote: str = "USD") -> dict[date, float]:
    rates = payload.get("rates") or {}
    return {date.fromisoformat(day): float(row[quote]) for day, row in rates.items() if quote in row}


def fetch_eurusd(start: date, *, end: date | None = None,
                 get_json: Callable[..., Any] = default_get_json) -> dict[date, float]:
    window = f"{start.isoformat()}..{end.isoformat() if end else ''}"
    return parse_rates(get_json(f"{FRANKFURTER_URL}/{window}", {"base": "EUR", "symbols": "USD"}))

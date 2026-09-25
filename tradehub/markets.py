"""Kalshi market model and strike geometry (pure)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from tradehub.backtest.kalshi_history import parse_ts


PROBABILITY_EPSILON = 1e-4


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    event_ticker: str
    series_ticker: str
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None
    open_time: datetime
    close_time: datetime
    title: str
    settlement_ts: datetime | None = None


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_market(raw: dict[str, Any]) -> KalshiMarket:
    event = raw["event_ticker"]
    return KalshiMarket(
        ticker=raw["ticker"],
        event_ticker=event,
        series_ticker=event.split("-")[0],
        strike_type=raw["strike_type"],
        floor_strike=_opt_float(raw.get("floor_strike")),
        cap_strike=_opt_float(raw.get("cap_strike")),
        open_time=parse_ts(raw["open_time"]),
        close_time=parse_ts(raw["close_time"]),
        title=raw.get("title", ""),
        settlement_ts=parse_ts(raw["settlement_ts"]) if raw.get("settlement_ts") else None,
    )


def event_date(event_ticker: str) -> date:
    """'KXHIGHNY-26SEP25' -> date(2026, 9, 25)."""
    return datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()


def yes_interval(market: KalshiMarket, resolution: float) -> tuple[float, float]:
    """Continuous interval of the settled value for which the market resolves YES.

    `resolution` is the reporting unit (1.0 °F for highs, $0.0001 for AAA gas),
    so a 'greater than k' market on an integer-reported value is YES above k + 0.5.
    """
    half = resolution / 2.0
    if market.strike_type == "greater":
        return (market.floor_strike + half, math.inf)
    if market.strike_type == "less":
        return (-math.inf, market.cap_strike - half)
    if market.strike_type == "between":
        return (market.floor_strike - half, market.cap_strike + half)
    raise ValueError(f"unsupported strike_type {market.strike_type!r} for {market.ticker}")


def _normal_cdf(x: float, mu: float, sigma: float) -> float:
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))


def prob_in_interval(mu: float, sigma: float, interval: tuple[float, float]) -> float:
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    lo, hi = interval
    probability = _normal_cdf(hi, mu, sigma) - _normal_cdf(lo, mu, sigma)
    return min(1.0 - PROBABILITY_EPSILON, max(PROBABILITY_EPSILON, probability))


def market_url(market: KalshiMarket) -> str:
    return f"https://kalshi.com/markets/{market.series_ticker.lower()}"

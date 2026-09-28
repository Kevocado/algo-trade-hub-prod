"""Kalshi market model and strike geometry (pure)."""

from __future__ import annotations

import math
import re
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


QUOTE_FIELDS = ("yes_bid", "yes_ask", "no_bid", "no_ask")


def _tradeable_cents(value: Any) -> float | None:
    """A price in 0-100 cents, or None when it is not one you could trade at."""
    if value is None or value == "":
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    # Rejects NaN, and the degenerate ends: Kalshi quotes 0.0000/1.0000 rather
    # than omitting the field, and a 0c ask would make `prob - 0` a fake edge.
    return price if 0.0 < price < 100.0 else None


def quote_cents(raw: dict[str, Any]) -> dict[str, float | None]:
    """Top-of-book YES/NO prices in cents (0-100) from a raw Kalshi market dict.

    Kalshi's current API publishes prices as 0-1 dollar *strings* under the
    ``*_dollars`` keys ("0.6200") and no longer emits the legacy cent keys
    ``yes_bid``/``yes_ask``/``no_bid``/``no_ask`` at all. Reading the legacy key
    with a ``0`` default therefore fabricates a 0-cent quote for every market --
    including ones quoting right now -- and downstream that becomes a
    probability-sized "edge" priced at zero. So: read the dollar string and
    rescale, and fall back to a legacy key only when it is genuinely present.

    A missing figure is never a number. Every absent, empty, unparseable or
    degenerate price is reported as None -- never as 0 -- so callers are forced
    to decide what to do about a market they cannot price.
    """
    prices: dict[str, float | None] = {}
    for field in QUOTE_FIELDS:
        dollars_key = f"{field}_dollars"
        if dollars_key in raw:
            try:
                # round() first: 0.29 * 100 == 28.999999999999996, and
                # 0.07 * 100 == 7.000000000000001 in IEEE 754.
                prices[field] = _tradeable_cents(round(float(raw[dollars_key]) * 100.0))
            except (TypeError, ValueError):
                prices[field] = None
        elif field in raw:
            prices[field] = _tradeable_cents(raw[field])  # legacy cents, never rescaled
        else:
            prices[field] = None
    return prices


def event_date(event_ticker: str) -> date:
    """'KXHIGHNY-26SEP25' -> date(2026, 9, 25); 'KXNFLGAME-26OCT01PITCLE' -> date(2026, 10, 1).

    The date is always the first 7 characters after the series; sports events append team codes.
    """
    return datetime.strptime(event_ticker.split("-")[1][:7], "%y%b%d").date()


def event_month(event_ticker: str) -> date:
    """Monthly-release events: 'KXCPI-26AUG' (and legacy 'CPI-22NOV') -> first day of that month.

    Only the first five characters are read: Kalshi has at least one stray suffix ('KXCPICORE-25DECT').
    """
    return datetime.strptime(event_ticker.split("-")[1][:5], "%y%b").date()


def parse_cpi_market(raw: dict[str, Any]) -> KalshiMarket:
    """parse_market for CPI ladders, including legacy 'CPI-*' markets that carry no strike fields.

    Every CPI market is 'more than X%' on the one-decimal BLS value; legacy tickers
    encode X as '-T0.3', or '-TN0.4' for -0.4.
    """
    if raw.get("strike_type") and raw.get("floor_strike") is not None:
        return parse_market(raw)
    suffix = raw["ticker"].rsplit("-", 1)[1]
    if not suffix.startswith("T"):
        raise ValueError(f"cannot infer strike from {raw['ticker']!r}")
    strike = -float(suffix[2:]) if suffix.startswith("TN") else float(suffix[1:])
    return parse_market(dict(raw, strike_type="greater", floor_strike=strike, cap_strike=None))


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


def kalshi_event_url(series_ticker: str, series_title: str, event_ticker: str) -> str:
    """Deep link to one event page: kalshi.com/markets/<series>/<series-title-slug>/<event>."""
    slug = re.sub(r"[^a-z0-9]+", "-", series_title.lower()).strip("-")
    return f"https://kalshi.com/markets/{series_ticker.lower()}/{slug}/{event_ticker.lower()}"

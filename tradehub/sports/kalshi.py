"""Open Kalshi sports markets (public API) with quote, volume and the ticker suffix after the event."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tradehub.backtest.kalshi_history import PAGE_LIMIT, KalshiHistoryClient
from tradehub.data.kalshi_live import quote_from_market_raw
from tradehub.edges import Quote
from tradehub.markets import KalshiMarket, parse_market


@dataclass(frozen=True)
class SportsMarket:
    market: KalshiMarket
    quote: Quote
    volume: float
    suffix: str   # after "<event>-": team code (winner), team code + strike (spread), strike (total)


def parse_sports_market(raw: dict[str, Any]) -> SportsMarket:
    ticker, event = raw["ticker"], raw["event_ticker"]
    return SportsMarket(
        market=parse_market(raw),
        quote=quote_from_market_raw(raw),
        volume=float(raw.get("volume_fp") or 0.0),
        suffix=ticker[len(event) + 1:],
    )


def team_code(sm: SportsMarket) -> str | None:
    """'LAR' -> 'LAR', 'IND8' -> 'IND', '67' (a total) -> None."""
    code = re.sub(r"\d+$", "", sm.suffix)
    return code or None


def parse_markets_tolerantly(
    raws: list[dict[str, Any]], series_ticker: str
) -> tuple[list[SportsMarket], list[dict[str, Any]]]:
    """Parse a page of markets, skipping rows that do not parse.

    Kalshi occasionally returns a row without a ticker or without prices, and
    `parse_sports_market` does `raw["ticker"]` / `raw["event_ticker"]`. One such row used to
    raise and take every other market in the series with it, so a partially broken series
    looked exactly like an empty one. Rejected rows are returned so the caller can report
    them rather than dropping them silently.
    """
    markets: list[SportsMarket] = []
    rejected: list[dict[str, Any]] = []
    for raw in raws:
        try:
            markets.append(parse_sports_market(raw))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            rejected.append({
                "ticker": raw.get("ticker") if isinstance(raw, dict) else None,
                "series": series_ticker,
                "reason": "malformed_market",
                "detail": f"{type(exc).__name__}: {exc}",
            })
    return markets, rejected


class SportsKalshi(KalshiHistoryClient):
    def open_markets(self, series_ticker: str) -> list[SportsMarket]:
        raws = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "open", "limit": PAGE_LIMIT})
        markets, _rejected = parse_markets_tolerantly(raws, series_ticker)
        return markets

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


class SportsKalshi(KalshiHistoryClient):
    def open_markets(self, series_ticker: str) -> list[SportsMarket]:
        raws = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "open", "limit": PAGE_LIMIT})
        return [parse_sports_market(r) for r in raws]

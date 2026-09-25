"""Kalshi public market history (candlesticks, trades) for backtests.

Kalshi splits data into a live tier and a historical tier; anything that
settled before GET /historical/cutoff's `market_settled_ts` must be read
from /historical/*. No auth is needed for market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from tradehub.backtest.http import default_get_json

KALSHI_PUBLIC_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PAGE_LIMIT = 1000


@dataclass(frozen=True)
class Candle:
    end_ts: datetime
    yes_bid: float | None
    yes_ask: float | None
    volume: float


@dataclass(frozen=True)
class Trade:
    created_at: datetime
    yes_price: float
    no_price: float
    count: float
    taker_side: str


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dollars(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_candle(raw: dict[str, Any]) -> Candle:
    return Candle(
        end_ts=datetime.fromtimestamp(int(raw["end_period_ts"]), tz=timezone.utc),
        yes_bid=_dollars((raw.get("yes_bid") or {}).get("close")),
        yes_ask=_dollars((raw.get("yes_ask") or {}).get("close")),
        volume=float(raw.get("volume") or 0.0),
    )


def parse_trade(raw: dict[str, Any]) -> Trade:
    return Trade(
        created_at=parse_ts(raw["created_time"]),
        yes_price=float(raw["yes_price_dollars"]),
        no_price=float(raw["no_price_dollars"]),
        count=float(raw["count_fp"]),
        taker_side=raw["taker_side"],
    )


class KalshiHistoryClient:
    def __init__(self, get_json: Callable[..., Any] = default_get_json, base_url: str = KALSHI_PUBLIC_BASE):
        self._get_json = get_json
        self._base = base_url.rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._get_json(f"{self._base}{path}", params)

    def _paginate(self, path: str, key: str, params: dict) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            data = self._get(path, page_params)
            out.extend(data.get(key) or [])
            cursor = data.get("cursor")
            if not cursor:
                return out

    def cutoff(self) -> datetime:
        return parse_ts(self._get("/historical/cutoff")["market_settled_ts"])

    def settled_markets(self, series_ticker: str) -> list[dict]:
        return self._paginate("/historical/markets", "markets", {"series_ticker": series_ticker, "limit": PAGE_LIMIT})

    def candles(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        period_minutes: int = 60,
        historical: bool = True,
        series_ticker: str | None = None,
    ) -> list[Candle]:
        if historical:
            path = f"/historical/markets/{ticker}/candlesticks"
        else:
            if not series_ticker:
                raise ValueError("live-tier candlesticks require series_ticker")
            path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        params = {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": period_minutes}
        raw = self._get(path, params).get("candlesticks") or []
        return sorted((parse_candle(c) for c in raw), key=lambda c: c.end_ts)

    def trades(self, ticker: str, *, historical: bool = True) -> list[Trade]:
        path = "/historical/trades" if historical else "/markets/trades"
        raw = self._paginate(path, "trades", {"ticker": ticker, "limit": PAGE_LIMIT})
        return sorted((parse_trade(t) for t in raw), key=lambda t: t.created_at)

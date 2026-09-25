"""Kalshi public market history (candlesticks, trades) for backtests.

Kalshi splits data into a live tier and a historical tier; anything that
settled before GET /historical/cutoff's `market_settled_ts` must be read
from /historical/*. No auth is needed for market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
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
    is_block_trade: bool = False


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dollars(value: Any) -> float | None:
    return None if value is None else float(value)


def _candle_field(raw: dict[str, Any], block_name: str, *field_names: str) -> Any:
    block = raw.get(block_name) or {}
    for field_name in field_names:
        if field_name in block:
            return block[field_name]
    for field_name in field_names:
        if field_name in raw:
            return raw[field_name]
    return None


def parse_candle(raw: dict[str, Any]) -> Candle:
    return Candle(
        end_ts=datetime.fromtimestamp(int(raw["end_period_ts"]), tz=timezone.utc),
        yes_bid=_dollars(_candle_field(raw, "yes_bid", "close_dollars", "close")),
        yes_ask=_dollars(_candle_field(raw, "yes_ask", "close_dollars", "close")),
        volume=float(raw.get("volume_fp", raw.get("volume", 0.0)) or 0.0),
    )


def parse_trade(raw: dict[str, Any]) -> Trade:
    taker_side = raw.get("taker_outcome_side") or raw["taker_side"]
    return Trade(
        created_at=parse_ts(raw["created_time"]),
        yes_price=float(raw["yes_price_dollars"]),
        no_price=float(raw["no_price_dollars"]),
        count=float(raw["count_fp"]),
        taker_side=taker_side,
        is_block_trade=bool(raw.get("is_block_trade", False)),
    )


class KalshiHistoryClient:
    def __init__(self, get_json: Callable[..., Any] = default_get_json, base_url: str = KALSHI_PUBLIC_BASE):
        self._get_json = get_json
        self._base = base_url.rstrip("/")
        self._cutoff_lock = Lock()
        self._cutoff_cache: dict[str, datetime] | None = None

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

    def cutoff_timestamps(self) -> dict[str, datetime]:
        """Return the independent market and trade historical/live boundaries."""
        with self._cutoff_lock:
            if self._cutoff_cache is None:
                raw = self._get("/historical/cutoff")
                self._cutoff_cache = {
                    "market_settled_ts": parse_ts(raw["market_settled_ts"]),
                    "trades_created_ts": parse_ts(raw["trades_created_ts"]),
                }
            return dict(self._cutoff_cache)

    def cutoffs(self) -> dict[str, datetime]:
        """Alias for :meth:`cutoff_timestamps` for callers that prefer a short name."""
        return self.cutoff_timestamps()

    def cutoff(self) -> datetime:
        """Return the market-settlement cutoff used by candle history queries."""
        return self.cutoff_timestamps()["market_settled_ts"]

    def settled_markets(self, series_ticker: str) -> list[dict]:
        return self._paginate("/historical/markets", "markets", {"series_ticker": series_ticker, "limit": PAGE_LIMIT})

    def merged_settled_markets(self, series_ticker: str) -> list[dict]:
        """Combine historical and live settled markets, deduplicated by ticker."""
        historical = self.settled_markets(series_ticker)
        live = self._paginate(
            "/markets",
            "markets",
            {"series_ticker": series_ticker, "status": "settled", "limit": PAGE_LIMIT},
        )
        by_ticker: dict[str, dict] = {}
        for market in historical + live:
            ticker = market.get("ticker")
            if ticker is not None:
                by_ticker.setdefault(ticker, market)
        return list(by_ticker.values())

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

    def merged_candles(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        period_minutes: int = 60,
        series_ticker: str | None = None,
    ) -> list[Candle]:
        """Return candles from the correct tier on each side of the market cutoff."""
        if end < start:
            raise ValueError(f"end must not precede start, got {end!r} < {start!r}")
        market_cutoff = self.cutoff_timestamps()["market_settled_ts"]
        parts: list[Candle] = []
        if start < market_cutoff:
            parts.extend(self.candles(
                ticker,
                start,
                min(end, market_cutoff),
                period_minutes=period_minutes,
                historical=True,
            ))
        if end > market_cutoff:
            if not series_ticker:
                raise ValueError("live-tier candlesticks require series_ticker")
            parts.extend(self.candles(
                ticker,
                max(start, market_cutoff),
                end,
                period_minutes=period_minutes,
                historical=False,
                series_ticker=series_ticker,
            ))
        by_timestamp: dict[datetime, Candle] = {}
        for candle in parts:
            by_timestamp.setdefault(candle.end_ts, candle)
        return sorted(by_timestamp.values(), key=lambda candle: candle.end_ts)

    def merge_candles(self, ticker: str, start: datetime, end: datetime, **kwargs: Any) -> list[Candle]:
        """Alias for :meth:`merged_candles`."""
        return self.merged_candles(ticker, start, end, **kwargs)

    def trades(self, ticker: str, *, historical: bool = True) -> list[Trade]:
        path = "/historical/trades" if historical else "/markets/trades"
        raw = self._paginate(path, "trades", {"ticker": ticker, "limit": PAGE_LIMIT})
        return sorted((parse_trade(t) for t in raw), key=lambda t: t.created_at)

    def merged_trades(
        self,
        ticker: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Trade]:
        """Combine both trade tiers, remove overlap duplicates, and sort oldest first."""
        self.cutoff_timestamps()["trades_created_ts"]
        combined = self.trades(ticker, historical=True)
        combined.extend(self.trades(ticker, historical=False))
        seen: set[tuple[Any, ...]] = set()
        merged: list[Trade] = []
        for trade in sorted(combined, key=lambda item: (item.created_at, item.taker_side, item.yes_price, item.no_price, item.count, item.is_block_trade)):
            if start is not None and trade.created_at < start:
                continue
            if end is not None and trade.created_at > end:
                continue
            key = (trade.created_at, trade.yes_price, trade.no_price, trade.count, trade.taker_side, trade.is_block_trade)
            if key in seen:
                continue
            seen.add(key)
            merged.append(trade)
        return merged

    def merge_trades(self, ticker: str, **kwargs: Any) -> list[Trade]:
        """Alias for :meth:`merged_trades`."""
        return self.merged_trades(ticker, **kwargs)

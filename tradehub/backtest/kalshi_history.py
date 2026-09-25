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
    is_block_trade: bool = False
    trade_id: str | None = None


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


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
        trade_id=raw.get("trade_id"),
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

    def cutoff_timestamps(self) -> dict[str, datetime]:
        """Return the independent market and trade historical/live boundaries."""
        raw = self._get("/historical/cutoff")
        return {
            "market_settled_ts": parse_ts(raw["market_settled_ts"]),
            "trades_created_ts": parse_ts(raw["trades_created_ts"]),
        }

    def cutoff(self) -> datetime:
        """Return the market-settlement cutoff used by candle history queries."""
        return self.cutoff_timestamps()["market_settled_ts"]

    def settled_markets(self, series_ticker: str) -> list[dict]:
        historical = self._paginate(
            "/historical/markets",
            "markets",
            {"series_ticker": series_ticker, "limit": PAGE_LIMIT},
        )
        live = self._paginate(
            "/markets",
            "markets",
            {"status": "settled", "series_ticker": series_ticker, "limit": PAGE_LIMIT},
        )
        by_ticker: dict[str, dict] = {}
        without_ticker: list[dict] = []
        for market in [*historical, *live]:
            ticker = market.get("ticker")
            if ticker is None:
                without_ticker.append(market)
            elif ticker not in by_ticker:
                by_ticker[ticker] = market
        return [*by_ticker.values(), *without_ticker]

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
        market_settled_at: datetime | None = None,
        period_minutes: int = 60,
        series_ticker: str | None = None,
    ) -> list[Candle]:
        """Return candles from the one tier that owns this market.

        A missing settlement timestamp means the market is still live, so use
        the live tier directly. All supplied timestamps must be timezone-aware
        to avoid silently interpreting local time as UTC.
        """
        _require_aware(start, "start")
        _require_aware(end, "end")
        if market_settled_at is not None:
            _require_aware(market_settled_at, "market_settled_at")
        if end < start:
            raise ValueError(f"end must not precede start, got {end!r} < {start!r}")
        if market_settled_at is None:
            historical = False
        else:
            market_cutoff = self.cutoff_timestamps()["market_settled_ts"]
            historical = market_settled_at < market_cutoff
        return self.candles(
            ticker,
            start,
            end,
            period_minutes=period_minutes,
            historical=historical,
            series_ticker=series_ticker,
        )

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
        """Combine both trade tiers, deduplicate identities, and sort oldest first."""
        combined = self.trades(ticker, historical=True)
        combined.extend(self.trades(ticker, historical=False))
        seen: set[tuple[Any, ...]] = set()
        merged: list[Trade] = []
        for trade in sorted(
            combined,
            key=lambda item: (
                item.created_at,
                item.taker_side,
                item.yes_price,
                item.no_price,
                item.count,
                item.is_block_trade,
            ),
        ):
            if start is not None and trade.created_at < start:
                continue
            if end is not None and trade.created_at > end:
                continue
            if trade.trade_id is not None:
                key = ("trade_id", trade.trade_id)
            else:
                key = (
                    "fields",
                    trade.created_at,
                    trade.yes_price,
                    trade.no_price,
                    trade.count,
                    trade.taker_side,
                    trade.is_block_trade,
                )
            if key in seen:
                continue
            seen.add(key)
            merged.append(trade)
        return merged

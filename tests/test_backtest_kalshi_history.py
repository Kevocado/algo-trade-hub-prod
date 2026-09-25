from datetime import datetime, timezone

import pytest

from tradehub.backtest import kalshi_history as kh

CANDLE = {
    "end_period_ts": 1784894400,
    "open_interest": "1335.68",
    "price": {"close": None, "high": None, "low": None, "mean": None, "open": None, "previous": "0.0100"},
    "volume": "12.00",
    "yes_ask": {"close": "0.0300", "high": "0.0400", "low": "0.0100", "open": "0.0100"},
    "yes_bid": {"close": "0.0200", "high": "0.0200", "low": "0.0000", "open": "0.0000"},
}
TRADE = {
    "count_fp": "83.00",
    "created_time": "2026-07-24T22:19:22.675922Z",
    "is_block_trade": False,
    "no_price_dollars": "0.9900",
    "taker_book_side": "bid",
    "taker_outcome_side": "yes",
    "taker_side": "yes",
    "ticker": "KXHIGHNY-26JUL24-T88",
    "trade_id": "a90acdda-3192-7344-f6e6-161b9667972e",
    "yes_price_dollars": "0.0100",
}


class FakeGet:
    """Serves canned JSON per path; records every (path, params) call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None):
        path = url.replace(kh.KALSHI_PUBLIC_BASE, "")
        self.calls.append((path, dict(params or {})))
        pages = self.routes[path]
        return pages.pop(0) if isinstance(pages, list) else pages


def test_parse_candle_uses_close_of_bid_and_ask_in_dollars():
    c = kh.parse_candle(CANDLE)
    assert c.end_ts == datetime.fromtimestamp(1784894400, tz=timezone.utc)
    assert c.yes_bid == pytest.approx(0.02)
    assert c.yes_ask == pytest.approx(0.03)
    assert c.volume == pytest.approx(12.0)


def test_parse_candle_missing_quote_is_none():
    c = kh.parse_candle({"end_period_ts": 1784894400, "volume": "0.00", "yes_ask": {"close": None}})
    assert c.yes_ask is None and c.yes_bid is None


def test_parse_trade():
    t = kh.parse_trade(TRADE)
    assert t.created_at == datetime(2026, 7, 24, 22, 19, 22, 675922, tzinfo=timezone.utc)
    assert t.yes_price == pytest.approx(0.01)
    assert t.no_price == pytest.approx(0.99)
    assert t.count == pytest.approx(83.0)
    assert t.taker_side == "yes"


def test_cutoff_reads_market_settled_ts():
    get = FakeGet({"/historical/cutoff": {"market_settled_ts": "2026-07-25T00:00:00Z", "trades_created_ts": "2026-07-25T00:00:00Z"}})
    assert kh.KalshiHistoryClient(get_json=get).cutoff() == datetime(2026, 7, 25, tzinfo=timezone.utc)


def test_settled_markets_follows_cursor_pagination():
    get = FakeGet({"/historical/markets": [
        {"markets": [{"ticker": "A"}], "cursor": "c1"},
        {"markets": [{"ticker": "B"}], "cursor": ""},
    ]})
    markets = kh.KalshiHistoryClient(get_json=get).settled_markets("KXHIGHNY")
    assert [m["ticker"] for m in markets] == ["A", "B"]
    assert get.calls[0][1]["series_ticker"] == "KXHIGHNY"
    assert get.calls[1][1]["cursor"] == "c1"


def test_candles_historical_path_params_and_sorting():
    later = dict(CANDLE, end_period_ts=1784898000)
    get = FakeGet({"/historical/markets/T/candlesticks": {"candlesticks": [later, CANDLE], "ticker": "T"}})
    start = datetime(2026, 7, 23, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 25, 5, tzinfo=timezone.utc)
    candles = kh.KalshiHistoryClient(get_json=get).candles("T", start, end)
    assert [c.end_ts.timestamp() for c in candles] == [1784894400, 1784898000]
    assert get.calls[0][1] == {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 60}


def test_candles_live_tier_requires_series_ticker():
    client = kh.KalshiHistoryClient(get_json=FakeGet({}))
    with pytest.raises(ValueError):
        client.candles("T", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 2, tzinfo=timezone.utc), historical=False)


def test_candles_live_tier_path():
    get = FakeGet({"/series/KXHIGHNY/markets/T/candlesticks": {"candlesticks": [CANDLE]}})
    kh.KalshiHistoryClient(get_json=get).candles(
        "T", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 2, tzinfo=timezone.utc),
        historical=False, series_ticker="KXHIGHNY",
    )
    assert get.calls[0][0] == "/series/KXHIGHNY/markets/T/candlesticks"


def test_trades_paginates_and_sorts_oldest_first():
    newer = dict(TRADE, created_time="2026-07-24T23:00:00Z")
    get = FakeGet({"/historical/trades": [{"trades": [newer], "cursor": "x"}, {"trades": [TRADE], "cursor": None}]})
    trades = kh.KalshiHistoryClient(get_json=get).trades("KXHIGHNY-26JUL24-T88")
    assert [t.created_at.hour for t in trades] == [22, 23]
    assert get.calls[0][1]["ticker"] == "KXHIGHNY-26JUL24-T88"


def test_live_trades_path():
    get = FakeGet({"/markets/trades": {"trades": [TRADE], "cursor": ""}})
    kh.KalshiHistoryClient(get_json=get).trades("T", historical=False)
    assert get.calls[0][0] == "/markets/trades"

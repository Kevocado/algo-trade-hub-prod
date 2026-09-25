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


def test_parse_live_candle_uses_dollar_close_and_fixed_point_volume():
    raw = {
        "end_period_ts": 1784898000,
        "yes_bid": {"close_dollars": "0.4100"},
        "yes_ask": {"close_dollars": "0.4200"},
        "volume_fp": "12.50",
    }
    candle = kh.parse_candle(raw)
    assert candle.yes_bid == pytest.approx(0.41)
    assert candle.yes_ask == pytest.approx(0.42)
    assert candle.volume == pytest.approx(12.5)


def test_parse_trade_prefers_canonical_outcome_side_and_exposes_block_flag():
    raw = dict(TRADE, taker_outcome_side="yes", taker_side="no", is_block_trade=True)
    trade = kh.parse_trade(raw)
    assert trade.taker_side == "yes"
    assert trade.is_block_trade is True

    legacy = dict(TRADE)
    legacy.pop("taker_outcome_side")
    legacy["taker_side"] = "no"
    assert kh.parse_trade(legacy).taker_side == "no"
    assert kh.parse_trade(legacy).is_block_trade is False


def test_cutoff_timestamps_exposes_market_and_trade_boundaries():
    get = FakeGet({"/historical/cutoff": {
        "market_settled_ts": "2026-07-25T00:00:00Z",
        "trades_created_ts": "2026-07-24T12:00:00Z",
    }})
    client = kh.KalshiHistoryClient(get_json=get)
    assert client.cutoff_timestamps() == {
        "market_settled_ts": datetime(2026, 7, 25, tzinfo=timezone.utc),
        "trades_created_ts": datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    }
    assert client.cutoff() == datetime(2026, 7, 25, tzinfo=timezone.utc)


def test_merged_candles_splits_at_market_cutoff_and_deduplicates_boundary():
    cutoff = datetime(2026, 7, 25, tzinfo=timezone.utc)
    start = datetime(2026, 7, 24, 23, tzinfo=timezone.utc)
    end = datetime(2026, 7, 25, 2, tzinfo=timezone.utc)
    historical = dict(CANDLE, end_period_ts=int(datetime(2026, 7, 24, 23, 30, tzinfo=timezone.utc).timestamp()))
    boundary = dict(CANDLE, end_period_ts=int(cutoff.timestamp()))
    live = {
        "end_period_ts": int(datetime(2026, 7, 25, 1, tzinfo=timezone.utc).timestamp()),
        "yes_bid": {"close_dollars": "0.2000"},
        "yes_ask": {"close_dollars": "0.2100"},
        "volume_fp": "3.00",
    }
    get = FakeGet({
        "/historical/cutoff": {
            "market_settled_ts": cutoff.isoformat().replace("+00:00", "Z"),
            "trades_created_ts": "2026-07-24T12:00:00Z",
        },
        "/historical/markets/T/candlesticks": {"candlesticks": [boundary, historical]},
        "/series/S/markets/T/candlesticks": {"candlesticks": [live, boundary]},
    })
    candles = kh.KalshiHistoryClient(get_json=get).merged_candles(
        "T", start, end, series_ticker="S",
    )
    assert [c.end_ts for c in candles] == [
        datetime.fromtimestamp(historical["end_period_ts"], tz=timezone.utc),
        cutoff,
        datetime.fromtimestamp(live["end_period_ts"], tz=timezone.utc),
    ]
    assert [c.yes_ask for c in candles] == pytest.approx([0.03, 0.03, 0.21])
    assert [path for path, _ in get.calls] == [
        "/historical/cutoff",
        "/historical/markets/T/candlesticks",
        "/series/S/markets/T/candlesticks",
    ]


def test_merged_trades_combines_tiers_and_deduplicates_overlap():
    cutoff = {
        "market_settled_ts": "2026-07-25T00:00:00Z",
        "trades_created_ts": "2026-07-24T22:30:00Z",
    }
    older = dict(TRADE, created_time="2026-07-24T22:19:22.675922Z")
    duplicate = dict(older)
    newer = dict(TRADE, created_time="2026-07-24T23:00:00Z")
    get = FakeGet({
        "/historical/cutoff": cutoff,
        "/historical/trades": {"trades": [older]},
        "/markets/trades": {"trades": [duplicate, newer]},
    })
    trades = kh.KalshiHistoryClient(get_json=get).merged_trades("T")
    assert [trade.created_at.hour for trade in trades] == [22, 23]
    assert len(trades) == 2
    assert [path for path, _ in get.calls] == [
        "/historical/cutoff",
        "/historical/trades",
        "/markets/trades",
    ]

from datetime import date, datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import EdgeSuggestion, Quote
from tradehub.engine_config import EngineConfig
from tradehub.markets import parse_market
from tradehub.scripts import scan

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)  # 13:00 LST NYC -> "today" = Sep 24


def _m(ticker, event, strike_type="greater", floor=74, cap=None, close="2026-09-26T05:00:00Z"):
    return parse_market({"ticker": ticker, "event_ticker": event, "strike_type": strike_type, "floor_strike": floor,
                         "cap_strike": cap, "open_time": "2026-09-23T14:00:00Z", "close_time": close,
                         "title": ticker})


class FakeLive:
    def __init__(self, markets, settled=()):
        self.markets = markets
        self.settled = list(settled)

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values(self, series):
        return self.settled


CFG = EngineConfig(min_edge_pct=5.0, prefer_maker=True, params={"error_bias": 0.0, "error_sigma": 2.0})
GOOD_QUOTE = Quote(yes_bid=0.30, yes_ask=0.34, yes_bid_size=50.0, yes_ask_size=50.0)


def test_edge_row_shape():
    m = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    row = scan.edge_row(m, EdgeSuggestion(m.ticker, "yes", 0.30, True, 12.5, 0.45, 0.32), "WEATHER")
    assert row["market_url"] == "https://kalshi.com/markets/kxhighny"
    assert row["edge"] == pytest.approx(0.125)
    assert row["model_probability"] == pytest.approx(0.45) and row["market_price"] == pytest.approx(0.32)
    assert row["edge_type"] == "WEATHER" and row["maker"] is True


def test_scan_weather_predicts_every_market_and_flags_edges():
    today = _m("KXHIGHNY-26SEP24-T74", "KXHIGHNY-26SEP24", close="2026-09-25T05:00:00Z")
    tomorrow = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    past = _m("KXHIGHNY-26SEP23-T74", "KXHIGHNY-26SEP23", close="2026-09-24T05:00:00Z")
    live = FakeLive([LiveMarket(today, GOOD_QUOTE), LiveMarket(tomorrow, GOOD_QUOTE), LiveMarket(past, GOOD_QUOTE)])
    calls = []

    def forecast_fn(city, target, now):
        calls.append(target)
        return [Observation(f"f:{target}", 77.0, now)]

    preds, edges = scan.scan_weather(live, NOW, CFG, forecast_fn=forecast_fn,
                                     cities={"KXHIGHNY": scan.WEATHER_CITIES["KXHIGHNY"]})
    assert sorted(calls) == [date(2026, 9, 24), date(2026, 9, 25)]
    assert {p["market_ticker"] for p in preds} == {today.ticker, tomorrow.ticker}
    assert all(p["engine"] == "weather" for p in preds)
    assert {e["market_ticker"] for e in edges} == {today.ticker, tomorrow.ticker}  # P(>=75 | mu 77) >> 0.34 ask
    assert all(e["edge_type"] == "WEATHER" for e in edges)


def test_scan_gas_uses_only_published_aaa_and_positive_horizons():
    m = _m("KXAAAGASD-26SEP25-4.5200", "KXAAAGASD-26SEP25", floor=4.52, close="2026-09-25T03:59:00Z")
    stale = _m("KXAAAGASD-26SEP24-4.5200", "KXAAAGASD-26SEP24", floor=4.52, close="2026-09-24T03:59:00Z")
    settled = [Observation("KXAAAGASD-26SEP23", 4.60, NOW - timedelta(days=1, hours=6)),
               Observation("KXAAAGASD-26SEP24", 4.61, NOW - timedelta(hours=6)),
               Observation("KXAAAGASD-26SEP25", 9.99, NOW + timedelta(hours=18))]  # not yet public
    live = FakeLive([LiveMarket(m, GOOD_QUOTE), LiveMarket(stale, GOOD_QUOTE)], settled)
    rbob = [Observation(f"RBOB:{i}", 3.0, NOW - timedelta(days=10 - i)) for i in range(8)]
    preds, edges = scan.scan_gas(live, NOW, EngineConfig(min_edge_pct=3.0), rbob_fn=lambda: rbob)
    assert [p["market_ticker"] for p in preds] == [m.ticker]  # stale market: horizon 0 -> skipped
    assert preds[0]["engine"] == "gas"
    assert preds[0]["our_prob"] > 0.99  # last known 4.61, default model -> far above 4.52
    assert edges and edges[0]["edge_type"] == "ENERGY"


def test_upsert_opportunities_writes_urls_and_energy(monkeypatch):
    from tradehub.core import supabase_client

    captured = {}

    class Table:
        def upsert(self, rows, on_conflict):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    monkeypatch.setattr(supabase_client, "get_client", lambda: type("C", (), {"table": lambda self, n: Table()})())
    supabase_client.upsert_opportunities([{"market_ticker": "KXAAAGASD-26SEP25-4.5200", "market_title": "gas",
                                           "market_price": 0.32, "model_probability": 0.45, "edge": 0.125,
                                           "edge_type": "ENERGY", "market_url": "https://kalshi.com/markets/kxaaagasd"}])
    row = captured["rows"][0]
    assert row["edge_type"] == "ENERGY"
    assert row["market_url"] == "https://kalshi.com/markets/kxaaagasd"
    assert row["source_url"] is None
    assert captured["on_conflict"] == "market_id"

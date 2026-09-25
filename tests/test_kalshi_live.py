from datetime import date, datetime, timezone

import pytest

from tradehub.backtest.kalshi_history import KALSHI_PUBLIC_BASE
from tradehub.data.kalshi_live import KalshiLive, quote_from_market_raw, settlement_observations
from tradehub.markets import event_date

OPEN = {
    "ticker": "KXAAAGASD-26SEP25-4.5200", "event_ticker": "KXAAAGASD-26SEP25", "strike_type": "greater",
    "floor_strike": 4.52, "cap_strike": None, "open_time": "2026-09-24T14:00:00Z",
    "close_time": "2026-09-25T03:59:00Z", "title": "US gas price",
    "yes_bid_dollars": "0.4100", "yes_ask_dollars": "0.4400", "yes_bid_size_fp": "120.00", "yes_ask_size_fp": "35.00",
}


class FakeGet:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None):
        path = url.replace(KALSHI_PUBLIC_BASE, "")
        self.calls.append((path, dict(params or {})))
        pages = self.routes[path]
        return pages.pop(0) if isinstance(pages, list) else pages


def test_quote_from_market_raw():
    q = quote_from_market_raw(OPEN)
    assert q.yes_bid == pytest.approx(0.41) and q.yes_ask == pytest.approx(0.44)
    assert q.yes_bid_size == pytest.approx(120.0) and q.yes_ask_size == pytest.approx(35.0)


def test_quote_empty_sides_are_none():
    q = quote_from_market_raw(dict(OPEN, yes_bid_dollars="0.0000", yes_ask_dollars="1.0000"))
    assert q.yes_bid is None and q.yes_ask is None


def test_open_markets_paginates_and_pairs_quotes():
    get = FakeGet({"/markets": [{"markets": [OPEN], "cursor": "c"}, {"markets": [OPEN], "cursor": ""}]})
    live = KalshiLive(get_json=get).open_markets("KXAAAGASD")
    assert len(live) == 2 and live[0].market.ticker == "KXAAAGASD-26SEP25-4.5200"
    assert get.calls[0][1] == {"series_ticker": "KXAAAGASD", "status": "open", "limit": 1000}


def test_settlement_observations_one_per_event_sorted_skipping_blanks():
    raws = [
        {"event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.4825", "settlement_ts": "2026-09-24T11:52:00Z"},
        {"event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.4825", "settlement_ts": "2026-09-24T11:50:26Z"},
        {"event_ticker": "KXAAAGASD-26SEP23", "expiration_value": "4.4610", "settlement_ts": "2026-09-23T11:49:00Z"},
        {"event_ticker": "KXAAAGASD-26SEP22", "expiration_value": "", "settlement_ts": "2026-09-22T11:49:00Z"},
    ]
    obs = settlement_observations(raws)
    assert [o.name for o in obs] == ["KXAAAGASD-26SEP23", "KXAAAGASD-26SEP24"]
    assert obs[1].value == pytest.approx(4.4825)
    assert obs[1].published_at == datetime(2026, 9, 24, 11, 50, 26, tzinfo=timezone.utc)
    assert event_date(obs[0].name) == date(2026, 9, 23)


def test_settled_values_merges_historical_and_live_tiers():
    get = FakeGet({
        "/historical/markets": {"markets": [{"ticker": "KXAAAGASD-26JUL01-4.1000", "event_ticker": "KXAAAGASD-26JUL01", "expiration_value": "4.1", "settlement_ts": "2026-07-01T11:50:00Z"}], "cursor": ""},
        "/markets": {"markets": [{"ticker": "KXAAAGASD-26SEP24-4.4800", "event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.48", "settlement_ts": "2026-09-24T11:50:00Z"}], "cursor": ""},
    })
    obs = KalshiLive(get_json=get).settled_values("KXAAAGASD")
    assert [o.name for o in obs] == ["KXAAAGASD-26JUL01", "KXAAAGASD-26SEP24"]
    assert ("/markets", {"series_ticker": "KXAAAGASD", "status": "settled", "limit": 1000}) in get.calls


def test_settled_values_reuses_tier_merged_settled_markets(monkeypatch):
    live = KalshiLive(get_json=lambda *args, **kwargs: pytest.fail("network should not be called"))
    calls = []
    raws = [{
        "ticker": "KXAAAGASD-26SEP24-4.4800",
        "event_ticker": "KXAAAGASD-26SEP24",
        "expiration_value": "4.48",
        "settlement_ts": "2026-09-24T11:50:00Z",
    }]

    def settled(series):
        calls.append(series)
        return raws

    monkeypatch.setattr(live, "settled_markets", settled)
    observations = live.settled_values("KXAAAGASD")

    assert calls == ["KXAAAGASD"]
    assert [observation.name for observation in observations] == ["KXAAAGASD-26SEP24"]

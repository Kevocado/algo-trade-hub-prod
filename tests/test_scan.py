from datetime import date, datetime, timedelta, timezone
import logging

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import EdgeSuggestion, Quote
from tradehub.engine_config import EngineConfig
from tradehub.markets import parse_market
from tradehub.scripts import backtest_engines, scan

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
    row = scan.edge_row(
        m,
        EdgeSuggestion(m.ticker, "yes", 0.30, True, 12.5, 0.45, 0.32),
        "WEATHER",
        engine="weather",
        engine_version="weather-v1",
    )
    assert row["market_url"] == "https://kalshi.com/markets/kxhighny"
    assert row["edge"] == pytest.approx(0.125)
    assert row["model_probability"] == pytest.approx(0.45) and row["market_price"] == pytest.approx(0.32)
    assert row["edge_type"] == "WEATHER" and row["maker"] is True
    assert row["engine"] == "weather"
    assert row["engine_version"] == "weather-v1"
    assert row["gate_status"] == "SHADOW"
    assert row["expires_at"] == m.close_time.isoformat()
    assert row["updated_at"]


def test_edge_row_requires_engine_keyword():
    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    suggestion = EdgeSuggestion(market.ticker, "yes", 0.30, True, 12.5, 0.45, 0.32)

    with pytest.raises(TypeError):
        scan.edge_row(market, suggestion, "WEATHER")


def test_latest_gate_statuses_requires_latest_backtest_and_matching_track_record():
    backtests = {
        "weather": {"engine": "weather", "engine_version": "weather-v2", "gate_status": "PROMOTED"},
        "gas": {"engine": "gas", "engine_version": "gas-v9", "gate_status": "PROMOTED"},
        "crypto": {"engine": "crypto", "engine_version": "crypto-v4", "gate_status": "SHADOW"},
    }
    tracks = {
        ("weather", "weather-v2"): "PROMOTED",
        ("gas", "gas-v9"): "SHADOW",
        ("crypto", "crypto-v4"): "PROMOTED",
    }
    calls = []

    class Table:
        def __init__(self, name):
            self.name = name
            self.filters = {}
            self.ordered = False
            self.limit_value = None

        def select(self, *args):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def order(self, key, *, desc=False):
            assert (key, desc) == ("created_at", True)
            self.ordered = True
            return self

        def limit(self, value):
            self.limit_value = value
            return self

        def execute(self):
            calls.append((self.name, dict(self.filters), self.ordered, self.limit_value))
            if self.name == "backtest_runs":
                row = backtests.get(self.filters["engine"])
                return type("Result", (), {"data": [row] if row else []})()
            key = (self.filters["engine"], self.filters["engine_version"])
            status = tracks.get(key)
            return type("Result", (), {"data": [{"gate_status": status}] if status else []})()

    class Client:
        def table(self, name):
            return Table(name)

    assert scan.latest_gate_statuses(
        Client(), {("weather", "weather-v2"), ("gas", "gas-v9"), ("crypto", "crypto-v4")}
    ) == {
        ("weather", "weather-v2"): "PROMOTED",
        ("gas", "gas-v9"): "SHADOW",
        ("crypto", "crypto-v4"): "SHADOW",
    }
    backtest_calls = [call for call in calls if call[0] == "backtest_runs"]
    assert len(backtest_calls) == 3
    assert all(ordered and limit == 1 for _, _, ordered, limit in backtest_calls)
    assert all(filters["engine_version"] for _, filters, _, _ in backtest_calls)
    assert ("track_record", {"engine": "weather", "engine_version": "weather-v2"}, False, 1) in calls
    assert ("track_record", {"engine": "gas", "engine_version": "gas-v9"}, False, 1) in calls
    assert not any(name == "track_record" and filters["engine"] == "crypto" for name, filters, _, _ in calls)


def test_latest_gate_statuses_never_promotes_a_different_engine_version():
    class Table:
        def __init__(self, name):
            self.name, self.filters = name, {}

        def select(self, *args):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def order(self, *args, **kwargs):
            return self

        def limit(self, value):
            return self

        def execute(self):
            # Only gas-v0 was ever backtested and promoted.
            promoted = self.filters.get("engine") == "gas" and self.filters.get("engine_version") == "gas-v0"
            data = [{"engine": "gas", "engine_version": "gas-v0", "gate_status": "PROMOTED"}] if promoted else []
            if self.name == "track_record" and promoted:
                data = [{"gate_status": "PROMOTED"}]
            return type("Result", (), {"data": data})()

    class Client:
        def table(self, name):
            return Table(name)

    assert scan.latest_gate_statuses(Client(), {("gas", "gas-v1")}) == {("gas", "gas-v1"): "SHADOW"}
    assert scan.latest_gate_statuses(Client(), {("gas", "gas-v0")}) == {("gas", "gas-v0"): "PROMOTED"}


def test_apply_gate_statuses_keys_on_engine_version_pair():
    edges = [
        {"engine": "weather", "engine_version": "weather-v1", "edge_type": "MACRO"},
        {"engine": "gas", "engine_version": "gas-v2", "edge_type": "WEATHER"},
    ]

    scan.apply_gate_statuses(edges, {("weather", "weather-v1"): "PROMOTED", ("gas", "gas-v2"): "SHADOW"})

    assert edges[0]["gate_status"] == "PROMOTED"
    assert edges[1]["gate_status"] == "SHADOW"


def test_remove_stale_edges_is_engine_scoped_and_uses_truncated_upsert_key():
    long_market_id = "W" * 60
    rows = [
        {"market_id": "weather-new", "engine": "weather"},
        {"market_id": long_market_id[:50], "engine": "weather"},
        {"market_id": "weather-old", "engine": "weather"},
        {"market_id": "gas-old", "engine": "gas"},
        {"market_id": "weather-old", "engine": "crypto"},
        {"market_id": "other-writer", "engine": None, "edge_type": "MACRO"},
    ]
    deleted = []

    class Table:
        def __init__(self, name):
            self.name = name
            self.filters = {}
            self.deleting = False

        def select(self, *args):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def delete(self):
            self.deleting = True
            return self

        def execute(self):
            matches = [
                row for row in rows
                if all(row.get(key) == value for key, value in self.filters.items())
            ]
            if self.deleting:
                deleted.extend((self.filters["engine"], row["market_id"]) for row in matches)
                rows[:] = [row for row in rows if row not in matches]
            return type("Result", (), {"data": matches})()

    class Client:
        def table(self, name):
            return Table(name)

    scan.remove_stale_edges(
        Client(),
        {"weather": {"weather-new", long_market_id}, "gas": set()},
    )

    assert set(deleted) == {("weather", "weather-old"), ("gas", "gas-old")}
    assert {(row.get("engine"), row["market_id"]) for row in rows} == {
        ("weather", "weather-new"),
        ("weather", long_market_id[:50]),
        ("crypto", "weather-old"),
        (None, "other-writer"),
    }


def test_scan_weather_predicts_only_strictly_future_lst_climate_days():
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
    assert calls == [date(2026, 9, 25)]
    assert {p["market_ticker"] for p in preds} == {tomorrow.ticker}
    assert all(p["engine"] == "weather" for p in preds)
    assert {e["market_ticker"] for e in edges} == {tomorrow.ticker}  # P(>=75 | mu 77) >> 0.34 ask
    assert all(e["edge_type"] == "WEATHER" for e in edges)


def test_scan_weather_predicts_all_three_cities():
    markets = [
        _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25"),
        _m("KXHIGHCHI-26SEP25-T74", "KXHIGHCHI-26SEP25"),
        _m("KXHIGHMIA-26SEP25-T84", "KXHIGHMIA-26SEP25", floor=84),
    ]
    live = FakeLive([LiveMarket(market, GOOD_QUOTE) for market in markets])

    def forecast_fn(city, target, now):
        return [Observation(f"forecast:{city.name}:{target}", 77.0, now)]

    predictions, edges = scan.scan_weather(
        live,
        NOW,
        CFG,
        forecast_fn=forecast_fn,
        historical_forecast_range_fn=lambda *args: [],
    )

    assert {row["market_ticker"] for row in predictions} == {market.ticker for market in markets}
    assert {row["market_ticker"] for row in edges} == {market.ticker for market in markets}


def test_scan_and_backtest_share_walk_forward_weather_error_model():
    city = scan.WEATHER_CITIES["KXHIGHNY"]
    target = date(2026, 9, 25)
    now = backtest_engines.weather_decision_time(target, 1, city)
    training_days = [target - timedelta(days=i) for i in range(25, 4, -1)]
    actuals = [
        Observation(f"KXHIGHNY-{day.strftime('%y%b%d').upper()}", 77.0, now - timedelta(hours=1))
        for day in training_days
    ]
    historical = {
        day: [Observation(f"openmeteo:gfs_seamless:high:{day}:lead1", 75.0,
                          backtest_engines.weather_decision_time(day, 1, city) - timedelta(hours=2))]
        for day in training_days
    }
    current = [Observation("openmeteo:gfs_seamless:high:2026-09-25:live", 75.0, now)]
    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    live = FakeLive([LiveMarket(market, GOOD_QUOTE)], actuals)

    predictions, _ = scan.scan_weather(
        live,
        now,
        CFG,
        forecast_fn=lambda city, day, as_of: current,
        historical_forecast_range_fn=lambda _city, start, end: [
            observation
            for day, observations in historical.items()
            if start <= day <= end
            for observation in observations
        ],
        cities={"KXHIGHNY": city},
    )
    decision = backtest_engines.build_weather_decisions(
        [market], {**historical, target: current}, actuals, city
    )[0]

    # The ledger contract stores probabilities to four decimals; the fitted
    # engine probability is the same before that serialization rounding.
    assert predictions[0]["our_prob"] == pytest.approx(decision.our_prob, abs=1e-4)


def test_scan_and_backtest_use_all_available_calibration_pairs():
    city = scan.WEATHER_CITIES["KXHIGHNY"]
    target = date(2026, 9, 25)
    now = backtest_engines.weather_decision_time(target, 1, city)
    training_days = [target - timedelta(days=i) for i in range(30, 5, -1)]
    actuals = [
        Observation(
            f"KXHIGHNY-{day.strftime('%y%b%d').upper()}",
            85.0 if index < 5 else 75.0,
            now - timedelta(hours=1),
        )
        for index, day in enumerate(training_days)
    ]
    historical = {
        day: [Observation(f"openmeteo:gfs_seamless:high:{day}:lead1", 75.0,
                          backtest_engines.weather_decision_time(day, 1, city) - timedelta(hours=2))]
        for day in training_days
    }
    current = [Observation("current", 75.0, now)]
    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    live = FakeLive([LiveMarket(market, GOOD_QUOTE)], actuals)

    predictions, _ = scan.scan_weather(
        live,
        now,
        CFG,
        forecast_fn=lambda city, day, as_of: current,
        historical_forecast_range_fn=lambda _city, start, end: [
            observation
            for day, observations in historical.items()
            if start <= day <= end
            for observation in observations
        ],
        cities={"KXHIGHNY": city},
    )
    decision = backtest_engines.build_weather_decisions(
        [market], {**historical, target: current}, actuals, city
    )[0]

    assert predictions[0]["our_prob"] == pytest.approx(decision.our_prob, abs=1e-4)


def test_scan_calibration_uses_smallest_forecast_lead_published_by_as_of():
    city = scan.WEATHER_CITIES["KXHIGHNY"]
    target = date(2026, 9, 25)
    now = backtest_engines.weather_decision_time(target, 1, city)
    training_days = [target - timedelta(days=i) for i in range(25, 0, -1)]
    actuals = [
        Observation(
            f"KXHIGHNY-{day.strftime('%y%b%d').upper()}",
            77.0,
            now - timedelta(hours=1),
        )
        for day in training_days
    ]

    def historical_forecast_range_fn(_city, start, end):
        return [
            observation
            for day in training_days
            if start <= day <= end
            for observation in (
                # lead 1 publishes after that day's own decision (D-1 23:30 LST): never used
                Observation(f"openmeteo:gfs_seamless:high:{day}:lead1", 90.0,
                            backtest_engines.weather_decision_time(day, 1, city) + timedelta(hours=1)),
                Observation(f"openmeteo:gfs_seamless:high:{day}:lead2", 75.0,
                            backtest_engines.weather_decision_time(day, 1, city) - timedelta(hours=1)),
            )
        ]

    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    predictions, _ = scan.scan_weather(
        FakeLive([LiveMarket(market, GOOD_QUOTE)], actuals),
        now,
        CFG,
        forecast_fn=lambda _city, _day, as_of: [Observation("forecast:live", 75.0, as_of)],
        historical_forecast_range_fn=historical_forecast_range_fn,
        cities={"KXHIGHNY": city},
    )

    assert predictions[0]["raw_payload"]["bias"] == pytest.approx(2.0)
    assert all(observation.published_at <= now for observation in actuals)


def test_scan_weather_calibration_fetches_only_the_last_90_days_once_per_city():
    city = scan.WEATHER_CITIES["KXHIGHNY"]
    target = date(2026, 9, 25)
    now = NOW
    actuals = [
        Observation(
            f"KXHIGHNY-{(now.date() - timedelta(days=offset)).strftime('%y%b%d').upper()}",
            77.0,
            now - timedelta(hours=1),
        )
        for offset in range(1, 101)
    ]
    range_calls = []

    def historical_forecast_range_fn(requested_city, start, end):
        range_calls.append((requested_city, start, end))
        return [
            Observation(
                f"openmeteo:gfs_seamless:high:{day.isoformat()}:lead1",
                75.0,
                backtest_engines.weather_decision_time(day, 1, requested_city) - timedelta(hours=1),
            )
            for day in (start + timedelta(days=offset) for offset in range((end - start).days + 1))
        ]

    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    predictions, _ = scan.scan_weather(
        FakeLive([LiveMarket(market, GOOD_QUOTE)], actuals),
        now,
        CFG,
        forecast_fn=lambda _city, _day, as_of: [Observation("forecast:live", 75.0, as_of)],
        historical_forecast_range_fn=historical_forecast_range_fn,
        cities={"KXHIGHNY": city},
    )

    assert range_calls == [(city, date(2026, 6, 26), date(2026, 9, 24))]
    assert predictions[0]["raw_payload"]["bias"] == pytest.approx(2.0)


def test_scan_and_backtest_share_yaml_fallback_below_minimum_samples():
    city = scan.WEATHER_CITIES["KXHIGHNY"]
    target = date(2026, 9, 25)
    now = backtest_engines.weather_decision_time(target, 1, city)
    actuals = [
        Observation(f"KXHIGHNY-{(target - timedelta(days=i)).strftime('%y%b%d').upper()}", 77.0, now - timedelta(hours=1))
        for i in range(1, 4)
    ]
    current = [Observation("current", 75.0, now)]
    market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    live = FakeLive([LiveMarket(market, GOOD_QUOTE)], actuals)
    cfg = EngineConfig(min_edge_pct=5.0, params={"error_bias": 2.0, "error_sigma": 1.0})

    predictions, _ = scan.scan_weather(
        live,
        now,
        cfg,
        forecast_fn=lambda city, day, as_of: current,
        historical_forecast_range_fn=lambda city, start, end: [],
        cities={"KXHIGHNY": city},
    )
    decision = backtest_engines.build_weather_decisions(
        [market], {target: current}, actuals, city,
        fallback=scan.ErrorModel(2.0, 1.0),
        min_pairs=20,
    )[0]

    assert predictions[0]["our_prob"] == pytest.approx(decision.our_prob, abs=1e-4)


def test_scan_weather_isolates_city_failures_when_requested(caplog):
    caplog.set_level(logging.INFO)
    nyc = scan.WEATHER_CITIES["KXHIGHNY"]
    chicago = scan.WEATHER_CITIES["KXHIGHCHI"]
    ny_market = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    chi_market = _m("KXHIGHCHI-26SEP25-T74", "KXHIGHCHI-26SEP25")
    live = FakeLive([LiveMarket(ny_market, GOOD_QUOTE), LiveMarket(chi_market, GOOD_QUOTE)])
    failures = []

    def forecast_fn(city, target, now):
        if city == chicago:
            raise RuntimeError("Chicago forecast unavailable")
        return [Observation("nyc", 77.0, now)]

    predictions, edges = scan.scan_weather(
        live,
        NOW,
        CFG,
        forecast_fn=forecast_fn,
        cities={"KXHIGHNY": nyc, "KXHIGHCHI": chicago},
        failures=failures,
    )

    assert {row["market_ticker"] for row in predictions} == {ny_market.ticker}
    assert {row["market_ticker"] for row in edges} == {ny_market.ticker}
    assert len(failures) == 1 and "KXHIGHCHI" in failures[0]
    assert "scan engine=weather city=KXHIGHCHI predictions=0 edges=0" in caplog.text


def test_scan_main_assigns_one_fifteen_minute_deadline_to_network_scan(monkeypatch):
    captured = {}

    class FakeLive:
        def __init__(self, deadline=None):
            captured["deadline"] = deadline

    monkeypatch.setattr(scan, "KalshiLive", FakeLive)
    monkeypatch.setattr(scan, "load_engine_config", lambda engine: EngineConfig(min_edge_pct=3.0))
    monkeypatch.setattr(scan, "scan_weather", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    from tradehub.core import supabase_client
    import tradehub.predictions as predictions_module

    monkeypatch.setattr(predictions_module, "record_predictions", lambda client, rows: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: None)

    before = scan.time.monotonic()
    assert scan.main(now=NOW, client=object()) == 0
    remaining = captured["deadline"] - before

    assert 890 <= remaining <= scan.SCAN_DEADLINE_SECONDS + 0.1
    assert scan.SCAN_DEADLINE_SECONDS == 15 * 60


def test_scan_main_isolates_engine_failure_and_returns_nonzero(monkeypatch, capsys, caplog):
    caplog.set_level(logging.INFO)
    gas_prediction = {"market_ticker": "KXAAAGASD-26SEP25-4.5200", "our_prob": 0.9}
    gas_edge = {
        "market_ticker": "KXAAAGASD-26SEP25-4.5200",
        "engine": "gas",
        "edge_type": "ENERGY",
        "gate_status": "SHADOW",
    }
    recorded = []
    upserted = []
    pruned = []

    monkeypatch.setattr(scan, "load_engine_config", lambda engine: EngineConfig(min_edge_pct=3.0))

    def weather(*args, **kwargs):
        raise RuntimeError("weather source unavailable")

    def gas(*args, **kwargs):
        return [gas_prediction], [gas_edge]

    monkeypatch.setattr(scan, "scan_weather", weather)
    monkeypatch.setattr(scan, "scan_gas", gas)
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: pruned.append(produced))
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    from tradehub.core import supabase_client
    import tradehub.predictions as predictions_module

    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    monkeypatch.setattr(predictions_module, "record_predictions", lambda client, rows: recorded.extend(rows))

    assert scan.main(now=NOW, live=object(), client=object()) == 1
    output = capsys.readouterr().out
    assert recorded == [gas_prediction]
    assert upserted == [gas_edge]
    assert pruned == [{"gas": {gas_edge["market_ticker"]}}]
    assert "scan engine=gas predictions=1 edges=1" in caplog.text
    assert "scan engine=weather predictions=0 edges=0" in caplog.text
    assert "partial_failure" in output and "weather source unavailable" in output


def test_scan_main_persists_successful_rows_from_a_partial_weather_scan(monkeypatch):
    prediction = {"market_ticker": "KXHIGHNY-26SEP25-T74", "our_prob": 0.9}
    edge = {"market_ticker": "KXHIGHNY-26SEP25-T74", "engine": "weather", "edge_type": "WEATHER"}
    recorded = []
    upserted = []
    pruned = []

    monkeypatch.setattr(scan, "load_engine_config", lambda engine: EngineConfig(min_edge_pct=3.0))
    monkeypatch.setattr(scan, "scan_weather", lambda *args, **kwargs: (
        kwargs["failures"].append("weather/KXHIGHCHI: forecast unavailable") or ([prediction], [edge])
    ))
    monkeypatch.setattr(scan, "scan_gas", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: pruned.append(produced))
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    from tradehub.core import supabase_client
    import tradehub.predictions as predictions_module

    monkeypatch.setattr(predictions_module, "record_predictions", lambda client, rows: recorded.extend(rows))
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))

    assert scan.main(now=NOW, live=object(), client=object()) == 1
    assert recorded == [prediction]
    assert upserted == [edge]
    assert pruned == [{"gas": set()}]


def test_scan_main_writes_edges_for_engines_whose_gate_loses(monkeypatch):
    weather_prediction = {"market_ticker": "KXHIGHNY-26SEP25-T74", "our_prob": 0.9}
    weather_edge = {"market_ticker": "KXHIGHNY-26SEP25-T74", "engine": "weather", "edge_type": "WEATHER"}
    gas_prediction = {"market_ticker": "KXAAAGASD-26SEP25-4.5200", "our_prob": 0.9}
    gas_edge = {"market_ticker": "KXAAAGASD-26SEP25-4.5200", "engine": "gas", "edge_type": "ENERGY"}
    upserted = []

    monkeypatch.setattr(scan, "load_engine_config", lambda engine: EngineConfig(min_edge_pct=3.0))
    monkeypatch.setattr(scan, "scan_weather", lambda *args, **kwargs: ([weather_prediction], [weather_edge]))
    monkeypatch.setattr(scan, "scan_gas", lambda *args, **kwargs: ([gas_prediction], [gas_edge]))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    from tradehub.core import supabase_client
    import tradehub.predictions as predictions_module

    monkeypatch.setattr(predictions_module, "record_predictions", lambda client, rows: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))

    assert scan.main(now=NOW, live=object(), client=object()) == 0
    assert upserted == [weather_edge, gas_edge]
    assert all(row["gate_status"] == "SHADOW" for row in upserted)


def test_upsert_opportunities_propagates_execute_failure(monkeypatch):
    from tradehub.core import supabase_client

    class FailingTable:
        def upsert(self, rows, on_conflict):
            return self

        def execute(self):
            raise RuntimeError("edge write failed")

    monkeypatch.setattr(supabase_client, "get_client", lambda: type("Client", (), {"table": lambda self, name: FailingTable()})())
    with pytest.raises(RuntimeError, match="edge write failed"):
        supabase_client.upsert_opportunities([{
            "market_ticker": "KXAAAGASD-26SEP25-4.5200",
            "model_probability": 0.5,
            "market_price": 0.4,
            "edge": 0.1,
            "edge_type": "ENERGY",
        }])


def test_scan_gas_uses_only_published_aaa_and_positive_horizons():
    m = _m("KXAAAGASD-26SEP25-4.5200", "KXAAAGASD-26SEP25", floor=4.52, close="2026-09-25T03:59:00Z")
    stale = _m("KXAAAGASD-26SEP24-4.5200", "KXAAAGASD-26SEP24", floor=4.52, close="2026-09-24T03:59:00Z")
    settled = [Observation("KXAAAGASD-26SEP23", 4.60, NOW - timedelta(days=1, hours=6)),
               Observation("KXAAAGASD-26SEP24", 4.61, NOW - timedelta(hours=6)),
               Observation("KXAAAGASD-26SEP25", 9.99, NOW + timedelta(hours=18))]  # not yet public
    live = FakeLive([LiveMarket(m, GOOD_QUOTE), LiveMarket(stale, GOOD_QUOTE)], settled)
    rbob = [Observation(f"RBOB:RBU26.NYM:{i}", 3.0, NOW - timedelta(days=10 - i)) for i in range(8)]
    preds, edges = scan.scan_gas(live, NOW, EngineConfig(min_edge_pct=3.0), rbob_fn=lambda: rbob)
    assert [p["market_ticker"] for p in preds] == [m.ticker]  # stale market: horizon 0 -> skipped
    assert preds[0]["engine"] == "gas"
    assert preds[0]["our_prob"] > 0.99  # last known 4.61, default model -> far above 4.52
    assert edges and edges[0]["edge_type"] == "ENERGY"


def test_scan_gas_passes_nymex_roll_dates_to_training_and_live_change(monkeypatch):
    market = _m("KXAAAGASD-26SEP25-4.5200", "KXAAAGASD-26SEP25", floor=4.52, close="2026-09-25T03:59:00Z")
    known = [Observation("KXAAAGASD-26SEP24", 4.50, NOW - timedelta(hours=1))]
    rbob = [Observation("RBOB:RBU26.NYM:2026-08-31", 3.0, NOW - timedelta(days=1))]
    roll_dates = [date(2026, 8, 31)]
    calls = {}

    def roll_dates_fn(start, end):
        calls["range"] = (start, end)
        return roll_dates

    def training_pairs(_aaa, _rbob, *, roll_dates):
        calls["training"] = roll_dates
        return []

    def change(_rbob, _as_of, *, roll_dates):
        calls["change"] = roll_dates
        return None

    monkeypatch.setattr(scan, "front_month_roll_dates", roll_dates_fn)
    monkeypatch.setattr(scan, "gas_training_pairs", training_pairs)
    monkeypatch.setattr(scan, "rbob_change", change)

    scan.scan_gas(
        FakeLive([LiveMarket(market, GOOD_QUOTE)], known),
        NOW,
        EngineConfig(min_edge_pct=3.0),
        rbob_fn=lambda: rbob,
        roll_dates_fn=roll_dates_fn,
    )

    assert calls == {
        "range": (date(2026, 9, 24), date(2026, 9, 24)),
        "training": roll_dates,
        "change": roll_dates,
    }


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
                                           "engine": "gas", "edge_type": "ENERGY",
                                           "market_url": "https://kalshi.com/markets/kxaaagasd"}])
    row = captured["rows"][0]
    assert row["engine"] == "gas"
    assert row["edge_type"] == "ENERGY"
    assert row["market_url"] == "https://kalshi.com/markets/kxaaagasd"
    assert row["source_url"] is None
    assert row["gate_status"] == "SHADOW"
    assert row["expires_at"] is None
    assert captured["on_conflict"] == "market_id"

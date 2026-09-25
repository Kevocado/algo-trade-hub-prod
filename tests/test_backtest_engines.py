from datetime import date, datetime, timedelta, timezone
from threading import Barrier, Lock
from zoneinfo import ZoneInfo

import pytest

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import Observation, check_no_lookahead
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.weather import WEATHER_CITIES
from tradehub.engine_config import EngineConfig
from tradehub.markets import parse_market
from tradehub.scripts import backtest_engines
from tradehub.scripts.backtest_engines import (
    GAS_DECISION_LEAD,
    build_gas_decisions,
    build_weather_decisions,
    weather_decision_time,
)

NYC = WEATHER_CITIES["KXHIGHNY"]
EST = ZoneInfo("Etc/GMT+5")


def _wm(day: date, *, settlement_ts: datetime | None = None):
    tag = day.strftime("%y%b%d").upper()
    close = datetime.combine(day + timedelta(days=1), datetime.min.time(), EST).astimezone(timezone.utc)
    raw = {"ticker": f"KXHIGHNY-{tag}-T74", "event_ticker": f"KXHIGHNY-{tag}", "strike_type": "greater",
           "floor_strike": 74, "cap_strike": None, "open_time": "2026-06-01T00:00:00Z",
           "close_time": close.isoformat().replace("+00:00", "Z"), "title": "NYC high"}
    if settlement_ts is not None:
        raw["settlement_ts"] = settlement_ts.isoformat().replace("+00:00", "Z")
    return parse_market(raw)


def _fc(day: date, value: float):
    published = datetime.combine(day, datetime.min.time().replace(hour=23), EST) - timedelta(days=1)
    return [Observation(f"openmeteo:gfs_seamless:high:{day}:lead1", value, published.astimezone(timezone.utc))]


def _actual(day: date, value: float):
    tag = day.strftime("%y%b%d").upper()
    published = datetime.combine(day + timedelta(days=1), datetime.min.time().replace(hour=12), timezone.utc)
    return Observation(f"KXHIGHNY-{tag}", value, published)


def test_weather_decision_time_is_2330_lst_the_day_before():
    t = weather_decision_time(date(2026, 7, 24), 1, NYC)
    assert t == datetime(2026, 7, 23, 23, 30, tzinfo=EST)


def test_weather_decisions_are_leakage_safe_and_fit_walk_forward():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(30)]
    forecasts = {d: _fc(d, 75.0) for d in days}
    actuals = [_actual(d, 77.0) for d in days]  # model is always 2°F too cold
    decisions = build_weather_decisions([_wm(d) for d in days], forecasts, actuals, NYC)
    assert len(decisions) == 30
    for d in decisions:
        check_no_lookahead(d)  # raises on leakage
    # Early decisions have < 20 known pairs -> default model; the last has 28 known pairs -> bias +2 learned.
    assert decisions[-1].our_prob > decisions[0].our_prob


def test_weather_decisions_skip_dates_without_forecasts():
    d = date(2026, 7, 5)
    assert build_weather_decisions([_wm(d)], {}, [], NYC) == []


def _gm(day: date, strike: float):
    tag = day.strftime("%y%b%d").upper()
    close = datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=3, minutes=59)
    return parse_market({"ticker": f"KXAAAGASD-{tag}-{strike:.4f}", "event_ticker": f"KXAAAGASD-{tag}",
                         "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
                         "open_time": "2026-06-01T00:00:00Z", "close_time": close.isoformat().replace("+00:00", "Z"),
                         "title": "US gas"})


def test_gas_decisions_use_only_published_inputs():
    start = date(2026, 7, 1)
    aaa = [Observation(f"KXAAAGASD-{(start + timedelta(days=i)).strftime('%y%b%d').upper()}", 4.00 + 0.001 * i,
                       datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc) + timedelta(hours=12))
           for i in range(40)]
    rbob = [Observation(f"RBOB:RBU26.NYM:{i}", 3.0 + 0.01 * i,
                        datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc) - timedelta(hours=2))
            for i in range(40)]
    target = start + timedelta(days=35)
    decisions = build_gas_decisions([_gm(target, 4.03)], aaa, rbob)
    assert len(decisions) == 1
    d = decisions[0]
    check_no_lookahead(d)
    assert d.decided_at == _gm(target, 4.03).close_time - GAS_DECISION_LEAD
    last = [o for o in d.features if o.name.startswith("KXAAAGASD")][0]
    assert last.published_at <= d.decided_at
    assert last.name.endswith(target.replace(day=target.day - 1).strftime("%y%b%d").upper())


def test_gas_decision_omits_rbob_features_for_roll_crossing_window():
    target = date(2026, 8, 10)
    aaa = [Observation("KXAAAGASD-26AUG09", 4.0, datetime(2026, 8, 9, 12, tzinfo=timezone.utc))]
    rbob = [
        Observation("RBOB:RBU26.NYM:2026-08-04", 3.0, datetime(2026, 8, 4, 22, tzinfo=timezone.utc)),
        Observation("RBOB:RBU26.NYM:2026-08-05", 3.1, datetime(2026, 8, 5, 22, tzinfo=timezone.utc)),
        Observation("RBOB:RBU26.NYM:2026-08-06", 3.2, datetime(2026, 8, 6, 22, tzinfo=timezone.utc)),
        Observation("RBOB:RBV26.NYM:2026-08-07", 3.0, datetime(2026, 8, 7, 22, tzinfo=timezone.utc)),
        Observation("RBOB:RBV26.NYM:2026-08-08", 3.1, datetime(2026, 8, 8, 22, tzinfo=timezone.utc)),
        Observation("RBOB:RBV26.NYM:2026-08-09", 3.2, datetime(2026, 8, 9, 22, tzinfo=timezone.utc)),
    ]

    decision = build_gas_decisions([_gm(target, 4.0)], aaa, rbob)[0]

    assert [feature.name for feature in decision.features if feature.name.startswith("KXAAAGASD")]
    assert not [feature for feature in decision.features if feature.name.startswith("RBOB:")]


def test_built_decisions_run_through_the_backtester():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(3)]
    markets = [_wm(d) for d in days]
    decisions = build_weather_decisions(markets, {d: _fc(d, 80.0) for d in days}, [], NYC)
    histories = {m.ticker: MarketHistory(m.ticker, "yes", m.close_time,
                                         [Candle(dec.decided_at - timedelta(hours=1), 0.40, 0.44, 1.0)], [])
                 for m, dec in zip(markets, decisions)}
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    assert result.n_decisions == 3 and result.n_fills == 3 and result.pnl_after_fees > 0


def test_weather_decisions_filter_current_forecasts_published_after_decision():
    target = date(2026, 7, 30)
    decided_at = weather_decision_time(target, 1, NYC)
    safe = Observation("safe-current", 75.0, decided_at - timedelta(minutes=30))
    late = Observation("late-current", 120.0, decided_at + timedelta(seconds=1))

    decisions = build_weather_decisions([_wm(target)], {target: [safe, late]}, [], NYC)

    assert len(decisions) == 1
    assert tuple(obs.name for obs in decisions[0].features) == ("safe-current",)
    check_no_lookahead(decisions[0])


def test_weather_decision_uses_lead_2_when_lead_1_is_published_late():
    target = date(2026, 9, 25)
    decided_at = weather_decision_time(target, 1, NYC)
    lead_1 = Observation(
        "openmeteo:gfs_seamless:high:2026-09-25:lead1",
        90.0,
        decided_at + timedelta(minutes=30),
    )
    lead_2 = Observation(
        "openmeteo:gfs_seamless:high:2026-09-25:lead2",
        75.0,
        decided_at - timedelta(minutes=30),
    )

    decisions = build_weather_decisions([_wm(target)], {target: [lead_1, lead_2]}, [], NYC)

    assert len(decisions) == 1
    assert tuple(observation.name for observation in decisions[0].features) == (lead_2.name,)
    assert all(observation.published_at <= decisions[0].decided_at for observation in decisions[0].features)
    check_no_lookahead(decisions[0])


def test_weather_decision_uses_only_smallest_published_lead():
    target = date(2026, 9, 25)
    decided_at = weather_decision_time(target, 1, NYC)
    lead_1 = Observation(
        "openmeteo:gfs_seamless:high:2026-09-25:lead1",
        75.0,
        decided_at - timedelta(hours=2),
    )
    lead_2 = Observation(
        "openmeteo:gfs_seamless:high:2026-09-25:lead2",
        85.0,
        decided_at - timedelta(hours=1),
    )

    decisions = build_weather_decisions([_wm(target)], {target: [lead_1, lead_2]}, [], NYC)

    assert tuple(observation.name for observation in decisions[0].features) == (lead_1.name,)


def test_weather_training_ignores_forecasts_published_after_decision():
    target = date(2026, 7, 30)
    decided_at = weather_decision_time(target, 1, NYC)
    training_days = [target - timedelta(days=i) for i in range(30, 0, -1)]
    actuals = [_actual(day, 77.0) for day in training_days]
    safe_forecasts = {day: _fc(day, 75.0) for day in training_days}
    mixed_forecasts = {
        day: _fc(day, 75.0) + [
            Observation(f"late-training:{day}", 125.0, decided_at + timedelta(minutes=1))
        ]
        for day in training_days
    }
    current = {target: _fc(target, 75.0)}
    market = [_wm(target)]

    expected = build_weather_decisions(market, {**safe_forecasts, **current}, actuals, NYC)[0]
    guarded = build_weather_decisions(market, {**mixed_forecasts, **current}, actuals, NYC)[0]

    assert guarded.our_prob == pytest.approx(expected.our_prob)
    check_no_lookahead(guarded)


def test_histories_use_merged_candles_and_trades_with_series_context():
    class RecordingClient:
        def __init__(self):
            self.calls = []

        def merged_candles(self, ticker, start, end, **kwargs):
            self.calls.append(("candles", ticker, start, end, kwargs))
            return []

        def merged_trades(self, ticker, **kwargs):
            self.calls.append(("trades", ticker, kwargs))
            return []

    settled_at = datetime(2026, 7, 6, 12, tzinfo=timezone.utc)
    market = _wm(date(2026, 7, 5), settlement_ts=settled_at)
    client = RecordingClient()
    histories = backtest_engines._histories(client, [market], {market.ticker: "yes"}, mode="maker")

    assert histories[market.ticker].result == "yes"
    assert histories[market.ticker].settled_at == settled_at
    assert client.calls[0][0:2] == ("candles", market.ticker)
    assert client.calls[0][4]["market_settled_at"] == settled_at
    assert client.calls[0][4]["series_ticker"] == market.series_ticker
    assert client.calls[1][0:2] == ("trades", market.ticker)


def test_histories_skip_trade_fetch_for_taker_mode():
    class RecordingClient:
        def __init__(self):
            self.calls = []

        def merged_candles(self, ticker, start, end, **kwargs):
            self.calls.append(("candles", ticker))
            return []

        def merged_trades(self, ticker, **kwargs):
            self.calls.append(("trades", ticker))
            return []

    market = _wm(date(2026, 7, 5))
    client = RecordingClient()
    histories = backtest_engines._histories(client, [market], {market.ticker: "yes"}, mode="taker")

    assert histories[market.ticker].trades == []
    assert client.calls == [("candles", market.ticker)]


def test_backtest_cli_uses_merged_markets_and_reproducible_metadata(monkeypatch):
    raw = {
        "ticker": "KXHIGHNY-26JUL01-T74",
        "event_ticker": "KXHIGHNY-26JUL01",
        "strike_type": "greater",
        "floor_strike": 74,
        "cap_strike": None,
        "open_time": "2026-06-01T00:00:00Z",
        "close_time": "2026-07-02T05:00:00Z",
        "settlement_ts": "2026-07-02T12:00:00Z",
        "result": "yes",
        "title": "NYC high",
    }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def settled_markets(self, series):
            self.calls.append(("settled_markets", series))
            return [raw]

    client = FakeClient()
    captured = {}
    backtest_kwargs = {}
    history_modes = []

    def fake_build_row(result, **kwargs):
        captured.update(kwargs)
        return {
            "engine": "weather",
            "mode": "taker",
            "n_decisions": 0,
            "n_fills": 0,
            "pnl_after_fees": 0.0,
            "max_drawdown": 0.0,
            "brier_ours": None,
            "brier_market": None,
            "gate_status": "SHADOW",
            "gate_reasons": [],
        }

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", lambda: client)
    monkeypatch.setattr(
        backtest_engines,
        "load_engine_config",
        lambda engine: EngineConfig(min_edge_pct=7.5, params={"error_bias": 1.0, "error_sigma": 1.0}),
        raising=False,
    )
    monkeypatch.setattr(backtest_engines, "settlement_observations", lambda raws: [])
    monkeypatch.setattr(backtest_engines, "historical_forecast_highs", lambda city, day, lead: [])

    def fake_histories(client, markets, results, mode):
        history_modes.append(mode)
        return {}

    monkeypatch.setattr(backtest_engines, "_histories", fake_histories)

    def fake_run_backtest(**kwargs):
        backtest_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(backtest_engines, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row", fake_build_row)

    assert backtest_engines.main([
        "--engine", "weather",
        "--start", "2026-07-01",
        "--end", "2026-07-01",
        "--train-days", "17",
    ]) == 0

    assert client.calls == [("settled_markets", "KXHIGHNY")]
    assert history_modes == ["taker"]
    assert captured["config"] == {
        "engine": "weather",
        "series": "KXHIGHNY",
        "mode": "taker",
        "start": "2026-07-01",
        "end": "2026-07-01",
        "train_days": 17,
        "min_edge_pct": 7.5,
    }
    assert backtest_kwargs["min_edge_pct"] == 7.5
    assert captured["date_from"] == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert captured["date_to"] == datetime(2026, 7, 1, 23, 59, tzinfo=timezone.utc)


def test_gas_cli_sizes_rbob_from_backtest_start(monkeypatch):
    raw = {
        "ticker": "KXAAAGASD-26JUL24-4.1000",
        "event_ticker": "KXAAAGASD-26JUL24",
        "strike_type": "greater",
        "floor_strike": 4.1,
        "cap_strike": None,
        "open_time": "2026-06-01T00:00:00Z",
        "close_time": "2026-07-25T03:59:00Z",
        "result": "yes",
        "title": "US gas",
    }
    rbob_calls = []
    captured = {}

    class FakeClient:
        def settled_markets(self, series):
            return [raw]

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", FakeClient)
    monkeypatch.setattr(backtest_engines, "settlement_observations", lambda raws: [Observation("KXAAAGASD-26JUL23", 4.0, datetime(2026, 7, 23, 12, tzinfo=timezone.utc))])

    def fake_rbob_closes(start=None, end=None):
        rbob_calls.append({"start": start, "end": end})
        return []

    def fake_gas_decisions(markets, aaa, rbob):
        captured["markets"] = markets
        captured["aaa"] = aaa
        captured["rbob"] = rbob
        return []

    monkeypatch.setattr(backtest_engines, "rbob_closes", fake_rbob_closes)
    monkeypatch.setattr(backtest_engines, "build_gas_decisions", fake_gas_decisions)
    monkeypatch.setattr(backtest_engines, "_histories", lambda *args, **kwargs: {})
    monkeypatch.setattr(backtest_engines, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row", lambda *args, **kwargs: {
        "engine": "gas", "mode": "taker", "n_decisions": 0, "n_fills": 0,
        "pnl_after_fees": 0.0, "max_drawdown": 0.0, "brier_ours": None,
        "brier_market": None, "gate_status": "SHADOW", "gate_reasons": [],
    })

    assert backtest_engines.main([
        "--engine", "gas", "--start", "2026-07-01", "--end", "2026-07-24", "--train-days", "90",
    ]) == 0
    assert rbob_calls == [{"start": date(2026, 4, 2), "end": date(2026, 7, 24)}]
    assert captured["markets"][0].ticker == raw["ticker"]


def test_fetch_weather_forecasts_is_bounded_concurrent_and_date_stable():
    days = [
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 4),
    ]
    barrier = Barrier(2)
    lock = Lock()
    active = 0
    peak_active = 0

    def fake_forecast(city, day, lead_days):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        barrier.wait(timeout=2)
        with lock:
            active -= 1
        return [Observation(f"forecast:{day}", float(day.day), datetime(2026, 7, 1, tzinfo=timezone.utc))]

    first = backtest_engines.fetch_weather_forecasts(
        NYC, days, forecast_fn=fake_forecast, max_workers=2,
    )
    second = backtest_engines.fetch_weather_forecasts(
        NYC, list(reversed(days)), forecast_fn=fake_forecast, max_workers=2,
    )

    assert set(first) == set(days)
    assert first == second
    assert peak_active == 2

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import Observation, check_no_lookahead
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.weather import WEATHER_CITIES
from tradehub.markets import parse_market
from tradehub.scripts.backtest_engines import (
    GAS_DECISION_LEAD,
    build_gas_decisions,
    build_weather_decisions,
    weather_decision_time,
)

NYC = WEATHER_CITIES["KXHIGHNY"]
EST = ZoneInfo("Etc/GMT+5")


def _wm(day: date):
    tag = day.strftime("%y%b%d").upper()
    close = datetime.combine(day + timedelta(days=1), datetime.min.time(), EST).astimezone(timezone.utc)
    return parse_market({"ticker": f"KXHIGHNY-{tag}-T74", "event_ticker": f"KXHIGHNY-{tag}", "strike_type": "greater",
                         "floor_strike": 74, "cap_strike": None, "open_time": "2026-06-01T00:00:00Z",
                         "close_time": close.isoformat().replace("+00:00", "Z"), "title": "NYC high"})


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
    rbob = [Observation(f"RBOB:{i}", 3.0 + 0.01 * i,
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


def test_built_decisions_run_through_the_backtester():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(3)]
    markets = [_wm(d) for d in days]
    decisions = build_weather_decisions(markets, {d: _fc(d, 80.0) for d in days}, [], NYC)
    histories = {m.ticker: MarketHistory(m.ticker, "yes", m.close_time,
                                         [Candle(dec.decided_at - timedelta(hours=1), 0.40, 0.44, 1.0)], [])
                 for m, dec in zip(markets, decisions)}
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    assert result.n_decisions == 3 and result.n_fills == 3 and result.pnl_after_fees > 0

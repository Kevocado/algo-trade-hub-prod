from datetime import date, timedelta

import pytest
from labor_fakes import synthetic_inputs

from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.labor_inputs import payroll_nowcasts
from tradehub.engines.labor import labor_market
from tradehub.scripts.backtest_labor import (
    build_labor_decisions,
    kalshi_implied_means,
    quoted_only,
    release_dates,
    settled_ladder,
)


def _raw(tag, floor, result, value, close):
    return {"ticker": f"KXPAYROLLS-{tag}-T{floor}", "event_ticker": f"KXPAYROLLS-{tag}", "strike_type": "greater",
            "floor_strike": floor, "open_time": "2013-01-01T00:00:00Z", "close_time": close, "title": "jobs",
            "result": result, "expiration_value": value}


RAWS = [
    _raw("13MAY", 0, "yes", "175,000", "2013-06-07T12:29:00Z"),
    _raw("13MAY", 200000, "no", "175,000", "2013-06-07T12:29:00Z"),
    _raw("13JUN", 0, "yes", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUN", 100000, "yes", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUN", 150000, "no", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUL", 0, "no", "", "2013-08-02T12:29:00Z"),  # no first print published: dropped
]


def test_release_dates_and_settled_ladder():
    assert release_dates(RAWS)[date(2013, 6, 1)] == date(2013, 7, 5)
    kept = settled_ladder(RAWS, date(2013, 6, 1), date(2013, 7, 1))
    assert [r["ticker"] for r in kept] == ["KXPAYROLLS-13JUN-T0", "KXPAYROLLS-13JUN-T100000", "KXPAYROLLS-13JUN-T150000"]


def _history(market, result, bid, ask):
    at = market.close_time - timedelta(hours=2)
    return MarketHistory(market.ticker, result, market.close_time, [Candle(at, bid, ask, 10.0)], [])


def test_labor_backtest_end_to_end_is_leak_free():
    raws = settled_ladder(RAWS, date(2013, 5, 1), date(2013, 6, 1))
    markets = [labor_market(r) for r in raws]
    nowcasts = payroll_nowcasts(synthetic_inputs(), [date(2013, 5, 1), date(2013, 6, 1)], {}, train_from=date(2010, 1, 1))
    decisions = build_labor_decisions(markets, nowcasts)
    assert len(decisions) == 5
    assert all(d.decided_at == m.close_time - timedelta(hours=1) for d, m in zip(decisions, markets))
    histories = {m.ticker: _history(m, r["result"], 0.40, 0.44) for m, r in zip(markets, raws)}
    histories[markets[0].ticker] = MarketHistory(markets[0].ticker, "yes", markets[0].close_time, [], [])  # unquoted
    quoted = quoted_only(decisions, histories)
    assert len(quoted) == 4
    result = run_backtest(engine="labor_nowcast", cadence="monthly", decisions=quoted, histories=histories)
    assert result.n_decisions == 4
    assert result.summary["brier_market"] is not None
    assert result.gate["status"] == "SHADOW"  # 4 contracts << the monthly minimum of 50
    means = kalshi_implied_means(markets, histories)
    assert set(means) == {date(2013, 6, 1)}  # May has one quoted strike: not a ladder
    # flat 0.42 ladder at cuts 0.5/100.5/150.5k, typical gap 75k: 0.58 * (0.5 - 37.5) + 0.42 * (150.5 + 37.5)
    assert means[date(2013, 6, 1)] == pytest.approx(0.58 * -37.0 + 0.42 * 188.0)


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


def test_throttled_get_json_spaces_calls_and_retries_429():
    responses = [_Resp(429), _Resp(200, {"ok": 1}), _Resp(200, {"ok": 2})]
    sleeps, clock = [], [0.0]

    def get(url, params=None, timeout=None):
        return responses.pop(0)

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    getter = ThrottledGetJson(min_interval=0.25, get=get, sleep=sleep, clock=lambda: clock[0])
    assert getter("u") == {"ok": 1}
    assert getter("u") == {"ok": 2}
    assert sleeps == [2.0, pytest.approx(0.25)]  # backoff after 429, then minimum spacing


def test_the_clis_only_call_methods_the_real_client_has():
    """`merged_settled_markets` was the plan's name for what is actually `settled_markets`
    (it already merges the historical and live endpoints and dedupes by ticker). The name no
    longer existed, and the first live run died with an AttributeError at the very first call --
    with 644 green tests, because the unit tests never construct a KalshiHistoryClient.

    This is the cheap structural guard for that whole class of drift.
    """
    import inspect
    import re

    from tradehub.backtest.kalshi_history import KalshiHistoryClient
    from tradehub.scripts import backtest_labor, build_jobs_scorecard

    for module in (backtest_labor, build_jobs_scorecard):
        source = inspect.getsource(module)
        for name in sorted(set(re.findall(r"\bclient\.(\w+)\(", source))):
            assert hasattr(KalshiHistoryClient, name), (
                f"{module.__name__} calls client.{name}(), which KalshiHistoryClient does not have"
            )


# ── --record must not be able to promote on non-point-in-time inputs ───────────

def test_record_guard_refuses_a_promoted_run_that_is_not_point_in_time():
    """The gate is the only thing that can promote labor_nowcast, so a PROMOTED run may only be
    stored when the inputs are demonstrably point-in-time. Before the vintage fix the weekly
    series came from ONE latest vintage, which `check_no_lookahead` cannot see: the Observation
    timestamps are the weeks' nominal publication dates either way."""
    from dataclasses import replace

    from tradehub.scripts.backtest_labor import record_guard

    inputs = synthetic_inputs()
    months = [date(2013, 5, 1), date(2013, 6, 1)]
    leaky = replace(inputs, icsa={date(2026, 9, 24): {date(2013, 8, 1): 1.0}}, ccsa={})

    with pytest.raises(SystemExit) as excinfo:
        record_guard({"gate_status": "PROMOTED"}, leaky, months)
    assert "refusing to record a PROMOTED run" in str(excinfo.value)

    # The real inputs pass, so a legitimate future promotion is not blocked by the interlock.
    assert record_guard({"gate_status": "PROMOTED"}, inputs, months) is None


def test_the_interlock_only_blocks_promotion():
    """SHADOW is this engine's expected outcome, and the plan's own validated result. Blocking it
    would make `--record` useless."""
    from dataclasses import replace

    from tradehub.scripts.backtest_labor import record_guard

    inputs = synthetic_inputs()
    months = [date(2013, 5, 1), date(2013, 6, 1)]
    leaky = replace(inputs, icsa={}, ccsa={})
    assert record_guard({"gate_status": "SHADOW"}, leaky, months) is None
    assert record_guard({}, leaky, months) is None

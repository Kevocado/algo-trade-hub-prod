import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import check_no_lookahead
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.markets import parse_cpi_market
from tradehub.scripts import backtest_engines
from tradehub.scripts.backtest_engines import CPI_DECISION_LEAD, build_cpi_decisions

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))
RAWS = {r["ticker"]: r for r in json.loads((FIXTURES / "kalshi_cpi_markets_trimmed.json").read_text(encoding="utf-8"))}
HISTORY = parse_nowcast_month(PAYLOAD)
UTC = timezone.utc


def test_decision_is_0800_et_on_release_morning_and_leakage_safe():
    market = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    [decision] = build_cpi_decisions([market], HISTORY)
    assert decision.decided_at == datetime(2026, 9, 11, 12, 0, tzinfo=UTC) == market.close_time - CPI_DECISION_LEAD
    check_no_lookahead(decision)
    names = [o.name for o in decision.features]
    assert names[0] == "CPI:2026-08@2026-09-10"  # the latest value usable at 08:00 ET
    assert "CPI:2026-08:actual" not in names      # its own print lands at 08:30 ET
    assert "CPI:2021-12:actual" in names          # the one earlier released month in the fixture
    assert decision.our_prob == pytest.approx(0.5244, abs=1e-4)


def test_extra_lead_uses_an_older_nowcast():
    market = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    [decision] = build_cpi_decisions([market], HISTORY, extra_lead=timedelta(days=7))
    assert decision.decided_at == datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    assert decision.features[0].name == "CPI:2026-08@2026-08-03"  # the Sep-10 value is not known yet
    check_no_lookahead(decision)


def test_months_without_a_nowcast_are_skipped():
    legacy = parse_cpi_market(RAWS["CPI-22AUG-TN0.4"])  # Aug 2022 is not in the trimmed fixture
    assert build_cpi_decisions([legacy], HISTORY) == []


def test_cpi_decisions_run_through_the_backtester():
    yes = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    no = parse_cpi_market(RAWS["KXCPI-26AUG-T0.4"])
    candle = [Candle(datetime(2026, 9, 11, 11, 0, tzinfo=UTC), 0.60, 0.62, 100.0)]
    histories = {m.ticker: MarketHistory(m.ticker, RAWS[m.ticker]["result"], m.close_time, candle, [])
                 for m in (yes, no)}
    result = run_backtest(engine="cpi_nowcast", cadence="monthly", decisions=build_cpi_decisions([yes, no], HISTORY),
                          histories=histories)
    assert result.n_decisions == 2
    assert result.summary["brier_market"] is not None


def test_backtest_cli_cpi_branch(monkeypatch):
    raws = [RAWS["KXCPI-26AUG-T0.3"], RAWS["KXCPI-26AUG-T0.4"], RAWS["CPI-22AUG-TN0.4"]]

    class FakeClient:
        def __init__(self):
            self.calls = []

        def settled_markets(self, series):
            self.calls.append(series)
            return raws

    client = FakeClient()
    captured = {}
    kinds = []

    def fake_histories(client, markets, results, mode, lookback=None):
        captured["lookback"] = lookback
        captured["history_tickers"] = sorted(m.ticker for m in markets)
        quoted = [Candle(datetime(2026, 9, 11, 11, 0, tzinfo=UTC), 0.60, 0.62, 100.0)]
        return {m.ticker: MarketHistory(m.ticker, results[m.ticker], m.close_time,
                                        quoted if m.ticker.endswith("T0.3") else [], [])
                for m in markets}

    def fake_run_backtest(**kwargs):
        captured["cadence"] = kwargs["cadence"]
        captured["scored"] = [d.market_ticker for d in kwargs["decisions"]]
        return object()

    def fake_build_row(result, **kwargs):
        captured.update(kwargs)
        return {k: None for k in ("engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                                  "brier_ours", "brier_market", "gate_status", "gate_reasons")}

    def fake_nowcast(kind):
        kinds.append(kind)
        return HISTORY

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", lambda: client)
    monkeypatch.setattr(backtest_engines, "fetch_nowcast_history", fake_nowcast)
    monkeypatch.setattr(backtest_engines, "_histories", fake_histories)
    monkeypatch.setattr(backtest_engines, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row", fake_build_row)

    assert backtest_engines.main(["--engine", "cpi_nowcast", "--start", "2026-08-01", "--end", "2026-08-31"]) == 0
    assert client.calls == ["KXCPI"] and kinds == ["headline"]
    assert captured["history_tickers"] == ["KXCPI-26AUG-T0.3", "KXCPI-26AUG-T0.4"]  # Aug 2022 filtered by date
    assert captured["lookback"] == timedelta(days=3)
    assert captured["scored"] == ["KXCPI-26AUG-T0.3"]  # T0.4 had no quote at decision time
    assert captured["cadence"] == "monthly"
    assert captured["engine_version"] == "cpi-v1"
    assert captured["config"]["lead_days"] == 0 and captured["config"]["series"] == "KXCPI"
    assert captured["date_from"] == datetime(2026, 8, 1, tzinfo=UTC)


def test_backtest_cli_core_series_uses_core_nowcast(monkeypatch):
    kinds = []
    captured = {}

    class FakeClient:
        def settled_markets(self, series):
            return []

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", FakeClient)
    monkeypatch.setattr(backtest_engines, "fetch_nowcast_history", lambda kind: kinds.append(kind) or {})
    monkeypatch.setattr(backtest_engines, "_histories", lambda *a, **k: {})
    monkeypatch.setattr(backtest_engines, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row",
                        lambda result, **kw: captured.update(kw) or {k: None for k in (
                            "engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                            "brier_ours", "brier_market", "gate_status", "gate_reasons")})
    assert backtest_engines.main(["--engine", "cpi_nowcast", "--series", "KXCPICORE",
                                  "--start", "2026-01-01", "--end", "2026-08-31", "--lead-days", "7"]) == 0
    assert kinds == ["core"]
    assert captured["engine_version"] == "cpi-core-v1" and captured["config"]["lead_days"] == 7

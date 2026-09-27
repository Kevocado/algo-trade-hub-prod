"""`--gas-lead-hours` exists to answer one question, so it is pinned by the behaviour it must have.

The redesign hypothesis for the gas engine (spec §5) was that it loses because it is asked 2h before
close, when Kalshi has already priced the AAA print almost exactly (market Brier 0.0268). If that were
the cause, deciding earlier would help. Measured on 2026-06-01..2026-09-20 over 1982 decisions, it does
not:

    lead   n      fills  brier_ours  brier_market  ours/market
      2h   1982     274   0.1148      0.02676       4.29x
     12h   1944     405   0.11216     0.0519        2.16x
     24h      0       0   null        null          -- no quotes; the contract does not exist yet

The model's own Brier barely moves (0.1148 -> 0.1122) while the market's doubles, so deciding earlier
does not make the model smarter, it only moves the comparison to a point where the market is less
efficient. At every lead where the market exists, the model is still worse than it. That is why this
flag is worth having in the repo rather than as a one-off command: the number above should be
reproducible by anyone who disagrees with the conclusion.

Two properties are pinned here, and the second is the one that would actually cause harm:

- **The default is the production 2h.** A diagnostic flag that silently moved the decision time would
  make every backtest number already recorded a lie.
- **The lead travels with the result.** It is recorded in the run config and printed, so a Brier can
  never be read without the lead it was measured at.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tradehub.scripts import backtest_engines as backtest_engines
from tradehub.backtest.pit import Observation

MARKET = {
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

EMPTY_ROW = {
    "engine": "gas", "mode": "taker", "n_decisions": 0, "n_fills": 0,
    "pnl_after_fees": 0.0, "max_drawdown": 0.0, "brier_ours": None,
    "brier_market": None, "gate_status": "SHADOW", "gate_reasons": [],
}


def _run_cli(monkeypatch, extra_argv: list[str], spy: dict | None = None) -> dict:
    """Drive the real CLI with every network/DB seam faked, and return what the decision builder saw."""
    captured: dict = {}

    class FakeClient:
        def settled_markets(self, series):
            return [MARKET]

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", FakeClient)
    monkeypatch.setattr(
        backtest_engines, "settlement_observations",
        lambda raws: [Observation("KXAAAGASD-26JUL23", 4.0, datetime(2026, 7, 23, 12, tzinfo=timezone.utc))],
    )
    monkeypatch.setattr(backtest_engines, "rbob_closes", lambda start=None, end=None: [])
    monkeypatch.setattr(backtest_engines, "_histories", lambda *a, **k: {})

    def fake_build(markets, aaa, rbob, *, roll_dates, decision_lead=None):
        captured["decision_lead"] = decision_lead
        return []

    monkeypatch.setattr(backtest_engines, "build_gas_decisions", fake_build)
    monkeypatch.setattr(backtest_engines, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda d, h: "hash")
    def fake_row(*a, **kwargs):
        # `spy` lets a test observe the recorded config; without one this is a plain stub.
        if spy is not None:
            spy.update(kwargs)
        return dict(EMPTY_ROW)

    monkeypatch.setattr(backtest_engines, "build_backtest_run_row", fake_row)

    exit_code = backtest_engines.main([
        "--engine", "gas", "--start", "2026-08-01", "--end", "2026-08-02", *extra_argv,
    ])
    assert exit_code == 0
    return captured


def test_the_default_lead_is_the_production_two_hours():
    """Read off the function, not the CLI: this is the value an in-process caller gets."""
    assert backtest_engines.GAS_DECISION_LEAD == timedelta(hours=2)
    assert backtest_engines.build_gas_decisions.__kwdefaults__["decision_lead"] == timedelta(hours=2)


def test_the_cli_defaults_to_the_production_lead(monkeypatch):
    """End to end through argparse, so the default cannot drift from the constant it mirrors."""
    assert _run_cli(monkeypatch, [])["decision_lead"] == timedelta(hours=2)


@pytest.mark.parametrize("hours", ["6", "12", "24"])
def test_the_flag_reaches_the_decision_builder(monkeypatch, hours):
    assert _run_cli(monkeypatch, ["--gas-lead-hours", hours])["decision_lead"] == timedelta(hours=float(hours))


def test_the_lead_is_recorded_in_the_run_config(monkeypatch):
    """Provenance. `config` is what a recorded `backtest_runs` row stores, so the lead has to live
    there -- otherwise a stored row cannot say what it measured, which is how the 2h assumption ended
    up baked into every gas number in the reports without anyone re-deriving it."""
    seen: dict = {}
    _run_cli(monkeypatch, ["--gas-lead-hours", "12"], spy=seen)

    assert seen["config"]["decision_lead_hours"] == 12.0


def test_the_printed_result_states_the_lead_it_was_measured_at(monkeypatch, capsys):
    """A Brier printed without its lead is how lead comparisons get misquoted later."""
    _run_cli(monkeypatch, ["--gas-lead-hours", "12"])
    printed = capsys.readouterr().out

    assert "decision_lead_hours" in printed
    assert "12.0" in printed

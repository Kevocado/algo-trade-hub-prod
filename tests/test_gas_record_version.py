"""A recorded backtest must say which decision lead produced it, or an experiment can decide the gate.

Review of #24: `--gas-lead-hours` was added so the "decide earlier" hypothesis could be tested, and the
lead was printed and stored in the run `config`. But the row's `engine_version` stayed `gas-v1`
regardless, and `engine_version` is the field the promotion evidence is keyed on. So a run at a 12h
lead was written into `backtest_runs` looking exactly like a production 2h run, and nothing downstream
could tell them apart.

That is the specific failure this pins: the whole point of #24 was that *the lead changes the answer*
(gas is 4.29x behind the market at 2h and 2.16x at 12h). A recorded run that hides the lead turns the
experiment into apparent production evidence, and an experiment can then decide the production gate.

Tagging rather than refusing, which review offered as the alternative: refusing would throw away the
evidence, and the experiment is worth keeping precisely because it is informative. A tag makes the row
self-describing and keeps it out of the production population by construction.
"""
import pytest

from tradehub.engines.gas import GAS_ENGINE_VERSION
from tradehub.scripts import backtest_engines as be
from tradehub.backtest.pit import Observation
from datetime import datetime, timezone

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


def _run_cli(monkeypatch, extra_argv, spy=None):
    """Always returns the captured build_backtest_run_row kwargs, creating the dict if the caller did
    not pass one -- otherwise a caller that forgets to supply a spy gets None back and the failure
    reads as a NoneType subscript rather than as the real problem."""
    spy = {} if spy is None else spy

    class FakeClient:
        def settled_markets(self, series):
            return [MARKET]

    monkeypatch.setattr(be, "KalshiHistoryClient", FakeClient)
    monkeypatch.setattr(
        be, "settlement_observations",
        lambda raws: [Observation("KXAAAGASD-26JUL23", 4.0, datetime(2026, 7, 23, 12, tzinfo=timezone.utc))],
    )
    monkeypatch.setattr(be, "rbob_closes", lambda start=None, end=None: [])
    monkeypatch.setattr(be, "_histories", lambda *a, **k: {})
    monkeypatch.setattr(be, "build_gas_decisions", lambda *a, **k: [])
    monkeypatch.setattr(be, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(be, "data_snapshot_hash", lambda d, h: "hash")

    def fake_row(*a, **kwargs):
        if spy is not None:
            spy.update(kwargs)
        return dict(EMPTY_ROW)

    monkeypatch.setattr(be, "build_backtest_run_row", fake_row)
    assert be.main(["--engine", "gas", "--start", "2026-08-01", "--end", "2026-08-02", *extra_argv]) == 0
    return spy


def test_the_production_lead_keeps_the_production_engine_version(monkeypatch):
    """A default run must stay `gas-v1`. Changing this would orphan every recorded gas run already
    in the table, and it is the only value the promotion evidence is keyed on."""
    spy = _run_cli(monkeypatch, [])

    assert spy["engine_version"] == GAS_ENGINE_VERSION == "gas-v1"


def test_a_non_default_lead_is_tagged_so_it_cannot_masquerade_as_production(monkeypatch):
    spy = _run_cli(monkeypatch, ["--gas-lead-hours", "12"])

    assert spy["engine_version"] == "gas-v1-lead12h"
    assert spy["engine_version"] != GAS_ENGINE_VERSION


@pytest.mark.parametrize(
    ("hours", "expected"),
    [("6", "gas-v1-lead6h"), ("6.5", "gas-v1-lead6.5h"), ("24", "gas-v1-lead24h")],
)
def test_the_tag_names_the_lead_exactly_including_a_fractional_one(monkeypatch, hours, expected):
    spy = _run_cli(monkeypatch, ["--gas-lead-hours", hours])

    assert spy["engine_version"] == expected


def test_the_tagged_version_still_records_the_lead_in_the_config(monkeypatch):
    """Both places, for different readers: `engine_version` for the promotion evidence,
    `config` for anyone reading the run's parameters."""
    spy = _run_cli(monkeypatch, ["--gas-lead-hours", "12"])

    assert spy["config"]["decision_lead_hours"] == 12.0


def test_a_lead_explicitly_set_to_the_production_value_is_not_tagged(monkeypatch):
    """`--gas-lead-hours 2` is the production run, and must be recorded as such. Tagging it would
    split the production population for no reason."""
    spy = _run_cli(monkeypatch, ["--gas-lead-hours", "2"])

    assert spy["engine_version"] == GAS_ENGINE_VERSION


def test_the_gas_lead_never_touches_another_engine_version(monkeypatch):
    """The version is chosen per engine, so the gas lead must not leak into weather or CPI."""
    captured = {}

    monkeypatch.setattr(be, "KalshiHistoryClient", type("C", (), {"settled_markets": lambda s, series: []}))
    monkeypatch.setattr(be, "load_weather_inputs", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(be, "build_weather_decisions", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(be, "settlement_observations", lambda raws: [])
    monkeypatch.setattr(be, "rbob_closes", lambda start=None, end=None: [])
    monkeypatch.setattr(be, "_histories", lambda *a, **k: {})
    monkeypatch.setattr(be, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(be, "data_snapshot_hash", lambda d, h: "hash")

    def fake_row(*a, **kwargs):
        captured.update(kwargs)
        return dict(EMPTY_ROW, engine="weather")

    monkeypatch.setattr(be, "build_backtest_run_row", fake_row)
    be.main(["--engine", "weather", "--start", "2026-08-01", "--end", "2026-08-02"])

    assert captured["engine_version"] == be.WEATHER_ENGINE_VERSION
    assert "lead" not in captured["engine_version"]

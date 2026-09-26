"""Task 6: scan KXPAYROLLS with labor_nowcast (MACRO edges, isolated, 3 runs a day).

The plan's wiring predates step 6 and 7b: `scan.main` now runs every engine through
`run_engine`, looks the promotion gate up per (engine, engine_version) pair across all produced
edges, writes and cleans up per engine behind a "ran AND wrote ok" guard, and runs sports last.
So labor is wired in as a peer of cpi_nowcast rather than appended to one big write, and the
main()-level tests below mirror the CPI ones.
"""
import json
from datetime import date, datetime, timezone

import pytest
from labor_fakes import synthetic_inputs

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.labor import labor_market
from tradehub.scripts import scan

QUOTE = Quote(yes_bid=0.02, yes_ask=0.05, yes_bid_size=10.0, yes_ask_size=10.0)
NOW = datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc)


def _lm(month_tag, floor, close):
    ticker = f"KXPAYROLLS-{month_tag}-T{floor}"
    return LiveMarket(labor_market({"ticker": ticker, "event_ticker": f"KXPAYROLLS-{month_tag}",
                                    "strike_type": "greater", "floor_strike": floor,
                                    "open_time": "2014-05-01T00:00:00Z", "close_time": close,
                                    "title": ticker}), QUOTE)


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def test_scan_labor_predicts_only_months_that_have_ended():
    now = datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc)
    may = [_lm("14MAY", 0, "2014-06-06T12:29:00Z"), _lm("14MAY", 150000, "2014-06-06T12:29:00Z")]
    june = [_lm("14JUN", 0, "2014-07-03T12:29:00Z")]  # June has not ended: no nowcast yet
    calls = []

    def inputs_fn(**kwargs):
        calls.append(kwargs)
        return synthetic_inputs()

    preds, edges = scan.scan_labor(FakeLive(may + june), now, EngineConfig(min_edge_pct=5.0), inputs_fn=inputs_fn)
    assert {p["market_ticker"] for p in preds} == {"KXPAYROLLS-14MAY-T0", "KXPAYROLLS-14MAY-T150000"}
    assert all(p["engine"] == "labor_nowcast" and p["engine_version"] == "labor-v1" for p in preds)
    assert calls[0]["releases"] == {date(2014, 5, 1): date(2014, 6, 6)} and calls[0]["as_of"] == date(2014, 6, 3)
    assert calls[0]["with_adp"] is False  # the core feature set does not use ADP
    assert preds[0]["raw_payload"]["month"] == "2014-05-01" and preds[0]["raw_payload"]["n_train"] > 24
    zero = next(p for p in preds if p["market_ticker"].endswith("T0"))
    assert zero["our_prob"] > 0.9
    assert all(e["edge_type"] == "MACRO" for e in edges)
    assert {e["market_ticker"] for e in edges} >= {"KXPAYROLLS-14MAY-T0"}  # P(>0) >> 0.05 ask


def test_scan_labor_skips_fetching_when_nothing_is_due():
    def inputs_fn(**_kwargs):
        raise AssertionError("must not fetch")

    june = [_lm("14JUN", 0, "2014-07-03T12:29:00Z")]
    now = datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc)
    assert scan.scan_labor(FakeLive(june), now, EngineConfig(min_edge_pct=5.0), inputs_fn=inputs_fn) == ([], [])


def test_every_labor_edge_is_shadow_and_carries_the_engine_version():
    """Kevin's decision: a losing engine's edges are still written, carry engine + engine_version
    and are tagged SHADOW. `edge_row` defaults SHADOW, so the pair gate can key on this version
    and a new model version starts at SHADOW on its own."""
    may = [_lm("14MAY", 0, "2014-06-06T12:29:00Z")]
    _, edges = scan.scan_labor(FakeLive(may), NOW, EngineConfig(min_edge_pct=5.0),
                              inputs_fn=lambda **k: synthetic_inputs())
    assert edges, "no edge to check"
    for edge in edges:
        assert edge["engine"] == "labor_nowcast"
        assert edge["engine_version"] == "labor-v1", edge
        assert edge["gate_status"] == "SHADOW", edge


def test_repo_config_has_labor_nowcast():
    cfg = load_engine_config("labor_nowcast")
    assert cfg.min_edge_pct > 0 and cfg.prefer_maker is True


def test_run_labor_step_runs_three_times_a_day_and_isolates_errors():
    live = FakeLive([])
    at_7 = datetime(2026, 10, 2, 11, 5, tzinfo=timezone.utc)   # 07:05 ET
    at_9 = datetime(2026, 10, 2, 13, 5, tzinfo=timezone.utc)   # 09:05 ET
    cfg = EngineConfig(min_edge_pct=5.0)

    def boom(*_a, **_k):
        raise RuntimeError("ALFRED down")

    assert scan.run_labor_step(live, at_9, cfg, scan_fn=boom) == ([], [], "skipped")
    assert scan.run_labor_step(live, at_7, cfg, scan_fn=lambda *a, **k: ([{"p": 1}], [])) == ([{"p": 1}], [], "ok")
    preds, edges, status = scan.run_labor_step(live, at_7, cfg, scan_fn=boom)
    assert (preds, edges) == ([], []) and status.startswith("error: RuntimeError")


def test_labor_scan_due_hours_are_eastern():
    """07:05 ET is the last run before the 08:30 release, so the hours are Eastern in summer and
    in winter -- a UTC-hour gate would fire at the wrong time for half the year."""
    assert scan.labor_scan_due(datetime(2026, 10, 2, 11, 5, tzinfo=timezone.utc))    # 07:05 EDT
    assert scan.labor_scan_due(datetime(2026, 1, 15, 12, 5, tzinfo=timezone.utc))    # 07:05 EST
    assert scan.labor_scan_due(datetime(2026, 10, 2, 16, 5, tzinfo=timezone.utc))    # 12:05 EDT
    assert scan.labor_scan_due(datetime(2026, 10, 2, 21, 5, tzinfo=timezone.utc))    # 17:05 EDT
    assert not scan.labor_scan_due(datetime(2026, 10, 2, 13, 5, tzinfo=timezone.utc))  # 09:05 EDT
    assert scan.LABOR_SCAN_HOURS_ET == (7, 12, 17)


# ── main()-level: isolation, gating and cleanup, mirroring the CPI tests ───────

def _base(monkeypatch, *, labor_due=True, labor_scan=None, upserted=None, cleaned=None, gate=None):
    from tradehub import predictions
    from tradehub.core import supabase_client

    monkeypatch.setattr(supabase_client, "get_client", lambda: "client")
    monkeypatch.setattr(supabase_client, "upsert_opportunities",
                        lambda rows: upserted.extend(rows) if upserted is not None else None)
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_stale_edges",
                        lambda client, produced: cleaned.append(produced) if cleaned is not None else None)
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "latest_gate_statuses", gate or (lambda client, pairs: {}))
    monkeypatch.setattr(scan, "labor_scan_due", lambda now: labor_due)
    if labor_scan is not None:
        monkeypatch.setattr(scan, "scan_labor", labor_scan)
    else:
        monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([], []))


def test_main_isolates_a_labor_failure(monkeypatch, capsys):
    """An ALFRED outage must not cost the other engines their writes, and must be visible."""
    _base(monkeypatch, labor_scan=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("alfred down")))

    def boom(*_a, **_k):
        raise RuntimeError("alfred down")

    monkeypatch.setattr(scan, "scan_labor", boom)
    assert scan.main(now=NOW, live=object(), client=object()) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["labor_nowcast"]["status"].startswith("error: RuntimeError"), summary["labor_nowcast"]
    assert summary["labor_nowcast"]["predictions"] == 0
    assert summary["writes"]["predictions"]["weather"] == "ok", summary["writes"]


def test_a_labor_failure_is_logged_with_a_traceback(monkeypatch, caplog):
    import logging
    _base(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("alfred down")

    monkeypatch.setattr(scan, "scan_labor", boom)
    with caplog.at_level(logging.ERROR):
        scan.main(now=NOW, live=object(), client=object())
    assert any(r.exc_info for r in caplog.records), "the labor failure was logged without a traceback"


def test_main_gates_labor_edges_per_engine_version(monkeypatch):
    upserted: list = []
    seen_pairs: list = []

    def gate(client, pairs):
        seen_pairs.append(set(pairs))
        return {("labor_nowcast", "labor-v1"): "PROMOTED"}

    _base(monkeypatch, upserted=upserted, gate=gate)
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([], [
        {"market_ticker": "A", "engine": "labor_nowcast", "engine_version": "labor-v1"},
    ]))
    assert scan.main(now=NOW, live=object(), client=object()) == 0
    # Labor has its own gate lookup (it runs after the shared one, so a hung ALFRED cannot delay
    # the other engines' writes), so the pair must appear in SOME lookup, not the first.
    assert any(("labor_nowcast", "labor-v1") in pairs for pairs in seen_pairs), (
        f"labor's (engine, engine_version) pair was not part of any gate lookup: {seen_pairs}"
    )
    assert [r["gate_status"] for r in upserted if r["engine"] == "labor_nowcast"] == ["PROMOTED"]


def test_an_unmatched_labor_version_fails_closed_to_shadow(monkeypatch):
    """A new model version must not inherit another version's promotion."""
    upserted: list = []
    _base(monkeypatch, upserted=upserted, gate=lambda client, pairs: {
        ("labor_nowcast", "labor-v1"): "PROMOTED",
    })
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([], [
        {"market_ticker": "A", "engine": "labor_nowcast", "engine_version": "labor-v2"},
    ]))
    assert scan.main(now=NOW, live=object(), client=object()) == 0
    assert [r["gate_status"] for r in upserted if r["engine"] == "labor_nowcast"] == ["SHADOW"]


@pytest.mark.parametrize("due", [True, False])
def test_labor_cleanup_runs_only_on_a_due_hour_with_a_successful_write(monkeypatch, due):
    cleaned: list = []
    _base(monkeypatch, labor_due=due, cleaned=cleaned)
    edge = {"market_ticker": "KXPAYROLLS-14MAY-T0", "engine": "labor_nowcast",
            "engine_version": "labor-v1", "edge_type": "MACRO"}
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([], [edge] if due else []))

    assert scan.main(now=NOW, live=object(), client=object()) == 0
    labor_cleaned = [produced for call in cleaned for name, produced in call.items()
                     if name == "labor_nowcast"]
    assert bool(labor_cleaned) is due


def test_a_failed_labor_edge_write_does_not_prune(monkeypatch):
    """The 'ran AND wrote ok' guard: a failed upsert must never read as 'this engine produced
    nothing', which would delete live edges."""
    from tradehub import predictions
    from tradehub.core import supabase_client

    cleaned: list = []
    _base(monkeypatch, cleaned=cleaned)
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)

    def failing_upsert(rows):
        if rows and rows[0].get("engine") == "labor_nowcast":
            raise RuntimeError("write failed")

    monkeypatch.setattr(supabase_client, "upsert_opportunities", failing_upsert)
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([], [
        {"market_ticker": "A", "engine": "labor_nowcast", "engine_version": "labor-v1"},
    ]))
    assert scan.main(now=NOW, live=object(), client=object()) == 1
    assert not [name for call in cleaned for name in call if name == "labor_nowcast"], cleaned


def test_labor_is_in_the_stale_edge_allowlist():
    """`remove_stale_edges` is engine-scoped by allowlist; without labor in it the cleanup call
    is a silent no-op and stale payroll edges would stay up for ever."""
    import inspect
    source = inspect.getsource(scan.remove_stale_edges)
    assert "labor_nowcast" in source, source

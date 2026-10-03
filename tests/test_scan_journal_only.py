"""CPI and labor are journal engines: the scan no longer writes their `predictions` rows (plan 14).

Labor is the live case: the scan still runs the labor step, still refuses to write its `predictions`
rows and still reports where they went. CPI is the other half of the set but the scan has no CPI step
any more -- the journal is the only producer of a CPI forecast -- so it is exercised through
`JOURNAL_ONLY_ENGINES` below rather than through a write.

Their edges, cleanup and gate lookups are unchanged. Weather, gas and sports keep writing `predictions`:
weather and gas have no journal scorecard, and sports rows are the edge ledger the reviewer scorecard
settles against (every rung of a ladder, not the one the journal picks).
"""
from datetime import datetime, timezone

from test_scan_labor import _base

from tradehub.scripts import scan
from tradehub.scripts.scan import JOURNAL_ONLY_ENGINES

NOW = datetime(2026, 10, 2, 11, 5, tzinfo=timezone.utc)


def _pred(engine, ticker):
    return {"engine": engine, "market_ticker": ticker, "our_prob": 0.5}


def _run(monkeypatch, recorded):
    import tradehub.predictions as predictions

    _base(monkeypatch)
    monkeypatch.setattr(predictions, "record_predictions", lambda client, rows: recorded.extend(rows))
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([_pred("weather", "W")], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([_pred("gas", "G")], []))
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([_pred("labor_nowcast", "L")], [], "ok", []))
    return scan.main(now=NOW, live=object(), client=object())


def test_the_journal_engines_are_named_once():
    assert JOURNAL_ONLY_ENGINES == frozenset({"cpi_nowcast", "labor_nowcast"})


def test_labor_predictions_are_not_written_but_weather_and_gas_still_are(monkeypatch):
    recorded: list = []
    assert _run(monkeypatch, recorded) == 0
    assert sorted(r["engine"] for r in recorded) == ["gas", "weather"]


def test_the_run_summary_says_where_the_labor_rows_went(monkeypatch, capsys):
    _run(monkeypatch, [])
    out = capsys.readouterr().out
    assert '"labor_nowcast": "journal"' in out, out
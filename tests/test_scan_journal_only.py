"""CPI and labor are journal engines: the scan no longer writes their `predictions` rows (plan 14).

Labor is the live case: the scan still runs the labor step, still refuses to write its `predictions`
rows and still reports where they went. CPI is the other half of the set but the scan has no CPI step
any more -- the journal is the only producer of a CPI forecast -- so nothing exercises a CPI write.

Their edges, cleanup and gate lookups are unchanged. Weather, gas and sports keep writing `predictions`:
weather and gas have no journal scorecard, and sports rows are the edge ledger the reviewer scorecard
settles against (every rung of a ladder, not the one the journal picks).
"""
from datetime import datetime, timezone

from test_scan_labor import _base

from tradehub.scripts import scan

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


def test_the_shared_prediction_write_loop_has_no_journal_only_branch_left():
    """A guard that cannot fire reads as a guard that can.

    `main()` tested `JOURNAL_ONLY_ENGINES` before writing each engine's predictions, which is what #72
    put there for `cpi_nowcast` -- and #92 then deleted the CPI scan step, which removed the ONLY engine
    in that loop the set could ever match. Weather and gas are not journal forecasters (`registry.py`
    builds no weather or gas forecaster at all), so the branch is unreachable. The set outlived its
    subject.

    Labor's suppression is not this branch and never depended on it: it is an unconditional
    `writes["predictions"]["labor_nowcast"] = "journal"` in labor's own block, so deleting the guard
    changes no behaviour. What deleting it removes is the false claim that this loop consults a list --
    the next engine added here would read the loop as protected and get a `predictions` row written for
    a journal engine, on the strength of a set that no longer exists. If a journal engine is ever added
    to this loop, this test is what should fail first.
    """
    import inspect

    assert "JOURNAL_ONLY_ENGINES" not in inspect.getsource(scan.main), (
        "the shared write loop still guards on a set no engine in it can match")
    assert not hasattr(scan, "JOURNAL_ONLY_ENGINES"), (
        "a set of journal-only engines that nothing reads is left behind in tradehub.scripts.scan")


def test_labor_predictions_are_not_written_but_weather_and_gas_still_are(monkeypatch):
    recorded: list = []
    assert _run(monkeypatch, recorded) == 0
    assert sorted(r["engine"] for r in recorded) == ["gas", "weather"]


def test_the_run_summary_says_where_the_labor_rows_went(monkeypatch, capsys):
    _run(monkeypatch, [])
    out = capsys.readouterr().out
    assert '"labor_nowcast": "journal"' in out, out
"""The closed-CPI-edge cleanup must be independent of the CPI engine's own schedule.

`cpi_scan_due` is true at only 08:00/12:00/16:00 ET, but the closed-market cleanup has to run on
EVERY hourly scan: an edge from the 08:05 run for a market that closes at 08:25 must be gone
before the 09:00 scan, not at noon. These tests pin that at main() level, and pin that a failing
cleanup is reported without taking the rest of the scan down with it.
"""
from datetime import datetime, timezone

from tradehub.scripts import scan as scan_mod

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)   # 09:00 ET, so cpi_scan_due would be False


def _run_main(monkeypatch, *, cpi_due, closed_raises=False):
    """Drive main() with every other engine stubbed out. Returns (rc, closed_calls, upserts, cleanups)."""
    from tradehub.core import supabase_client
    import tradehub.predictions as predictions

    closed_calls: list[bool] = []
    upserts: list[list] = []
    cleanups: list[dict] = []

    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: cpi_due)
    # Stub the CPI scan itself: these tests are about the cleanup's schedule and failure
    # handling, and `object()` has no `open_markets`.
    monkeypatch.setattr(scan_mod, "scan_cpi", lambda live, now, cfg: ([], []))
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda client, produced: cleanups.append(produced))
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserts.append(rows))

    def closed(client, now):
        closed_calls.append(now)
        if closed_raises:
            raise RuntimeError("supabase down")

    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", closed)
    # The labor closed-market cleanup has its own schedule and its own tests; stub it here so
    # these stay about the CPI one.
    monkeypatch.setattr(scan_mod, "remove_closed_labor_edges", lambda *a, **k: None)
    rc = scan_mod.main(now=NOW, live=object(), client=object())
    return rc, closed_calls, upserts, cleanups


def test_closed_cpi_cleanup_runs_on_a_non_cpi_due_hour(monkeypatch):
    """09:00 ET is not a CPI scan hour; the cleanup must still fire."""
    rc, closed_calls, _upserts, _cleanups = _run_main(monkeypatch, cpi_due=False)
    assert closed_calls == [NOW], "cleanup was skipped because cpi_scan_due was False"
    assert rc == 0


def test_closed_cpi_cleanup_runs_on_a_cpi_due_hour_too(monkeypatch):
    rc, closed_calls, _upserts, _cleanups = _run_main(monkeypatch, cpi_due=True)
    assert closed_calls == [NOW]
    assert rc == 0


def test_a_failing_closed_cleanup_is_reported_but_does_not_stop_the_scan(monkeypatch, capsys):
    """A cleanup failure must land in `failures` and be visible in the summary, while the
    weather/gas/CPI upserts and stale-edge cleanups still run."""
    rc, closed_calls, upserts, cleanups = _run_main(monkeypatch, cpi_due=False, closed_raises=True)

    assert closed_calls == [NOW], "the cleanup must have been attempted"
    assert rc == 1, "a failed cleanup must be reported in the exit code"
    import json
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "partial_failure"
    assert any("supabase down" in f for f in summary["failures"]), summary["failures"]
    assert any("closed_cleanup" in f for f in summary["failures"]), summary["failures"]
    # The rest of the scan is unaffected.
    assert upserts, "the engine upserts must still run after a cleanup failure"
    assert cleanups, "the other engines' stale-edge cleanup must still run"

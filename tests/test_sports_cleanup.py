"""Finding 3: sports edges were never cleaned up.

`remove_stale_edges` is scoped to an allowlist of engines, and main() only looped over
weather and gas, so every sports edge ever produced stayed in kalshi_edges forever. The
/api/sports-edges endpoint filters on start_utc in Python so the UI hid them, but the table
grew without bound.

The safety rules that matter:
- only clean up an engine whose edge write SUCCEEDED this run (a failed upsert must not be
  read as "the engine produced nothing", which would delete live edges);
- only clean up when the sport engine actually RAN (sports runs every 3rd hour, so a
  not-due hour must not prune);
- a crashed or not-due sports scan must not prune.
"""
import inspect
from datetime import datetime, timezone

from tradehub.scripts import scan as scan_mod

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
SPORT_EDGES = [{"market_ticker": "T1", "edge_type": "SPORTS", "engine": "sports_nfl",
                "engine_version": "feed:v1", "gate_status": "SHADOW"}]
SPORT_RESULT = ([{"engine": "sports_nfl", "market_ticker": "T1"}], SPORT_EDGES, {"nfl": {"matched": 1}})


def _sports_cleanup_calls(calls):
    return [produced for call in calls for name, produced in call.items() if name.startswith("sports")]


def _run_main(monkeypatch, *, sports_due=True, sports_result=SPORT_RESULT,
              sports_raises=False, edge_write_ok=True):
    """Drive scan.main() with sports stubbed on scan's own reference. Returns (rc, cleanup calls)."""
    from tradehub.core import supabase_client
    import tradehub.predictions as predictions

    calls = []
    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: sports_due)
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda client, produced: calls.append(produced))
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)

    def fake_upsert(rows):
        if rows and rows[0].get("edge_type") == "SPORTS" and not edge_write_ok:
            raise RuntimeError("edge write failed")

    monkeypatch.setattr(supabase_client, "upsert_opportunities", fake_upsert)

    if sports_raises:
        def boom(now, supa, **k):
            raise RuntimeError("kalshi down")
        monkeypatch.setattr(scan_mod, "run_sports_for_cron", boom)
    elif sports_due:
        monkeypatch.setattr(scan_mod, "run_sports_for_cron", lambda now, supa, **k: sports_result)
    else:
        def must_not_run(now, supa, **k):
            raise AssertionError("sports scan ran on a not-due hour")
        monkeypatch.setattr(scan_mod, "run_sports_for_cron", must_not_run)

    return scan_mod.main(now=NOW, live=object(), client=object()), calls


def test_cleanup_allowlist_includes_the_sport_engines():
    """Structural guard: a refactor must not quietly drop sports from the cleanup scope."""
    source = inspect.getsource(scan_mod.remove_stale_edges)
    assert "sports_nfl" in source and "sports_cfb" in source


def test_sports_cleanup_runs_after_a_successful_write(monkeypatch):
    rc, calls = _run_main(monkeypatch)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == [{"T1"}]


def test_sports_cleanup_is_skipped_when_the_edge_write_fails(monkeypatch):
    """A failed upsert must never be read as 'the engine produced nothing'."""
    rc, calls = _run_main(monkeypatch, edge_write_ok=False)
    assert _sports_cleanup_calls(calls) == [], "cleanup ran despite a failed sports edge write"
    assert rc == 1, "the failed write must still be reported"


def test_sports_cleanup_is_skipped_when_the_sport_scan_crashed(monkeypatch):
    rc, calls = _run_main(monkeypatch, sports_raises=True)
    assert _sports_cleanup_calls(calls) == [], "cleanup ran despite the sports scan crashing"
    assert rc == 0, "a sports outage must not fail the whole scan"


def test_sports_cleanup_is_skipped_on_a_not_due_hour(monkeypatch):
    rc, calls = _run_main(monkeypatch, sports_due=False)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == []


def test_a_silent_sport_cannot_prune_another_sport(monkeypatch):
    """If the NFL feed 404s and CFB works, only CFB is pruned. An engine that produced
    nothing this run is left alone rather than having its rows treated as stale."""
    result = (
        [{"engine": "sports_cfb", "market_ticker": "C1"}],
        [{"market_ticker": "C1", "edge_type": "SPORTS", "engine": "sports_cfb",
          "engine_version": "feed:v1", "gate_status": "SHADOW"}],
        {"nfl": {"feed_error": "404"}, "cfb": {"matched": 1}},
    )
    rc, calls = _run_main(monkeypatch, sports_result=result)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == [{"C1"}]
    assert "sports_nfl" not in calls[0], "a silent sport must not be pruned"

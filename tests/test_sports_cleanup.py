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
import json
from datetime import datetime, timezone

from tradehub.scripts import scan as scan_mod
from tradehub.sports.scan import SportsRun

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
SPORT_EDGES = [{"market_ticker": "T1", "edge_type": "SPORTS", "engine": "sports_nfl",
                "engine_version": "feed:v1", "gate_status": "SHADOW"}]
# run_sports_for_cron returns a SportsRun; per_sport is what the health check reads, so a stub
# that omits it would make every sport look like it produced nothing.
SPORT_RESULT = SportsRun(
    predictions=[{"engine": "sports_nfl", "market_ticker": "T1"}],
    edges=SPORT_EDGES,
    reports={"nfl": {"matched": 1}},
    per_sport={"nfl": {"feed_ok": True, "edges": SPORT_EDGES}},
)


def _sports_cleanup_calls(calls):
    """Flatten remove_stale_edges calls into one {engine: produced} view, so the order the
    engines are visited in does not matter and weather/gas entries drop out."""
    merged: dict[str, set] = {}
    for call in calls:
        for name, produced in call.items():
            if name.startswith("sports"):
                merged[name] = produced
    return [merged] if merged else []


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
    monkeypatch.setattr(scan_mod, "remove_started_sports_edges_errors", lambda *a, **k: [])
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
    assert _sports_cleanup_calls(calls) == [{"sports_nfl": {"T1"}}]


def test_sports_cleanup_is_skipped_when_the_edge_write_fails(monkeypatch):
    """A failed upsert must never be read as 'the engine produced nothing'."""
    rc, calls = _run_main(monkeypatch, edge_write_ok=False)
    assert _sports_cleanup_calls(calls) == [], "cleanup ran despite a failed sports edge write"
    assert rc == 1, "the failed write must still be reported"


def test_sports_cleanup_is_skipped_when_the_sport_scan_crashed(monkeypatch, capsys):
    rc, calls = _run_main(monkeypatch, sports_raises=True)
    assert _sports_cleanup_calls(calls) == [], "cleanup ran despite the sports scan crashing"
    # B6 requires the sports failure to be logged and recorded in `failures`; that makes the exit
    # code 1 (partial_failure) while leaving every other engine's write intact.
    assert rc == 1, "a sports outage must be reported via the exit code"
    summary = json.loads(capsys.readouterr().out)
    assert "kalshi down" in str(summary["sports"])
    assert any("kalshi down" in f for f in summary["failures"]), summary["failures"]
    assert summary["writes"]["edges"]["weather"] == "ok", "weather's write was affected"


def test_sports_cleanup_is_skipped_on_a_not_due_hour(monkeypatch):
    rc, calls = _run_main(monkeypatch, sports_due=False)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == []


def test_a_silent_sport_cannot_prune_another_sport(monkeypatch):
    """If the NFL feed 404s and CFB works, only CFB is pruned. A sport whose feed failed is
    left alone rather than having its rows treated as stale — and a sport that succeeded but
    produced nothing still IS pruned, which is the round-3 fix."""
    cfb_edges = [{"market_ticker": "C1", "edge_type": "SPORTS", "engine": "sports_cfb",
                  "engine_version": "feed:v1", "gate_status": "SHADOW"}]
    result = SportsRun(
        predictions=[{"engine": "sports_cfb", "market_ticker": "C1"}],
        edges=cfb_edges,
        reports={"nfl": {"feed_error": "404"}, "cfb": {"matched": 1}},
        per_sport={"nfl": {"feed_ok": False, "edges": []},
                   "cfb": {"feed_ok": True, "edges": cfb_edges}},
    )
    rc, calls = _run_main(monkeypatch, sports_result=result)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == [{"sports_cfb": {"C1"}}], calls
    assert "sports_nfl" not in _sports_cleanup_calls(calls)[0], "a sport whose feed failed must not be pruned"


def test_a_healthy_sport_with_zero_edges_is_still_pruned(monkeypatch):
    """The round-3 fix: pruning used to be driven by the produced rows, so a sport that
    legitimately produced nothing kept its previous rows up forever."""
    result = SportsRun(
        predictions=[],
        edges=[],
        reports={"nfl": {"matched": 0}, "cfb": {"matched": 0}},
        per_sport={"nfl": {"feed_ok": True, "edges": []},
                   "cfb": {"feed_ok": True, "edges": []}},
    )
    rc, calls = _run_main(monkeypatch, sports_result=result)
    assert rc == 0
    assert _sports_cleanup_calls(calls) == [{"sports_nfl": set(), "sports_cfb": set()}], calls

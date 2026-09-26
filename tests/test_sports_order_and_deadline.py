"""B6: scan order and robustness.

Four gaps:
1. The sports step ran BEFORE the weather/gas/CPI gate lookup, upserts and cleanups. A slow
   sports run therefore delayed the other engines' writes and put them at risk if the sports
   step blew the scan deadline. Sports must run last.
2. Only the Kalshi client got the deadline. The feed fetches and the OpenRouter calls did not,
   so a hung feed or a slow model could still overrun the hourly timer.
3. A sports failure was swallowed into the summary without `log.exception` or an entry in
   `failures`, so it was invisible to the exit code and to anyone reading the run summary.
4. `kalshi.open_markets` was called per sport in a dict comprehension, so one failing series
   took out the whole sport with no isolation.
"""
import time
from datetime import datetime, timezone

from tradehub.scripts import scan as scan_mod

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
REVIEW_STOP_MARGIN_SECONDS = 60


def _base(monkeypatch, *, sports_due=True, sports_hook=None):
    """Stub every engine; returns the ordered call log."""
    from tradehub.core import supabase_client

    calls: list[str] = []
    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: (calls.append("weather_scan") or [], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: (calls.append("gas_scan") or [], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: sports_due)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses",
                        lambda client, pairs: calls.append("gate_lookup") or {})
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_started_sports_edges_errors", lambda *a, **k: [])
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda client, produced: calls.append("cleanup"))
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    # record_predictions is imported INTO scan.main's namespace, so patch it there.
    monkeypatch.setattr(scan_mod, "record_predictions", lambda *a, **k: calls.append("pred_write"),
                        raising=False)
    # Distinguish the sports upsert so "sports runs last" can be asserted precisely.
    monkeypatch.setattr(supabase_client, "upsert_opportunities",
                        lambda rows: calls.append("sports_edge_write"
                                                  if rows and rows[0].get("edge_type") == "SPORTS"
                                                  else "edge_write"))

    if sports_due:
        def run(now, supa, **kw):
            from tradehub.sports.scan import SportsRun
            calls.append("sports_scan")
            if sports_hook:
                sports_hook()
            edges = [{"market_ticker": "S1", "edge_type": "SPORTS",
                      "engine": "sports_nfl", "engine_version": "feed:v1"}]
            return SportsRun([], edges, {"nfl": {"matched": 1}},
                            {"nfl": {"feed_ok": True, "edges": edges}})
        monkeypatch.setattr(scan_mod, "run_sports_for_cron", run)
    return calls


def test_sports_runs_after_the_other_engines_have_written(monkeypatch):
    """The weather/gas gate lookup, both upserts and the stale-edge cleanups must all complete
    BEFORE the sports step begins."""
    calls = _base(monkeypatch)
    scan_mod.main(now=NOW, live=object(), client=object())
    assert "sports_scan" in calls
    sports_at = calls.index("sports_scan")
    before_sports = calls[:sports_at]
    for required in ("gate_lookup", "edge_write", "cleanup"):
        assert required in before_sports, f"{required} did not happen before sports: {calls}"
    # After sports_scan the ONLY engine write is the sports one. The trailing "cleanup" is the
    # SPORTS prune, which is expected to run last of all; what must not appear is a
    # weather/gas/CPI write or cleanup.
    after = calls[sports_at + 1:]
    assert "sports_edge_write" in after, f"sports edges were never written: {calls}"
    assert "edge_write" not in after, f"a non-sports write followed sports: {calls}"
    assert "pred_write" not in after or after.index("pred_write") == 0, calls


def test_the_gate_lookup_happens_before_sports(monkeypatch):
    calls = _base(monkeypatch)
    scan_mod.main(now=NOW, live=object(), client=object())
    assert calls.index("gate_lookup") < calls.index("sports_scan"), calls


def test_a_slow_sports_run_does_not_delay_the_other_writes(monkeypatch):
    """Weather/gas edges are on the board before sports even starts."""
    from tradehub.core import supabase_client
    from tradehub.sports.scan import SportsRun

    writes: list[str] = []
    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: True)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_started_sports_edges_errors", lambda *a, **k: [])
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(scan_mod, "record_predictions", lambda *a, **k: None, raising=False)

    def slow_sports(now, supa, **kw):
        # The engine edges are already written by the time we get here.
        assert "engine" in writes, "the engine edges were not written before sports started"
        return SportsRun([], [{"market_ticker": "S1", "edge_type": "SPORTS",
                               "engine": "sports_nfl", "engine_version": "feed:v1"}], {}, {})

    monkeypatch.setattr(supabase_client, "upsert_opportunities",
                        lambda rows: writes.append("sports" if rows and rows[0].get("edge_type") == "SPORTS"
                                                   else "engine"))
    monkeypatch.setattr(scan_mod, "run_sports_for_cron", slow_sports)
    scan_mod.main(now=NOW, live=object(), client=object())
    assert writes[0] == "engine", writes


# ── deadline ──────────────────────────────────────────────────────────────────

def test_the_sports_step_is_bounded_by_the_scan_deadline():
    import pytest
    from tradehub.sports import scan as sports

    assert sports.remaining_seconds(time.monotonic() + 5.0) == pytest.approx(5.0, abs=1.0)
    assert sports.remaining_seconds(time.monotonic() - 1.0) < 0


def test_reviewing_stops_when_under_sixty_seconds_remain(monkeypatch):
    """Spending the remaining budget on LLM calls risks overrunning the timer, so reviewing
    stops once the margin is reached — edges are still written, just unreviewed."""
    from tradehub.sports import scan as sports

    assert sports.should_review(time.monotonic() + 300) is True
    assert sports.should_review(time.monotonic() + 30) is False
    assert sports.REVIEW_STOP_MARGIN_SECONDS == 60


def test_a_deadline_exhausted_sports_step_reports_and_does_not_raise(monkeypatch, capsys):
    """A deadline that expires DURING the sports step must be reported, and the engines that
    already wrote must keep their rows.

    The deadline is consumed rather than pre-expired: an already-expired deadline also trips
    `_ensure_scan_deadline` in the weather/gas scans, which would test the wrong thing.
    """
    import json

    calls = _base(monkeypatch)

    def expire_then_sports(now, supa, **kw):
        # The deadline kwarg must be threaded through to the sports client, and the step then
        # burns what is left and gives up.
        assert kw.get("deadline") is not None, "the scan deadline was not passed to the sports step"
        raise TimeoutError("scan deadline exceeded")

    monkeypatch.setattr(scan_mod, "run_sports_for_cron", expire_then_sports)
    rc = scan_mod.main(now=NOW, live=object(), client=object(), deadline=time.monotonic() + 30)
    summary = json.loads(capsys.readouterr().out)
    assert "deadline" in str(summary["sports"]).lower(), summary["sports"]
    assert any("deadline" in f.lower() for f in summary["failures"]), summary["failures"]
    # The point of moving sports last: the engine writes already landed.
    assert "edge_write" in calls, calls
    assert summary["writes"]["edges"]["weather"] == "ok", summary["writes"]
    assert rc == 1, "an exhausted deadline must be visible in the exit code"


def test_sports_failure_is_logged_with_a_traceback(monkeypatch, caplog):
    import logging
    calls = _base(monkeypatch)

    def boom(now, supa, **kw):
        raise RuntimeError("kalshi down")

    monkeypatch.setattr(scan_mod, "run_sports_for_cron", boom)
    with caplog.at_level(logging.ERROR):
        scan_mod.main(now=NOW, live=object(), client=object())
    assert any(r.exc_info for r in caplog.records), "the sports failure was logged without a traceback"


# ── per-series isolation ──────────────────────────────────────────────────────

def _empty_feed(sport):
    from tradehub.sports.feed import Feed
    return Feed(sport=sport, games=(), rejected=(), generated_at=NOW,
                calibration={"winner": {}, "spread": {}, "total": {}})


def test_one_failing_series_does_not_cost_the_sport(monkeypatch):
    from tradehub.sports import scan as sports
    from tradehub.sports.config import load_sport_config

    cfg = load_sport_config("nfl")

    class Kalshi:
        def open_markets(self, series):
            if series == cfg.series["winner"]:
                raise RuntimeError("series 500")
            return []

    run = sports.run_sports_scan(NOW, Kalshi(), fetch=lambda url, **k: _empty_feed("nfl"), sports=("nfl",))
    assert "series_errors" in run.reports["nfl"], run.reports["nfl"]
    assert cfg.series["winner"] in run.reports["nfl"]["series_errors"]
    assert run.per_sport["nfl"]["feed_ok"] is True, "a partial series failure must not disable the sport"


def test_all_series_failing_disables_the_sport(monkeypatch):
    from tradehub.sports import scan as sports


    class Kalshi:
        def open_markets(self, series):
            raise RuntimeError("kalshi down")

    run = sports.run_sports_scan(NOW, Kalshi(), fetch=lambda url, **k: _empty_feed("nfl"), sports=("nfl",))
    assert "kalshi_error" in run.reports["nfl"], run.reports["nfl"]
    assert run.per_sport["nfl"]["feed_ok"] is False, "a fully-failed sport must not be eligible to prune"

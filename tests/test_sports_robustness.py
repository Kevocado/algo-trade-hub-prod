"""Finding 5: the sports scan ignored the scan deadline and let one bad row kill a whole series.

(a) `run_sports_for_cron` built `SportsKalshi()` with no deadline, while every other engine in
    the same process runs under `SCAN_DEADLINE_SECONDS`. Sports paginates the public markets
    API per series, so a slow Kalshi could push the hourly timer past its budget and overlap
    the next run.

(b) `SportsKalshi.open_markets` maps every raw row through `parse_sports_market`, which does
    `raw["ticker"]` / `raw["event_ticker"]`. A single row missing a field raised and took the
    whole series' markets with it, so one malformed market silently emptied a sport.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


from tradehub.sports import scan as sports_scan
from tradehub.sports.kalshi import SportsKalshi, parse_sports_market

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _raw_markets(sport="nfl"):
    return json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())


# ── (a) deadline ──────────────────────────────────────────────────────────────

def test_sports_kalshi_is_built_with_the_scan_deadline(monkeypatch):
    """The sports client must inherit the scan's deadline, not start a fresh budget."""
    seen = {}

    class FakeSportsKalshi:
        def __init__(self, *args, **kwargs):
            seen["deadline"] = kwargs.get("deadline")

    class FakeSupa:
        def table(self, name):
            raise AssertionError("no writes expected")

    monkeypatch.setattr(sports_scan, "SportsKalshi", FakeSportsKalshi)
    monkeypatch.setattr(sports_scan, "run_sports_scan", lambda *a, **k: sports_scan.SportsRun([], [], {}))

    sports_scan.run_sports_for_cron(NOW, FakeSupa(), deadline=1234.5)
    assert seen["deadline"] == 1234.5, "the scan deadline was not passed to SportsKalshi"


def test_sports_scan_passes_the_deadline_into_the_client(monkeypatch):
    captured = {}

    class FakeKalshi:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def open_markets(self, series):
            return []

    monkeypatch.setattr(sports_scan, "SportsKalshi", FakeKalshi)
    monkeypatch.setattr(sports_scan, "load_sport_config", lambda sport: _cfg())
    monkeypatch.setattr(sports_scan, "fetch_feed", lambda url, **k: _feed_stub())
    sports_scan.run_sports_scan(NOW, FakeKalshi(deadline=99.0))
    assert captured == {"deadline": 99.0}


def _cfg():
    from tradehub.sports.config import load_sport_config
    return load_sport_config("nfl")


def _feed_stub():
    from tradehub.sports.feed import Feed
    return Feed(sport="nfl", games=(), rejected=[])


# ── (b) malformed market rows ─────────────────────────────────────────────────

class _Paginated:
    """A KalshiHistoryClient stand-in that returns the given raw rows."""

    def __init__(self, raws):
        self._raws = raws

    def _paginate(self, *_a, **_k):
        return list(self._raws)


def test_one_malformed_market_does_not_empty_the_series():
    good = _raw_markets()["KXNFLGAME"][0]
    bad = {k: v for k, v in good.items() if k != "ticker"}          # no ticker
    bad2 = {"ticker": "X", "event_ticker": "E", "yes_bid": None, "yes_ask": None}   # no prices

    client = _Paginated([bad, good, bad2])
    markets = _open(client)

    assert len(markets) == 1
    assert markets[0].market.ticker == good["ticker"]


def _open(client):
    """Call the real open_markets body with _paginate stubbed."""
    stub = SportsKalshi.__new__(SportsKalshi)
    stub._paginate = client._paginate
    return SportsKalshi.open_markets(stub, "KXNFLGAME")


def test_all_rows_malformed_returns_empty_rather_than_raising():
    stub = SportsKalshi.__new__(SportsKalshi)
    stub._paginate = lambda *a, **k: [{"event_ticker": "E"}]
    assert SportsKalshi.open_markets(stub, "KXNFLGAME") == []


def test_malformed_rows_are_reported_not_swallowed_silently(caplog):
    """A dropped market must be visible in the report, or a broken series looks like a quiet one."""
    from tradehub.sports.kalshi import parse_markets_tolerantly

    good = _raw_markets()["KXNFLGAME"][0]
    markets, rejected = parse_markets_tolerantly([{"event_ticker": "E"}, good], "KXNFLGAME")
    assert len(markets) == 1
    assert len(rejected) == 1
    assert rejected[0]["ticker"] is None
    assert rejected[0]["series"] == "KXNFLGAME"
    assert rejected[0]["reason"] == "malformed_market"
    assert "ticker" in rejected[0]["detail"]


def test_price_failure_on_one_market_does_not_kill_the_sport(monkeypatch):
    """A market the pricer chokes on must be skipped, not abort the whole sport scan."""
    from tradehub.sports.config import load_sport_config
    from tradehub.sports.feed import parse_feed

    raw_feed = json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())
    for kind in ("winner", "spread", "total"):
        for b in raw_feed["calibration"][kind]:
            mid = round(b["lo"] + 0.05, 2)
            b.update(n=40, mean_prob=mid, hit_rate=mid)
    feed = parse_feed(raw_feed)
    markets = {s: [parse_sports_market(m) for m in ms] for s, ms in _raw_markets().items()}

    calls = {"n": 0}
    real_price = sports_scan.price_market

    def flaky(kind, sm, mg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad strike")
        return real_price(kind, sm, mg)

    monkeypatch.setattr(sports_scan, "price_market", flaky)
    result = sports_scan.scan_sport(load_sport_config("nfl"), markets, feed, NOW)
    assert result.edges, "the rest of the sport must still be scanned"
    assert result.report["markets_skipped"] >= 1


# ── (c) a feed 404 is the expected state until 7a is deployed, so it is logged ─

def test_a_feed_404_is_logged_at_warning(caplog):
    """The live feed 404s until 7a ships, and that is the expected result, not a fault. It was
    written into the run summary only, so `journalctl` on the scan timer showed nothing at all and
    the summary had to be found by hand to explain a sport that produced no edges."""
    import logging

    from tradehub.sports.feed import FeedUnavailable

    def fetch(url, **_kw):
        raise FeedUnavailable("404")

    with caplog.at_level(logging.WARNING):
        sports_scan.run_sports_scan(NOW, object(), fetch=fetch, sports=("nfl",))
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warned, "a 404 predictor produced no log record at all"
    assert any("nfl" in r.getMessage() for r in warned), [r.getMessage() for r in warned]
    assert any("404" in r.getMessage() for r in warned), [r.getMessage() for r in warned]


def test_a_feed_404_still_does_not_fail_the_scan(monkeypatch, capsys):
    """It stays out of `failures` and the exit code stays 0 — a predictor that has not been
    deployed yet must not turn the hourly timer red. Only the log line and the summary carry it."""
    import json

    from tradehub.scripts import scan as scan_mod
    from tradehub.sports.scan import SportsRun

    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: True)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_closed_labor_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr("tradehub.core.supabase_client.get_client", lambda: "supa")
    monkeypatch.setattr("tradehub.core.supabase_client.upsert_opportunities", lambda rows: None)

    def not_deployed(now, supa, **kw):
        return SportsRun([], [], {"nfl": {"feed_error": "404"}, "cfb": {"feed_error": "404"}},
                         {"nfl": {"feed_ok": False, "edges": []},
                          "cfb": {"feed_ok": False, "edges": []}})

    monkeypatch.setattr(scan_mod, "run_sports_for_cron", not_deployed)
    rc = scan_mod.main(now=NOW, live=object(), client=object())
    summary = json.loads(capsys.readouterr().out)
    assert rc == 0, f"a not-yet-deployed predictor made the scan fail: {summary['failures']}"
    assert summary["failures"] == [], summary["failures"]
    assert "404" in str(summary["sports"]), summary["sports"]

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

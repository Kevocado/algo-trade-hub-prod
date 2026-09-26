import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.sports import scan as sports_scan
from tradehub.sports.config import load_sport_config
from tradehub.sports.feed import FeedUnavailable, parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.reviewer import Review

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)   # Sunday 17:00Z games are 29h out


def _feed(sport, calibrated=True):
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    if calibrated:   # the recorded feed has no graded pre-game history yet; pretend it is calibrated
        for kind in ("winner", "spread", "total"):
            for b in raw["calibration"][kind]:
                mid = round(b["lo"] + 0.05, 2)
                b.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


class FakeKalshi:
    def __init__(self, sport):
        raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
        self.markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}
        self.asked = []

    def open_markets(self, series):
        self.asked.append(series)
        return self.markets.get(series, [])


def test_scan_sport_predicts_matched_markets_and_flags_edges():
    cfg = load_sport_config("nfl")
    kalshi = FakeKalshi("nfl")
    result = sports_scan.scan_sport(cfg, kalshi.markets, _feed("nfl"), NOW)

    assert result.report["matched"] == 3 and result.report["unmatched_events"] == ["KXNFLGAME-26SEP27KCMIA"]
    tickers = {p["market_ticker"] for p in result.predictions}
    assert "KXNFLGAME-26SEP27HOUIND-IND" in tickers and "KXNFLSPREAD-26SEP27HOUIND-IND8" in tickers
    assert "KXNFLGAME-26SEP27KCMIA-KC" not in tickers
    pred = next(p for p in result.predictions if p["market_ticker"] == "KXNFLGAME-26SEP27HOUIND-IND")
    assert pred["engine"] == "sports_nfl"
    assert pred["engine_version"] == "feed:ridge@2026-09-04T22:12:49.750941+00:00"
    assert pred["our_prob"] == pytest.approx(0.2954, abs=1e-4)
    assert pred["raw_payload"]["game_id"] == "2026_03_HOU_IND" and pred["raw_payload"]["kind"] == "winner"

    assert result.edges, "the recorded HOU@IND prices leave an edge against the predictor"
    for edge in result.edges:
        assert edge["engine"] == "sports_nfl"
        assert edge["gate_status"] == "SHADOW"
        assert edge["edge_type"] == "SPORTS"
        assert edge["market_url"].startswith("https://kalshi.com/markets/kxnfl")
        assert edge["source_url"] == (f"{cfg.site_url}/?sport=nfl&game={edge['game_id']}")
        assert edge["tier"] in ("filtered", "unreviewed")
        assert edge["candidate"] == (edge["reject_reasons"] == [])
    assert len(result.review_requests) == sum(e["candidate"] for e in result.edges)


def test_uncalibrated_feed_produces_edges_but_no_candidates():
    result = sports_scan.scan_sport(load_sport_config("nfl"), FakeKalshi("nfl").markets, _feed("nfl", calibrated=False), NOW)
    assert result.edges and result.review_requests == []
    assert all("calibration_insufficient" in e["reject_reasons"] for e in result.edges)


def test_apply_reviews_sets_tiers_without_touching_probabilities():
    result = sports_scan.scan_sport(load_sport_config("nfl"), FakeKalshi("nfl").markets, _feed("nfl"), NOW)
    assert result.review_requests
    before = [e["model_probability"] for e in result.edges]
    key = result.review_requests[0].key
    reviews = {key: Review(status="ok", explainable=True, drivers=("margin",), red_flags=(), model="m")}
    sports_scan.apply_reviews(result.edges, reviews)
    reviewed = next(e for e in result.edges if e.get("review_key") == key)
    assert reviewed["tier"] == "top_pick" and reviewed["review"]["drivers"] == ["margin"]
    assert [e["model_probability"] for e in result.edges] == before


def test_run_sports_scan_reports_a_down_predictor_and_keeps_going():
    kalshi = FakeKalshi("cfb")

    def fetch(base_url):
        if "nfl" in base_url:
            raise FeedUnavailable("404")
        return _feed("cfb")

    out = sports_scan.run_sports_scan(NOW, kalshi, fetch=fetch)
    assert out.reports["nfl"] == {"feed_error": "404"}
    assert out.reports["cfb"]["matched"] == 2
    assert all(p["engine"] == "sports_cfb" for p in out.predictions)
    assert all(e["tier"] != "top_pick" for e in out.edges)   # no reviewer configured


def test_unrecorded_drops_markets_already_in_the_ledger():
    class Q:
        def __init__(self, parent):
            self.parent, self.tickers = parent, []

        def select(self, *_a):
            return self

        def eq(self, col, val):
            assert (col, val) == ("engine", "sports_nfl")
            return self

        def in_(self, col, values):
            self.tickers = list(values)
            self.parent.chunks.append(len(values))
            return self

        def execute(self):
            return type("R", (), {"data": [{"market_ticker": t} for t in self.tickers if t.endswith("-OLD")]})()

    class Supa:
        chunks = []

        def table(self, name):
            assert name == "predictions"
            return Q(self)

    rows = [{"market_ticker": f"T{i}", "engine": "sports_nfl"} for i in range(150)] + [
        {"market_ticker": "X-OLD", "engine": "sports_nfl"}]
    supa = Supa()
    kept = sports_scan.unrecorded(supa, rows)
    assert len(kept) == 150 and all(not r["market_ticker"].endswith("-OLD") for r in kept)
    assert supa.chunks == [100, 51]


@pytest.mark.parametrize("hour,due", [(0, True), (3, True), (4, False), (23, False)])
def test_sports_run_every_third_hour(hour, due, monkeypatch):
    monkeypatch.delenv("SPORTS_SCAN_EVERY_RUN", raising=False)
    assert sports_scan.sports_due(NOW.replace(hour=hour)) is due


def test_sports_due_env_override(monkeypatch):
    monkeypatch.setenv("SPORTS_SCAN_EVERY_RUN", "1")
    assert sports_scan.sports_due(NOW.replace(hour=4)) is True


def test_scan_main_includes_sports_when_due(monkeypatch, capsys):
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    import tradehub.predictions as predictions

    prediction_writes = []
    edge_writes = []
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([{"engine": "weather"}], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "sports_due", lambda now: True)
    # scan.main() defaults to the wall clock, and cpi_nowcast only runs at 08/12/16 ET. Without
    # this the CPI engine runs against the stub client whenever the suite happens to execute in
    # one of those hours, which is how these two sports tests became time-of-day flaky.
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "run_sports_for_cron", lambda now, supa, **kw: (
        [{"engine": "sports_nfl"}],
        [{"edge_type": "SPORTS", "engine": "sports_nfl", "market_ticker": "T1"}],
        {"nfl": {"matched": 1}}))
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: prediction_writes.append(rows))
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: edge_writes.append(rows))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, versions: {"weather": "SHADOW", "gas": "SHADOW"})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    assert scan.main() == 0
    assert [r["engine"] for rows in prediction_writes for r in rows] == ["weather", "sports_nfl"]
    assert [row for rows in edge_writes for row in rows] == [
        {"edge_type": "SPORTS", "engine": "sports_nfl", "market_ticker": "T1", "gate_status": "SHADOW"}
    ]
    assert json.loads(capsys.readouterr().out)["sports"] == {"nfl": {"matched": 1}}


def test_scan_main_survives_a_sports_crash(monkeypatch, capsys):
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    import tradehub.predictions as predictions

    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "sports_due", lambda now: True)
    # See the note in test_scan_main_includes_sports_when_due: keep CPI off the wall clock.
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: False)

    def boom(now, supa, **kw):
        raise RuntimeError("kalshi down")

    monkeypatch.setattr(scan, "run_sports_for_cron", boom)
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: rows)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: None)
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, versions: {"weather": "SHADOW", "gas": "SHADOW"})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *args, **kwargs: None)

    assert scan.main() == 0
    assert "kalshi down" in json.loads(capsys.readouterr().out)["sports"]["error"]

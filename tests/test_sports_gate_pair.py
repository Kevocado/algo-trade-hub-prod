"""Finding 2: sports edges must be gated per (engine, engine_version) like every other engine.

`tradehub.scripts.scan` keys the promotion gate on (engine, engine_version). The sports edge
row hardcoded gate_status="SHADOW" and carried no engine_version, so sports edges could never
be promoted, and once they were included in the pair set they would have been keyed on a
placeholder version that matches no backtest or track record.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from tradehub.sports import scan as sports_scan
from tradehub.sports.config import load_sport_config
from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _feed(sport):
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    for kind in ("winner", "spread", "total"):
        for b in raw["calibration"][kind]:
            mid = round(b["lo"] + 0.05, 2)
            b.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


def _scan(sport="nfl"):
    cfg = load_sport_config(sport)
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}
    return cfg, sports_scan.scan_sport(cfg, markets, _feed(sport), NOW)


def test_every_sports_edge_carries_the_engine_version_of_its_prediction():
    cfg, result = _scan()
    assert result.edges
    versions = {p["engine_version"] for p in result.predictions}
    for edge in result.edges:
        # Same key the ledger row uses, so the gate lookup for this edge can actually match.
        assert edge["engine_version"].startswith("feed:")
        assert edge["engine"] == cfg.engine
    assert len(versions) == 1, "the recorded feed has one model version"
    for edge in result.edges:
        assert edge["engine_version"] in versions


def test_edge_and_prediction_versions_agree_for_the_same_market():
    _, result = _scan()
    by_ticker = {p["market_ticker"]: p["engine_version"] for p in result.predictions}
    matched = [e for e in result.edges if e["market_ticker"] in by_ticker]
    assert matched
    for edge in matched:
        assert edge["engine_version"] == by_ticker[edge["market_ticker"]]


def test_sports_gate_lookup_promotes_only_the_promoted_feed_version(monkeypatch):
    """The pair (engine, engine_version) must be what gets looked up, and a PROMOTED verdict
    for the live feed version must reach the edge."""
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    from tradehub.sports import scan as sports
    import tradehub.predictions as predictions

    upserted = []
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "sports_due", lambda now: True)
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))

    live_version = "feed:ridge@2026-09-04T22:12:49.750941+00:00"
    monkeypatch.setattr(scan, "run_sports_for_cron", lambda now, supa, **k: (
        [{"engine": "sports_nfl", "market_ticker": "T"}],
        [{"market_ticker": "T", "engine": "sports_nfl", "engine_version": live_version}],
        {"nfl": {"matched": 1}},
    ))
    # A PROMOTED verdict exists only for this exact pair.
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {
        ("sports_nfl", live_version): "PROMOTED",
    })

    assert scan.main(now=NOW, live=object(), client=object()) == 0
    sports_rows = [r for r in upserted if r.get("edge_type") == "SPORTS"]
    assert len(sports_rows) == 1
    assert sports_rows[0]["gate_status"] == "PROMOTED"


def test_an_unmatched_sports_edge_version_stays_shadow(monkeypatch):
    """An edge whose version has no backtest row must fail closed to SHADOW, never inherit
    another version's promotion."""
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    from tradehub.sports import scan as sports
    import tradehub.predictions as predictions

    upserted = []
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "sports_due", lambda now: True)
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    monkeypatch.setattr(scan, "run_sports_for_cron", lambda now, supa, **k: (
        [],
        [{"market_ticker": "T", "edge_type": "SPORTS",
          "engine": "sports_nfl", "engine_version": "feed:brand-new"}],
        {"nfl": {"matched": 1}},
    ))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {
        ("sports_nfl", "feed:old"): "PROMOTED",
    })

    assert scan.main(now=NOW, live=object(), client=object()) == 0
    sports_rows = [r for r in upserted if r.get("edge_type") == "SPORTS"]
    assert sports_rows[0]["gate_status"] == "SHADOW"

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.markets import parse_cpi_market
from tradehub.scripts import scan

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc)  # 08:05 EDT on the Aug-2026 release morning
CFG = EngineConfig(min_edge_pct=5.0, prefer_maker=True, params={"train_months": 24.0, "use_bias": 0.0})


def _lm(series, strike, month="26AUG", close="2026-09-11T12:25:00Z", bid=0.30, ask=0.34):
    event = f"{series}-{month}"
    market = parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                               "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                               "title": f"{series} {strike}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=50.0, yes_ask_size=50.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _nowcast_fn(calls):
    def fn(kind):
        calls.append(kind)
        return parse_nowcast_month(PAYLOAD, kind)
    return fn


def test_scan_cpi_predicts_headline_and_core_with_their_versions():
    calls = []
    live = FakeLive([_lm("KXCPI", 0.3), _lm("KXCPI", 0.4), _lm("KXCPICORE", 0.2)])
    preds, edges = scan.scan_cpi(live, NOW, CFG, nowcast_fn=_nowcast_fn(calls))
    assert calls == ["headline", "core"]
    by_ticker = {p["market_ticker"]: p for p in preds}
    assert set(by_ticker) == {"KXCPI-26AUG-T0.3", "KXCPI-26AUG-T0.4", "KXCPICORE-26AUG-T0.2"}
    assert all(p["engine"] == "cpi_nowcast" for p in preds)
    assert by_ticker["KXCPI-26AUG-T0.3"]["engine_version"] == "cpi-v1"
    assert by_ticker["KXCPICORE-26AUG-T0.2"]["engine_version"] == "cpi-core-v1"
    headline = by_ticker["KXCPI-26AUG-T0.3"]["raw_payload"]
    # The Sep-10 value (0.3592) became usable at 00:00 ET Sep 11; too few released months -> default sigma.
    assert headline["nowcast_obs"] == "CPI:2026-08@2026-09-10"
    assert headline["nowcast"] == pytest.approx(0.359180537639179)
    assert headline["sigma"] == pytest.approx(0.15) and headline["n_train"] == 1
    assert by_ticker["KXCPI-26AUG-T0.3"]["our_prob"] == pytest.approx(0.5244, abs=1e-4)  # P(N(0.3592, 0.15) > 0.35)
    assert edges and all(e["edge_type"] == "MACRO" for e in edges)
    assert all(e["engine"] == "cpi_nowcast" and e["gate_status"] == "SHADOW" for e in edges)


def test_scan_cpi_skips_months_without_a_nowcast_and_closed_markets():
    live = FakeLive([_lm("KXCPI", 0.3, month="26OCT", close="2026-11-10T13:25:00Z"),
                     _lm("KXCPI", 0.3, close="2026-09-11T12:00:00Z")])
    assert scan.scan_cpi(live, NOW, CFG, nowcast_fn=_nowcast_fn([])) == ([], [])


def test_scan_cpi_does_not_fetch_the_nowcast_without_open_markets():
    calls = []
    assert scan.scan_cpi(FakeLive([]), NOW, CFG, nowcast_fn=_nowcast_fn(calls)) == ([], [])
    assert calls == []


def test_cpi_scan_due_hours_are_eastern():
    assert scan.cpi_scan_due(datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc))      # 08:05 EDT
    assert scan.cpi_scan_due(datetime(2026, 12, 10, 13, 5, tzinfo=timezone.utc))     # 08:05 EST
    assert not scan.cpi_scan_due(datetime(2026, 9, 11, 13, 5, tzinfo=timezone.utc))  # 09:05 EDT


def test_repo_config_has_cpi_nowcast():
    cfg = load_engine_config("cpi_nowcast")
    assert cfg.min_edge_pct > 0 and cfg.prefer_maker is True
    assert cfg.params == {"train_months": 24.0, "use_bias": 0.0}


def test_main_isolates_a_cpi_failure(monkeypatch, capsys):
    from tradehub import predictions
    from tradehub.core import supabase_client

    prediction_writes = []
    edge_writes = []
    monkeypatch.setattr(supabase_client, "get_client", lambda: "client")
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: edge_writes.append(rows))
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: prediction_writes.append(rows))
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda live, now, cfg, **kwargs: ([{"w": 1}], []))
    monkeypatch.setattr(scan, "scan_gas", lambda live, now, cfg, **kwargs: ([{"g": 1}], [{"e": 1, "engine": "gas"}]))
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: True)

    def boom(live, now, cfg):
        raise RuntimeError("cleveland fed down")

    monkeypatch.setattr(scan, "scan_cpi", boom)
    assert scan.main() == 1
    assert [{"w": 1}] in prediction_writes and [{"g": 1}] in prediction_writes
    assert [{"e": 1, "engine": "gas", "gate_status": "SHADOW"}] in edge_writes
    summary = json.loads(capsys.readouterr().out)
    assert summary["cpi_nowcast"]["status"].startswith("error: RuntimeError")
    assert summary["cpi_nowcast"]["predictions"] == 0


def test_main_gates_cpi_edges_per_engine_version(monkeypatch):
    from tradehub.core import supabase_client
    from tradehub import predictions

    upserted = []
    monkeypatch.setattr(supabase_client, "get_client", lambda: object())
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    monkeypatch.setattr(predictions, "record_predictions", lambda *args: None)
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: True)
    monkeypatch.setattr(scan, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {
        ("cpi_nowcast", "cpi-core-v1"): "PROMOTED",
    })
    monkeypatch.setattr(scan, "scan_cpi", lambda *a, **k: ([], [
        {"market_ticker": "A", "engine": "cpi_nowcast", "engine_version": "cpi-v1"},
        {"market_ticker": "B", "engine": "cpi_nowcast", "engine_version": "cpi-core-v1"},
    ]))

    assert scan.main(now=datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc), live=object(), client=object()) == 0
    assert {row["engine_version"]: row["gate_status"] for row in upserted} == {
        "cpi-v1": "SHADOW", "cpi-core-v1": "PROMOTED",
    }

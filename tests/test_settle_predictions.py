import json

from tradehub.scripts import settle_predictions


class _FakeSupa:
    pass


def test_engines_match_spec_engine_set_and_cadences():
    assert dict(settle_predictions.ENGINES) == {
        "weather": "daily",
        "gas": "daily",
        "cpi_nowcast": "monthly",
        "labor_nowcast": "monthly",
        "crypto": "daily",
    }


def test_main_wires_pass_and_refresh(monkeypatch, capsys):
    calls = {}

    def fake_get_client():
        calls["client"] = True
        return _FakeSupa()

    def fake_fetch_market(ticker):
        return {"market": {"status": "active", "result": None}}

    def fake_run_pass(supa, fetch):
        calls["pass"] = True
        assert fetch is fake_fetch_market
        return {"checked": 3, "settled": 0, "canceled": 0, "skipped": 3}

    refreshed = []

    def fake_refresh(supa, engine, **kwargs):
        refreshed.append(engine)
        return [{"engine": engine, "engine_version": "v1"}]

    monkeypatch.setattr(settle_predictions, "get_client", fake_get_client)
    monkeypatch.setattr(settle_predictions, "fetch_market", fake_fetch_market)
    monkeypatch.setattr(settle_predictions, "run_settlement_pass", fake_run_pass)
    monkeypatch.setattr(settle_predictions, "refresh_track_record", fake_refresh)
    monkeypatch.setattr(settle_predictions, "ENGINES", [("weather", "daily"), ("macro", "monthly")])

    assert settle_predictions.main() == 0
    assert calls == {"client": True, "pass": True}
    assert refreshed == ["weather", "macro"]
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 3
    assert out["track_record_refreshed"] == ["weather@v1", "macro@v1"]

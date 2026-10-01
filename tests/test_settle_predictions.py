import json

from tradehub.scripts import settle_predictions


class _FakeSupa:
    """No journal scorecards: the journal table is empty (or not deployed yet)."""

    def table(self, name):
        assert name == "journal_scores"
        return self

    def select(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


def test_engines_match_spec_engine_set_and_cadences():
    assert dict(settle_predictions.ENGINES) == {
        "weather": "daily",
        "gas": "daily",
        "cpi_nowcast": "monthly",
        "labor_nowcast": "monthly",
        "crypto": "daily",
        "sports_nfl": "daily",
        "sports_cfb": "daily",
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


def test_an_engine_on_the_journal_is_not_refreshed_into_the_legacy_track_record(monkeypatch, capsys):
    class OnJournal(_FakeSupa):
        def execute(self):
            return type("R", (), {"data": [{"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1"}]})()

    refreshed = []
    monkeypatch.setattr(settle_predictions, "get_client", lambda: OnJournal())
    monkeypatch.setattr(settle_predictions, "fetch_market", lambda t: {})
    monkeypatch.setattr(settle_predictions, "run_settlement_pass", lambda supa, fetch: {"checked": 0})
    monkeypatch.setattr(settle_predictions, "refresh_track_record",
                        lambda supa, engine, **kw: refreshed.append(engine) or [{"engine": engine, "engine_version": "v1"}])
    monkeypatch.setattr(settle_predictions, "ENGINES", [("weather", "daily"), ("cpi_nowcast", "monthly")])

    assert settle_predictions.main() == 0
    assert refreshed == ["weather"]  # cpi_nowcast is graded by the journal now
    out = json.loads(capsys.readouterr().out)
    assert out["track_record_skipped_on_journal"] == ["cpi_nowcast"] and out["track_record_refreshed"] == ["weather@v1"]

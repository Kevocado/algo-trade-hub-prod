from datetime import UTC, datetime

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

T0 = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)


def _client(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def teardown_function(_fn):
    app.dependency_overrides.clear()


def test_journal_returns_precomputed_scorecards_in_order():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [
        {"forecaster": "labor", "forecaster_version": "v1", "gate_status": "SHADOW", "n_settled": 9,
         "n_targets": 12, "calibration_ready": False},
        {"forecaster": "cpi", "forecaster_version": "v1", "gate_status": "PROMOTED", "n_settled": 60,
         "n_targets": 30, "calibration_ready": True},
    ]
    res = _client(db).get("/api/journal")
    assert res.status_code == 200
    body = res.json()
    assert [r["forecaster"] for r in body["forecasters"]] == ["cpi", "labor"]
    # headline counts cover calibrated forecasters only (spec §10); the page renders, never sums.
    # That comment was here before the page honoured it -- `Journal.tsx` called `totals(rows)` over
    # every card, provisional ones included. See the frontend half of this change.
    assert body["headline"] == {"forecasters": 2, "calibrated": 1, "frozen_calibrated": 30,
                                "settled_calibrated": 60, "promoted": 1, "market_skill": None}
    # `market_skill` is None, not 0.0: neither fixture card names a market baseline, so there is
    # nothing to be better than. A hero reading 0.00 here would be a fabricated number.


def test_feed_is_newest_first_with_calibration_and_provisional_flag():
    db = FakeJournalDB(lambda: T0)
    for i in (1, 2, 3):
        db.tables["journal_forecasts"].append({"id": i, "forecaster": "cpi", "forecaster_version": "v1",
                                               "target": f"t{i}", "probability": 0.6, "market_prob": 0.5,
                                               "frozen_at": T0.isoformat(), "rebuilt": False, "source_hash": "h"})
    db.tables["journal_scores"].append({"forecaster": "cpi", "forecaster_version": "v1", "gate_status": "SHADOW",
                                        "reliability": [{"bucket": "60-70", "n": 3}], "calibration_ready": False})
    body = _client(db).get("/api/journal/feed", params={"forecaster": "cpi", "version": "v1", "limit": 2}).json()
    assert [f["target"] for f in body["forecasts"]] == ["t3", "t2"]
    assert body["calibration"] == [{"bucket": "60-70", "n": 3}]
    assert body["gate_status"] == "SHADOW" and body["provisional"] is True


def test_feed_rejects_bad_paging_and_503s_without_supabase():
    db = FakeJournalDB(lambda: T0)
    assert _client(db).get("/api/journal/feed", params={"forecaster": "x", "version": "v1", "limit": 0}).status_code == 422
    app.dependency_overrides[get_supabase] = lambda: None
    assert TestClient(app).get("/api/journal").status_code == 503


def test_a_missing_journal_table_names_the_migration():
    class NoJournal(FakeJournalDB):
        def table(self, name):
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")

    res = _client(NoJournal(lambda: T0)).get("/api/journal")
    assert res.status_code == 503


def test_a_multi_column_order_is_chained_one_column_per_call():
    # The real postgrest-py order() accepts a single column; the fake now rejects more, so an
    # `.order(a, b)` regression fails here instead of in production.
    from tradehub.journal.store import select_all

    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [{"forecaster": "b", "forecaster_version": "1"},
                                    {"forecaster": "a", "forecaster_version": "2"},
                                    {"forecaster": "a", "forecaster_version": "1"}]
    rows = select_all(db, "journal_scores", lambda q: q, ("forecaster", "forecaster_version"))
    assert [(r["forecaster"], r["forecaster_version"]) for r in rows] == [("a", "1"), ("a", "2"), ("b", "1")]


def test_a_cautious_copy_is_not_counted_as_a_second_set_of_evidence_in_the_headline():
    """Plan 15 registers `<model>_cautious` beside each market-linked model, scored on the model's
    EXACT target set. Summing `n_settled` over every card therefore counted each event twice: 200
    settled forecasts displayed as 400, in the one number the journal headlines. This asserts the
    sum runs over each target once -- the cautious copy still counts as a forecaster, because it is
    one."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [
        {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "gate_status": "PROMOTED",
         "n_settled": 200, "calibration_ready": True},
        {"forecaster": "cpi_nowcast_cautious", "forecaster_version": "cpi-v1+w25", "gate_status": "PROMOTED",
         "n_settled": 200, "calibration_ready": True},
    ]
    body = _client(db).get("/api/journal").json()
    assert body["headline"]["settled_calibrated"] == 200, body["headline"]
    assert body["headline"]["forecasters"] == 2


# ── standings: the front page's "what we found" ─────────────────────────────────
# Every claim on that page is compared against the standard error stored beside the gap, because a
# bare skill number reads as a result when it is noise (migration 20260428000017).


def _score(forecaster, version, **over):
    row = {"forecaster": forecaster, "forecaster_version": version, "cadence": "daily", "baseline": "market",
           "n_targets": 100, "n_settled": 50, "n_baseline": 50, "brier": 0.21, "brier_baseline": 0.25,
           "brier_on_baseline": 0.24, "bss": 0.04, "calibration_ready": True, "gate_status": "SHADOW"}
    row.update(over)
    return row


def _replay(forecaster, version, diff, se, **over):
    row = {"forecaster": forecaster, "forecaster_version": version, "n": 760, "brier": 0.21,
           "brier_baseline": 0.22, "brier_diff": diff, "brier_diff_se": se, "bss": 0.045,
           "date_from": "2026-06-01", "date_to": "2026-09-20", "created_at": "2026-10-01T12:00:00+00:00"}
    row.update(over)
    return row


def test_standings_ship_with_the_journal_payload():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [_score("gas", "gas-v2"), _score("weather_high", "v1")]
    db.tables["journal_backtests"] += [
        _replay("gas", "gas-v2", -0.030, 0.005),
        _replay("weather_high", "v1", -0.010, 0.009),
    ]
    body = _client(db).get("/api/journal").json()
    s = body["standings"]
    # Market-linked section
    assert s["market_linked_best"]["forecaster"] == "gas"
    assert s["market_linked_best"]["verdict"] == "beats"
    assert s["market_linked_worst"]["forecaster"] == "weather_high"
    assert s["market_linked_worst"]["verdict"] == "indistinguishable"
    assert s["n_settled"] == 100
    assert s["distinct_se"] == 2.0
    # The lede is assembled from the numbers, and a real result is stated with its interval.
    assert "gas" in s["verdict"]
    assert "0.005" in s["verdict"]
    assert "beat" in s["verdict"].lower()


def test_standings_with_no_replays_says_so_instead_of_scoring_zero():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [_score("gas", "gas-v2")]
    s = _client(db).get("/api/journal").json()["standings"]
    assert s["market_linked_best"] is None
    assert s["market_linked_worst"] is None
    assert s["n_settled"] == 50
    assert "no replay" in s["verdict"].lower()


def test_the_newest_replay_wins_when_a_forecaster_has_been_replayed_twice():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [_score("gas", "gas-v2")]
    db.tables["journal_backtests"] += [
        _replay("gas", "gas-v2", -0.001, 0.001, created_at="2026-09-01T12:00:00+00:00"),
        _replay("gas", "gas-v2", -0.030, 0.005, created_at="2026-10-01T12:00:00+00:00"),
    ]
    s = _client(db).get("/api/journal").json()["standings"]
    assert s["market_linked_best"]["gap"] == -0.030
    assert s["n_replayed"] == 1


def test_a_missing_journal_backtests_table_degrades_standings_rather_than_500():
    """A half-deployed journal must not take the front page down. 'No replay yet' is the true answer."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [_score("gas", "gas-v2")]

    def _missing(name):
        if name == "journal_backtests":
            raise RuntimeError(
                "Could not find the table 'public.journal_backtests' in the schema cache (PGRST205)")
        return FakeJournalDB.table(db, name)

    db.table = _missing
    res = _client(db).get("/api/journal")
    assert res.status_code == 200
    assert res.json()["standings"]["market_linked_best"] is None
    assert "no replay" in res.json()["standings"]["verdict"].lower()


def test_a_non_missing_table_error_on_backtests_is_still_an_error():
    """The degradation is for 'the table is not there', not for 'the database is on fire'."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [_score("gas", "gas-v2")]

    def _broken(name):
        if name == "journal_backtests":
            raise RuntimeError("connection reset by peer")
        return FakeJournalDB.table(db, name)

    db.table = _broken
    res = _client(db).get("/api/journal")
    assert res.status_code != 200


# ── Weather/ERCOT panel endpoint ────────────────────────────────────────────

def _weather_forecast(forecaster, target, probability, market_prob, frozen_at=None):
    return {"forecaster": forecaster, "forecaster_version": "v1", "target": target,
            "probability": probability, "market_prob": market_prob,
            "frozen_at": frozen_at or T0.isoformat(), "rebuilt": False, "source_hash": "h"}


def _weather_settlement(target, outcome):
    return {"target": target, "outcome": outcome}


def test_weather_panel_returns_latest_settled_day_contracts():
    """Only the latest settled day's contracts are returned; earlier days are excluded."""
    db = FakeJournalDB(lambda: T0)
    day1 = "26SEP30"
    day2 = "26OCT18"  # latest; and 'OCT' sorts before 'SEP' as text, so only a real date gets this right
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", f"kalshi:KXHIGHNY-{day1}-T76", 0.6, 0.55, "2026-09-30T10:00:00+00:00"),
        _weather_forecast("weather_high", f"kalshi:KXHIGHNY-{day2}-T76", 0.7, 0.65, "2026-10-18T10:00:00+00:00"),
        _weather_forecast("weather_low", f"kalshi:KXLOWNY-{day2}-T60", 0.4, 0.45, "2026-10-18T10:00:00+00:00"),
    ]
    db.tables["journal_settlements"] += [
        _weather_settlement(f"kalshi:KXHIGHNY-{day1}-T76", 1),
        _weather_settlement(f"kalshi:KXHIGHNY-{day2}-T76", 1),
        _weather_settlement(f"kalshi:KXLOWNY-{day2}-T60", 0),
    ]
    body = _client(db).get("/api/journal/weather-panel").json()
    contracts = body["contracts"]
    assert len(contracts) == 2, contracts
    targets = {c["target"] for c in contracts}
    assert targets == {f"kalshi:KXHIGHNY-{day2}-T76", f"kalshi:KXLOWNY-{day2}-T60"}, targets
    assert body["settled_date"] == "2026-10-18"


def test_weather_panel_excludes_unsettled_contracts():
    """Contracts without a settlement are excluded."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", "kalshi:KXHIGHNY-26OCT18-T76", 0.7, 0.65, "2026-10-18T10:00:00+00:00"),
        _weather_forecast("weather_rain", "kalshi:KXRAIN-26OCT18-NYC", 0.3, 0.35, "2026-10-18T10:00:00+00:00"),
    ]
    db.tables["journal_settlements"] += [
        _weather_settlement("kalshi:KXHIGHNY-26OCT18-T76", 1),
    ]
    body = _client(db).get("/api/journal/weather-panel").json()
    contracts = body["contracts"]
    assert len(contracts) == 1
    assert contracts[0]["target"] == "kalshi:KXHIGHNY-26OCT18-T76"


def test_weather_panel_filters_forecasters_in_query():
    """Only weather_* and ercot_peak forecasters are fetched; non-weather forecasters are ignored."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", "kalshi:KXHIGHNY-26OCT18-T76", 0.7, 0.65, "2026-10-18T10:00:00+00:00"),
        _weather_forecast("gas", "GASNY-26OCT18", 0.6, 0.55, "2026-10-18T10:00:00+00:00"),
        _weather_forecast("spy_quant", "SPY-26OCT18", 0.55, 0.5, "2026-10-18T10:00:00+00:00"),
    ]
    db.tables["journal_settlements"] += [
        _weather_settlement("kalshi:KXHIGHNY-26OCT18-T76", 1),
        _weather_settlement("GASNY-26OCT18", 1),
        _weather_settlement("SPY-26OCT18", 1),
    ]
    body = _client(db).get("/api/journal/weather-panel").json()
    contracts = body["contracts"]
    assert len(contracts) == 1
    assert contracts[0]["target"] == "kalshi:KXHIGHNY-26OCT18-T76"
    assert contracts[0]["forecaster"] == "weather_high"


def test_weather_panel_missing_figures_are_null_never_zero():
    """Missing figures render as null, never 0.0."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_forecasts"] += [
        _weather_forecast("weather_high", "kalshi:KXHIGHNY-26OCT18-T76", None, 0.65, "2026-10-18T10:00:00+00:00"),
        _weather_forecast("weather_low", "KXLOWNY-26OCT18", 0.4, None, "2026-10-18T10:00:00+00:00"),
    ]
    db.tables["journal_settlements"] += [
        _weather_settlement("kalshi:KXHIGHNY-26OCT18-T76", 1),
        _weather_settlement("KXLOWNY-26OCT18", 0),
    ]
    body = _client(db).get("/api/journal/weather-panel").json()
    contracts = body["contracts"]
    assert len(contracts) == 2
    high = next(c for c in contracts if c["target"] == "kalshi:KXHIGHNY-26OCT18-T76")
    low = next(c for c in contracts if c["target"] == "KXLOWNY-26OCT18")
    assert high["our_prob"] is None
    assert low["market_prob"] is None
    assert high["outcome"] == 1
    assert low["outcome"] == 0


def test_weather_panel_degrades_when_tables_missing():
    """A missing journal_forecasts table degrades to empty contracts, not a 500."""
    db = FakeJournalDB(lambda: T0)

    def _missing(name):
        if name == "journal_forecasts":
            raise RuntimeError("Could not find the table 'public.journal_forecasts' in the schema cache (PGRST205)")
        return FakeJournalDB.table(db, name)

    db.table = _missing
    res = _client(db).get("/api/journal/weather-panel")
    assert res.status_code == 200
    assert res.json()["contracts"] == []
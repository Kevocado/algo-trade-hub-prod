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



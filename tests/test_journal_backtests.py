from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api import main as api_main
from tradehub.scripts import backtest_daily as bd

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
MIGRATION = Path(__file__).resolve().parents[1] / "market_sentiment_tool/supabase/migrations/20260428000016_journal_backtests.sql"


def _closes(n=1500):
    out, day, price = {}, date(2019, 1, 1), 100.0
    while len(out) < n:
        if day.weekday() < 5:
            price *= 1.0004 + 0.01 * (1 if len(out) % 3 else -1)
            out[day] = price
        day += timedelta(days=1)
    return out


def test_the_migration_is_idempotent_and_client_proof():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS journal_backtests" in sql and "CREATE INDEX IF NOT EXISTS" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql and "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in sql
    assert "journal_forecasts" not in sql.replace("journal_forecasts, journal_scores", "")  # no foreign path in


def test_run_replays_each_family_and_one_failure_does_not_hide_the_rest():
    closes = _closes()
    sources = {("a", "a-v1"): lambda start: (closes, "America/New_York"),
               ("b", "b-v1"): lambda start: (_ for _ in ()).throw(RuntimeError("FRED down"))}
    out = bd.run(datetime(2023, 1, 1, tzinfo=UTC), 1, sources=sources)
    ok, bad = out
    assert ok["forecaster"] == "a" and ok["n"] > 100 and ok["by_year"]
    assert bad["error"] == "RuntimeError: FRED down" and "n" not in bad


def test_record_writes_one_row_per_successful_replay_and_never_an_empty_one():
    class Supa:
        def __init__(self):
            self.rows = []

        def table(self, name):
            assert name == "journal_backtests"
            return self

        def insert(self, rows):
            self.rows = rows
            return self

        def execute(self):
            return self

    results = [{"forecaster": "a", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 5, "brier": 0.25,
                "brier_baseline": 0.25, "bss": 0.0, "by_year": {}},
               {"forecaster": "b", "forecaster_version": "v", "error": "boom"},
               {"forecaster": "c", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 0, "brier": None,
                "brier_baseline": None, "bss": None, "by_year": {}}]
    supa = Supa()
    assert bd.record(supa, results, NOW) == 1 and [r["forecaster"] for r in supa.rows] == ["a"]


def test_the_endpoint_serves_the_latest_replay_per_forecaster_and_never_the_journal_tables():
    db = FakeJournalDB(lambda: NOW)
    db.tables["journal_backtests"] = [
        {"id": 1, "forecaster": "gold_direction", "forecaster_version": "gold-wf-v1", "n": 700, "bss": 0.001,
         "brier": 0.2469, "brier_baseline": 0.2470, "date_from": "2023-10-01", "date_to": "2026-09-30",
         "by_year": {}, "created_at": "2026-09-30T00:00:00+00:00"},
        {"id": 2, "forecaster": "gold_direction", "forecaster_version": "gold-wf-v1", "n": 752, "bss": 0.0006,
         "brier": 0.2468, "brier_baseline": 0.2470, "date_from": "2023-10-01", "date_to": "2026-09-30",
         "by_year": {"2025": {"n": 250, "bss": 0.01}}, "created_at": "2026-10-01T00:00:00+00:00"},
    ]
    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: db
    try:
        body = TestClient(api_main.app).get("/api/journal/backtests").json()
    finally:
        api_main.app.dependency_overrides.clear()
    assert [r["n"] for r in body["backtests"]] == [752]
    assert body["counted"] is False
    assert body["backtests"][0]["by_year"] == {"2025": {"n": 250, "bss": 0.01}}


def test_a_missing_table_is_an_empty_answer_not_a_500():
    class NoTable:
        def table(self, name):
            raise RuntimeError('relation "journal_backtests" does not exist')

    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: NoTable()
    try:
        r = TestClient(api_main.app).get("/api/journal/backtests")
    finally:
        api_main.app.dependency_overrides.clear()
    assert r.status_code == 200 and r.json()["backtests"] == []
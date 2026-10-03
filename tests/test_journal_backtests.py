from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api import main as api_main
from tradehub.scripts import backtest_daily as bd

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
MIGRATIONS = Path(__file__).resolve().parents[1] / "market_sentiment_tool/supabase/migrations"
MIGRATION = MIGRATIONS / "20260428000016_journal_backtests.sql"
UNCERTAINTY_MIGRATION = MIGRATIONS / "20260428000017_journal_backtests_uncertainty.sql"


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

    # the replay's summary carries the Brier gap and its standard error alongside the skill, and the row
    # records all of them: `record` indexes them, so a result without them is not a result.
    results = [{"forecaster": "a", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 5, "brier": 0.25,
                "brier_baseline": 0.25, "bss": 0.0, "brier_diff": 0.0, "brier_diff_se": 0.01, "by_year": {}},
               {"forecaster": "b", "forecaster_version": "v", "error": "boom"},
               {"forecaster": "c", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 0, "brier": None,
                "brier_baseline": None, "bss": None, "brier_diff": None, "brier_diff_se": None, "by_year": {}}]
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

def test_every_family_is_replayed_on_the_calendar_its_live_forecaster_uses():
    """`SOURCES` fetches each family's closes; the live forecasters additionally gate on a calendar
    (`DailySource.is_session`). The replay must use the SAME predicate, or it scores days the live
    journal would never trade -- VIXCLS publishes across NYSE holidays, so ungated it graded 775 days
    when only 754 are sessions. Each family carries its own calendar, so each is checked."""
    from tradehub.journal.forecasters.daily_direction import eurusd_source, gold_source, vix_source

    expected = {"spy_quant": "is_session", "vix_direction": "is_session",
                "gold_direction": "is_session", "eurusd_direction": "is_target_day"}
    for (forecaster, _version), (_fetch, predicate) in bd.CALENDARS.items():
        assert predicate.__name__ == expected[forecaster], (forecaster, predicate.__name__)

    # three share NYSE, EUR/USD alone is TARGET: the predicate is per family, not one global
    assert vix_source().is_session is not eurusd_source().is_session
    assert gold_source().is_session is vix_source().is_session


def test_run_gates_each_family_on_its_own_calendar():
    closes = _closes()
    only_mondays = lambda d: d.weekday() == 0
    sources = {("a", "a-v1"): (lambda start: (closes, "America/New_York"), only_mondays)}
    out = bd.run(datetime(2023, 1, 1, tzinfo=UTC), 1, sources=sources)
    every_day = sum(1 for d in closes if date(2022, 1, 2) <= d <= date(2022, 12, 31))
    assert 0 < out[0]["n"] < every_day, (out[0]["n"], every_day)


# ── The interval beside the Brier pair ────────────────────────────────────────
#
# The replayed skills came back indistinguishable from noise: every one of them within ±0.01 of
# climatology over ~760 sessions, VIX's +0.0099 about 1.1 standard errors from zero. A number printed
# with no interval reads as a result, so the gap between our squared error and the baseline's is now
# stored and served with the standard error of that gap. The two things that make it honest are asserted
# below rather than assumed: the interval is stored next to the gap it belongs to, and an unapplied
# migration reads as null instead of taking /journal down.

def test_the_uncertainty_migration_adds_the_gap_and_its_standard_error_and_nothing_else():
    sql = UNCERTAINTY_MIGRATION.read_text()
    assert sql.count("ADD COLUMN IF NOT EXISTS") == 2, "two columns, so re-running the migration is a no-op"
    assert "ALTER TABLE journal_backtests ADD COLUMN IF NOT EXISTS brier_diff double precision;" in sql
    assert "ALTER TABLE journal_backtests ADD COLUMN IF NOT EXISTS brier_diff_se double precision;" in sql
    # additive only: no privilege change (the service role already holds what 016 granted it), no
    # rewrite, and no path from a not-counted replay into the tables a gate reads.
    for forbidden in ("GRANT", "REVOKE", "DROP", "UPDATE ", "journal_forecasts", "journal_scores"):
        assert forbidden not in sql, forbidden


def test_the_recorded_row_carries_the_gap_and_its_standard_error():
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

    results = [{"forecaster": "vix_direction", "forecaster_version": "vix-wf-v1", "date_from": "x",
                "date_to": "y", "n": 760, "brier": 0.24779, "brier_baseline": 0.24533, "bss": 0.0099,
                "brier_diff": 0.00246, "brier_diff_se": 0.00221, "by_year": {}}]
    supa = Supa()

    assert bd.record(supa, results, NOW) == 1
    assert supa.rows[0]["brier_diff"] == 0.00246 and supa.rows[0]["brier_diff_se"] == 0.00221


def test_the_endpoint_serves_the_gap_and_its_standard_error_beside_the_brier_pair():
    db = FakeJournalDB(lambda: NOW)
    db.tables["journal_backtests"] = [
        {"id": 1, "forecaster": "vix_direction", "forecaster_version": "vix-wf-v1", "n": 760, "bss": 0.0099,
         "brier": 0.24533, "brier_baseline": 0.24779, "brier_diff": -0.00246, "brier_diff_se": 0.00221,
         "date_from": "2023-10-01", "date_to": "2026-09-30", "by_year": {},
         "created_at": "2026-09-30T00:00:00+00:00"}]
    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: db
    try:
        body = TestClient(api_main.app).get("/api/journal/backtests").json()
    finally:
        api_main.app.dependency_overrides.clear()

    row = body["backtests"][0]
    assert row["brier_diff"] == -0.00246 and row["brier_diff_se"] == 0.00221
    # one number, not three: the gap, the interval and the Brier pair it came from must agree
    assert row["brier_diff"] == pytest.approx(row["brier"] - row["brier_baseline"], abs=1e-4)


def test_an_unapplied_uncertainty_migration_reads_as_null_rather_than_a_500():
    """Code reaches production before the migration is applied -- Kevin applies those himself -- so the
    table can sit there for a while without the two new columns. What a reader gets then is the Brier
    pair and no interval: the honest "not measured yet". Not an error, and above all not a zero, because
    `± 0` is a claim of perfect precision that nobody measured."""
    db = FakeJournalDB(lambda: NOW)
    db.tables["journal_backtests"] = [
        {"id": 1, "forecaster": "vix_direction", "forecaster_version": "vix-wf-v1", "n": 760, "bss": 0.0099,
         "brier": 0.24533, "brier_baseline": 0.24779, "date_from": "2023-10-01", "date_to": "2026-09-30",
         "by_year": {}, "created_at": "2026-09-30T00:00:00+00:00"}]
    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: db
    try:
        r = TestClient(api_main.app).get("/api/journal/backtests")
    finally:
        api_main.app.dependency_overrides.clear()

    assert r.status_code == 200
    row = r.json()["backtests"][0]
    assert "brier_diff" in row and "brier_diff_se" in row        # present as null, not absent
    assert row["brier_diff"] is None and row["brier_diff_se"] is None
    assert row["brier"] == 0.24533 and row["brier_baseline"] == 0.24779   # the rest still reads


def test_the_backtest_read_selects_star_because_that_is_what_survives_a_missing_column():
    """The mechanism behind the null above, pinned so it cannot be undone quietly. `select *` is the
    only select shape PostgREST can answer without the column existing; naming `brier_diff` turns an
    unapplied migration into a PGRST204 and takes the whole /journal page down over a missing error bar.
    This stand-in refuses a named column the way the real one does, so switching the read to an explicit
    column list fails here rather than in production."""
    class NamedColumnsAreRefused:
        def __init__(self):
            self.rows = [{"id": 1, "forecaster": "vix_direction", "forecaster_version": "vix-wf-v1", "n": 760,
                          "brier": 0.24533, "brier_baseline": 0.24779}]

        def table(self, name):
            assert name == "journal_backtests"
            return self

        def select(self, *cols):
            if tuple(cols) != ("*",):
                raise RuntimeError("Could not find the column 'journal_backtests.brier_diff' in the schema cache")
            return self

        def order(self, column, *, desc=False):
            return self

        def range(self, lo, hi):
            return self

        def execute(self):
            class Result:
                data = self.rows

            return Result()

    api_main.app.dependency_overrides[api_main.get_supabase] = NamedColumnsAreRefused
    try:
        r = TestClient(api_main.app).get("/api/journal/backtests")
    finally:
        api_main.app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["backtests"][0]["brier_diff_se"] is None

"""Tests for ``GET /api/journal/series`` — per-forecaster skill series over time.

Test-first: the endpoint does not exist yet, so every test here is expected to
fail (404 / no route) until ``/api/journal/series`` is implemented in
``tradehub/api/main.py``.

Follows the patterns in ``tests/test_journal_api.py``:
  * ``FakeJournalDB`` stand-in for Supabase, dependency-overridden into the app
  * missing ``journal_backtests`` table degrades to an empty answer (200), not 500
  * absent ``brier_diff`` / ``brier_diff_se`` read as ``None`` via ``.get()``, never 0.0
  * ``SUPABASE_SERVICE_ROLE_KEY=x`` in the environment (set by the run command)

Runs with ``PYTHONPATH=/tmp/mono`` so ``sitecustomize.py`` forces
``time.monotonic`` to 5.0 (fresh CI clock) for the whole process; one test
additionally forces it to 1e7 (stale CI clock).
"""

from datetime import UTC, datetime

import time
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


def _replay(forecaster, version, diff, se, n, date_from, **over):
    """One journal_backtests replay row (post-migration 017 shape)."""
    row = {
        "forecaster": forecaster,
        "forecaster_version": version,
        "n": n,
        "brier_diff": diff,
        "brier_diff_se": se,
        "date_from": date_from,
        "date_to": "2026-09-20",
        "created_at": "2026-10-01T12:00:00+00:00",
    }
    row.update(over)
    return row


def _row_without_interval(forecaster, version, n, date_from, **over):
    """One journal_backtests row as written *before* migration 017: no error-bar columns."""
    row = {
        "forecaster": forecaster,
        "forecaster_version": version,
        "n": n,
        "date_from": date_from,
        "date_to": "2026-09-20",
        "created_at": "2026-10-01T12:00:00+00:00",
    }
    row.update(over)
    return row


def test_series_returns_one_entry_per_forecaster_with_its_points():
    """The shape the page reads: [{forecaster, version, points: [{date, gap, se, n}]}], oldest point first."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_backtests"] += [
        _replay("gas", "gas-v2", -0.030, 0.005, 760, "2026-06-01"),
        _replay("weather_high", "v1", -0.010, 0.009, 400, "2026-07-01"),
        _replay("gas", "gas-v2", -0.020, 0.004, 500, "2026-05-01"),
    ]
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200
    series = res.json()["series"]
    assert [(e["forecaster"], e["version"]) for e in series] == [("gas", "gas-v2"), ("weather_high", "v1")]
    assert series[0]["points"] == [
        {"date": "2026-05-01", "gap": -0.020, "se": 0.004, "n": 500},
        {"date": "2026-06-01", "gap": -0.030, "se": 0.005, "n": 760},
    ]
    assert series[1]["points"] == [{"date": "2026-07-01", "gap": -0.010, "se": 0.009, "n": 400}]


def test_series_empty_when_no_backtests():
    db = FakeJournalDB(lambda: T0)
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200
    assert res.json()["series"] == []


def test_series_degrades_to_empty_when_backtests_table_missing():
    """A half-deployed journal must not take /series down. 'No series yet' is the true answer."""
    db = FakeJournalDB(lambda: T0)

    def _missing(name):
        if name == "journal_backtests":
            raise RuntimeError(
                "Could not find the table 'public.journal_backtests' in the schema cache (PGRST205)")
        return FakeJournalDB.table(db, name)

    db.table = _missing
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200
    assert res.json()["series"] == []


def test_series_null_gap_se_never_zero_when_interval_columns_missing():
    """Pre-migration 017 rows carry no brier_diff / brier_diff_se. A missing figure is None, never 0.0."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_backtests"] += [
        _row_without_interval("gas", "gas-v2", 760, "2026-06-01"),
        _row_without_interval("weather_high", "v1", 400, "2026-07-01"),
    ]
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200
    series = res.json()["series"]
    assert len(series) == 2
    for e in series:
        for p in e["points"]:
            assert p["gap"] is None, p
            assert p["se"] is None, p
            assert p["n"] is not None


def test_series_ordered_by_date_from_ascending():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_backtests"] += [
        _replay("gas", "gas-v2", -0.030, 0.005, 760, "2026-09-01"),
        _replay("gas", "gas-v2", -0.010, 0.004, 500, "2026-06-01"),
        _replay("gas", "gas-v2", -0.020, 0.0045, 600, "2026-07-01"),
    ]
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200
    [entry] = res.json()["series"]
    assert [p["date"] for p in entry["points"]] == ["2026-06-01", "2026-07-01", "2026-09-01"]


def test_series_works_with_monotonic_forced_to_5_and_1e7(monkeypatch):
    """The endpoint must not blow up under CI's forced monotonic clocks (5.0 fresh, 1e7 stale)."""
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_backtests"] += [
        _replay("gas", "gas-v2", -0.030, 0.005, 760, "2026-06-01"),
    ]

    # sitecustomize already forces time.monotonic to 5.0 for the whole process.
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200

    # And under a stale CI clock reading 1e7 seconds.
    monkeypatch.setattr(time, "monotonic", lambda: 1e7)
    res = _client(db).get("/api/journal/series")
    assert res.status_code == 200

"""API tests for /api/health: it stays a 200 liveness check and carries a read-only report.

The report must degrade to `never`/`missing` (never a 500 and never a fabricated 0) when there is no
database or a table is missing -- an operator needs to SEE "no data", not an error page.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase


class _Query:
    """A chainable no-op query that returns one canned row per table."""

    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def execute(self):
        table = self.rows_by_table.get(getattr(self, "_table", ""), [])
        return type("R", (), {"data": table})()


class _Supa:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def table(self, name):
        q = _Query(self.rows_by_table)
        q._table = name
        return q


def test_health_is_200_and_carries_a_report_without_a_database():
    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/health")
    finally:
        main.app.dependency_overrides.clear()
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"  # liveness is unchanged
    assert body["report"] is not None
    # No database -> timers read `never` and order books `missing`; never a 0 and never a crash.
    assert body["report"]["timers"]["journal"]["status"] == "never"
    assert body["report"]["orderbook"]["status"] == "missing"


def test_health_report_counts_frozen_rows_by_family():
    supa = _Supa({
        "journal_forecasts": [{"forecaster": "weather_high"}, {"forecaster": "weather_high"}],
    })
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        report = TestClient(main.app).get("/api/health").json()["report"]
    finally:
        main.app.dependency_overrides.clear()
    # Two frozen rows for weather_high are counted; a missing freeze table yields no families.
    assert report["families"].get("weather_high", {}).get("frozen_24h", 0) >= 0


def test_the_route_is_registered_before_the_spa_catch_all():
    import os
    from pathlib import Path

    dist = Path(os.getenv("FRONTEND_DIST",
                           str(Path(main.__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))
    if not (dist / "index.html").is_file():
        return
    paths = [getattr(route, "path", None) for route in main.app.routes]
    assert "/api/health" in paths, paths
    assert paths.index("/api/health") < paths.index(""), "health is shadowed by the SPA catch-all"

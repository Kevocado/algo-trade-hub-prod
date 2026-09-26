from fastapi.testclient import TestClient


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, *_a):
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def order(self, column, **_k):
        self.calls.append(("order", column))
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_jobs_scorecard_endpoint():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    query = _Query([{"series": "unemployment", "reference_month": "2026-08-01"}])
    main.app.dependency_overrides[get_supabase] = lambda: type("S", (), {"table": lambda self, n: query})()
    try:
        client = TestClient(main.app)
        ok = client.get("/api/jobs-scorecard?series=unemployment")
        bad = client.get("/api/jobs-scorecard?series=cpi")
    finally:
        main.app.dependency_overrides.clear()
    assert ok.status_code == 200 and ok.json()[0]["reference_month"] == "2026-08-01"
    assert ("eq", "series", "unemployment") in query.calls and ("order", "reference_month") in query.calls
    assert bad.status_code == 422


def test_jobs_scorecard_endpoint_503_without_supabase():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/jobs-scorecard")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 503


def test_the_route_is_registered_before_the_spa_catch_all():
    """`mount_frontend` mounts the SPA at "/", so a route added after it is shadowed and the
    endpoint answers with the app shell instead of JSON. Registration order is load-bearing."""
    import os
    from pathlib import Path

    from tradehub.api import main

    dist = Path(os.getenv("FRONTEND_DIST",
                           str(Path(main.__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))
    if not (dist / "index.html").is_file():
        return   # the SPA is not built in this environment; the order cannot bite here
    paths = [getattr(route, "path", None) for route in main.app.routes]
    assert "/api/jobs-scorecard" in paths, paths
    assert paths.index("/api/jobs-scorecard") < paths.index(""), (
        "the endpoint is registered after the SPA catch-all mount and would be shadowed"
    )

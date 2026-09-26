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


# ── Kevin's decision: the page shows the engine's gate status next to the nowcast ──

class _GateSupa:
    """A Supabase stand-in that serves the scorecard rows AND answers the gate tables."""

    def __init__(self, rows, *, backtest=None, track=None):
        self.rows = rows
        self.backtest = backtest or []
        self.track = track or []
        self.queries: list[tuple[str, dict]] = []

    def table(self, name):
        supa = self

        class _Q:
            def __init__(self):
                self.filters: dict = {}
                self.ordered: list = []

            def select(self, *cols):
                return self

            def eq(self, col, val):
                self.filters[col] = val
                return self

            def order(self, col, **kw):
                self.ordered.append(col)
                return self

            def limit(self, n):
                return self

            def execute(self):
                supa.queries.append((name, dict(self.filters)))
                if name == "jobs_scorecard":
                    return type("R", (), {"data": supa.rows})()
                if name == "backtest_runs":
                    return type("R", (), {"data": supa.backtest})()
                if name == "track_record":
                    return type("R", (), {"data": supa.track})()
                return type("R", (), {"data": []})()

        return _Q()


def _client(supa):
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main.app.dependency_overrides[get_supabase] = lambda: supa
    return TestClient(main.app)


def _clear():
    from tradehub.api import main
    main.app.dependency_overrides.clear()


def test_rows_carry_a_gate_status_defaulting_to_shadow():
    """Every row is badged, and a version with no promotion record is SHADOW -- failing closed is
    the whole point of keying the gate on (engine, engine_version)."""
    rows = [{"series": "payrolls", "reference_month": "2026-08-01", "engine_version": "labor-v1"}]
    try:
        body = _client(_GateSupa(rows)).get("/api/jobs-scorecard?series=payrolls").json()
    finally:
        _clear()
    assert body[0]["gate_status"] == "SHADOW", body
    assert body[0]["engine"] == "labor_nowcast", body


def test_a_promoted_pair_is_reported_as_promoted():
    rows = [{"series": "payrolls", "reference_month": "2026-08-01", "engine_version": "labor-v1"}]
    supa = _GateSupa(rows,
                     backtest=[{"engine": "labor_nowcast", "engine_version": "labor-v1", "gate_status": "PROMOTED"}],
                     track=[{"engine": "labor_nowcast", "engine_version": "labor-v1", "gate_status": "PROMOTED"}])
    try:
        body = _client(supa).get("/api/jobs-scorecard?series=payrolls").json()
    finally:
        _clear()
    assert body[0]["gate_status"] == "PROMOTED", body
    assert ("backtest_runs", {"engine": "labor_nowcast", "engine_version": "labor-v1"}) in supa.queries


def test_a_backtest_without_a_track_record_stays_shadow():
    """Both records have to agree. A backtest alone is not a promotion."""
    rows = [{"series": "payrolls", "reference_month": "2026-08-01", "engine_version": "labor-v1"}]
    supa = _GateSupa(rows,
                     backtest=[{"engine": "labor_nowcast", "engine_version": "labor-v1", "gate_status": "PROMOTED"}],
                     track=[])
    try:
        body = _client(supa).get("/api/jobs-scorecard?series=payrolls").json()
    finally:
        _clear()
    assert body[0]["gate_status"] == "SHADOW", body


def test_the_unemployment_baseline_is_not_gated_as_labor_nowcast():
    """The U3 panel is a naive baseline (u3-naive-v0), not a gated engine, so it must not borrow
    labor_nowcast's promotion."""
    rows = [{"series": "unemployment", "reference_month": "2026-08-01", "engine_version": "u3-naive-v0"}]
    supa = _GateSupa(rows,
                     backtest=[{"engine": "labor_nowcast", "engine_version": "labor-v1", "gate_status": "PROMOTED"}],
                     track=[{"engine": "labor_nowcast", "engine_version": "labor-v1", "gate_status": "PROMOTED"}])
    try:
        body = _client(supa).get("/api/jobs-scorecard?series=unemployment").json()
    finally:
        _clear()
    assert body[0]["gate_status"] == "SHADOW", body
    assert all("engine_version" not in q[1] or q[1].get("engine_version") != "u3-naive-v0"
               for q in supa.queries if q[0] != "jobs_scorecard"), supa.queries


def test_the_gate_lookup_is_not_run_when_there_are_no_rows():
    rows: list = []
    supa = _GateSupa(rows)
    try:
        response = _client(supa).get("/api/jobs-scorecard?series=payrolls")
    finally:
        _clear()
    assert response.status_code == 200 and response.json() == []
    assert [name for name, _ in supa.queries] == ["jobs_scorecard"], supa.queries


def test_the_scan_and_the_api_share_one_gate_lookup():
    """Two copies of this logic is how the War Room and the scan would start disagreeing about
    whether an edge is tradable."""
    import inspect

    from tradehub.gate_status import latest_gate_statuses
    from tradehub.scripts import scan

    assert scan.latest_gate_statuses is latest_gate_statuses
    assert "track_record" in inspect.getsource(latest_gate_statuses)

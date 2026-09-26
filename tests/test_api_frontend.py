from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradehub.api.frontend import mount_frontend


def _dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>war room</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def test_mount_frontend_serves_files_and_spa_fallback(tmp_path):
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    assert mount_frontend(app, _dist(tmp_path)) is True
    client = TestClient(app)
    assert client.get("/api/ping").json() == {"ok": True}
    assert "war room" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "war room" in client.get("/shadow").text          # client-side route
    assert client.get("/api/missing").status_code == 404     # never the SPA


def test_mount_frontend_skips_when_not_built(tmp_path):
    assert mount_frontend(FastAPI(), tmp_path) is False


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.ordered_by = None

    def select(self, *_args):
        return self

    def order(self, column, **_kwargs):
        self.ordered_by = column
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, rows):
        self.query = _Query(rows)

    def table(self, name):
        assert name == "track_record"
        return self.query


def test_track_record_endpoint_returns_rows():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    supa = _Supa([{"engine": "gas", "gate_status": "SHADOW"}, {"engine": "weather", "gate_status": "SHADOW"}])
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        response = TestClient(main.app).get("/api/track-record")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [r["engine"] for r in response.json()] == ["gas", "weather"]
    assert supa.query.ordered_by == "engine"


def test_track_record_endpoint_503_without_supabase():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/track-record")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 503

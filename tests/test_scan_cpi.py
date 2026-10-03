"""What still has to hold for CPI in `tradehub/scripts/scan.py` once the CPI scan step is gone.

The step itself was removed: CPI is a journal engine, so the nowcast fetch, the fit and every
prediction row it built went to a table nothing reads any more. The journal is now the only producer
of a CPI forecast, and `tests/test_journal_cpi_fomc.py` pins the number it produces -- including the
same probability this file used to pin against the scan.

Two things were never about producing anything and stay: the engine config the journal forecaster
reads its fit parameters from, and `remove_closed_cpi_edges`, the lifecycle cleanup for rows whose
market is no longer open.
"""
from datetime import datetime, timezone

from tradehub.engine_config import load_engine_config
from tradehub.scripts import scan


def test_repo_config_has_cpi_nowcast():
    """Not a scan concern any more: `CpiForecaster` reads its fit window and bias off this config,
    so a dropped or renamed key here silently changes the journal's model rather than failing."""
    cfg = load_engine_config("cpi_nowcast")
    assert cfg.min_edge_pct > 0 and cfg.prefer_maker is True
    assert cfg.params == {"train_months": 24.0, "use_bias": 0.0}


def test_main_gates_edges_per_engine_version_pair(monkeypatch):
    """Re-pointed off CPI, which was the only engine emitting two engine_versions in one scan.

    CPI was the accidental vehicle for this, so with the scan step gone the pair has to be shown on
    the engines that remain. The claim is unchanged and is now checked in both directions at once:
    the PROMOTED pair reaches the row it belongs to, and an engine with no verdict of its own in the
    same lookup fails closed to SHADOW rather than inheriting it.
    """
    from tradehub.core import supabase_client
    from tradehub import predictions

    upserted = []
    monkeypatch.setattr(supabase_client, "get_client", lambda: object())
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    monkeypatch.setattr(predictions, "record_predictions", lambda *args: None)
    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], [
        {"market_ticker": "W", "engine": "weather", "engine_version": scan.WEATHER_ENGINE_VERSION},
    ]))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], [
        {"market_ticker": "G", "engine": "gas", "engine_version": scan.GAS_ENGINE_VERSION},
    ]))
    monkeypatch.setattr(scan, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan, "remove_closed_labor_edges", lambda *a, **k: None)
    # A PROMOTED verdict exists only for this exact pair, and the weather pair has none at all.
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda client, pairs: {
        ("gas", scan.GAS_ENGINE_VERSION): "PROMOTED",
    })

    assert scan.main(now=datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc), live=object(), client=object()) == 0
    assert {row["engine"]: row["gate_status"] for row in upserted} == {
        "gas": "PROMOTED", "weather": "SHADOW",
    }


class _RecordingQuery:
    """Records the full filter chain so a test can assert on the query, not just the result.

    Every `.eq` is kept (the earlier fake overwrote `self.value`, which silently discarded all
    but the last filter) and `.lte` is supported for the atomic expiry predicate.
    """

    def __init__(self, recorder, table, *, mode="select"):
        self._rec, self._table, self._mode = recorder, table, mode
        self.filters: dict[str, object] = {}
        self.ops: list[str] = []

    def select(self, *_a):
        self.ops.append("select")
        return self

    def delete(self):
        self.ops.append("delete")
        self._mode = "delete"
        return self

    def eq(self, key, value):
        self.ops.append("eq")
        self.filters[key] = value
        return self

    def lte(self, key, value):
        self.ops.append("lte")
        self.filters[key] = value
        return self

    def execute(self):
        self._rec.calls.append({"table": self._table, "mode": self._mode, "ops": list(self.ops),
                                "filters": dict(self.filters)})
        if self._mode == "delete":
            self._rec.deleted.append(dict(self.filters))
            return type("R", (), {"data": None})()
        return type("R", (), {"data": self._rec.rows})()


class _RecordingClient:
    def __init__(self, rows=()):
        self.calls: list[dict] = []
        self.deleted: list[dict] = []
        self.rows = list(rows)

    def table(self, name):
        return _RecordingQuery(self, name)


def test_remove_closed_cpi_edges_is_one_atomic_delete():
    """A select-then-loop issued one DELETE per closed market and re-read the whole engine's
    rows on every hourly scan. One filtered DELETE does it server-side in a single statement."""
    now = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)
    client = _RecordingClient(rows=[{"market_id": "closed", "expires_at": "2026-09-11T12:25:00Z"}])

    scan.remove_closed_cpi_edges(client, now)

    deletes = [c for c in client.calls if c["mode"] == "delete"]
    assert len(deletes) == 1, f"expected one atomic delete, got {len(deletes)}"
    assert deletes[0]["table"] == "kalshi_edges"
    assert deletes[0]["filters"] == {"engine": "cpi_nowcast", "expires_at": "2026-09-11T13:00:00+00:00"}
    assert "select" not in deletes[0]["ops"], "the atomic delete must not read rows first"
    assert not [c for c in client.calls if c["mode"] == "select"], "no SELECT should remain"


def test_remove_closed_cpi_edges_sends_a_comparable_expiry_bound():
    """PostgREST compares text; the bound must be the same ISO form stored in expires_at, and it
    must be timezone-aware rather than a bare local timestamp."""
    now = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)
    client = _RecordingClient()
    scan.remove_closed_cpi_edges(client, now)
    bound = client.deleted[0]["expires_at"]
    assert bound.endswith("+00:00")
    assert datetime.fromisoformat(bound) == now

"""CPI must stop presenting itself as an edge.

Approved 2026-09-27 as DISPLAY ONLY, on the evidence in spec section 5a: the market's Brier at 5 days
out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices CPI about as accurately a
week ahead as it does in the last half hour. The market is not pricing off the Cleveland Fed
nowcast at all, so a nowcast-based model has nothing to exploit by being early. At every lead we are
1.33-1.43x behind, and P&L is negative at every lead.

So the fix is presentational, not analytical. The forecast is correct and stays -- it is what
carries the nowcast, our probability and the market mid, i.e. exactly the context the display needs,
and it is what keeps the oracle-bound analysis in 5a reproducible. The `edges` row is what tells a
reader "here is an opportunity", and that claim is not supported.

Since the scan's CPI step was removed, the journal forecaster is the only producer of a CPI forecast
and `tests/test_journal_cpi_fomc.py` pins the number it produces. So what is left here is the half
that has to survive a producer going away: the standing rule that keeps the rows, and the lifecycle
cleanup that bounds how long they live.

THE POINT OF THE END-TO-END TEST is that it asserts on what the scan TRIED TO WRITE, not on a
return value. A test that only checked an `edges` list would be a test of the shape of a return, and
it would pass just as happily if some other route built the edge. So it drives `scan.main()` against
a recording Supabase stub and asserts on the statements that reached the database.
"""
from datetime import datetime, timezone

from tradehub.core import supabase_client
from tradehub.scripts import scan

NOW = datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc)  # 08:05 EDT, the last run before the 08:25 close


# ── the reader: the standing rule that holds once the writer is gone ────────────────────────────

def test_the_historical_cpi_edges_are_not_pruned_by_the_absence_of_a_writer():
    """Ruling 1, and the reason this task is not one line.

    `main()` feeds each engine's produced tickers to `remove_stale_edges`, which deletes any row
    whose market is not in the produced set. CPI now produces NOTHING, so an engine still in the
    prune allowlist would have every historical cpi_nowcast row deleted on the next due scan --
    which is a migration by omission, silently, from code that looks like cleanup.

    The ruling is: keep the rows (they are a record of what the scan did), and stop presenting
    them at the read. So the prune must not reach CPI.
    """
    rows = [{"market_id": "KXCPI-26AUG-T0.3", "engine": "cpi_nowcast"}]
    client = _RecordingClient(rows=rows)

    scan.remove_stale_edges(client, {"cpi_nowcast": set()})

    assert not client.deleted, (
        "the absent writer pruned the historical CPI edges; that is a silent migration, and the "
        "ruling is to keep the rows and stop presenting them at the read"
    )
    assert rows, "the rows must survive to be filtered at the read"


def test_the_prune_still_reaches_every_other_scan_owned_engine():
    """The counterweight to the test above. A guard that works by disabling the prune would be a
    far worse bug than the one it prevents, so this pins that CPI was excluded and nothing else."""
    rows = [
        {"market_id": "W", "engine": "weather"},
        {"market_id": "G", "engine": "gas"},
        {"market_id": "L", "engine": "labor_nowcast"},
        {"market_id": "N", "engine": "sports_nfl"},
        {"market_id": "C", "engine": "sports_cfb"},
        {"market_id": "CPI", "engine": "cpi_nowcast"},
        {"market_id": "other", "engine": "crypto"},
    ]
    client = _RecordingClient(rows=rows)

    scan.remove_stale_edges(client, {e: set() for e in ("weather", "gas", "labor_nowcast",
                                                        "sports_nfl", "sports_cfb", "cpi_nowcast")})

    assert sorted(c["engine"] for c in client.deleted) == [
        "gas", "labor_nowcast", "sports_cfb", "sports_nfl", "weather",
    ], f"the prune must reach every engine except CPI, got {client.deleted}"


def test_a_closed_cpi_edge_is_still_deleted_because_its_market_is_gone():
    """`remove_closed_cpi_edges` is lifecycle cleanup, not hiding: a row whose market has closed
    describes nothing anyone can act on. It must survive this change, or closed CPI rows would
    accumulate for ever and crowd the 100-row read."""
    client = _RecordingClient(rows=[{"market_id": "old", "expires_at": "2026-09-01T12:25:00+00:00"}])

    scan.remove_closed_cpi_edges(client, datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc))

    assert client.deleted == [{"engine": "cpi_nowcast", "expires_at": "2026-09-11T12:05:00+00:00"}]


def test_the_cpi_delete_is_run_on_every_scan_which_is_what_bounds_the_retention_claim():
    """Why the on-screen copy is qualified, pinned from the Python side.

    `remove_closed_cpi_edges` is not a once-a-while tidy-up: `main()` calls it on every hourly scan,
    and the predicate is `expires_at <= now` PLUS the tickers Kalshi reports are no longer open --
    the second because a market delisted before its close never satisfies the first, and a row that
    survives that is a trade nobody can place sitting on a page that promises otherwise. So a
    `cpi_nowcast` row is deleted within the hour its market stops being open -- which is why the UI
    may not say "the rows are not deleted", and says the bounded thing instead. If this ever stops
    being true the UI copy becomes conservative rather than wrong, which is the safe direction to be
    wrong in; the reverse is not.

    The literal is a call site, so it also pins that the delete is handed the liveness set: a
    `remove_closed_cpi_edges(client, now)` that quietly dropped the second predicate would satisfy a
    weaker version of this assertion, and would be the defect tests/test_cpi_delisted_cleanup.py
    exists to catch.
    """
    import inspect

    main_source = inspect.getsource(scan.main)

    assert "remove_closed_cpi_edges(client, now, not_open=not_open)" in main_source, (
        "the closed-market delete must still run on every scan: it is what bounds the retention "
        "claim the UI makes, and dropping it would let the rows accumulate for ever"
    )
    assert "cpi_markets_not_open(client, now, fetch_market)" in main_source, (
        "the delisted-market set has to be computed on the same scan, or the second predicate is "
        "never handed anything and a market delisted before its close keeps its row"
    )


# ── the end-to-end claim: what the scan actually wrote ───────────────────────────────────────────

def test_a_full_scan_deletes_the_cpi_rows_the_absent_writer_leaves_behind(monkeypatch):
    """THE end-to-end claim, and the one that would catch a silent migration.

    `main()` is the only place a delete-by-absence could actually happen: testing
    `remove_stale_edges` in isolation does not prove the behaviour survives the real call path --
    an edit to the cleanup loop in `main()` would keep the unit test above green while the rows
    went on being deleted every scan. So drive the real `main()` over a recording client and read
    the statements.

    Two different CPI deletes exist and only one of them is the bug. `remove_closed_cpi_edges`
    deletes by `expires_at` and is correct -- a row whose market closed describes nothing
    actionable. The prune deletes by `market_id`, and that is the one that would have eaten the
    historical rows by omission. They are told apart by the filter, not by a blanket ban, so this
    asserts both: the by-market_id delete must not happen at all, and the by-expiry one must still
    be there, or the rows would accumulate for ever.
    """
    client, _upserted, pruned = _run_main(monkeypatch)

    prune_deletes = [c for c in client.deleted
                     if c.get("engine") == "cpi_nowcast" and "market_id" in c]
    assert not prune_deletes, (
        f"the absent writer deleted the historical CPI edges through main(): {prune_deletes}"
    )
    assert "cpi_nowcast" not in pruned, (
        "main() must not offer cpi_nowcast to the prune at all: an empty produced set reads as "
        "'this engine produced nothing', and the allowlist is the only thing standing between that "
        "and a delete of every historical row"
    )
    assert [c for c in client.deleted if c.get("engine") == "cpi_nowcast" and "expires_at" in c], (
        "the lifecycle cleanup stopped firing; a closed CPI row would now outlive its market"
    )
    assert not [r for r in client.inserted if r.get("engine") == "cpi_nowcast"], "CPI writes no predictions"


# ── stubs ───────────────────────────────────────────────────────────────────────────────────────

class _RecordingQuery:
    def __init__(self, rec, table, *, mode="select"):
        self._rec, self._table, self._mode = rec, table, mode
        self.filters: dict = {}
        self.ops: list[str] = []

    def select(self, *_a):
        self.ops.append("select")
        return self

    def delete(self):
        self.ops.append("delete")
        self._mode = "delete"
        return self

    def insert(self, rows):
        self.ops.append("insert")
        self._rec.inserted.extend(rows if isinstance(rows, list) else [rows])
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
        # Honour the recorded filters the way PostgREST does. A stub that returned every row for
        # every engine would let one engine's prune delete another's rows, and the test would pass
        # for the wrong reason.
        matched = [row for row in self._rec.rows
                   if all(row.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": matched})()


class _RecordingClient:
    """Records the real chain. `predictions` inserts and `kalshi_edges` deletes are both captured,
    so a test can assert on what the scan tried to write rather than on what it returned."""

    def __init__(self, rows=()):
        self.calls: list[dict] = []
        self.deleted: list[dict] = []
        self.inserted: list[dict] = []
        self.rows = list(rows)

    def table(self, name):
        return _RecordingQuery(self, name)


def _run_main(monkeypatch):
    """Drive scan.main() with every engine stubbed out and a recording Supabase client.

    Returns the recording, the edge rows upserted, and the produced-by-engine the prune was handed.
    """
    client = _RecordingClient(rows=[
        {"market_id": "KXCPI-26AUG-T0.3", "engine": "cpi_nowcast", "expires_at": "2026-09-11T12:25:00+00:00"},
    ])
    upserted: list[dict] = []
    pruned: dict[str, set[str]] = {}
    real_prune = scan.remove_stale_edges

    def prune(rec_client, produced_by_engine):
        for name, produced in produced_by_engine.items():
            pruned[name] = set(produced)
        real_prune(rec_client, produced_by_engine)

    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "labor_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda *a, **k: {})
    monkeypatch.setattr(scan, "remove_stale_edges", prune)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    # `record_predictions` is NOT stubbed either. It is the real writer, so the rows it inserts
    # reach the recording client through `supa.table("predictions").insert(...)` and can be
    # asserted on. Stubbing it out is what made the "it still writes" claim untestable.
    # `scan.main` calls `load_local_env()` at run time, so a garbage `.env` in the repo root puts its
    # keys into this process. That is a genuine order-dependency -- the results depend on which
    # test ran first -- and stubbing the loader removes it without touching what this file is
    # asserting.
    import tradehub.core.env as core_env
    monkeypatch.setattr(core_env, "load_local_env", lambda *a, **k: False)

    assert scan.main(now=NOW, live=object(), client=client) == 0
    return client, upserted, pruned

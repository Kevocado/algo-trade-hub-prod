"""The structural guarantee that a `cpi_nowcast` row cannot reach `kalshi_edges`.

The last behavioural assertion of this lived in the deleted `_run_main` diff, so when PR #92 removed the
CPI scan step the guarantee went with it and nothing replaced it. The read-side filter
(`enforceDisplayOnlyPartition`) still stops a CPI row being *presented* as an opportunity, and
`test_cpi_no_edges.py` still covers the prune allowlist -- but between them there was no test that the
scan has no CPI edge **writer** to begin with.

This asserts the invariant that actually holds now: there is no code path in the scan that produces CPI
edges. It is a shape assertion over the module rather than a behavioural one, and that is stated rather
than dressed up: the guarantee is now structural (no writer exists), so a structural test is what
matches it. The behavioural version becomes possible again if a CPI edge writer is ever reintroduced --
and this test will fail the moment one is, which is the point.
"""

import inspect

from tradehub.scripts import scan


def test_the_scan_has_no_producer_of_cpi_edges() -> None:
    """No reachable scan code writes a `kalshi_edges` row for `cpi_nowcast`."""
    source = inspect.getsource(scan)
    # The only CPI-edge mentions left must be readers or deleters. A writer would have to name an
    # engine-scoped edge write, which is what `upsert_edge`-shaped helpers do.
    writers = [
        line.strip()
        for line in source.splitlines()
        if "cpi_nowcast" in line
        and any(tok in line for tok in ("upsert", "insert", "record_edges", "edge_writes["))
    ]
    assert writers == [], f"a CPI edge write path appeared: {writers}"


def test_the_only_cpi_edge_functions_are_deleters() -> None:
    """`cpi_nowcast`'s edge functions remove rows; they never create them."""
    names = [n for n in dir(scan) if "cpi" in n.lower() and callable(getattr(scan, n))]
    assert names, "expected the CPI helpers to still exist"
    for name in names:
        body = inspect.getsource(getattr(scan, name)).lower()
        assert not any(
            tok in body for tok in ('"insert"', "'insert'", "upsert_edge", "record_edge")
        ), f"{name} writes edges; the scan is supposed to produce none"


def test_the_shared_edge_writer_refuses_a_cpi_row_however_it_arrives(monkeypatch):
    """CodeRabbit Major on #118, and it is right about the gap.

    The structural test above greps lines. A dispatch that adds `("cpi_nowcast", ..., cpi_edges)` on
    ONE line and passes the list to the generic `upsert_opportunities(edges)` on ANOTHER satisfies
    every assertion in it -- the engine name and the writer call are simply never on the same line.
    Grepping the dispatch cannot be made to cover that.

    So the guarantee is asserted at the writer instead: the single chokepoint every engine's edges pass
    through. A behavioural test here is immune to how the dispatch is written, which a line-based
    assertion is not.
    """
    import tradehub.core.supabase_client as sc

    written: list[dict] = []

    class Q:
        def upsert(self, rows, **_kw):
            written.extend(rows)
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    class S:
        def table(self, _name):
            return Q()

    monkeypatch.setattr(sc, "get_client", lambda: S())
    monkeypatch.setattr(sc, "is_quarantined_row", lambda _op: False)

    rows = [
        {"engine": "cpi_nowcast", "market_id": "cpi-1", "edge_pct": 0.4},
        {"engine": "sports_nfl", "market_id": "nfl-1", "edge_pct": 0.2},
    ]
    sc.upsert_opportunities(rows)

    assert [r["engine"] for r in written] == ["sports_nfl"], (
        f"a display-only engine's row reached kalshi_edges: {written}")

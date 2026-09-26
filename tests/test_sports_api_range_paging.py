"""Finding B4: the endpoint must page with .range() to PostgREST's 1000-row cap, and must sort
before it slices.

Two defects:
- A single `.execute()` returns at most PostgREST's default/max row cap (1000). With more rows
  than that, `total` was computed from a silently truncated page and rows past the cap were
  invisible — the endpoint would report "3 of 1000" on a 2,500-row table.
- Sorting happened AFTER `rows[offset:offset+limit]`, so the ranking was applied to whatever
  arbitrary window the offset landed in. Page 2 could start with a `filtered` row while a
  `top_pick` sat unsorted on page 1's tail. Ranking must be global, then paged.

The fake below enforces the 1000-row cap exactly as PostgREST does, so a regression to a single
`.execute()` fails here rather than in production.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

POSTGREST_CAP = 1000
FUTURE = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
# expires_at is a real column on kalshi_edges and is what the query filters on; start_utc lives
# inside raw_payload. Rows whose game has started must have an expires_at in the past.
FUTURE_EXPIRES = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
PAST_EXPIRES = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
TOTAL_ROWS = 2500


def _edge(i: int, *, tier: str, start: str = FUTURE, expires_at: str = FUTURE_EXPIRES) -> dict:
    return {
        "market_id": f"T{i:05d}", "title": f"T{i:05d}", "edge_type": "SPORTS", "engine": "sports_nfl",
        "gate_status": "SHADOW", "our_prob": 0.3, "market_prob": 0.25, "expires_at": expires_at,
        "edge_pct": round(0.30 - (i % 100) / 1000, 6), "market_url": "https://kalshi.com/markets/x",
        "source_url": "https://sports/x",
        "raw_payload": {"sport": "nfl", "kind": "winner", "side": "yes", "entry_price": 0.25, "maker": True,
                        "home": "IND", "away": "HOU", "start_utc": start, "tier": tier, "candidate": tier != "filtered",
                        "reject_reasons": [], "review": None, "game_id": "g", "engine_version": "feed:v1"},
    }


def _rows() -> list[dict]:
    """2,500 upcoming rows: the top 5 are top_pick, the next 5 flagged, the rest filtered.

    Row order in the table is deliberately NOT the desired display order, so a sort-after-slice
    implementation is caught.
    """
    rows = []
    for i in range(TOTAL_ROWS):
        if i < 5:
            tier = "top_pick"
        elif i < 10:
            tier = "flagged"
        else:
            tier = "filtered"
        rows.append(_edge(i, tier=tier))
    # Shuffle deterministically so stored order != display order.
    return list(reversed(rows))


class _Q:
    def __init__(self, table, store):
        self.table, self.store = table, store
        self.rows = list(store.tables[table])
        self.filters: dict = {}
        self.window: tuple[int, int] | None = None
        self.ops: list[str] = []

    def select(self, *_a):
        self.ops.append("select")
        return self

    def eq(self, col, val):
        self.ops.append("eq")
        self.filters[col] = val
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        self.ops.append("in")
        self.filters[col] = list(vals)
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def gte(self, col, val):
        self.ops.append(f"gte:{col}")
        self.filters[col] = val
        self.rows = [r for r in self.rows if str(r.get(col, "")) >= str(val)]
        return self

    def gt(self, col, val):
        self.ops.append(f"gt:{col}")
        self.filters[col] = val
        self.rows = [r for r in self.rows if str(r.get(col, "")) > str(val)]
        return self

    def order(self, *_a, **_k):
        self.ops.append("order")
        return self

    def limit(self, n):
        self.ops.append(f"limit:{n}")
        self.rows = self.rows[:n]
        return self

    def range(self, lo, hi):
        self.ops.append(f"range:{lo},{hi}")
        self.window = (lo, hi)
        return self

    def execute(self):
        self.store.queries.append({"table": self.table, "ops": list(self.ops), "filters": dict(self.filters)})
        # Supabase raises when a column does not exist on the real table; a fake that silently
        # returns [] for an unknown column would hide exactly the bug these tests hunt.
        for col in self.filters:
            if self.rows and col not in self.rows[0]:
                raise AssertionError(f"unknown column {col!r} on {self.table}")
        if self.window is not None:
            lo, hi = self.window
            # PostgREST `Range: lo-hi` is INCLUSIVE of hi and capped at 1000 rows per response.
            data = self.rows[lo:hi + 1]
        else:
            data = self.rows
        if len(data) > POSTGREST_CAP:
            data = data[:POSTGREST_CAP]
        return type("R", (), {"data": data})()


class _Supa:
    def __init__(self, tables):
        self.tables = tables
        self.queries: list[dict] = []

    def table(self, name):
        return _Q(name, self)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _client(rows=None):
    supa = _Supa({
        "kalshi_edges": _rows() if rows is None else rows,
        "sports_reviews": [],
        "predictions": [],
    })
    app.dependency_overrides[get_supabase] = lambda: supa
    return TestClient(app), supa


def test_total_is_not_capped_at_the_postgrest_limit():
    client, _ = _client()
    body = client.get("/api/sports-edges", params={"limit": 50}).json()
    assert body["total"] == TOTAL_ROWS, (
        f"total was {body['total']}, expected {TOTAL_ROWS}: a single execute() is silently "
        f"capped at {POSTGREST_CAP} rows by PostgREST"
    )


def test_rows_beyond_the_cap_are_reachable():
    """SPORTS_PAGE_MAX caps a single response at 200, so walking 2,500 rows takes 13 calls.
    The point is that the union covers everything, which only holds if the server-side read
    paged internally rather than stopping at PostgREST's cap."""
    client, _ = _client()
    seen: set[str] = set()
    for offset in range(0, TOTAL_ROWS, 200):
        page = client.get("/api/sports-edges", params={"limit": 200, "offset": offset}).json()
        expected = min(200, TOTAL_ROWS - offset)
        assert len(page["edges"]) == expected, f"short page at offset {offset}"
        seen |= {e["market_id"] for e in page["edges"]}
    assert len(seen) == TOTAL_ROWS, f"only {len(seen)} of {TOTAL_ROWS} rows were reachable"


def test_paging_uses_range_not_a_single_execute():
    client, supa = _client()
    client.get("/api/sports-edges", params={"limit": 50})
    edge_reads = [q for q in supa.queries if q["table"] == "kalshi_edges"]
    assert edge_reads, "no kalshi_edges query was recorded"
    assert all(any(op.startswith("range:") for op in q["ops"]) for q in edge_reads), (
        f"expected every kalshi_edges read to page with .range(), got {edge_reads}"
    )


def test_page_one_starts_with_the_best_top_pick():
    client, _ = _client()
    body = client.get("/api/sports-edges", params={"limit": 50}).json()
    assert body["edges"], "no edges returned"
    assert body["edges"][0]["tier"] == "top_pick"
    top_picks = [e for e in body["edges"] if e["tier"] == "top_pick"]
    assert len(top_picks) == 5, "all five top picks must be on page one"
    # Within a tier, biggest edge first.
    assert top_picks == sorted(top_picks, key=lambda e: -float(e["edge_pct"]))


def test_ranking_is_global_not_per_offset_window():
    """Every top_pick must precede every flagged row across the whole result set, not just
    inside one page."""
    client, _ = _client()
    order: list[str] = []
    for offset in range(0, TOTAL_ROWS, 200):
        page = client.get("/api/sports-edges", params={"limit": 200, "offset": offset}).json()
        order += [e["tier"] for e in page["edges"]]
    first_non_top = next((i for i, t in enumerate(order) if t != "top_pick"), None)
    assert first_non_top == 5, (
        f"a non-top_pick row appeared at index {first_non_top}; ranking is not global "
        f"(sequence starts {order[:12]})"
    )


def test_within_tier_edges_descend_across_page_boundaries():
    client, _ = _client()
    page1 = client.get("/api/sports-edges", params={"limit": 100}).json()["edges"]
    page2 = client.get("/api/sports-edges", params={"limit": 100, "offset": 100}).json()["edges"]
    filtered = [e for e in page1 + page2 if e["tier"] == "filtered"]
    assert len(filtered) > 100
    edges = [float(e["edge_pct"]) for e in filtered]
    assert edges == sorted(edges, reverse=True), "edge_pct is not descending across the page boundary"


@pytest.mark.parametrize("table", ["sports_reviews", "predictions"])
def test_review_and_settlement_reads_are_paged_too(table):
    # 1500 rows against a 1000-row cap: one full page, then a short second page that ends the
    # loop. A single execute() would have returned 1000 and silently dropped 500. Review rows
    # need every field reviewer_scorecard reads, or the endpoint 500s before we get here.
    def row(i):
        if table == "sports_reviews":
            return {"market_ticker": f"R{i}", "status": "ok", "explainable": True, "red_flags": [],
                    "side": "yes", "entry_price": 0.4, "our_prob": 0.5,
                    "created_at": "2026-09-26T12:00:00+00:00"}
        # predictions is filtered by engine + status, so the row must carry both.
        return {"market_ticker": f"R{i}", "result": "yes", "engine": "sports_nfl", "status": "SETTLED"}

    supa = _Supa({"kalshi_edges": _rows()[:10],
                  "sports_reviews": [row(i) for i in range(1500)],
                  "predictions": [row(i) for i in range(1500)]})
    app.dependency_overrides[get_supabase] = lambda: supa
    TestClient(app).get("/api/sports-edges", params={"limit": 10})

    reads = [q for q in supa.queries if q["table"] == table]
    assert reads, f"{table} was never read"
    assert all(any(op.startswith("range:") for op in q["ops"]) for q in reads), (
        f"{table} is read with a single capped execute(): {reads}"
    )
    assert len(reads) == 2, f"{table} should page twice for 1500 rows, got {len(reads)}: {reads}"


def test_a_truncated_review_scan_would_shrink_the_scorecard():
    """Why the paging above matters: the scorecard counts settled reviewed picks, so a silently
    truncated read would understate it and could flip a keep/drop verdict near the threshold."""
    def review(i):
        return {"market_ticker": f"R{i}", "status": "ok", "explainable": True, "red_flags": [],
                "side": "yes", "entry_price": 0.4, "our_prob": 0.5,
                "created_at": "2026-09-26T12:00:00+00:00"}

    supa = _Supa({"kalshi_edges": _rows()[:10],
                  "sports_reviews": [review(i) for i in range(1200)],
                  "predictions": [{"market_ticker": f"R{i}", "result": "yes",
                                   "engine": "sports_nfl", "status": "SETTLED"} for i in range(1200)]})
    app.dependency_overrides[get_supabase] = lambda: supa
    card = TestClient(app).get("/api/sports-edges", params={"limit": 10}).json()["reviewer_scorecard"]
    assert card["n_settled"] == 1200, f"scorecard saw only {card['n_settled']} of 1200 settled picks"


def test_started_games_are_excluded_by_the_query_not_only_in_python():
    client, supa = _client(rows=[
        _edge(1, tier="top_pick"),
        # Started game: past expires_at, so the query must drop it before Python sees it.
        _edge(2, tier="top_pick", start=PAST, expires_at=PAST_EXPIRES),
    ])
    response = client.get("/api/sports-edges")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["market_id"] for e in body["edges"]] == ["T00001"]
    assert body["total"] == 1
    reads = [q for q in supa.queries if q["table"] == "kalshi_edges"]
    assert any(op.startswith("gt:") or op.startswith("gte:") for q in reads for op in q["ops"]), (
        f"the not-started filter was not pushed into the query: {reads}"
    )

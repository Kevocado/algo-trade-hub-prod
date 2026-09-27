"""The "all N were rejected" banner must describe the whole result set, not the current page.

Found in review of PR #20. `SportsEdges.tsx` computed the banner from the rows in the page it had
just fetched, so on page 2+ it would claim "all 40 upcoming sports markets were priced and all 40 were
rejected" while page 1 was full of candidates. The page is ordered top_pick-first, so page 2 is
*always* the rejected tail — which means the false claim appears exactly when a reader has already seen
picks on page 1.

The fix is to have the API return the count, because the count is a property of the whole filtered set
and the client cannot derive it from a page. The banner can then be correct on any page, and "only show
it on page 0" is no longer necessary.

These tests use the same paging fixtures as `test_sports_api_range_paging.py`, so a candidate on page 1
and rejects after it is the real shape rather than a contrived one.
"""
import pytest
from fastapi.testclient import TestClient

from tradehub.api import main as api_main
from tradehub.api.dependencies import get_supabase


class _Q:
    """Mimics the ordered/ranged PostgREST chain, recording the range actually pushed down."""

    def __init__(self, rows, table):
        self.rows = rows
        self.table = table
        self.order_by = None
        self.ranges = []
        self.filters = []

    def select(self, *a):
        return self

    def eq(self, *a):
        self.filters.append(a)
        return self

    def in_(self, *a):
        return self

    def gte(self, *a):
        self.filters.append(a)
        return self

    def lte(self, *a):
        self.filters.append(a)
        return self

    def gt(self, *a):
        self.filters.append(a)
        return self

    def lt(self, *a):
        self.filters.append(a)
        return self

    def order(self, *a):
        self.order_by = a
        return self

    def range(self, lo, hi):
        self.ranges.append((lo, hi))
        return self

    def limit(self, *a):
        return self

    def execute(self):
        rows = [r for r in self.rows if self._matches(r)]
        if self.order_by:
            for col, direction in reversed(self.order_by):
                rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)),
                              reverse=(direction == "desc"))
        if self.ranges:
            lo, hi = self.ranges[-1]
            rows = rows[lo:hi + 1]
        return type("R", (), {"data": rows})()

    def _matches(self, row):
        """Honours the filters the real endpoint actually pushes down, so the fixtures are the rows
        that reach the handler rather than being silently dropped by an over-permissive stub."""
        for col, value in self.filters:
            if col == "engine" and row.get("engine") != value:
                return False
            if col == "status" and row.get("status") != value:
                return False
            if col == "edge_type" and row.get("edge_type") != value:
                return False
            if col == "expires_at" and str(row.get(col) or "") < str(value):
                return False
        return True


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        if name not in self.tables:
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")
        return _Q(self.tables[name], name)


def _client(edges, reviews=(), settled=()):
    return _Client({
        "kalshi_edges": list(edges),
        "sports_reviews": list(reviews),
        "predictions": list(settled),
    })


def _app(supa):
    """Override on the real module-level app.

    A hand-built app with the same route objects copied in does NOT work: the copied `APIRoute`
    keeps resolving `Depends(get_supabase)` against the original app, so the override never applies
    and the real client is constructed instead. Cost me a confusing 503 before I read how the
    existing sports tests do it.
    """
    api_main.app.dependency_overrides[get_supabase] = lambda: supa
    return api_main.app


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    api_main.app.dependency_overrides.clear()


def _edge(market_id, *, tier, page_one_candidate=True):
    """A shaped edge. `tier` drives the ranking, so candidates sort ahead of rejects."""
    return {
        "market_id": market_id,
        "title": market_id,
        "edge_type": "SPORTS",
        "engine": "sports_cfb",
        "gate_status": "SHADOW",
        "engine_version": "feed:xgb@2026-09-04",
        "our_prob": 0.6,
        "market_prob": 0.5,
        "edge_pct": 0.09 if tier == "top_pick" else 0.01,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "market_url": "https://kalshi.com/x",
        "source_url": "https://sports/x",
        "raw_payload": {
            "sport": "cfb", "kind": "winner", "side": "yes", "entry_price": 0.5, "maker": True,
            "home": "UConn", "away": "Syracuse", "start_utc": "2099-01-01T00:00:00+00:00",
            "tier": tier, "candidate": tier == "top_pick", "reject_reasons": [] if tier == "top_pick"
            else ["wide_quote"],
            "game_id": "g1", "review": None,
        },
    }


def test_the_response_carries_a_candidate_count_for_the_whole_result_set():
    """Two candidates and three rejects, paged so page 2 is all rejects."""
    edges = [_edge("P1", tier="top_pick"), _edge("P2", tier="top_pick"),
             _edge("F1", tier="filtered"), _edge("F2", tier="filtered"), _edge("F3", tier="filtered")]
    body = TestClient(_app(_client(edges))).get("/api/sports-edges", params={"limit": 2, "offset": 0}).json()

    assert body["total"] == 5
    assert body["candidate_count"] == 2, body.get("candidate_count")
    # The page itself holds only candidates, so a client reading the page would have got this right by
    # luck. That is exactly the bug: it is only wrong when the count is derived from a reject page.
    assert [e["tier"] for e in body["edges"]] == ["top_pick", "top_pick"]


def test_the_candidate_count_is_unchanged_on_a_later_page():
    """The actual defect. Page 2 contains only rejects, so a page-derived count would read 0."""
    edges = [_edge("P1", tier="top_pick"), _edge("P2", tier="top_pick"),
             _edge("F1", tier="filtered"), _edge("F2", tier="filtered"), _edge("F3", tier="filtered")]
    body = TestClient(_app(_client(edges))).get("/api/sports-edges", params={"limit": 2, "offset": 2}).json()

    assert [e["tier"] for e in body["edges"]] == ["filtered", "filtered"]
    assert body["candidate_count"] == 2, "a page of rejects must not report zero candidates"
    assert body["total"] == 5


def test_the_candidate_count_is_zero_when_nothing_survives_the_filter():
    edges = [_edge("F1", tier="filtered"), _edge("F2", tier="filtered")]
    body = TestClient(_app(_client(edges))).get("/api/sports-edges", params={"limit": 50}).json()

    assert body["candidate_count"] == 0
    assert body["total"] == 2


def test_the_candidate_count_respects_the_sport_filter():
    """A count is only useful if it is the count for what was asked. A CFB-only request must not be
    told about NFL candidates, or the banner would overstate what the reader can see."""
    cfb = _edge("C1", tier="top_pick")
    nfl = _edge("N1", tier="top_pick")
    nfl["raw_payload"] = {**nfl["raw_payload"], "sport": "nfl"}
    nfl["engine"] = "sports_nfl"
    body = TestClient(_app(_client([cfb, nfl]))).get("/api/sports-edges", params={"sport": "cfb"}).json()

    assert body["candidate_count"] == 1, body

"""Finding 4: /api/sports-edges loaded every SPORTS row, every ok review and every settled
sports prediction, with no filter and no limit. Combined with finding 3 (sports edges were
never pruned) that table grows without bound, so the endpoint cost grew with the season.

The endpoint must:
- filter by sport and tier in the query, not after fetching everything;
- paginate with a bounded default and a hard maximum;
- report the pre-slice total so the UI can tell "3 of 240" from "3 total";
- refuse a nonsense limit/offset instead of silently clamping to something surprising.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

FUTURE = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
MAX_LIMIT = 200


def _edge(market_id, *, sport="nfl", tier="top_pick", edge_pct=0.05, start=FUTURE, engine="sports_nfl",
          expires_at=FUTURE):
    return {
        "market_id": market_id, "title": market_id, "edge_type": "SPORTS", "engine": engine,
        "gate_status": "SHADOW", "our_prob": 0.3, "market_prob": 0.25, "edge_pct": edge_pct,
        # expires_at is a real column and is what the query filters on; start_utc is in
        # raw_payload and is re-checked in Python.
        "expires_at": expires_at,
        "market_url": "https://kalshi.com/markets/x", "source_url": "https://sports/x",
        "raw_payload": {"sport": sport, "kind": "winner", "side": "yes", "entry_price": 0.25, "maker": True,
                        "home": "IND", "away": "HOU", "start_utc": start, "tier": tier, "candidate": True,
                        "reject_reasons": [], "review": None, "game_id": "g", "engine_version": "feed:v1"},
    }


class _Q:
    """Minimal query builder that records the filters actually pushed down to the database."""

    def __init__(self, table, store):
        self.table, self.store, self.rows = table, store, list(store.tables[table])
        self.filters = {}

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        self.filters[col] = list(vals)
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def gte(self, col, val):
        self.filters[col] = val
        self.rows = [r for r in self.rows if str(r.get(col, "")) >= str(val)]
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self.filters["_limit"] = n
        self.rows = self.rows[:n]
        return self

    def range(self, lo, hi):
        # PostgREST `Range: lo-hi` is inclusive of hi.
        self.filters["_range"] = (lo, hi)
        self.rows = self.rows[lo:hi + 1]
        return self

    def execute(self):
        self.store.queries.append((self.table, dict(self.filters)))
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, name):
        return _Q(name, self)


def _client(edges, reviews=None, settled=None):
    supa = _Supa({
        "kalshi_edges": edges,
        "sports_reviews": reviews or [],
        "predictions": settled or [],
    })
    app.dependency_overrides[get_supabase] = lambda: supa
    return TestClient(app), supa


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_default_page_is_bounded():
    client, supa = _client([_edge(f"T{i}") for i in range(500)])
    body = client.get("/api/sports-edges").json()
    assert len(body["edges"]) <= MAX_LIMIT
    assert body["offset"] == 0
    assert 1 <= body["limit"] <= MAX_LIMIT
    assert body["limit"] == 100, "the documented default page size"
    assert body["total"] == 500, "total counts every upcoming match, not just this page"


def test_limit_and_offset_paginate_without_repeating_rows():
    edges = [_edge(f"T{i:03d}", edge_pct=0.01 * (500 - i)) for i in range(60)]
    client, _ = _client(edges)
    first = client.get("/api/sports-edges", params={"limit": 20}).json()
    second = client.get("/api/sports-edges", params={"limit": 20, "offset": 20}).json()
    ids_first = [e["market_id"] for e in first["edges"]]
    ids_second = [e["market_id"] for e in second["edges"]]
    assert len(ids_first) == 20 and len(ids_second) == 20
    assert not set(ids_first) & set(ids_second)
    assert second["offset"] == 20 and second["total"] == first["total"] == 60


def test_sport_filter_is_pushed_down_to_the_database():
    edges = [_edge(f"N{i}", sport="nfl", engine="sports_nfl") for i in range(3)]
    edges += [_edge(f"C{i}", sport="cfb", engine="sports_cfb") for i in range(3)]
    client, supa = _client(edges)
    body = client.get("/api/sports-edges", params={"sport": "cfb"}).json()
    assert {e["sport"] for e in body["edges"]} == {"cfb"}
    assert body["total"] == 3
    # The engine filter must be applied by the query, not by post-filtering in Python.
    edge_queries = [f for t, f in supa.queries if t == "kalshi_edges"]
    assert any(f.get("engine") == "sports_cfb" for f in edge_queries), edge_queries


def test_tier_filter_is_pushed_down_or_applied_exactly():
    edges = [_edge(f"P{i}", tier="top_pick") for i in range(3)]
    edges += [_edge(f"F{i}", tier="filtered") for i in range(4)]
    client, supa = _client(edges)
    body = client.get("/api/sports-edges", params={"tier": "top_pick"}).json()
    assert {e["tier"] for e in body["edges"]} == {"top_pick"}
    assert body["total"] == 3


def test_tier_filter_rejects_an_unknown_tier():
    client, _ = _client([_edge("T")])
    assert client.get("/api/sports-edges", params={"tier": "nonsense"}).status_code == 422


def test_bad_pagination_is_rejected_not_silently_clamped():
    client, _ = _client([_edge("T")])
    assert client.get("/api/sports-edges", params={"limit": 0}).status_code == 422
    assert client.get("/api/sports-edges", params={"limit": -5}).status_code == 422
    assert client.get("/api/sports-edges", params={"limit": 10_000}).status_code == 422
    assert client.get("/api/sports-edges", params={"offset": -1}).status_code == 422


def test_started_games_are_still_hidden_and_do_not_inflate_the_total():
    edges = [_edge("LIVE", start=PAST, expires_at=PAST)]
    edges += [_edge(f"U{i}") for i in range(3)]
    client, _ = _client(edges)
    body = client.get("/api/sports-edges").json()
    assert "LIVE" not in [e["market_id"] for e in body["edges"]]
    assert body["total"] == 3, "a game that already started must not count toward the total"


def test_gate_status_and_engine_version_are_exposed_for_the_badge():
    client, _ = _client([_edge("T")])
    edge = client.get("/api/sports-edges").json()["edges"][0]
    assert edge["gate_status"] == "SHADOW"
    assert edge["engine"] == "sports_nfl"
    assert edge["engine_version"] == "feed:v1"

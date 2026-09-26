from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app
from tradehub.sports.scorecard import MIN_SETTLED, reviewer_scorecard


def _review(ticker, side="yes", price=0.40, prob=0.55, explainable=True, flags=(), at="2026-09-26T12:00:00+00:00"):
    return {"market_ticker": ticker, "side": side, "entry_price": price, "our_prob": prob, "status": "ok",
            "explainable": explainable, "red_flags": list(flags), "created_at": at}


def test_scorecard_is_insufficient_below_the_spec_threshold():
    card = reviewer_scorecard([_review("A")], {"A": "yes"})
    assert card["n_settled"] == 1 and card["verdict"] == "insufficient" and MIN_SETTLED == 100


def test_scorecard_compares_approved_and_rejected():
    reviews, results = [], {}
    for i in range(60):   # approved picks win
        reviews.append(_review(f"A{i}"))
        results[f"A{i}"] = "yes"
    for i in range(60):   # flagged picks lose
        reviews.append(_review(f"R{i}", flags=("late injury news unknown",)))
        results[f"R{i}"] = "no"
    card = reviewer_scorecard(reviews, results)
    assert card["n_settled"] == 120
    assert card["approved"]["n"] == 60 and card["rejected"]["n"] == 60
    assert card["approved"]["brier"] == pytest.approx(0.2025)          # (0.55 - 1)^2
    assert card["approved"]["pnl_per_contract"] > 0 > card["rejected"]["pnl_per_contract"]
    assert card["verdict"] == "keep"


def test_scorecard_says_drop_when_approval_does_not_help():
    reviews = [_review(f"A{i}") for i in range(60)] + [_review(f"R{i}", explainable=False) for i in range(60)]
    results = {r["market_ticker"]: "no" for r in reviews}
    assert reviewer_scorecard(reviews, results)["verdict"] == "drop"


def test_scorecard_uses_the_latest_review_per_market_side_and_skips_unsettled():
    reviews = [_review("A", explainable=False, at="2026-09-26T09:00:00+00:00"),
               _review("A", explainable=True, at="2026-09-26T12:00:00+00:00"), _review("B")]
    card = reviewer_scorecard(reviews, {"A": "yes"})
    assert card["approved"]["n"] == 1 and card["rejected"]["n"] == 0 and card["n_settled"] == 1


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def gte(self, col, val):
        self.rows = [r for r in self.rows if str(r.get(col, "")) >= str(val)]
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, lo, hi):
        # PostgREST `Range: lo-hi` is inclusive of hi.
        self.rows = self.rows[lo:hi + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(list(self.tables[name]))


def _edge(market_id, tier, edge_pct, hours):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    return {"market_id": market_id, "title": market_id, "edge_type": "SPORTS", "our_prob": 0.3, "market_prob": 0.25,
            "edge_pct": edge_pct, "market_url": "https://kalshi.com/markets/x", "source_url": "https://sports/x",
            # expires_at is the indexed column the query filters on; start_utc is in raw_payload.
            "expires_at": start,
            "raw_payload": {"sport": "nfl", "kind": "winner", "side": "yes", "entry_price": 0.25, "maker": True,
                            "home": "IND", "away": "HOU", "start_utc": start, "tier": tier, "candidate": True,
                            "reject_reasons": [], "review": None, "game_id": "g"}}


def test_sports_edges_endpoint_orders_by_tier_and_hides_started_games():
    supa = _Supa({
        "kalshi_edges": [_edge("U", "unreviewed", 0.20, 5), _edge("T", "top_pick", 0.05, 5),
                         _edge("F", "flagged", 0.30, 5), _edge("OLD", "top_pick", 0.5, -1),
                         {**_edge("W", "top_pick", 0.9, 5), "edge_type": "WEATHER"}],
        "sports_reviews": [], "predictions": [],
    })
    app.dependency_overrides[get_supabase] = lambda: supa
    try:
        body = TestClient(app).get("/api/sports-edges").json()
    finally:
        app.dependency_overrides.clear()
    assert [e["market_id"] for e in body["edges"]] == ["T", "F", "U"]
    first = body["edges"][0]
    assert first["tier"] == "top_pick" and first["home"] == "IND" and first["source_url"] == "https://sports/x"
    assert body["reviewer_scorecard"]["verdict"] == "insufficient"


def test_sports_edges_endpoint_503_without_supabase():
    app.dependency_overrides[get_supabase] = lambda: None
    try:
        assert TestClient(app).get("/api/sports-edges").status_code == 503
    finally:
        app.dependency_overrides.clear()

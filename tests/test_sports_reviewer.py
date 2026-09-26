import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from tradehub.sports.reviewer import (
    REVIEW_SCHEMA, OpenRouterReviewer, Review, ReviewRequest, SupabaseReviewStore, cache_key, parse_review,
    price_bucket, review_candidates, tier,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _content(name):
    return json.loads((FIXTURES / name).read_text())["choices"][0]["message"]["content"]


def _request(ticker="KXNFLGAME-26SEP27HOUIND-IND", price=0.27):
    bucket = price_bucket(price, 5)
    return ReviewRequest(
        key=cache_key("nfl", "2026_03_HOU_IND", ticker, "yes", bucket), sport="nfl", game_id="2026_03_HOU_IND",
        market_ticker=ticker, side="yes", entry_price=price, price_bucket=bucket, our_prob=0.35, net_edge_pct=7.5,
        fact_pack={"sport": "nfl", "market": {"ticker": ticker}},
    )


def test_schema_is_strict_and_has_no_probability_field():
    assert REVIEW_SCHEMA["additionalProperties"] is False
    assert set(REVIEW_SCHEMA["required"]) == {"explainable", "drivers", "red_flags"}
    assert "probability" not in json.dumps(REVIEW_SCHEMA)


def test_parse_recorded_reviews():
    ok = parse_review(_content("openrouter_ok.json"))
    flagged = parse_review(_content("openrouter_flagged.json"))
    assert ok.status == "ok" and ok.explainable is True and len(ok.drivers) == 2 and ok.red_flags == ()
    assert flagged.status == "ok" and flagged.red_flags
    assert (tier(ok), tier(flagged)) == ("top_pick", "flagged")


@pytest.mark.parametrize("content", [
    "not json",
    '{"explainable": true, "drivers": []}',                                        # missing red_flags
    '{"explainable": "yes", "drivers": [], "red_flags": []}',                      # wrong type
    '{"explainable": true, "drivers": [], "red_flags": [], "probability": 0.7}',   # tries to add a number
    '{"explainable": true, "drivers": [1], "red_flags": []}',
])
def test_malformed_output_falls_back_to_unreviewed(content):
    review = parse_review(content)
    assert review.status == "invalid"
    assert tier(review) == "unreviewed"


def test_price_bucket_and_cache_key():
    assert price_bucket(0.27, 5) == 5 and price_bucket(0.30, 5) == 6 and price_bucket(0.994, 5) == 19
    assert cache_key("nfl", "g", "T", "no", 5) == "nfl:g:T:no:5"


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_openrouter_request_shape_and_parse():
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return _Resp(200, __import__("json").loads((FIXTURES / "openrouter_ok.json").read_text()))

    reviewer = OpenRouterReviewer(api_key="test-key-not-real", model="m:free", timeout=60, post=post)
    review = reviewer.review({"sport": "nfl"})
    assert review.status == "ok" and review.model == "m:free"
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-key-not-real"
    body = sent["body"]
    assert body["model"] == "m:free" and body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True}
    assert '"sport": "nfl"' in body["messages"][1]["content"]


def test_openrouter_errors_never_raise():
    def post(url, headers, json, timeout):
        return _Resp(429, {"error": {"message": "rate limited"}})

    review = OpenRouterReviewer(api_key="k", model="m", timeout=5, post=post).review({})
    assert review.status == "error" and tier(review) == "unreviewed"


class _FakeStore:
    def __init__(self, cached=None, used=0):
        self.cached_reviews = cached or {}
        self.used = used
        self.saved = []

    def cached(self, key):
        return self.cached_reviews.get(key)

    def calls_since(self, since):
        return self.used

    def save(self, request, review):
        self.saved.append((request.key, review.status))


class _FakeReviewer:
    model = "m:free"

    def __init__(self):
        self.calls = 0

    def review(self, fact_pack):
        self.calls += 1
        return parse_review(_content("openrouter_ok.json"))


def test_cache_hit_skips_the_call():
    req = _request()
    hit = Review(status="ok", explainable=True, drivers=("cached",), red_flags=(), model="m")
    reviewer = _FakeReviewer()
    out = review_candidates([req], _FakeStore(cached={req.key: hit}), reviewer, budget=40, now=NOW)
    assert out[req.key] == hit and reviewer.calls == 0


def test_daily_budget_is_enforced_and_every_call_is_saved():
    reqs = [_request(f"T{i}") for i in range(3)]
    store, reviewer = _FakeStore(used=39), _FakeReviewer()
    out = review_candidates(reqs, store, reviewer, budget=40, now=NOW)
    assert reviewer.calls == 1
    assert [out[r.key].status for r in reqs] == ["ok", "skipped_budget", "skipped_budget"]
    assert store.saved == [(reqs[0].key, "ok")]


def test_no_api_key_means_unreviewed_not_blocked():
    req = _request()
    out = review_candidates([req], _FakeStore(), None, budget=40, now=NOW)
    assert out[req.key].status == "no_key" and tier(out[req.key]) == "unreviewed"


def test_reviewing_never_changes_the_probability():
    req = _request()
    before = req.our_prob
    review_candidates([req], _FakeStore(), _FakeReviewer(), budget=40, now=NOW)
    assert req.our_prob == before
    assert not any("prob" in f for f in Review.__dataclass_fields__)


class _Query:
    def __init__(self, table):
        self.table, self.filters, self.inserted = table, [], None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self.filters.append(("gte", col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def insert(self, row):
        self.inserted = row
        self.table.rows.append(row)
        return self

    def execute(self):
        if self.inserted is not None:
            return type("R", (), {"data": [self.inserted]})()
        rows = [r for r in self.table.rows if all(
            (r.get(c) == v) if op == "eq" else (r.get(c) >= v) for op, c, v in self.filters)]
        return type("R", (), {"data": rows})()


class _Table:
    def __init__(self):
        self.rows = []


class _Supa:
    def __init__(self):
        self.t = _Table()

    def table(self, name):
        assert name == "sports_reviews"
        return _Query(self.t)


def test_supabase_store_round_trip():
    supa = _Supa()
    store = SupabaseReviewStore(supa, now=lambda: NOW)
    req = _request()
    store.save(req, Review(status="invalid", explainable=None, drivers=(), red_flags=(), model="m"))
    assert store.cached(req.key) is None                    # failures are counted, never served
    store.save(req, parse_review(_content("openrouter_ok.json")))
    assert store.cached(req.key).explainable is True
    assert store.calls_since(datetime(2026, 9, 26, tzinfo=timezone.utc)) == 2
    assert supa.t.rows[0]["created_at"] == NOW.isoformat()

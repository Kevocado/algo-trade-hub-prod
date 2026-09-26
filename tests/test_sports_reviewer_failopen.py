from datetime import datetime, timezone

from tradehub.sports.reviewer import (
    MemoryReviewStore, ReviewRequest, SupabaseReviewStore, cache_key, price_bucket, review_candidates,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _request(ticker="KXNFLGAME-26SEP27HOUIND-IND", price=0.27):
    bucket = price_bucket(price, 5)
    return ReviewRequest(
        key=cache_key("nfl", "2026_03_HOU_IND", ticker, "yes", bucket), sport="nfl", game_id="2026_03_HOU_IND",
        market_ticker=ticker, side="yes", entry_price=price, price_bucket=bucket, our_prob=0.35, net_edge_pct=7.5,
        fact_pack={"sport": "nfl"},
    )


class _BrokenQuery:
    """Every Supabase call on this client raises, the way a dropped VPS connection does."""

    def __init__(self, name):
        self.name = name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        raise ConnectionError("supabase unreachable")


class BrokenSupa:
    def table(self, name):
        return _BrokenQuery(name)


def test_store_cache_lookup_fails_open_to_a_miss():
    """The module contract is 'any failure leaves the edge unreviewed and never blocks it'.
    A dead cache must read as a miss, not propagate out and kill the whole sports scan."""
    store = SupabaseReviewStore(BrokenSupa())
    assert store.cached("nfl:any:key") is None


def test_store_budget_and_save_fail_open():
    store = SupabaseReviewStore(BrokenSupa())
    # The budget count fails CLOSED, not open: an unknown count must not become an
    # unlimited LLM spend. 0 here would let a DB outage silently buy unlimited reviews.
    assert store.calls_since(NOW) >= 10**6
    store.save(_request(), reviewer_ok())   # must not raise


def test_an_unmeasurable_budget_stops_new_llm_calls():
    """The fail-closed budget must actually stop spend when a reviewer IS configured."""
    class CountingReviewer:
        model = "m"

        def __init__(self):
            self.calls = 0

        def review(self, fact_pack):
            self.calls += 1
            return reviewer_ok()

    reviewer = CountingReviewer()
    out = review_candidates([_request(f"T{i}") for i in range(3)],
                            SupabaseReviewStore(BrokenSupa()), reviewer, budget=5, now=NOW)
    assert reviewer.calls == 0
    assert {r.status for r in out.values()} == {"skipped_budget"}


def reviewer_ok():
    from tradehub.sports.reviewer import Review
    return Review(status="ok", explainable=True, drivers=("margin",), red_flags=(), model="m")


def test_a_broken_store_never_blocks_a_candidate():
    """End to end: with the DB down, review_candidates still returns a verdict for every
    candidate instead of raising."""
    out = review_candidates([_request()], SupabaseReviewStore(BrokenSupa()), reviewer=None, budget=5, now=NOW)
    assert list(out.values())[0].status == "no_key"


def test_memory_store_still_works_as_the_control():
    """Guard the guard: the in-process store keys on the request key and keeps working,
    so the fail-open tests above cannot pass for the wrong reason."""
    store = MemoryReviewStore()
    req = _request()
    assert store.cached(req.key) is None
    store.save(req, reviewer_ok())
    assert store.cached(req.key).status == "ok"
    assert store.calls_since(NOW.replace(year=2000)) == 1


def test_partial_failure_on_save_still_returns_the_verdict(monkeypatch):
    """A review we already paid for must not be thrown away because the insert failed."""
    calls = []

    class FlakyStore(MemoryReviewStore):
        def save(self, request, review):
            calls.append(review)
            raise ConnectionError("insert failed")

    class FakeReviewer:
        model = "m"

        def review(self, fact_pack):
            return reviewer_ok()

    out = review_candidates([_request()], FlakyStore(), FakeReviewer(), budget=5, now=NOW)
    assert len(calls) == 1
    assert out[list(out)[0]].status == "ok"

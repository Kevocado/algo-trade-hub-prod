"""Round 4, item 2: the deadline must bound reviewing and the feed fetches, not just Kalshi.

Round 3 threaded `SCAN_DEADLINE_SECONDS` into `SportsKalshi` and checked `should_review` ONCE,
before the review loop started. So:

- `review_candidates` could spend the rest of the budget on OpenRouter calls long after the
  margin was gone, because nothing re-checked between calls;
- each call used the reviewer's full configured timeout, not the time actually left, so one slow
  call could sit past the deadline by a minute per candidate;
- `fetch_feed` used its own 60s timeout with one unconditional retry — up to 122 seconds of
  predictor call inside a scan that has a 15-minute budget and four other engines to serve.

`should_review` must be re-checked before EACH call, and every HTTP timeout must be clamped to
what is left.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.sports import deadline as deadline_mod
from tradehub.sports.feed import FeedUnavailable, fetch_feed
from tradehub.sports.reviewer import (
    OpenRouterReviewer, Review, ReviewRequest, review_candidates, tier,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock. `deadline.remaining_seconds` reads `_clock`, so the rule
    is exercised for real instead of being stubbed out."""
    state = {"t": 1000.0}

    def _clock() -> float:
        return state["t"]

    monkeypatch.setattr(deadline_mod, "_clock", _clock)
    return state


def _request(i: int) -> ReviewRequest:
    return ReviewRequest(
        key=f"nfl:g{i}:T{i}:yes:8", sport="nfl", game_id=f"g{i}", market_ticker=f"T{i}", side="yes",
        entry_price=0.42, price_bucket=8, our_prob=0.55, net_edge_pct=10.0 - i,
        fact_pack={"sport": "nfl", "i": i},
    )


class _Store:
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


class _Reviewer:
    model = "m:free"

    def __init__(self, clock=None, cost=0.0, status="ok"):
        self.calls, self.clock, self.cost, self.status = 0, clock, cost, status

    def review(self, fact_pack):
        self.calls += 1
        if self.clock is not None:
            self.clock["t"] += self.cost        # each call burns some of the budget
        if self.status == "ok":
            return Review(status="ok", explainable=True, drivers=("d",), red_flags=(), model="m")
        return Review(status=self.status, explainable=None, drivers=(), red_flags=(), model="m")


# ── no OpenRouter call once the margin is gone ─────────────────────────────────

def test_no_reviewer_call_is_made_with_only_thirty_seconds_left():
    reqs = [_request(i) for i in range(5)]
    store, reviewer = _Store(), _Reviewer()
    out = review_candidates(reqs, store, reviewer, budget=40, now=NOW, deadline=1000.0 + 30)
    assert reviewer.calls == 0, "an OpenRouter call was made with 30s of budget left"
    assert {r.status for r in out.values()} == {"skipped_deadline"}, out
    assert all(tier(r) == "unreviewed" for r in out.values()), "a deadline-skipped edge lost its tier"
    assert store.saved == [], "a deadline-skipped request was written to the review log"


def test_a_deadline_skipped_request_is_never_saved_to_the_review_log():
    """`sports_reviews.status` has a CHECK constraint (ok|invalid|error) and is the append-only
    budget count, so a skip written there would corrupt both."""
    reqs = [_request(0)]
    store = _Store()
    review_candidates(reqs, store, _Reviewer(), budget=40, now=NOW, deadline=1000.0 + 30)
    assert store.saved == [], f"a deadline skip was logged as an API call: {store.saved}"
    assert store.used == 0


def test_cached_reviews_are_still_applied_when_the_deadline_has_passed():
    """A cache hit costs no API call, so a tight budget must not throw away a verdict we already
    paid for."""
    req = _request(0)
    hit = Review(status="ok", explainable=True, drivers=("cached",), red_flags=(), model="m")
    store, reviewer = _Store(cached={req.key: hit}), _Reviewer()
    out = review_candidates([req], store, reviewer, budget=40, now=NOW, deadline=1000.0 + 5)
    assert out[req.key] == hit and reviewer.calls == 0


def test_reviewing_stops_mid_list_when_the_deadline_approaches(clock):
    """The check is per call, not once up front: 10 candidates, 90s of budget, each call costs
    10s and reviewing stops at the 60s margin, so exactly three are reviewed."""
    reqs = [_request(i) for i in range(10)]
    store, reviewer = _Store(), _Reviewer(clock=clock, cost=10.0)
    out = review_candidates(reqs, store, reviewer, budget=40, now=NOW, deadline=1090.0)
    assert reviewer.calls == 3, f"expected 3 calls before the 60s margin, made {reviewer.calls}"
    statuses = [out[r.key].status for r in reqs]
    assert statuses[:3] == ["ok", "ok", "ok"], statuses
    assert set(statuses[3:]) == {"skipped_deadline"}, statuses
    # The three verdicts we paid for are kept, and only those are logged as calls.
    assert [k for k, _ in store.saved] == [r.key for r in reqs[:3]], store.saved


def test_the_review_deadline_is_reported_not_silent(clock, caplog):
    import logging
    reqs = [_request(i) for i in range(4)]
    with caplog.at_level(logging.WARNING):
        review_candidates(reqs, _Store(), _Reviewer(clock=clock, cost=30.0), budget=40, now=NOW,
                          deadline=1090.0)
    assert any("deadline" in r.getMessage().lower() for r in caplog.records), (
        f"stopping mid-list was silent: {[r.getMessage() for r in caplog.records]}"
    )


def test_no_deadline_means_no_limit():
    """The dry run and the tests pass no deadline; that must stay an unbounded budget."""
    reqs = [_request(i) for i in range(3)]
    reviewer = _Reviewer()
    out = review_candidates(reqs, _Store(), reviewer, budget=40, now=NOW)
    assert reviewer.calls == 3
    assert all(r.status == "ok" for r in out.values())


# ── the OpenRouter timeout is clamped to what is left ──────────────────────────

def _ok_response():
    payload = json.loads((FIXTURES / "openrouter_ok.json").read_text())
    return type("R", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: payload,
    })()


def test_the_openrouter_timeout_is_clamped_to_the_remaining_time(clock):
    sent = {}

    def post(url, headers, json, timeout):
        sent["timeout"] = timeout
        return _ok_response()

    reviewer = OpenRouterReviewer(api_key="k-not-real", model="m:free", timeout=60, post=post,
                                  deadline=1000.0 + 12.5)
    assert reviewer.review({"sport": "nfl"}).status == "ok"
    assert sent["timeout"] == pytest.approx(12.5), (
        f"the call used the configured 60s timeout with 12.5s of budget left: {sent['timeout']}"
    )


def test_a_short_deadline_never_produces_a_zero_or_negative_timeout(clock):
    seen = []

    def post(url, headers, json, timeout):
        seen.append(timeout)
        return _ok_response()

    OpenRouterReviewer(api_key="k", model="m", timeout=60, post=post,
                       deadline=1000.0 - 5).review({})          # deadline already passed
    assert seen and 0 < seen[0] <= 1.0, f"timeout was {seen[0]}"


def test_a_configured_timeout_still_wins_when_there_is_time(clock):
    sent = {}

    def post(url, headers, json, timeout):
        sent["timeout"] = timeout
        return _ok_response()

    OpenRouterReviewer(api_key="k", model="m", timeout=30, post=post,
                       deadline=1000.0 + 600).review({})
    assert sent["timeout"] == 30, sent


def test_a_reviewer_without_a_deadline_is_unchanged():
    sent = {}

    def post(url, headers, json, timeout):
        sent["timeout"] = timeout
        return _ok_response()

    OpenRouterReviewer(api_key="k", model="m", timeout=42, post=post).review({})
    assert sent["timeout"] == 42, sent


# ── the feed fetch is bounded too ─────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {"sport": "nfl", "generated_at":
                                                               "2026-09-26T06:00:00Z", "games": []}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def test_the_feed_timeout_is_clamped_to_the_remaining_time(clock):
    seen = []
    fetch_feed("https://nfl.example", get=lambda url, timeout: seen.append(timeout) or _Resp(),
               sleep=lambda _s: None, timeout=60, deadline=1000.0 + 9)
    assert seen == [pytest.approx(9.0)], seen


def test_the_feed_retry_is_skipped_when_the_remaining_time_is_shorter_than_the_timeout(clock):
    """60s timeout with 30s left: a second 60s attempt cannot finish inside the scan budget, so
    it must not be started at all."""
    attempts = []
    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example",
                   get=lambda url, timeout: attempts.append(timeout) or _Resp(500),
                   sleep=lambda _s: None, timeout=60, deadline=1000.0 + 30)
    assert len(attempts) == 1, f"a retry was started with less time than one attempt needs: {attempts}"
    assert attempts[0] == pytest.approx(30.0), attempts


def test_the_feed_retry_still_runs_when_there_is_time_for_it(clock):
    """The retry exists because scale-to-zero predictors time out on the first request; it must
    survive a generous budget."""
    attempts = []
    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example",
                   get=lambda url, timeout: attempts.append(timeout) or _Resp(500),
                   sleep=lambda s: None, timeout=10, deadline=1000.0 + 300)
    assert len(attempts) == 2, attempts
    assert attempts == [10.0, 10.0], attempts


def test_a_feed_fetch_with_no_budget_left_raises_without_any_request(clock):
    called = []
    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example", get=lambda url, timeout: called.append(timeout) or _Resp(),
                   sleep=lambda _s: None, deadline=1000.0 - 1)
    assert called == [], "a request was issued with the budget already exhausted"


def test_the_sleep_between_retries_cannot_overrun_the_deadline(clock):
    slept = []
    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example",
                   get=lambda url, timeout: _Resp(500), sleep=slept.append, timeout=5,
                   deadline=1000.0 + 100)
    assert slept, "the retry pause was skipped entirely"
    assert sum(slept) <= 100, f"the pause outlived the budget: {slept}"


# ── the orchestrator threads the deadline into both ───────────────────────────

def test_run_sports_scan_passes_the_deadline_to_the_feed_and_the_reviewer(monkeypatch):
    import time
    from tradehub.sports import scan as sports

    seen: dict = {}
    deadline = time.monotonic() + 300

    def fetch(url, **kw):
        seen["fetch"] = kw
        raise FeedUnavailable("404")

    sports.run_sports_scan(NOW, object(), fetch=fetch, sports=("nfl",), deadline=deadline)
    assert seen["fetch"].get("deadline") == deadline, (
        f"the feed fetch was not bounded by the scan deadline: {seen['fetch']}"
    )


def test_run_sports_for_cron_gives_the_reviewer_the_deadline(monkeypatch):
    from tradehub.sports import scan as sports

    seen = {}

    class FakeReviewer:
        def __init__(self, *a, **kw):
            seen.update(kw)

    class FakeKalshi:
        def __init__(self, *a, **kw):
            seen["kalshi_deadline"] = kw.get("deadline")

        def open_markets(self, series):
            return []

    monkeypatch.setattr(sports, "OpenRouterReviewer", FakeReviewer)
    monkeypatch.setattr(sports, "SportsKalshi", FakeKalshi)
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-not-real")
    sports.run_sports_for_cron(NOW, supa=object(), deadline=777.0)
    assert seen.get("deadline") == 777.0, f"the reviewer got no deadline: {seen}"


def test_the_dry_run_still_works_with_no_deadline():
    """`python -m tradehub.sports.scan --dry-run` passes no deadline; that path must be unaffected
    by the clamping, and a 404 predictor must still be reported rather than raising."""
    from tradehub.sports import scan as sports

    def fetch(url, **kw):
        assert "deadline" not in kw or kw["deadline"] > 1e12, kw   # +inf when unbounded
        raise FeedUnavailable("404: the feed is not deployed yet")

    out = sports.run_sports_scan(NOW, object(), fetch=fetch, sports=("nfl",))
    assert out.reports["nfl"] == {"feed_error": "404: the feed is not deployed yet"}
    assert out.edges == [] and out.predictions == []

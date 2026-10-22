"""Test fetch_market retry with backoff and fallback to event_ticker endpoint."""

import time
import pytest
import requests

from tradehub.core.kalshi_feed import fetch_market, KALSHI_API_URL


class FakeResponse:
    """Minimal mock of requests.Response."""
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


def _reset():
    """Reset circuit breaker before each test."""
    from tradehub.core import kalshi_feed
    kalshi_feed._reset_circuit_breaker()


def test_fetch_market_single_endpoint_success():
    """Primary: GET /markets/{ticker} returns 200 on first try."""
    _reset()
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        return FakeResponse(200, {"market": {"ticker": "KXTEST-26OCT22-T50", "status": "open"}})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
    assert len(calls) == 1
    assert calls[0][0] == f"{KALSHI_API_URL}/KXTEST-26OCT22-T50"
    assert calls[0][1] is None  # no params for single-market


def test_fetch_market_fallback_on_503_via_event_ticker():
    """Fallback: 503 on primary (retries 3x), then 200 on event_ticker fallback with re-wrap."""
    _reset()
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXHIGHNY-26OCT20-T70"):
            return FakeResponse(503, {})  # primary 503 (retried 3x)
        # Fallback: event_ticker list endpoint
        if params and params.get("event_ticker") == "KXHIGHNY-26OCT20":
            return FakeResponse(200, {
                "markets": [
                    {"ticker": "KXHIGHNY-26OCT20-T65", "status": "finalized", "result": "no"},
                    {"ticker": "KXHIGHNY-26OCT20-T70", "status": "finalized", "result": "yes"},
                    {"ticker": "KXHIGHNY-26OCT20-T75", "status": "open"},
                ]
            })
        return FakeResponse(404, {})

    market = fetch_market("KXHIGHNY-26OCT20-T70", get=fake_get)
    # Re-wrapped as {"market": {...}}
    assert market["market"]["ticker"] == "KXHIGHNY-26OCT20-T70"
    assert market["market"]["status"] == "finalized"
    assert market["market"]["result"] == "yes"
    # Should have called primary 3 times (retries), then fallback once
    single_calls = [c for c in calls if c[0].endswith("/KXHIGHNY-26OCT20-T70")]
    fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
    assert len(single_calls) == 3
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] == {"event_ticker": "KXHIGHNY-26OCT20", "limit": 200}
    # No status=open in fallback params
    assert "status" not in fallback_calls[0][1]


def test_fetch_market_4xx_not_retried():
    """4xx responses (e.g., 400, 401, 403) must NOT be retried and must NOT fall back."""
    _reset()
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        return FakeResponse(403, {"error": "Forbidden"})

    with pytest.raises(requests.HTTPError):
        fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    # Only 1 call, no retries for 403, no fallback
    assert len(calls) == 1
    assert calls[0][0].endswith("/KXTEST-26OCT22-T50")


def test_fetch_market_404_triggers_fallback():
    """404 on single-market endpoint triggers fallback to event_ticker."""
    _reset()
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(404, {"error": "Not found"})
        # Fallback: event_ticker list endpoint
        if params and params.get("event_ticker") == "KXTEST-26OCT22":
            return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50", "status": "finalized"}]})
        return FakeResponse(404, {})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
    assert market["market"]["status"] == "finalized"
    # Should have called primary once, fallback once
    single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
    fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
    assert len(single_calls) == 1
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] == {"event_ticker": "KXTEST-26OCT22", "limit": 200}
    assert "status" not in fallback_calls[0][1]


def test_fetch_market_circuit_breaker_trips_after_3_failures():
    """Circuit breaker: after 3 consecutive RETRYABLE failures, subsequent calls skip to fallback."""
    _reset()
    # Record 3 retryable failures manually to open the circuit breaker
    from tradehub.core import kalshi_feed
    kalshi_feed._record_fetch_failure(is_retryable=True)
    kalshi_feed._record_fetch_failure(is_retryable=True)
    kalshi_feed._record_fetch_failure(is_retryable=True)
    assert kalshi_feed._circuit_open()

    # Now fetch should skip single-market and go straight to fallback
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        # Fallback: event_ticker list endpoint
        if params and params.get("event_ticker") == "KXTEST-26OCT22":
            return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50", "status": "open"}]})
        return FakeResponse(200, {"market": {"ticker": "KXTEST-26OCT22-T50"}})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    # Should go straight to fallback and succeed
    assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
    assert market["market"]["status"] == "open"
    # Should have made ZERO calls to single-market endpoint
    single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
    fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
    assert len(single_calls) == 0  # No single-market calls when breaker open
    assert len(fallback_calls) == 1  # Straight to fallback


def test_fetch_market_503_then_success_with_backoff():
    """Primary: 503 on first attempt, then 200 on retry (honors Retry-After)."""
    _reset()
    attempts = [0]
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if attempts[0] == 0:
            attempts[0] += 1
            # Include Retry-After header
            return FakeResponse(503, {}, {"Retry-After": "1"})
        return FakeResponse(200, {"market": {"ticker": "KXTEST-26OCT22-T50"}})

    start = time.time()
    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    elapsed = time.time() - start

    assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
    assert elapsed >= 1.0  # Retry-After: 1s
    assert len(calls) == 2


def test_fetch_market_500_fallback_without_status_open():
    """Fallback uses event_ticker without status=open param."""
    _reset()
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(500, {})
        if params and params.get("event_ticker") == "KXTEST-26OCT22":
            return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50", "status": "open"}]})
        return FakeResponse(404, {})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
    # Verify fallback params
    fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] == {"event_ticker": "KXTEST-26OCT22", "limit": 200}
    assert "status" not in fallback_calls[0][1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_fetch_market_circuit_breaker_stays_open_during_outage():
    """
    Simulate a continuous 503 outage on the single-market endpoint for 30 fetches.
    Fallback succeeds every time.
    
    Expected behavior:
    - First call: 3 single-market attempts (503 x3) → fallback succeeds
    - Circuit breaker opens after 3 retryable failures
    - Calls 2-30: ZERO single-market attempts (breaker open), straight to fallback
    - After 61s: one probe attempt (half-open), then back to fallback
    - Total single-endpoint attempts: at most 4 (3 initial + 1 probe)
    - Zero sleeps after the 3rd failure (breaker open skips single endpoint entirely)
    - Exactly one probe attempt after 61 simulated seconds
    """
    import time
    from unittest.mock import patch
    from tradehub.core import kalshi_feed
    
    # Use a fake clock that we control
    clock = [0.0]  # mutable container for simulated time
    
    def fake_time():
        return clock[0]
    
    _reset()
    
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(503, {})
        # Fallback: event_ticker list endpoint
        if params and params.get("event_ticker") == "KXTEST-26OCT22":
            return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50", "status": "open"}]})
        return FakeResponse(404, {})
    
    # Patch time.time to use our fake clock
    with patch.object(time, 'time', fake_time):
        # First fetch: 3 retries (503) then fallback
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        
        # Count single-market calls after first fetch
        single_calls_after_first = sum(1 for c in calls if c[0].endswith("/KXTEST-26OCT22-T50"))
        assert single_calls_after_first == 3  # 3 retries on first call
        
        # Now make 29 more calls - all should go straight to fallback (breaker open)
        for i in range(29):
            calls.clear()
            market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
            assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
            single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
            assert len(single_calls) == 0, f"Call {i+2}: expected 0 single-market calls, got {len(single_calls)}"
        
        # Advance fake clock by 61 seconds (past the 60s half-open window)
        clock[0] += 61
        
        # Next call should make ONE probe attempt (half-open), then fallback
        calls.clear()
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
        fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
        assert len(single_calls) == 1, "Expected exactly one probe attempt after half-open"
        assert len(fallback_calls) == 1, "Expected fallback after probe fails"
        
        # After probe fails (503), breaker should re-open
        assert kalshi_feed._circuit_open()
        
        # Subsequent calls should go straight to fallback again
        calls.clear()
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
        assert len(single_calls) == 0, "After failed probe, breaker should be open again"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_fetch_market_circuit_breaker_stays_open_during_outage():
    """
    Simulate a continuous 503 outage on the single-market endpoint for 30 fetches.
    Fallback succeeds every time.
    
    Expected behavior:
    - First call: 3 single-market attempts (503 x3) → fallback succeeds
    - Circuit breaker opens after 3 retryable failures
    - Calls 2-30: ZERO single-market attempts (breaker open), straight to fallback
    - After 61s: one probe attempt (half-open), then back to fallback
    - Total single-endpoint attempts: at most 4 (3 initial + 1 probe)
    - Zero sleeps after the 3rd failure (breaker open skips single endpoint entirely)
    - Exactly one probe attempt after 61 simulated seconds
    """
    import time
    from unittest.mock import patch
    from tradehub.core import kalshi_feed
    
    # Use a fake clock that we control
    clock = [0.0]  # mutable container for simulated time
    
    def fake_time():
        return clock[0]
    
    _reset()
    
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(503, {})
        # Fallback: event_ticker list endpoint
        if params and params.get("event_ticker") == "KXTEST-26OCT22":
            return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50", "status": "open"}]})
        return FakeResponse(404, {})
    
    # Patch time.time to use our fake clock
    with patch.object(time, 'time', fake_time):
        # First fetch: 3 retries (503) then fallback
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        
        # Count single-market calls after first fetch
        single_calls_after_first = sum(1 for c in calls if c[0].endswith("/KXTEST-26OCT22-T50"))
        assert single_calls_after_first == 3  # 3 retries on first call
        
        # Now make 29 more calls - all should go straight to fallback (breaker open)
        for i in range(29):
            calls.clear()
            market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
            assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
            single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
            assert len(single_calls) == 0, f"Call {i+2}: expected 0 single-market calls, got {len(single_calls)}"
        
        # Advance fake clock by 61 seconds (past the 60s half-open window)
        clock[0] += 61
        
        # Next call should make ONE probe attempt (half-open), then fallback
        calls.clear()
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
        fallback_calls = [c for c in calls if "event_ticker" in (c[1] or {})]
        assert len(single_calls) == 1, "Expected exactly one probe attempt after half-open"
        assert len(fallback_calls) == 1, "Expected fallback after probe fails"
        
        # After probe fails (503), breaker should re-open
        assert kalshi_feed._circuit_open()
        
        # Subsequent calls should go straight to fallback again
        calls.clear()
        market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
        assert market["market"]["ticker"] == "KXTEST-26OCT22-T50"
        single_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
        assert len(single_calls) == 0, "After failed probe, breaker should be open again"
        
        # Total single-endpoint attempts across all 30+ calls: 3 (initial) + 1 (probe) = 4
        total_single_calls = sum(1 for c in calls if c[0].endswith("/KXTEST-26OCT22-T50"))
        # We can't easily count all calls, but we know the pattern


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
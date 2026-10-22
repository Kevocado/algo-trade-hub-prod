"""Test fetch_market retry with backoff and fallback to list endpoint."""

import time
import pytest
import requests

from tradehub.core.kalshi_feed import fetch_market, KALSHI_API_URL


class FakeResponse:
    """Minimal mock of requests.Response."""
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


def test_fetch_market_single_endpoint_success():
    """Single-market endpoint returns 200 on first try."""
    calls = []
    def fake_get(url, headers=None, timeout=30):
        calls.append(url)
        return FakeResponse(200, {"ticker": "KXTEST-26OCT22-T50", "yes_ask": 0.5})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    assert market["ticker"] == "KXTEST-26OCT22-T50"
    assert len(calls) == 1
    assert calls[0] == f"{KALSHI_API_URL}/KXTEST-26OCT22-T50"


def test_fetch_market_503_then_success():
    """503 on first attempt, then 200 on retry."""
    attempts = [0]
    calls = []
    def fake_get(url, headers=None, timeout=30):
        calls.append(url)
        if attempts[0] == 0:
            attempts[0] += 1
            return FakeResponse(503, {})
        return FakeResponse(200, {"ticker": "KXTEST-26OCT22-T50"})

    start = time.time()
    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    elapsed = time.time() - start

    assert market["ticker"] == "KXTEST-26OCT22-T50"
    assert elapsed >= 1.0  # base_delay * 2^0 = 1s
    assert len(calls) >= 2  # two GET calls


def test_fetch_market_503_all_retries_then_fallback_success():
    """All single-market retries 503, fallback to list endpoint succeeds."""
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(503, {})
        # List endpoint fallback
        return FakeResponse(200, {"markets": [{"ticker": "KXTEST-26OCT22-T50"}]})

    market = fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    assert market["ticker"] == "KXTEST-26OCT22-T50"
    # Should have 3 single-market attempts + 1 fallback = 4 calls
    single_market_calls = [c for c in calls if c[0].endswith("/KXTEST-26OCT22-T50")]
    list_calls = [c for c in calls if not c[0].endswith("/KXTEST-26OCT22-T50")]
    assert len(single_market_calls) == 3
    assert len(list_calls) == 1
    # Verify fallback uses tickers param
    assert list_calls[0][1] == {"tickers": "KXTEST-26OCT22-T50", "limit": 1, "status": "open"}


def test_fetch_market_all_fail_raises():
    """All retries and fallback fail -> raises RuntimeError."""
    def fake_get(url, headers=None, timeout=30, params=None):
        return FakeResponse(503, {})

    with pytest.raises(RuntimeError, match="fetch failed for KXTEST-26OCT22-T50"):
        fetch_market("KXTEST-26OCT22-T50", get=fake_get)


def test_fetch_market_fallback_empty_raises():
    """Single-market 503, fallback returns empty -> raises."""
    calls = []
    def fake_get(url, headers=None, timeout=30, params=None):
        calls.append((url, params))
        if url.endswith("/KXTEST-26OCT22-T50"):
            return FakeResponse(503, {})
        return FakeResponse(200, {"markets": []})

    with pytest.raises(RuntimeError, match="fetch failed for KXTEST-26OCT22-T50"):
        fetch_market("KXTEST-26OCT22-T50", get=fake_get)


def test_fetch_market_backoff_timing():
    """Verify exponential backoff: 1s, 2s."""
    attempts = [0]
    start = time.time()
    def fake_get(url, headers=None, timeout=30):
        if attempts[0] < 2:
            attempts[0] += 1
            return FakeResponse(503, {})
        return FakeResponse(200, {"ticker": "KXTEST-26OCT22-T50"})

    fetch_market("KXTEST-26OCT22-T50", get=fake_get)
    elapsed = time.time() - start
    # 1s + 2s = 3s minimum
    assert elapsed >= 2.5  # allow some margin


# Need to import the fetch_market function with a get parameter
# The current signature doesn't support get=, so we'll need to monkeypatch requests.get

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

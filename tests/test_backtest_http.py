from datetime import datetime, timezone

import pytest
import requests

from tradehub.backtest import http


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload or {"ok": True}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self.payload


def test_default_get_json_retries_429_and_honors_retry_after_seconds(monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse()]
    sleeps = []
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda url, **kwargs: calls.append(kwargs) or responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    assert http.default_get_json("https://example.test") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_default_get_json_retries_5xx_with_capped_exponential_backoff(monkeypatch):
    responses = [FakeResponse(503), FakeResponse(502), FakeResponse(500), FakeResponse()]
    sleeps = []
    monkeypatch.setattr(http, "BASE_BACKOFF_SECONDS", 1.0)
    monkeypatch.setattr(http, "MAX_BACKOFF_SECONDS", 2.0)
    monkeypatch.setattr(http.requests, "get", lambda url, **kwargs: responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    assert http.default_get_json("https://example.test") == {"ok": True}
    assert sleeps == [1.0, 2.0, 2.0]


def test_default_get_json_exhausts_attempts_and_reraises(monkeypatch):
    responses = [FakeResponse(429) for _ in range(3)]
    sleeps = []
    calls = []
    monkeypatch.setattr(http, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(http.requests, "get", lambda url, **kwargs: calls.append(url) or responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    with pytest.raises(requests.HTTPError):
        http.default_get_json("https://example.test")
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_default_get_json_does_not_retry_ordinary_4xx(monkeypatch):
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda url, **kwargs: calls.append(url) or FakeResponse(404))

    with pytest.raises(requests.HTTPError):
        http.default_get_json("https://example.test")
    assert len(calls) == 1


def test_retry_after_http_date_is_parsed(monkeypatch):
    monkeypatch.setattr(http, "BASE_BACKOFF_SECONDS", 1.0)
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert http._retry_after_seconds("Thu, 01 Jan 2026 12:00:30 GMT", now=now) == 30.0

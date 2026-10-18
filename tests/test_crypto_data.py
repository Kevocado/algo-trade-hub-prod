"""Tests for the keyless crypto market data source: Kraken OHLC with Coinbase fallback.

No credentials. Both endpoints are public and were checked live on 2026-10-18.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime

from tradehub.scripts import shadow_performance as sp


# ── recorded responses ─────────────────────────────────────────────────────────

KRAKEN_OK = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            ["1729200000", "67000.0", "67100.0", "66900.0", "67050.0", "100.0", "6700000.0", 10],
            ["1729203600", "67050.0", "67150.0", "66950.0", "67100.0", "120.0", "6705000.0", 12],
            ["1729207200", "67100.0", "67200.0", "67000.0", "67150.0", "110.0", "6710000.0", 11],
        ],
        "last": "1729207200",
    },
}

KRAKEN_PARTIAL = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            ["1729200000", "67000.0", "67100.0", "66900.0", "67050.0", "100.0", "6700000.0", 10],
            ["1729203600", "67050.0", "67150.0", "66950.0", "67100.0", "120.0", "6705000.0", 12],
            # Last bar still forming — must be dropped
            ["1729207200", "67100.0", "67200.0", "67000.0", "67150.0", "110.0", "6710000.0", 11],
        ],
        "last": "1729207200",
    },
}

KRAKEN_RATE_LIMIT = {"error": ["EAPI:Rate limit exceeded"]}

COINBASE_OK = [
    [1729207200, 66900.0, 67150.0, 67100.0, 67000.0, 100.0],
    [1729203600, 66950.0, 67100.0, 67050.0, 67000.0, 120.0],
    [1729200000, 66900.0, 67050.0, 67000.0, 66900.0, 110.0],
]

COINBASE_RATE_LIMIT = {"message": "rate limit exceeded"}


# ── helpers ────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} Client Error")


def _mock_get(monkeypatch, responses):
    """Mock requests.get to return responses in order, recording calls."""
    calls = []

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        resp = responses.pop(0) if responses else _Resp({}, 500)
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr("requests.get", _get)
    return calls


# ── Kraken parsing ─────────────────────────────────────────────────────────────


def test_kraken_normal_response(monkeypatch):
    from tradehub.core.crypto_data import parse_kraken_ohlc

    _mock_get(monkeypatch, [_Resp(KRAKEN_OK)])
    df = parse_kraken_ohlc(KRAKEN_OK, pair="XBTUSD")
    assert len(df) == 3
    assert df.columns.tolist() == ["Close"]
    assert float(df.iloc[0]["Close"]) == 67050.0  # First bar close price
    assert df.index.name == "timestamp"


def test_kraken_partial_drops_last_bar(monkeypatch):
    """The last bar is still forming and must be dropped."""
    from tradehub.core.crypto_data import parse_kraken_ohlc

    df = parse_kraken_ohlc(KRAKEN_PARTIAL, pair="XBTUSD", drop_last=True)
    assert len(df) == 2  # 3 bars in, 1 dropped


def test_kraken_rate_limit_raises(monkeypatch):
    from tradehub.core.crypto_data import parse_kraken_ohlc

    with pytest.raises(RuntimeError, match="error"):
        parse_kraken_ohlc(KRAKEN_RATE_LIMIT, pair="XBTUSD")


# ── Coinbase parsing ───────────────────────────────────────────────────────────


def test_coinbase_normal_response(monkeypatch):
    from tradehub.core.crypto_data import parse_coinbase_candles

    df = parse_coinbase_candles(COINBASE_OK, product="BTC-USD")
    assert len(df) == 3
    assert df.columns.tolist() == ["Close"]
    # Coinbase candles are [time, low, high, open, close, volume]
    # First candle: [1729207200, 66900.0, 67150.0, 67100.0, 67000.0, 100.0]
    # After sort_index, the first row is the earliest timestamp (1729200000)
    # which has close=66900.0
    assert float(df.iloc[0]["Close"]) == 66900.0


def test_coinbase_rate_limit_raises(monkeypatch):
    from tradehub.core.crypto_data import parse_coinbase_candles

    with pytest.raises(RuntimeError):
        parse_coinbase_candles(COINBASE_RATE_LIMIT, product="BTC-USD")


# ── source selection and fallback ──────────────────────────────────────────────


def test_fetch_closes_kraken_first(monkeypatch):
    from tradehub.core.crypto_data import fetch_hourly_closes

    calls = _mock_get(monkeypatch, [_Resp(KRAKEN_OK)])
    df, source = fetch_hourly_closes("BTC", start=_ts("2026-10-17"), end=_ts("2026-10-18"))
    assert source == "kraken"
    assert len(df) == 3
    # Only Kraken was called
    assert len(calls) == 1
    assert "kraken" in calls[0][0]


def test_fetch_closes_falls_back_to_coinbase(monkeypatch):
    """Kraken rate-limits; Coinbase succeeds."""
    from tradehub.core.crypto_data import fetch_hourly_closes

    calls = _mock_get(monkeypatch, [_Resp(KRAKEN_RATE_LIMIT, 429), _Resp(COINBASE_OK)])
    df, source = fetch_hourly_closes("BTC", start=_ts("2026-10-17"), end=_ts("2026-10-18"))
    assert source == "coinbase"
    assert len(df) == 3
    assert len(calls) == 2
    assert "kraken" in calls[0][0]
    assert "coinbase" in calls[1][0]


def test_fetch_closes_both_fail_raises(monkeypatch):
    """Both sources fail — the caller must know, not get an empty DataFrame."""
    from tradehub.core.crypto_data import fetch_hourly_closes

    _mock_get(monkeypatch, [_Resp(KRAKEN_RATE_LIMIT, 429), _Resp(COINBASE_RATE_LIMIT, 429)])
    with pytest.raises(Exception, match="both|failed|unavailable"):
        fetch_hourly_closes("BTC", start=_ts("2026-10-17"), end=_ts("2026-10-18"))


def test_fetch_closes_works_with_alpaca_unset(monkeypatch):
    """The route must work with ALPACA_* unset — it never reads them."""
    from tradehub.core.crypto_data import fetch_hourly_closes

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    _mock_get(monkeypatch, [_Resp(KRAKEN_OK)])
    df, source = fetch_hourly_closes("BTC", start=_ts("2026-10-17"), end=_ts("2026-10-18"))
    assert source == "kraken"
    assert len(df) > 0


# ── shadow_performance integration ────────────────────────────────────────────


def test_fetch_alpaca_hourly_closes_removed():
    """The old Alpaca read is gone; the new keyless read is used."""
    assert not hasattr(sp, "_fetch_alpaca_hourly_closes")
    assert hasattr(sp, "_fetch_crypto_hourly_closes")


def test_alpaca_config_removed():
    """The Alpaca credential check is gone from shadow_performance."""
    assert not hasattr(sp, "_alpaca_config")


def test_no_alpaca_env_reads_in_shadow_performance():
    """shadow_performance.py must not read ALPACA_* environment variables."""
    import inspect

    src = inspect.getsource(sp)
    assert "ALPACA_API_KEY" not in src
    assert "ALPACA_SECRET_KEY" not in src


# ── helpers ────────────────────────────────────────────────────────────────────


def _ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)

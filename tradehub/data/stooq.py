"""Stooq daily close series – fallback to Yahoo Finance when Stooq serves a JS wall.

Spec §8: Gold via `XAUUSD`, EUR/USD via `EURUSD` on Stooq. Yahoo equivalents (`GC=F`, `EURUSD=X`)
are used when Stooq returns a JS challenge or errors, so Wave 2 stays live even when Stooq rate-limits.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Callable
from datetime import date
from zoneinfo import ZoneInfo

import httpx

CT = ZoneInfo("America/Chicago")


def _yahoo_daily(symbol: str, start: date) -> dict[date, float]:
    """Yahoo Finance adjusted close series."""
    period1 = int(__import__("datetime").datetime(start.year, start.month, start.day).timestamp())
    url = f"https://query1.finance.yahoo.com/v7/finance/download/{symbol}?period1={period1}&period2=9999999999&interval=1d&events=history"
    rows: dict[date, float] = {}
    resp = httpx.get(url, timeout=30, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; AlgoTradeHub/1.0)"})
    resp.raise_for_status()
    for r in csv.DictReader(io.StringIO(resp.text)):
        rows[date.fromisoformat(r["Date"])] = float(r["Close"])
    return rows


def _stooq_daily(symbol: str, start: date) -> dict[date, float]:
    """Stooq daily OHLCV; falls back to Yahoo when Stooq serves a JS wall."""
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&d1={start.strftime('%Y%m%d')}&d2={date.today().strftime('%Y%m%d')}&i=d"
    resp = httpx.get(url, timeout=30, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; AlgoTradeHub/1.0)"})
    if resp.status_code != 200 or "<html" in resp.text[:500].lower():
        # JS wall / non-CSV – fall back to Yahoo
        return _yahoo_daily(symbol, start)
    rows: dict[date, float] = {}
    for r in csv.DictReader(io.StringIO(resp.text)):
        rows[date.fromisoformat(r["Date"])] = float(r["Close"])
    return rows


def fetch_stooq_daily(symbol: str, start: date) -> dict[date, float]:
    """Fetch daily close series from Stooq, with Yahoo fallback.

    Args:
        symbol: Stooq ticker (e.g., `XAUUSD`, `EURUSD`)
        start: Earliest date to fetch

    Returns:
        dict mapping date -> close price
    """
    try:
        return _stooq_daily(symbol, start)
    except Exception:
        yahoo_map = {"XAUUSD": "GC=F", "EURUSD": "EURUSD=X"}
        return _yahoo_daily(yahoo_map.get(symbol, symbol), start)

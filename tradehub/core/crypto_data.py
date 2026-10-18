"""Keyless crypto market data: Kraken OHLC with Coinbase fallback.

No credentials. Both endpoints are public and were checked live on 2026-10-18.

Kraken: https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60
Coinbase: https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
COINBASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"

# Map our asset names to exchange pairs
KRAKEN_PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD"}
COINBASE_PRODUCTS = {"BTC": "BTC-USD", "ETH": "ETH-USD"}

# Coinbase requires a User-Agent header
COINBASE_HEADERS = {"User-Agent": "tradehub/1.0"}


def parse_kraken_ohlc(payload: dict[str, Any], pair: str = "XBTUSD", *, drop_last: bool = False) -> pd.DataFrame:
    """Parse Kraken OHLC response into a DataFrame with a timestamp index and Close column.

    Kraken returns bars as [time, open, high, low, close, vwap, volume, count].
    The last bar may still be forming; drop_last=True removes it.
    Raises if the payload contains an error.
    """
    if payload.get("error"):
        raise RuntimeError(f"Kraken error: {payload['error']}")
    result = payload.get("result") or {}
    # Kraken uses a dynamic key like "XXBTZUSD" for XBTUSD
    bars = None
    for key, value in result.items():
        if key != "last" and isinstance(value, list):
            bars = value
            break
    if not bars:
        return pd.DataFrame(columns=["Close"])

    rows = []
    for bar in bars:
        ts = datetime.fromtimestamp(int(bar[0]), tz=UTC)
        close = float(bar[4])
        rows.append((ts, close))

    if drop_last and rows:
        rows = rows[:-1]

    df = pd.DataFrame(rows, columns=["timestamp", "Close"]).set_index("timestamp")
    return df.sort_index()


def parse_coinbase_candles(payload: list[list[Any]], product: str = "BTC-USD") -> pd.DataFrame:
    """Parse Coinbase candles response into a DataFrame with a timestamp index and Close column.

    Coinbase returns candles as [time, low, high, open, close, volume].
    Raises if the payload is an error dict.
    """
    if isinstance(payload, dict) and payload.get("message"):
        raise RuntimeError(f"Coinbase error: {payload['message']}")
    if not payload or not isinstance(payload, list):
        return pd.DataFrame(columns=["Close"])

    rows = []
    for candle in payload:
        ts = datetime.fromtimestamp(int(candle[0]), tz=UTC)
        close = float(candle[4])
        rows.append((ts, close))

    df = pd.DataFrame(rows, columns=["timestamp", "Close"]).set_index("timestamp")
    return df.sort_index()


def fetch_hourly_closes(
    asset: str,
    *,
    start: datetime,
    end: datetime,
    drop_last: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Fetch hourly closes for an asset. Returns (DataFrame, source_name).

    Tries Kraken first, falls back to Coinbase. Raises if both fail.
    """
    kraken_pair = KRAKEN_PAIRS.get(asset.upper())
    coinbase_product = COINBASE_PRODUCTS.get(asset.upper())

    if not kraken_pair or not coinbase_product:
        raise ValueError(f"Unsupported crypto asset: {asset}")

    # Try Kraken first
    try:
        resp = requests.get(
            KRAKEN_URL,
            params={"pair": kraken_pair, "interval": 60},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            raise RuntimeError(f"Kraken error: {payload['error']}")
        df = parse_kraken_ohlc(payload, pair=kraken_pair, drop_last=drop_last)
        if not df.empty:
            return df, "kraken"
    except Exception:
        pass

    # Fall back to Coinbase
    try:
        resp = requests.get(
            COINBASE_URL.format(product=coinbase_product),
            params={"granularity": 3600},
            headers=COINBASE_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("message"):
            raise RuntimeError(f"Coinbase error: {payload['message']}")
        df = parse_coinbase_candles(payload, product=coinbase_product)
        if not df.empty:
            return df, "coinbase"
    except Exception:
        pass

    raise RuntimeError(f"Both Kraken and Coinbase failed for {asset}")

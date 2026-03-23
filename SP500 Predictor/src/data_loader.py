"""
Data Loader — Multi-Source Acquisition for SPY/QQQ

Strategy:
  1. Tiingo: Historical 1-min OHLCV bars (accurate volume ground truth)
  2. Alpaca: Real-time streams and fallback historical
  3. FRED: VIX and yield curve macro data

No crypto support — SPY/QQQ only (proxies for SPX/Nasdaq).
"""

import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta, timezone
import dateutil.relativedelta
from dotenv import load_dotenv

load_dotenv()

# API Keys
ALPACA_KEY = os.getenv("ALPACA_API_KEY", "").strip('"')
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "").strip('"')
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip('"')

# Supported tickers and their index mappings
TICKER_MAP = {
    "SPX": "SPY",
    "Nasdaq": "QQQ",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


def get_macro_data():
    """Fetches VIX and 10Y-2Y Yield Curve from FRED."""
    from fredapi import Fred
    fred_key = os.getenv("FRED_API_KEY", "").strip('"')
    if not fred_key:
        return {"vix": 20, "yield_curve": 0}
    try:
        fred = Fred(api_key=fred_key)
        vix = fred.get_series('VIXCLS').iloc[-1]
        yc = fred.get_series('T10Y2Y').iloc[-1]
        return {"vix": vix, "yield_curve": yc}
    except Exception:
        return {"vix": 20, "yield_curve": 0}


def fetch_tiingo(ticker="SPY", period="5d", interval="1min"):
    """
    Fetch historical OHLCV from Tiingo IEX endpoint (1-min bars).
    Tiingo provides accurate volume ground truth missing from Alpaca free tier.

    Args:
        ticker: Stock symbol (SPY, QQQ)
        period: '1d', '5d', '1mo'
        interval: '1min', '5min', '1hour'

    Returns:
        pd.DataFrame with OHLCV columns and DatetimeIndex
    """
    if not TIINGO_KEY:
        print("  ⚠️ TIINGO_API_KEY not set, falling back to Alpaca")
        return pd.DataFrame()

    import requests

    symbol = TICKER_MAP.get(ticker, ticker)

    # Parse period to start date
    now = datetime.now(timezone.utc)
    period_map = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": dateutil.relativedelta.relativedelta(months=1),
        "3mo": dateutil.relativedelta.relativedelta(months=3),
        "6mo": dateutil.relativedelta.relativedelta(months=6),
        "1y": dateutil.relativedelta.relativedelta(years=1),
        "2y": dateutil.relativedelta.relativedelta(years=2),
        "3y": dateutil.relativedelta.relativedelta(years=3),
    }
    delta = period_map.get(period, timedelta(days=5))
    start = (now - delta).strftime("%Y-%m-%d")

    # Tiingo IEX endpoint for intraday
    url = f"https://api.tiingo.com/iex/{symbol}/prices"
    params = {
        "startDate": start,
        "resampleFreq": interval,
        "columns": "open,high,low,close,volume",
        "token": TIINGO_KEY,
    }

    try:
        print(f"  📡 Fetching {symbol} from Tiingo ({period}, {interval})...")
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            print(f"  ⚠️ Tiingo error {r.status_code}: {r.text[:200]}")
            return pd.DataFrame()

        data = r.json()
        if not data:
            print("  ⚠️ No data from Tiingo")
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # Rename columns
        df = df.rename(columns={
            'date': 'datetime',
            'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close',
            'volume': 'Volume'
        })

        # Parse datetime and set index
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime')

        # Ensure timezone
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert('US/Eastern')

        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        print(f"  ✅ Tiingo: {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        print(f"  ⚠️ Tiingo fetch error: {e}")
        return pd.DataFrame()


def fetch_alpaca(ticker="SPY", period="5d", interval="1m"):
    """
    Fetch from Alpaca Markets (fallback or real-time supplement).
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("  ⚠️ Missing Alpaca credentials")
        return pd.DataFrame()

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    symbol = TICKER_MAP.get(ticker, ticker)
    print(f"  📡 Fetching {symbol} from Alpaca ({period}, {interval})...")

    # Parse period
    now = datetime.now(timezone.utc)
    period_map = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": dateutil.relativedelta.relativedelta(months=1),
        "3mo": dateutil.relativedelta.relativedelta(months=3),
    }
    delta = period_map.get(period, timedelta(days=5))
    start = now - delta

    # Parse interval
    tf_map = {"1m": TimeFrame.Minute, "5m": TimeFrame.Minute, "1h": TimeFrame.Hour, "1d": TimeFrame.Day}
    timeframe = tf_map.get(interval, TimeFrame.Minute)

    try:
        client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=start)
        bars = client.get_stock_bars(req)

        if not bars or not bars.data or symbol not in bars.data:
            print("  ⚠️ No Alpaca data")
            return pd.DataFrame()

        df = bars.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index(level=0, drop=True)

        df = df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        })
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
        else:
            df.index = df.index.tz_convert('US/Eastern')

        df = df.dropna()
        print(f"  ✅ Alpaca: {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        print(f"  ⚠️ Alpaca fetch error: {e}")
        return pd.DataFrame()


def fetch_data(ticker="SPY", period="5d", interval="1m"):
    """
    Primary data acquisition: Tiingo first, Alpaca fallback.
    """
    symbol = TICKER_MAP.get(ticker, ticker)

    # Map interval for Tiingo format
    tiingo_interval_map = {"1m": "1min", "5m": "5min", "1h": "1hour"}
    tiingo_interval = tiingo_interval_map.get(interval, "1min")

    # Try Tiingo first (better volume data)
    df = fetch_tiingo(symbol, period, tiingo_interval)
    if not df.empty:
        return df

    # Fallback to Alpaca
    df = fetch_alpaca(symbol, period, interval)
    return df


def save_data(df, filepath="Data/spy_data.csv"):
    """Saves data to CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath)
    print(f"  💾 Saved to {filepath}")


def load_data(filepath="Data/spy_data.csv"):
    """Loads data from CSV."""
    if not os.path.exists(filepath):
        return None
    return pd.read_csv(filepath, index_col=0, parse_dates=True)


if __name__ == "__main__":
    print("Testing Multi-Source Data Loader...")
    for ticker in ["SPY", "QQQ"]:
        df = fetch_data(ticker, period="5d", interval="1m")
        if not df.empty:
            print(f"\n  {ticker}: {len(df)} rows, {df.index[0]} → {df.index[-1]}")
            print(f"  Last close: ${df['Close'].iloc[-1]:.2f}")
            print(f"  Avg volume: {df['Volume'].mean():,.0f}")
        else:
            print(f"\n  {ticker}: No data fetched")

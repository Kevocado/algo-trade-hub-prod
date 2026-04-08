import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.crypto_features import build_features

FEATURE_WARMUP_HOURS = 21 * 24
FEATURE_COMPARISON_HOURS = 72


def _fetch_alpaca_bars(start: datetime, end: datetime) -> pd.DataFrame:
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    base_url = os.getenv("ALPACA_DATA_API_BASE", "https://data.alpaca.markets")
    if not api_key or not secret_key:
        raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_SECRET_KEY for calibration.")

    response = requests.get(
        f"{base_url}/v1beta3/crypto/us/bars",
        headers={
            "accept": "application/json",
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        },
        params={
            "symbols": "BTC/USD",
            "timeframe": "1Hour",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": max(int((end - start).total_seconds() // 3600) + 24, 300),
            "sort": "asc",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = ((response.json().get("bars") or {}).get("BTC/USD")) or []
    if not rows:
        raise RuntimeError("Alpaca returned no BTC/USD hourly bars.")
    frame = pd.DataFrame(rows).rename(
        columns={"t": "timestamp", "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.set_index("timestamp").sort_index()
    return frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()


def _fetch_yfinance_bars(start: datetime, end: datetime) -> pd.DataFrame:
    frame = yf.download(
        "BTC-USD",
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(hours=1)).strftime("%Y-%m-%d"),
        interval="1h",
        progress=False,
        auto_adjust=False,
    )
    if frame.empty:
        raise RuntimeError("yfinance returned no BTC-USD hourly bars.")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    return frame.loc[(frame.index >= start) & (frame.index <= end)]


def _align_ohlcv(alpaca: pd.DataFrame, yfin: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    common_index = alpaca.index.intersection(yfin.index)
    if len(common_index) < 48:
        raise RuntimeError(f"Insufficient overlapping hourly bars after alignment: {len(common_index)}")
    return alpaca.loc[common_index], yfin.loc[common_index]


def _restrict_to_last_hours(frame: pd.DataFrame, hours: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    cutoff = frame.index.max() - timedelta(hours=hours - 1)
    return frame.loc[frame.index >= cutoff]


def _print_feature_stats(label: str, frame: pd.DataFrame) -> None:
    print(f"\n{label} feature stats")
    for column in ("Volume", "force_idx", "relative_vol", "vol_pressure"):
        print(
            f"  {column}: mean={frame[column].mean():.6f} std={frame[column].std():.6f}"
        )


async def main() -> None:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=FEATURE_WARMUP_HOURS)

    alpaca_bars, yfinance_bars = await asyncio.gather(
        asyncio.to_thread(_fetch_alpaca_bars, start, end),
        asyncio.to_thread(_fetch_yfinance_bars, start, end),
    )

    print(f"Alpaca rows: {len(alpaca_bars)}")
    print(f"yfinance rows: {len(yfinance_bars)}")
    alpaca_aligned, yfinance_aligned = _align_ohlcv(alpaca_bars, yfinance_bars)
    print(f"Aligned rows: {len(alpaca_aligned)}")

    volume_ratio = alpaca_aligned["Volume"] / yfinance_aligned["Volume"].replace(0, pd.NA)
    volume_ratio = volume_ratio.dropna()
    if volume_ratio.empty:
        raise RuntimeError("Volume ratio could not be computed; overlapping yfinance volume is empty or zero.")
    recommended_multiplier = yfinance_aligned["Volume"].median() / alpaca_aligned["Volume"].replace(0, pd.NA).median()

    print("\nRaw volume ratio Alpaca / yfinance")
    print(f"  mean={volume_ratio.mean():.6f}")
    print(f"  median={volume_ratio.median():.6f}")
    print(f"  min={volume_ratio.min():.6f}")
    print(f"  max={volume_ratio.max():.6f}")
    print(f"Recommended CRYPTO_ALPACA_VOLUME_MULTIPLIER={recommended_multiplier:.10f}")

    alpaca_features = build_features(alpaca_aligned, is_live_inference=True)
    yfinance_features = build_features(yfinance_aligned, is_live_inference=True)
    alpaca_features, yfinance_features = _align_ohlcv(alpaca_features, yfinance_features)
    alpaca_features = _restrict_to_last_hours(alpaca_features, FEATURE_COMPARISON_HOURS)
    yfinance_features = _restrict_to_last_hours(yfinance_features, FEATURE_COMPARISON_HOURS)
    alpaca_features, yfinance_features = _align_ohlcv(alpaca_features, yfinance_features)

    print(f"Feature-aligned rows (last {FEATURE_COMPARISON_HOURS}h): {len(alpaca_features)}")

    _print_feature_stats("Alpaca", alpaca_features)
    _print_feature_stats("yfinance", yfinance_features)

    latest_ts = alpaca_features.index[-1]
    print(f"\nFeature parity at {latest_ts.isoformat()}")
    for column in ("Volume", "force_idx", "relative_vol", "vol_pressure"):
        alpaca_value = float(alpaca_features.iloc[-1][column])
        yfinance_value = float(yfinance_features.iloc[-1][column])
        print(
            f"  {column}: alpaca={alpaca_value:.6f} yfinance={yfinance_value:.6f} abs_diff={abs(alpaca_value - yfinance_value):.6f}"
        )


if __name__ == "__main__":
    asyncio.run(main())

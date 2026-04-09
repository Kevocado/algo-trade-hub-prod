from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

VOLUME_MULTIPLIER_BTC = 1.0
VOLUME_MULTIPLIER_ETH = 0.0047616754759827115

CANONICAL_CRYPTO_FEATURES = [
    "Close",
    "High",
    "Low",
    "Open",
    "Volume",
    "hour",
    "dayofweek",
    "is_weekend",
    "is_retail_window",
    "is_us_session",
    "sin_hour",
    "cos_hour",
    "midnight_signal",
    "rsi_5",
    "rsi_7",
    "rsi_14",
    "vol_ratio",
    "dist_ma200",
    "force_idx",
    "rsi_div",
    "ret_1h_z",
    "ret_4h",
    "rsi_z",
    "z_score_24h",
    "vol_adj_ret",
    "relative_vol",
    "vol_pressure",
    "vol_spike",
    "retail_rsi",
    "trend_bias",
]


def calibrate_features(df: pd.DataFrame, asset: str | None = None) -> pd.DataFrame:
    calibrated = df.copy()
    normalized_asset = (asset or "").upper()
    if "Volume" not in calibrated.columns:
        return calibrated
    if normalized_asset == "BTC":
        calibrated["Volume"] = calibrated["Volume"] * VOLUME_MULTIPLIER_BTC
    elif normalized_asset == "ETH":
        calibrated["Volume"] = calibrated["Volume"] * VOLUME_MULTIPLIER_ETH
    return calibrated


def _require_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Crypto feature builder requires OHLCV columns; missing: {missing}")
    df = frame.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Crypto feature builder requires a DatetimeIndex.")
    if df.index.tz is None:
        df.index = pd.to_datetime(df.index, utc=True)
    else:
        df.index = pd.to_datetime(df.index, utc=True)
    for column in required:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[required].sort_index()


def build_features(
    df: pd.DataFrame,
    *,
    asset: str | None = None,
    is_live_inference: bool = False,
    include_target: bool = False,
) -> pd.DataFrame:
    import ta

    frame = _require_ohlcv(df)

    frame["rsi_5_raw"] = ta.momentum.rsi(frame["Close"], window=5)
    frame["rsi_7_raw"] = ta.momentum.rsi(frame["Close"], window=7)
    frame["rsi_14_raw"] = ta.momentum.rsi(frame["Close"], window=14)

    atr = ta.volatility.average_true_range(frame["High"], frame["Low"], frame["Close"], window=14)
    rolling_std_24 = frame["Close"].pct_change().rolling(window=24).std()
    rolling_std_168 = frame["Close"].pct_change().rolling(window=168).std()

    frame["hour"] = frame.index.hour
    frame["dayofweek"] = frame.index.dayofweek
    frame["is_weekend"] = (frame["dayofweek"] >= 5).astype(int)
    frame["is_retail_window"] = (frame["dayofweek"] >= 4).astype(int)
    frame["is_us_session"] = ((frame["hour"] >= 14) & (frame["hour"] <= 21)).astype(int)
    frame["sin_hour"] = np.sin(2 * np.pi * frame["hour"] / 24)
    frame["cos_hour"] = np.cos(2 * np.pi * frame["hour"] / 24)
    frame["midnight_signal"] = (frame["hour"] == 0).astype(int)

    frame["vol_ratio_raw"] = rolling_std_24 / (rolling_std_168 + 1e-6)
    frame["dist_ma200_raw"] = (
        (frame["Close"] - frame["Close"].rolling(200).mean())
        / (frame["Close"].rolling(200).std() + 1e-6)
    )
    frame["force_idx_raw"] = frame["Close"].diff(1) * frame["Volume"]
    frame["rsi_slope"] = frame["rsi_7_raw"].diff(3)
    frame["price_slope"] = frame["Close"].diff(3)
    frame["rsi_div_raw"] = ((frame["rsi_slope"] < 0) & (frame["price_slope"] > 0)).astype(int)

    for raw_column in (
        "rsi_5_raw",
        "rsi_7_raw",
        "rsi_14_raw",
        "vol_ratio_raw",
        "dist_ma200_raw",
        "force_idx_raw",
        "rsi_div_raw",
    ):
        frame[raw_column.replace("_raw", "")] = frame[raw_column].shift(1)

    frame["ret_1h_z"] = (frame["Close"].pct_change(1) / (rolling_std_24 + 1e-6)).shift(1)
    frame["ret_4h"] = frame["Close"].pct_change(4).shift(1)
    frame["rsi_z"] = (
        (
            frame["rsi_7_raw"] - frame["rsi_7_raw"].rolling(24).mean()
        ) / (frame["rsi_7_raw"].rolling(24).std() + 1e-6)
    ).shift(1)
    frame["z_score_24h"] = (
        (frame["Close"] - frame["Close"].rolling(24).mean())
        / (frame["Close"].rolling(24).std() + 1e-6)
    ).shift(1)
    frame["vol_adj_ret"] = (frame["Close"].pct_change() / (atr / frame["Close"] + 1e-6)).shift(1)
    frame["relative_vol"] = (frame["Volume"] / (frame["Volume"].rolling(24).mean() + 1e-6)).shift(1)
    frame["vol_pressure"] = frame["relative_vol"] / (frame["vol_ratio_raw"].shift(1) + 1e-6)
    frame["vol_spike"] = (frame["Volume"] > frame["Volume"].rolling(24).mean()).astype(int).shift(1)
    frame["retail_rsi"] = frame["rsi_z"] * frame["is_retail_window"]

    plus_dm = frame["High"].diff().clip(lower=0)
    minus_dm = frame["Low"].diff().clip(upper=0).abs()
    frame["trend_bias"] = ((plus_dm.rolling(14).mean() - minus_dm.rolling(14).mean()) / (atr + 1e-6)).shift(1)

    if include_target and not is_live_inference:
        frame["target"] = (frame["Close"].shift(-1) > frame["Close"]).astype(int)

    cols_to_drop = [column for column in frame.columns if "_raw" in column or "slope" in column]
    frame = frame.drop(columns=cols_to_drop)

    output_columns: list[str] = list(CANONICAL_CRYPTO_FEATURES)
    if include_target and not is_live_inference:
        output_columns.append("target")

    if is_live_inference:
        frame = calibrate_features(frame, asset)
    frame = frame[output_columns]
    frame = frame.dropna()
    return frame


def canonical_feature_names() -> list[str]:
    return list(CANONICAL_CRYPTO_FEATURES)


def feature_dict_from_row(row: pd.Series | pd.DataFrame | Iterable[float]) -> dict[str, float]:
    if isinstance(row, pd.DataFrame):
        if len(row) != 1:
            raise ValueError("Expected single-row DataFrame for feature serialization.")
        row = row.iloc[0]
    if isinstance(row, pd.Series):
        return {name: float(row[name]) for name in CANONICAL_CRYPTO_FEATURES}
    values = list(row)
    if len(values) != len(CANONICAL_CRYPTO_FEATURES):
        raise ValueError("Feature vector length does not match canonical feature contract.")
    return {name: float(value) for name, value in zip(CANONICAL_CRYPTO_FEATURES, values)}

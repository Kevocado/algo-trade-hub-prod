from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from shared.feature_engine import FeatureEngine

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


class CryptoFeatureEngine(FeatureEngine):
    domain = "crypto"

    def canonical_feature_names(self) -> list[str]:
        return list(CANONICAL_CRYPTO_FEATURES)

    def build_features(
        self,
        frame: pd.DataFrame,
        *,
        asset: str | None = None,
        is_live_inference: bool = False,
        include_target: bool = False,
    ) -> pd.DataFrame:
        import ta

        normalized = _require_ohlcv(frame)
        if is_live_inference:
            normalized = calibrate_features(normalized, asset)

        normalized["rsi_5_raw"] = ta.momentum.rsi(normalized["Close"], window=5)
        normalized["rsi_7_raw"] = ta.momentum.rsi(normalized["Close"], window=7)
        normalized["rsi_14_raw"] = ta.momentum.rsi(normalized["Close"], window=14)

        atr = ta.volatility.average_true_range(normalized["High"], normalized["Low"], normalized["Close"], window=14)
        rolling_std_24 = normalized["Close"].pct_change().rolling(window=24).std()
        rolling_std_168 = normalized["Close"].pct_change().rolling(window=168).std()

        normalized["hour"] = normalized.index.hour
        normalized["dayofweek"] = normalized.index.dayofweek
        normalized["is_weekend"] = (normalized["dayofweek"] >= 5).astype(int)
        normalized["is_retail_window"] = (normalized["dayofweek"] >= 4).astype(int)
        normalized["is_us_session"] = ((normalized["hour"] >= 14) & (normalized["hour"] <= 21)).astype(int)
        normalized["sin_hour"] = np.sin(2 * np.pi * normalized["hour"] / 24)
        normalized["cos_hour"] = np.cos(2 * np.pi * normalized["hour"] / 24)
        normalized["midnight_signal"] = (normalized["hour"] == 0).astype(int)

        normalized["vol_ratio_raw"] = rolling_std_24 / (rolling_std_168 + 1e-6)
        normalized["dist_ma200_raw"] = (
            (normalized["Close"] - normalized["Close"].rolling(200).mean())
            / (normalized["Close"].rolling(200).std() + 1e-6)
        )
        normalized["force_idx_raw"] = normalized["Close"].diff(1) * normalized["Volume"]
        normalized["rsi_slope"] = normalized["rsi_7_raw"].diff(3)
        normalized["price_slope"] = normalized["Close"].diff(3)
        normalized["rsi_div_raw"] = ((normalized["rsi_slope"] < 0) & (normalized["price_slope"] > 0)).astype(int)

        for raw_column in (
            "rsi_5_raw",
            "rsi_7_raw",
            "rsi_14_raw",
            "vol_ratio_raw",
            "dist_ma200_raw",
            "force_idx_raw",
            "rsi_div_raw",
        ):
            normalized[raw_column.replace("_raw", "")] = normalized[raw_column].shift(1)

        normalized["ret_1h_z"] = (normalized["Close"].pct_change(1) / (rolling_std_24 + 1e-6)).shift(1)
        normalized["ret_4h"] = normalized["Close"].pct_change(4).shift(1)
        normalized["rsi_z"] = (
            (
                normalized["rsi_7_raw"] - normalized["rsi_7_raw"].rolling(24).mean()
            ) / (normalized["rsi_7_raw"].rolling(24).std() + 1e-6)
        ).shift(1)
        normalized["z_score_24h"] = (
            (normalized["Close"] - normalized["Close"].rolling(24).mean())
            / (normalized["Close"].rolling(24).std() + 1e-6)
        ).shift(1)
        normalized["vol_adj_ret"] = (normalized["Close"].pct_change() / (atr / normalized["Close"] + 1e-6)).shift(1)
        normalized["relative_vol"] = (normalized["Volume"] / (normalized["Volume"].rolling(24).mean() + 1e-6)).shift(1)
        normalized["vol_pressure"] = normalized["relative_vol"] / (normalized["vol_ratio_raw"].shift(1) + 1e-6)
        normalized["vol_spike"] = (normalized["Volume"] > normalized["Volume"].rolling(24).mean()).astype(int).shift(1)
        normalized["retail_rsi"] = normalized["rsi_z"] * normalized["is_retail_window"]

        plus_dm = normalized["High"].diff().clip(lower=0)
        minus_dm = normalized["Low"].diff().clip(upper=0).abs()
        normalized["trend_bias"] = ((plus_dm.rolling(14).mean() - minus_dm.rolling(14).mean()) / (atr + 1e-6)).shift(1)

        if include_target and not is_live_inference:
            normalized["target"] = (normalized["Close"].shift(-1) > normalized["Close"]).astype(int)

        cols_to_drop = [column for column in normalized.columns if "_raw" in column or "slope" in column]
        normalized = normalized.drop(columns=cols_to_drop)

        output_columns: list[str] = list(CANONICAL_CRYPTO_FEATURES)
        if include_target and not is_live_inference:
            output_columns.append("target")

        normalized = normalized[output_columns]
        return normalized.dropna()


ENGINE = CryptoFeatureEngine()


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
    return ENGINE.build_features(
        df,
        asset=asset,
        is_live_inference=is_live_inference,
        include_target=include_target,
    )


def canonical_feature_names() -> list[str]:
    return ENGINE.canonical_feature_names()


def feature_dict_from_row(row: pd.Series | pd.DataFrame | Iterable[float]) -> dict[str, float]:
    return ENGINE.feature_dict_from_row(row)

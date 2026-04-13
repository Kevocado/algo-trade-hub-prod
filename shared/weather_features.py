from __future__ import annotations

import numpy as np
import pandas as pd

from shared.feature_engine import FeatureEngine

CANONICAL_WEATHER_FEATURES = [
    "forecast_hour",
    "ensemble_mean",
    "ensemble_std",
    "ensemble_skew",
    "temp_drift_from_avg",
    "threshold_gap",
    "zscore_to_threshold",
]


class WeatherFeatureEngine(FeatureEngine):
    domain = "weather"

    def canonical_feature_names(self) -> list[str]:
        return list(CANONICAL_WEATHER_FEATURES)

    def build_features(self, frame: pd.DataFrame, **kwargs) -> pd.DataFrame:
        required = ["ensemble_mean", "ensemble_std", "ensemble_skew", "temp_drift_from_avg", "forecast_hour", "threshold"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Weather feature builder requires columns: {missing}")

        normalized = frame.copy()
        for column in required:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        normalized["threshold_gap"] = normalized["ensemble_mean"] - normalized["threshold"]
        normalized["zscore_to_threshold"] = normalized["threshold_gap"] / (normalized["ensemble_std"].replace(0, np.nan) + 1e-6)
        normalized = normalized[CANONICAL_WEATHER_FEATURES].dropna()
        return normalized


ENGINE = WeatherFeatureEngine()


def build_features(frame: pd.DataFrame, **kwargs) -> pd.DataFrame:
    return ENGINE.build_features(frame, **kwargs)


def canonical_feature_names() -> list[str]:
    return ENGINE.canonical_feature_names()

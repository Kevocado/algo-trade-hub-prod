from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd


class FeatureEngine(ABC):
    """Canonical feature-builder contract shared across all asset domains."""

    domain: str

    @abstractmethod
    def canonical_feature_names(self) -> list[str]:
        """Return the ordered feature contract for the domain."""

    @abstractmethod
    def build_features(self, frame: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """Build a feature frame that conforms to the canonical contract."""

    def feature_dict_from_row(self, row: pd.Series | pd.DataFrame | Iterable[float]) -> dict[str, float]:
        feature_names = self.canonical_feature_names()
        if isinstance(row, pd.DataFrame):
            if len(row) != 1:
                raise ValueError("Expected single-row DataFrame for feature serialization.")
            row = row.iloc[0]
        if isinstance(row, pd.Series):
            return {name: float(row[name]) for name in feature_names}
        values = list(row)
        if len(values) != len(feature_names):
            raise ValueError("Feature vector length does not match the canonical feature contract.")
        return {name: float(value) for name, value in zip(feature_names, values)}

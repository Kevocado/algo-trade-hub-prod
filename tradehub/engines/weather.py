"""Weather engine (pure): P(Kalshi daily-high market resolves YES) from a model-blend forecast.

The settled high ~ Normal(mean(model highs) + bias, sqrt(sigma^2 + model disagreement)),
with bias/sigma fit walk-forward on past (forecast, actual) pairs.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

WEATHER_ENGINE_VERSION = "weather-v1"
TEMP_RESOLUTION = 1.0
MIN_SIGMA = 1.0


@dataclass(frozen=True)
class ErrorModel:
    bias: float
    sigma: float


DEFAULT_ERROR = ErrorModel(bias=0.0, sigma=2.5)


def fit_error_model(pairs: list[tuple[float, float]], min_pairs: int = 20) -> ErrorModel:
    if len(pairs) < min_pairs:
        return DEFAULT_ERROR
    errors = [actual - forecast for forecast, actual in pairs]
    bias = statistics.fmean(errors)
    sigma = statistics.stdev(errors)
    return ErrorModel(bias=bias, sigma=max(MIN_SIGMA, sigma))


def weather_prob(market: KalshiMarket, highs: list[float], error: ErrorModel) -> float:
    if not highs:
        raise ValueError(f"no forecast highs for {market.ticker}")
    mu = statistics.fmean(highs) + error.bias
    spread = statistics.pvariance(highs) if len(highs) > 1 else 0.0
    sigma = math.sqrt(error.sigma ** 2 + spread)
    return prob_in_interval(mu, sigma, yes_interval(market, TEMP_RESOLUTION))

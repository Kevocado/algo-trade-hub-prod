"""Weather engine (pure): P(Kalshi daily-high market resolves YES) from a model-blend forecast.

The settled high ~ Normal(mean(model highs) + bias, sigma), with bias/sigma fit
walk-forward on past (forecast, actual) pairs. Model disagreement is already
represented by the fitted error term and is not added again here.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

WEATHER_ENGINE_VERSION = "weather-v1"
TEMP_RESOLUTION = 1.0
MIN_SIGMA = 1.0
MIN_ERROR_PAIRS = 20


@dataclass(frozen=True)
class ErrorModel:
    bias: float
    sigma: float


DEFAULT_ERROR = ErrorModel(bias=0.0, sigma=2.5)
_LEAD_PATTERN = re.compile(r":lead(\d+)$")


def forecast_lead_days(observation: Observation) -> int:
    """Return a comparable lead rank; live and unlabelled values rank first."""
    match = _LEAD_PATTERN.search(observation.name)
    return int(match.group(1)) if match else 0


def select_forecast_observations(
    observations: Iterable[Observation],
    as_of: datetime,
) -> list[Observation]:
    """Select every model value from the smallest lead published by ``as_of``."""
    known = [observation for observation in observations if observation.published_at <= as_of]
    if not known:
        return []
    lead = min(forecast_lead_days(observation) for observation in known)
    return [observation for observation in known if forecast_lead_days(observation) == lead]


def fit_error_model(
    pairs: list[tuple[float, float]],
    min_pairs: int = MIN_ERROR_PAIRS,
    fallback: ErrorModel = DEFAULT_ERROR,
) -> ErrorModel:
    if len(pairs) < min_pairs:
        return fallback
    errors = [actual - forecast for forecast, actual in pairs]
    bias = statistics.fmean(errors)
    sigma = statistics.stdev(errors)
    return ErrorModel(bias=bias, sigma=max(MIN_SIGMA, sigma))


def walk_forward_error_model(
    actuals: Iterable[Observation],
    forecasts: Mapping[date, Sequence[Observation]],
    as_of: datetime,
    *,
    fallback: ErrorModel = DEFAULT_ERROR,
    min_pairs: int = MIN_ERROR_PAIRS,
) -> ErrorModel:
    """Fit forecast errors using only actuals and lead-matched forecasts known at ``as_of``."""
    pairs: list[tuple[float, float]] = []
    for actual in actuals:
        if actual.published_at > as_of:
            continue
        known = select_forecast_observations(
            forecasts.get(event_date(actual.name), ()),
            as_of,
        )
        if known:
            pairs.append((statistics.fmean(observation.value for observation in known), actual.value))
    return fit_error_model(pairs, min_pairs=min_pairs, fallback=fallback)


def weather_prob(market: KalshiMarket, highs: list[float], error: ErrorModel) -> float:
    if not highs:
        raise ValueError(f"no forecast highs for {market.ticker}")
    mu = statistics.fmean(highs) + error.bias
    # The fitted error sigma is the complete uncertainty term. Adding the
    # current model blend spread here would count model disagreement twice.
    sigma = error.sigma
    return prob_in_interval(mu, sigma, yes_interval(market, TEMP_RESOLUTION))

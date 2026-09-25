"""CPI nowcast engine (pure): P(Kalshi KXCPI / KXCPICORE 'more than X%' resolves YES).

The first-print MoM change ~ Normal(latest Cleveland Fed nowcast + bias, sigma), with
bias/sigma fit on past (nowcast at the same horizon before release, first print) pairs,
using only months whose print was public at decision time.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping

from tradehub.backtest.pit import Observation
from tradehub.data.cleveland_fed import MonthNowcast
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

CPI_ENGINE_VERSION = "cpi-v1"
CPI_CORE_ENGINE_VERSION = "cpi-core-v1"
CPI_SERIES = "KXCPI"
# Kalshi series -> (Cleveland Fed series kind, engine_version). Both write engine "cpi_nowcast";
# the version keeps headline and core in separate track records (step 2b keys on engine_version).
CPI_TARGETS = {"KXCPI": ("headline", CPI_ENGINE_VERSION), "KXCPICORE": ("core", CPI_CORE_ENGINE_VERSION)}
CPI_RESOLUTION = 0.1
CLOSE_TO_RELEASE = timedelta(minutes=5)  # Kalshi closes 08:25 ET, BLS publishes 08:30 ET
MIN_CPI_SIGMA = 0.05
CPI_TRAIN_MONTHS = 24
CPI_MIN_TRAIN = 12


@dataclass(frozen=True)
class CpiErrorModel:
    bias: float
    sigma: float


DEFAULT_CPI_ERROR = CpiErrorModel(bias=0.0, sigma=0.15)


def latest_nowcast(month: MonthNowcast | None, as_of: datetime) -> Observation | None:
    if month is None:
        return None
    known = [o for o in month.path if o.published_at <= as_of]
    return known[-1] if known else None


def training_pairs(
    history: Mapping[date, MonthNowcast], as_of: datetime, horizon: timedelta
) -> list[tuple[Observation, Observation]]:
    """(nowcast, first print) for every month released by `as_of`.

    The nowcast is the one known `horizon` before that month's market close, so the
    error distribution matches the horizon of the decision being made.
    """
    pairs = []
    for month in history.values():
        actual = month.actual
        if actual is None or actual.published_at > as_of:
            continue
        nowcast = latest_nowcast(month, actual.published_at - CLOSE_TO_RELEASE - horizon)
        if nowcast is not None:
            pairs.append((nowcast, actual))
    return sorted(pairs, key=lambda pair: pair[1].published_at)


def fit_cpi_error(
    pairs: list[tuple[Observation, Observation]],
    *,
    window: int = CPI_TRAIN_MONTHS,
    min_points: int = CPI_MIN_TRAIN,
    use_bias: bool = False,
) -> CpiErrorModel:
    recent = pairs[-window:]
    if len(recent) < min_points:
        return DEFAULT_CPI_ERROR
    errors = [actual.value - nowcast.value for nowcast, actual in recent]
    bias = statistics.fmean(errors) if use_bias else 0.0
    sigma = statistics.pstdev(errors, mu=bias)
    return CpiErrorModel(bias=bias, sigma=max(MIN_CPI_SIGMA, sigma))


def cpi_prob(market: KalshiMarket, nowcast: float, model: CpiErrorModel) -> float:
    return prob_in_interval(nowcast + model.bias, model.sigma, yes_interval(market, CPI_RESOLUTION))

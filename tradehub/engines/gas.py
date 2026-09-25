"""Gas engine (pure): P(AAA US average > strike) from last AAA value + lagged RBOB pass-through.

Retail follows wholesale RBOB with a 1-3 week lag, so the day-over-day AAA change
is modeled as alpha + beta * (RBOB change over the last RBOB_WINDOW closes).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

GAS_ENGINE_VERSION = "gas-v1"
GAS_SERIES = "KXAAAGASD"
GAS_RESOLUTION = 0.0001
MIN_GAS_SIGMA = 0.002
RBOB_WINDOW = 5


@dataclass(frozen=True)
class GasModel:
    alpha: float
    beta: float
    sigma: float


DEFAULT_GAS = GasModel(alpha=0.0, beta=0.0, sigma=0.01)


def _contract_id(observation: Observation) -> str | None:
    parts = observation.name.split(":")
    if len(parts) != 3 or not parts[1]:
        return None
    return parts[1]


def _observation_date(observation: Observation) -> date:
    return date.fromisoformat(observation.name.rsplit(":", 1)[1])


def rbob_change_window(
    closes: list[Observation],
    as_of: datetime,
    window: int = RBOB_WINDOW,
    *,
    roll_dates: list[date] | None = None,
) -> tuple[float, tuple[Observation, ...]] | None:
    """Return a same-contract RBOB change and its exact six-observation window."""
    known = sorted((o for o in closes if o.published_at <= as_of), key=lambda o: o.published_at)
    if len(known) < window + 1:
        return None
    sample = tuple(known[-(window + 1):])
    contracts = {_contract_id(observation) for observation in sample}
    if any(contract is None for contract in contracts) or len(contracts) != 1:
        return None
    if roll_dates:
        first_day = _observation_date(sample[0])
        last_day = _observation_date(sample[-1])
        if any(first_day < roll_day <= last_day for roll_day in roll_dates):
            return None
    return sample[-1].value - sample[0].value, sample


def rbob_change(
    closes: list[Observation],
    as_of: datetime,
    window: int = RBOB_WINDOW,
    *,
    roll_dates: list[date] | None = None,
) -> float | None:
    result = rbob_change_window(closes, as_of, window, roll_dates=roll_dates)
    return None if result is None else result[0]


def gas_training_pairs(
    aaa: list[Observation],
    rbob: list[Observation],
    window: int = RBOB_WINDOW,
    *,
    roll_dates: list[date] | None = None,
) -> list[tuple[float, float, datetime]]:
    ordered = sorted(aaa, key=lambda o: event_date(o.name))
    pairs = []
    for prev, cur in zip(ordered, ordered[1:]):
        if (event_date(cur.name) - event_date(prev.name)).days != 1:
            continue
        x = rbob_change(rbob, prev.published_at, window, roll_dates=roll_dates)
        if x is None:
            continue
        pairs.append((x, cur.value - prev.value, cur.published_at))
    return pairs


def fit_gas_model(pairs: list[tuple[float, float]], min_points: int = 30) -> GasModel:
    if len(pairs) < min_points:
        return DEFAULT_GAS
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in pairs) / sxx if sxx > 0 else 0.0
    alpha = my - beta * mx
    residuals = [y - (alpha + beta * x) for x, y in pairs]
    sigma = math.sqrt(sum(r * r for r in residuals) / (len(pairs) - 2))
    return GasModel(alpha=alpha, beta=beta, sigma=max(MIN_GAS_SIGMA, sigma))


def gas_prob(market: KalshiMarket, last_value: float, horizon_days: int, rbob_x: float | None, model: GasModel) -> float:
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be >= 1, got {horizon_days}")
    x = 0.0 if rbob_x is None else rbob_x
    mu = last_value + horizon_days * (model.alpha + model.beta * x)
    sigma = model.sigma * math.sqrt(horizon_days)
    return prob_in_interval(mu, sigma, yes_interval(market, GAS_RESOLUTION))

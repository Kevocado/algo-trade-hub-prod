"""Gas engine (pure): P(AAA US average > strike) from last AAA value + lagged RBOB pass-through.

Retail follows wholesale RBOB with a 1-3 week lag, so the day-over-day AAA change
is modeled as alpha + beta * (RBOB change over the last RBOB_WINDOW closes).

`gas-v2` fixes the regressor's train/serve skew: `gas-v1` computed the training feature at the
previous day's AAA print time (before that day's RBOB close), while inference uses it at the
decision time (close minus lead, after the close), so beta was fit on a feature one RBOB session
stale relative to the one applied. Both now use `decision_time`.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

GAS_ENGINE_VERSION = "gas-v2"
GAS_SERIES = "KXAAAGASD"
GAS_RESOLUTION = 0.0001
MIN_GAS_SIGMA = 0.002
RBOB_WINDOW = 5
# Kalshi's last trading time is 11:59 PM ET the day before the reference day (contract terms).
GAS_DECISION_LEAD = timedelta(hours=2)
_EASTERN = ZoneInfo("America/New_York")
_MARKET_CLOSE = time(23, 59)


@dataclass(frozen=True)
class GasModel:
    alpha: float
    beta: float
    sigma: float


DEFAULT_GAS = GasModel(alpha=0.0, beta=0.0, sigma=0.01)


def market_close(day: date) -> datetime:
    """When the market that settles on `day` stops trading: 11:59 PM ET the day before."""
    return datetime.combine(day - timedelta(days=1), _MARKET_CLOSE, _EASTERN)


def decision_time(day: date, lead: timedelta = GAS_DECISION_LEAD) -> datetime:
    """When the model decides the market that settles on `day`: its close minus `lead`.

    The RBOB feature must be read here (in training and at inference alike), so it reflects the same
    RBOB session. Any lead under ~6h lands after the previous day's 18:00 ET RBOB close and before
    that day's, so the window is the same; a lead past ~6h reads one session earlier.
    """
    return market_close(day) - lead


def _contract_id(observation: Observation) -> str | None:
    parts = observation.name.split(":")
    if len(parts) != 3 or not parts[1] or parts[1].lower() == "unknown":
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
        if any(first_day < roll_day < last_day for roll_day in roll_dates):
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
    lead: timedelta = GAS_DECISION_LEAD,
) -> list[tuple[float, float, datetime]]:
    ordered = sorted(aaa, key=lambda o: event_date(o.name))
    pairs = []
    for prev, cur in zip(ordered, ordered[1:]):
        if (event_date(cur.name) - event_date(prev.name)).days != 1:
            continue
        x = rbob_change(rbob, decision_time(event_date(cur.name), lead), window, roll_dates=roll_dates)
        if x is None:
            continue
        pairs.append((x, cur.value - prev.value, cur.published_at))
    return pairs


def aaa_daily_changes(aaa: list[Observation]) -> list[float]:
    ordered = sorted(aaa, key=lambda observation: event_date(observation.name))
    return [
        current.value - previous.value
        for previous, current in zip(ordered, ordered[1:])
        if (event_date(current.name) - event_date(previous.name)).days == 1
    ]


def fit_gas_model(
    pairs: list[tuple[float, float]],
    min_points: int = 30,
    *,
    aaa: list[Observation] | None = None,
) -> GasModel:
    if len(pairs) < min_points:
        changes = aaa_daily_changes(aaa or [])
        if len(changes) < min_points:
            return DEFAULT_GAS
        return GasModel(
            alpha=statistics.fmean(changes),
            beta=0.0,
            sigma=max(MIN_GAS_SIGMA, statistics.stdev(changes)),
        )
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

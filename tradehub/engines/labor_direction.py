"""UNRATE and JOLTS-quits direction (v2 spec §5), pure: the payroll ridge pattern on new targets.

Target, exactly: "up" iff the FIRST PRINT of month m, minus month m-1 as printed in that same
release, is at least one printed unit (UNRATE +0.1pp; quits +1k). Self-settling from FRED
vintages; no consensus feed. The fit is `fit_payroll_model` on the same point-in-time
`labor_features`, walk-forward (months strictly before m), with a floor on sigma in the target's
own units. P(up) = P(Normal(mu, sigma) > half a printed unit).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from tradehub.engines.labor import (
    CORE_FEATURES,
    MIN_TRAIN_ROWS,
    LaborFeatures,
    PayrollModel,
    Vintage,
    _change,
    fit_payroll_model,
    is_trainable,
    training_rows,
)
from tradehub.markets import PROBABILITY_EPSILON

UNRATE_UP = 0.05  # UNRATE prints to 0.1pp, so a first-print change of +0.1 or more is "up"
QUITS_UP = 0.5  # JTSQUL prints in whole thousands
MIN_UNRATE_SIGMA = 0.05
MIN_QUITS_SIGMA = 20.0
QUITS_FEATURES = CORE_FEATURES + ("quits_last",)
CLIMATOLOGY_BOUNDS = (0.02, 0.98)


@dataclass(frozen=True)
class DirectionNowcast:
    month: date
    mu: float
    sigma: float
    prob_up: float
    climatology: float
    model: PayrollModel


def up_probability(mu: float, sigma: float, threshold: float) -> float:
    p = 0.5 * math.erfc((threshold - mu) / (sigma * math.sqrt(2.0)))
    return min(1.0 - PROBABILITY_EPSILON, max(PROBABILITY_EPSILON, p))


def climatology(prints: Mapping[date, float], before: date, threshold: float) -> float | None:
    """Share of trainable months before `before` whose first-print change was up; None if too few."""
    past = [v for m, v in prints.items() if m < before and is_trainable(m)]
    if len(past) < MIN_TRAIN_ROWS:
        return None
    lo, hi = CLIMATOLOGY_BOUNDS
    return min(hi, max(lo, sum(v > threshold for v in past) / len(past)))


def with_quits_feature(feats: LaborFeatures, quits_vintage: Vintage | None) -> LaborFeatures | None:
    """Add the latest quits change known at the same month-end vintage (JOLTS lags ~5 weeks)."""
    if not quits_vintage:
        return None
    change = _change(quits_vintage, max(quits_vintage))
    if change is None:
        return None
    return replace(feats, values={**feats.values, "quits_last": change})


def direction_nowcast(
    table: Mapping[date, LaborFeatures],
    prints: Mapping[date, float],
    month: date,
    *,
    threshold: float,
    min_sigma: float,
    features: Sequence[str] = CORE_FEATURES,
) -> DirectionNowcast | None:
    """Walk-forward P(up) for `month`; None when its features or enough history are missing."""
    feats = table.get(month)
    base = climatology(prints, month, threshold)
    if feats is None or base is None:
        return None
    model = fit_payroll_model(training_rows(table, prints, before=month), features, min_sigma=min_sigma)
    mu = model.predict(feats.values)
    return DirectionNowcast(month, mu, model.sigma, up_probability(mu, model.sigma, threshold), base, model)

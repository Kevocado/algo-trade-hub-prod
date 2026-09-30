"""Monthly-series direction features and training set (v2 spec §8, housing).

Same walk-forward discipline as `spy_direction`: the row for month t uses levels strictly before t, the
label is `level[t] > level[t-1]`, and a model for month m is trained only on months before m. Fitting and
the hashed artifact store are shared (`tradehub.models.spy_direction.model`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from itertools import pairwise

FEATURES = ("g1", "g3", "g6", "g12", "accel")
MIN_HISTORY = 14  # levels needed before a month to compute every feature


def _add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def feature_row(levels: list[float]) -> dict[str, float] | None:
    """Features from `levels` (oldest first), all known before the target month."""
    if len(levels) < MIN_HISTORY:
        return None
    def g(k: int) -> float:
        return math.log(levels[-1] / levels[-1 - k])
    g1, g3 = g(1), g(3)
    return {"g1": g1, "g3": g3, "g6": g(6), "g12": g(12), "accel": g1 - g3 / 3.0}


def features_for(levels: Mapping[date, float], month: date) -> tuple[dict[str, float], date] | None:
    """(features, date of the newest level used) for target `month`; None without enough history."""
    months = sorted(m for m in levels if m < month)
    row = feature_row([levels[m] for m in months])
    return (row, months[-1]) if row is not None else None


def training_set(levels: Mapping[date, float], before: date) -> tuple[list[list[float]], list[int], list[date]]:
    """One row per month t < `before`: features from levels before t, label = level[t] > level[t-1]."""
    months = sorted(m for m in levels if m < before)
    values = [levels[m] for m in months]
    x, y, used = [], [], []
    for i in range(MIN_HISTORY, len(months)):
        row = feature_row(values[:i])
        if row is None:
            continue
        x.append([row[f] for f in FEATURES])
        y.append(int(values[i] > values[i - 1]))
        used.append(months[i])
    return x, y, used


def climatology(levels: Mapping[date, float], before: date, window: int = 120, minimum: int = 60) -> float | None:
    """Share of the last `window` month-over-month changes before `before` that were up; clamped away from 0/1."""
    months = sorted(m for m in levels if m < before)[-(window + 1):]
    if len(months) - 1 < minimum:
        return None
    ups = sum(levels[b] > levels[a] for a, b in pairwise(months))
    return min(0.98, max(0.02, ups / (len(months) - 1)))

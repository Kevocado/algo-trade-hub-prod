"""Price-derived features only (spec §7), computed from closes strictly before the target session.

FRED SP500 carries no volume and no breadth series is freely reachable (see the sentiment meter), so
v1 is price-only; that is a narrower feature set than the spec allows, never a wider one.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from datetime import date

FEATURES = ("r1", "r5", "r20", "vol20", "ma50_gap", "ma200_gap")
MIN_HISTORY = 201  # closes needed before a session to compute every feature


def _ret(closes: list[float], k: int) -> float:
    return math.log(closes[-1] / closes[-1 - k])


def feature_row(history: list[float]) -> dict[str, float] | None:
    """Features from `history` (oldest first), all of which is known before the target session."""
    if len(history) < MIN_HISTORY:
        return None
    daily = [math.log(b / a) for a, b in zip(history[-21:-1], history[-20:])]
    return {
        "r1": _ret(history, 1),
        "r5": _ret(history, 5),
        "r20": _ret(history, 20),
        "vol20": statistics.pstdev(daily),
        "ma50_gap": history[-1] / statistics.fmean(history[-50:]) - 1.0,
        "ma200_gap": history[-1] / statistics.fmean(history[-200:]) - 1.0,
    }


def features_for(closes: Mapping[date, float], day: date) -> tuple[dict[str, float], date] | None:
    """(features, date of the newest close used) for session `day`, or None without enough history."""
    days = sorted(d for d in closes if d < day)
    row = feature_row([closes[d] for d in days])
    return (row, days[-1]) if row is not None else None


def training_set(closes: Mapping[date, float], before: date) -> tuple[list[list[float]], list[int], list[date]]:
    """Rows for every session t < `before`: features from closes before t, label = close(t) > close(t-1)."""
    days = sorted(d for d in closes if d < before)
    values = [closes[d] for d in days]
    x, y, used = [], [], []
    for i in range(MIN_HISTORY, len(days)):
        row = feature_row(values[:i])
        if row is None:
            continue
        x.append([row[f] for f in FEATURES])
        y.append(int(values[i] > values[i - 1]))
        used.append(days[i])
    return x, y, used

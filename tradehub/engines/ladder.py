"""Kalshi 'greater than k' ladders as a probability distribution, plus ladder scoring (pure).

A ladder is a list of (cut, P(X > cut)) points. Mid prices across a ladder
are not always monotone, so the implied survival curve is made
non-increasing with pool-adjacent-violators before it is summarized.
"""

from __future__ import annotations

import math
import statistics
from typing import Sequence

MAX_SPREAD = 0.15  # a strike whose yes bid/ask spread is wider than this carries no price information

Ladder = list[tuple[float, float]]  # (cut, P(X > cut)), cuts ascending


def usable_mid(yes_bid: float | None, yes_ask: float | None, max_spread: float = MAX_SPREAD) -> float | None:
    if yes_bid is None or yes_ask is None or yes_ask - yes_bid > max_spread:
        return None
    return (yes_bid + yes_ask) / 2.0


def isotonic_survival(points: Sequence[tuple[float, float]]) -> Ladder:
    """Sort by cut and force P(X > cut) non-increasing (equal-weight pool adjacent violators)."""
    ordered = sorted(points)
    blocks: list[list[float]] = []  # [sum, count]
    for _, prob in ordered:
        blocks.append([min(1.0, max(0.0, prob)), 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    fitted: list[float] = []
    for total, count in blocks:
        fitted.extend([total / count] * int(count))
    return [(cut, prob) for (cut, _), prob in zip(ordered, fitted)]


def _typical_gap(ladder: Ladder) -> float:
    gaps = [b[0] - a[0] for a, b in zip(ladder, ladder[1:]) if b[0] > a[0]]
    return statistics.median(gaps) if gaps else 0.0


def implied_mean(ladder: Ladder) -> float:
    """Mean of the step distribution: bin masses at bin midpoints, tails half a typical gap outside."""
    if not ladder:
        raise ValueError("empty ladder")
    gap = _typical_gap(ladder)
    mean = (1.0 - ladder[0][1]) * (ladder[0][0] - gap / 2.0)
    for (lo, p_lo), (hi, p_hi) in zip(ladder, ladder[1:]):
        mean += (p_lo - p_hi) * (lo + hi) / 2.0
    mean += ladder[-1][1] * (ladder[-1][0] + gap / 2.0)
    return mean


def implied_median(ladder: Ladder) -> float:
    """Where the survival curve crosses 0.5 (linear between cuts, clamped to the ladder's ends)."""
    if not ladder:
        raise ValueError("empty ladder")
    if ladder[0][1] <= 0.5:
        return ladder[0][0]
    for (lo, p_lo), (hi, p_hi) in zip(ladder, ladder[1:]):
        if p_lo >= 0.5 >= p_hi:
            return lo if p_lo == p_hi else lo + (p_lo - 0.5) / (p_lo - p_hi) * (hi - lo)
    return ladder[-1][0]


def normal_ladder(cuts: Sequence[float], mu: float, sigma: float) -> Ladder:
    # Do not use prob_in_interval here: its 1e-4 probability floor is meant for
    # tradable YES probabilities, not an unbounded survival curve.
    return [(cut, 0.5 * math.erfc((cut - mu) / (sigma * math.sqrt(2.0)))) for cut in sorted(cuts)]


def ladder_brier(ladder: Ladder, outcome: float) -> float:
    """Mean Brier score over the ladder's strikes against the settled value."""
    if not ladder:
        raise ValueError("empty ladder")
    return sum((p - (1.0 if outcome > cut else 0.0)) ** 2 for cut, p in ladder) / len(ladder)


def ladder_crps(ladder: Ladder, outcome: float) -> float:
    """CRPS restricted to the ladder: sum of per-strike Brier terms times each strike's spacing.

    Same units as the cuts, so ours and Kalshi's are comparable when scored on the same cuts.
    """
    if not ladder:
        raise ValueError("empty ladder")
    cuts = [cut for cut, _ in ladder]
    gap = _typical_gap(ladder) or 1.0
    edges = [cuts[0] - gap / 2.0] + [(a + b) / 2.0 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + gap / 2.0]
    return sum((p - (1.0 if outcome > cut else 0.0)) ** 2 * (edges[i + 1] - edges[i])
               for i, (cut, p) in enumerate(ladder))

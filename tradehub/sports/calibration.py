"""Per-model post-hoc calibration for sports engines, fitted walk-forward on settled results.

Protocol (docs/superpowers/plans/2026-10-18-improve-the-models.md):
1. Frozen before looking: state change and metric before running anything.
2. Time split: develop on earlier 70% of history, judge once on later 30%.
3. Count variants tried and report the count next to the result.
4. New version beside the old: ships as `<name>_cal` in the journal, runs live next to old.
5. Stop rule: if out-of-sample gap does not clear 2 SE better than old version, stop.
6. Free data only.

Metric: Brier gap vs the Kalshi price on the same contracts, with a standard error.
NEGATIVE gap = better than baseline (our squared error < baseline's).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from scipy.optimize import minimize_scalar

from tradehub.journal.store import FORECASTS, fetch_settlements, select_all

log = logging.getLogger(__name__)

# How many calibration variants we attempt. Reported alongside the result.
N_VARIANTS_TRIED = 4

# Time split: earlier 70% for fitting, later 30% for judgement.
TRAIN_FRACTION = 0.70

# Two standard errors is the stop rule threshold.
DISTINCT_SE = 2.0


def _logit(p: float) -> float:
    """logit(p) = log(p / (1-p)), clamped to avoid infinities at 0 and 1."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Inverse of logit."""
    return 1.0 / (1.0 + math.exp(-x))


def brier_score(pairs: list[tuple[float, bool]]) -> float | None:
    """Mean squared error of probability predictions against binary outcomes."""
    if not pairs:
        return None
    return sum((p - float(h)) ** 2 for p, h in pairs) / len(pairs)


def brier_se(pairs: list[tuple[float, bool]], brier: float | None = None) -> float | None:
    """Standard error of the Brier score: sqrt(var((p-h)^2) / n)."""
    if not pairs or brier is None:
        return None
    n = len(pairs)
    if n < 2:
        return None
    sq_errors = [(p - float(h)) ** 2 for p, h in pairs]
    var = sum((e - brier) ** 2 for e in sq_errors) / (n - 1)
    return math.sqrt(var / n)


@dataclass
class CalibrationFit:
    """Result of fitting one calibration variant.

    `name` identifies the variant (for the variant count report).
    `params` is the fitted parameter tuple, interpreted by `apply_calibration`.
    `train_brier` / `test_brier` are Brier scores on train / test splits.
    `test_n` is the number of test pairs.
    """

    name: str
    params: tuple[float, ...]
    train_brier: float | None
    test_brier: float | None
    test_n: int
    test_se: float | None


def _fit_platt(train: list[tuple[float, bool]]) -> tuple[float, float] | None:
    """Platt scaling: fit a + b * logit(p) -> logit(calibrated_p).

    Coordinate descent on logistic loss: alternate between intercept (a) and
    slope (b), each optimized with scipy's bounded 1-D search."""
    if len(train) < 5:
        return None

    base_rate = sum(float(h) for _, h in train) / len(train)
    base_logit = _logit(base_rate)

    def neg_log_likelihood(params: tuple[float, float]) -> float:
        a, b = params
        if abs(b) > 50:
            return 1e6
        total = 0.0
        for p, h in train:
            z = a + b * _logit(p)
            z = min(max(z, -50), 50)
            q = 1.0 / (1.0 + math.exp(-z))
            q = min(max(q, 1e-9), 1.0 - 1e-9)
            total += float(h) * math.log(q) + (1.0 - float(h)) * math.log(1 - q)
        return -total

    a, b = base_logit, 1.0
    for _ in range(20):
        res_a = minimize_scalar(
            lambda av: neg_log_likelihood((av, b)),
            bounds=(base_logit - 5, base_logit + 5), method="bounded",
        )
        a = res_a.x
        res_b = minimize_scalar(
            lambda bv: neg_log_likelihood((a, bv)),
            bounds=(-10, 10), method="bounded",
        )
        b = res_b.x
    return (a, b)


def _fit_isotonic(train: list[tuple[float, bool]]) -> list[tuple[float, float]] | None:
    """Isotonic regression via Pool Adjacent Violators Algorithm.

    Returns a sorted list of (prob_boundary, calibrated_prob) knots for
    piecewise-linear interpolation."""
    if len(train) < 5:
        return None

    points = sorted((p, float(h)) for p, h in train)
    blocks: list[list[tuple[float, float]]] = [[points[0]]]
    for p, h in points[1:]:
        blocks.append([(p, h)])
        while len(blocks) >= 2:
            prev = blocks[-2]
            curr = blocks[-1]
            prev_mean = sum(h for _, h in prev) / len(prev)
            curr_mean = sum(h for _, h in curr) / len(curr)
            if prev_mean <= curr_mean:
                break
            blocks[-2:] = [prev + curr]

    knots: list[tuple[float, float]] = []
    for block in blocks:
        p_mean = sum(p for p, _ in block) / len(block)
        h_mean = sum(h for _, h in block) / len(block)
        knots.append((p_mean, h_mean))
    return knots


def _fit_linear_shrinkage(train: list[tuple[float, bool]]) -> tuple[float, float] | None:
    """Linear shrinkage: calibrated_p = base_rate + shrinkage * (p - base_rate).

    Fit shrinkage by least squares on training pairs, clamped to [0, 2]."""
    if len(train) < 5:
        return None
    base_rate = sum(float(h) for _, h in train) / len(train)
    xs = [p - base_rate for p, _ in train]
    ys = [float(h) - base_rate for _, h in train]
    denom = sum(x * x for x in xs)
    if denom == 0:
        return (base_rate, 0.0)
    shrinkage = sum(x * y for x, y in zip(xs, ys)) / denom
    shrinkage = min(max(shrinkage, 0.0), 2.0)
    return (base_rate, shrinkage)


def _apply_platt(p: float, params: tuple[float, float]) -> float:
    a, b = params
    return _sigmoid(a + b * _logit(p))


def _apply_isotonic(p: float, knots: list[tuple[float, float]]) -> float:
    if not knots:
        return p
    if p <= knots[0][0]:
        return knots[0][1]
    if p >= knots[-1][0]:
        return knots[-1][1]
    for i in range(len(knots) - 1):
        p0, h0 = knots[i]
        p1, h1 = knots[i + 1]
        if p0 <= p <= p1:
            if p1 == p0:
                return h0
            return h0 + (h1 - h0) * (p - p0) / (p1 - p0)
    return knots[-1][1]


def _apply_linear_shrinkage(p: float, params: tuple[float, float]) -> float:
    base_rate, shrinkage = params
    return min(max(base_rate + shrinkage * (p - base_rate), 0.0), 1.0)


def fit_all_variants(train: list[tuple[float, bool]]) -> list[CalibrationFit]:
    """Fit all N_VARIANTS_TRIED calibration variants on training pairs.

    Returns a list of CalibrationFit, one per variant. Variant 0 is always
    identity (no calibration) - the baseline to beat."""
    fits: list[CalibrationFit] = []

    # Variant 0: Identity (no calibration)
    fits.append(CalibrationFit(
        name="identity",
        params=(),
        train_brier=brier_score(train),
        test_brier=None,
        test_n=0,
        test_se=None,
    ))

    # Variant 1: Platt scaling
    platt_params = _fit_platt(train)
    if platt_params is not None:
        fits.append(CalibrationFit(
            name="platt",
            params=platt_params,
            train_brier=brier_score([(_apply_platt(p, platt_params), h) for p, h in train]),
            test_brier=None,
            test_n=0,
            test_se=None,
        ))

    # Variant 2: Isotonic regression
    isotonic_knots = _fit_isotonic(train)
    if isotonic_knots is not None:
        fits.append(CalibrationFit(
            name="isotonic",
            params=isotonic_knots,
            train_brier=brier_score([(_apply_isotonic(p, isotonic_knots), h) for p, h in train]),
            test_brier=None,
            test_n=0,
            test_se=None,
        ))

    # Variant 3: Linear shrinkage toward base rate
    shrinkage_params = _fit_linear_shrinkage(train)
    if shrinkage_params is not None:
        fits.append(CalibrationFit(
            name="shrinkage",
            params=shrinkage_params,
            train_brier=brier_score([(_apply_linear_shrinkage(p, shrinkage_params), h) for p, h in train]),
            test_brier=None,
            test_n=0,
            test_se=None,
        ))

    return fits


def evaluate_fit(fit: CalibrationFit, test: list[tuple[float, bool]]) -> CalibrationFit:
    """Evaluate a fitted calibration variant on test pairs. Returns updated fit."""
    name = fit.name
    params = fit.params
    if name == "identity":
        calibrated = [(p, h) for p, h in test]
    elif name == "platt":
        calibrated = [(_apply_platt(p, params), h) for p, h in test]
    elif name == "isotonic":
        calibrated = [(_apply_isotonic(p, params), h) for p, h in test]
    elif name == "shrinkage":
        calibrated = [(_apply_linear_shrinkage(p, params), h) for p, h in test]
    else:
        calibrated = [(p, h) for p, h in test]

    tb = brier_score(calibrated)
    se = brier_se(calibrated, tb)
    return CalibrationFit(
        name=fit.name, params=fit.params,
        train_brier=fit.train_brier,
        test_brier=tb, test_n=len(calibrated), test_se=se,
    )


def time_split(pairs: list[tuple[float, bool]], ids: list[int]) -> tuple[list[tuple[float, bool]], list[tuple[float, bool]]]:
    """Split pairs into train (earlier 70%) and test (later 30%) by id order.

    `ids` are database ids used as a time proxy. Pairs are sorted by id ascending
    before splitting."""
    combined = sorted(zip(ids, pairs), key=lambda x: x[0])
    split_idx = int(len(combined) * TRAIN_FRACTION)
    train_pairs = [p for _, p in combined[:split_idx]]
    test_pairs = [p for _, p in combined[split_idx:]]
    return train_pairs, test_pairs


def calibrate_engine(engine: str, kind: str, pairs_with_ids: list[tuple[int, float, bool]]) -> dict | None:
    """Run the full calibration protocol for one engine+kind.

    `pairs_with_ids` is a list of (id, probability, hit) tuples, one per settled result.

    Returns a dict with the best variant, its test Brier score, SE, and the gap
    vs identity (no calibration) on the test set. Returns None if there are
    insufficient results (< 10 total, or < 5 in either split).
    """
    if len(pairs_with_ids) < 10:
        return None

    ids = [pid for pid, _, _ in pairs_with_ids]
    pairs = [(p, h) for _, p, h in pairs_with_ids]

    train_pairs, test_pairs = time_split(pairs, ids)
    if len(train_pairs) < 5 or len(test_pairs) < 3:
        return None

    # Fit all variants on training data
    fits = fit_all_variants(train_pairs)

    # Evaluate each on test data
    evaluated = [evaluate_fit(f, test_pairs) for f in fits]

    # Pick best variant by test Brier (None sorts last)
    best = min(
        (f for f in evaluated if f.test_brier is not None),
        key=lambda f: f.test_brier,
        default=None,
    )
    if best is None:
        return None

    # Identity fit for gap comparison
    identity = next((f for f in evaluated if f.name == "identity"), None)

    # Brier gap: calibrated - identity (negative = calibration is better)
    gap = None
    gap_se = None
    if best.test_brier is not None and identity is not None and identity.test_brier is not None:
        gap = best.test_brier - identity.test_brier
        if best.test_se is not None and identity.test_se is not None:
            gap_se = math.sqrt(best.test_se ** 2 + identity.test_se ** 2)

    # Stop rule: does the best variant clear 2 SE better than identity on test?
    stop = False
    stop_reason = ""
    if gap is not None and gap_se is not None and gap_se > 0:
        se_clear = abs(gap) / gap_se
        if se_clear < DISTINCT_SE:
            stop = True
            stop_reason = f"gap {gap:+.4f} is {se_clear:.1f} SE, below {DISTINCT_SE} SE threshold"
        else:
            direction = "better" if gap < 0 else "worse"
            stop_reason = f"gap {gap:+.4f} is {se_clear:.1f} SE ({direction})"
    elif gap is not None:
        stop_reason = f"gap {gap:+.4f}, no SE available"

    return {
        "engine": engine,
        "kind": kind,
        "n_variants_tried": N_VARIANTS_TRIED,
        "train_n": len(train_pairs),
        "test_n": len(test_pairs),
        "best_variant": best.name,
        "train_brier": best.train_brier,
        "test_brier": best.test_brier,
        "test_se": best.test_se,
        "identity_test_brier": identity.test_brier if identity else None,
        "gap": gap,
        "gap_se": gap_se,
        "stop": stop,
        "stop_reason": stop_reason,
        "params": best.params,
    }


def load_settled_pairs(supa, engine: str) -> dict[str, list[tuple[int, float, bool]]]:
    """Load settled (id, probability, hit) pairs per kind for one engine.

    Reads from journal_forecasts + journal_settlements, ordered by id (time proxy).
    Returns {kind: [(id, probability, hit), ...]}."""
    from tradehub.sports.journal_ledger import _forecaster, HUB_FEED_VERSION

    result: dict[str, list[tuple[int, float, bool]]] = {}
    for kind in ("winner", "spread", "total"):
        sport = engine.replace("sports_", "")
        name = _forecaster(sport, kind)
        forecasts = select_all(
            supa, FORECASTS,
            lambda q, n=name: q.eq("forecaster", n).eq("forecaster_version", HUB_FEED_VERSION),
            ("id", "target", "probability",))
        if not forecasts:
            continue
        outcomes = fetch_settlements(supa, [f["target"] for f in forecasts])
        rows = []
        for f in forecasts:
            target = f["target"]
            if target not in outcomes:
                continue
            prob = f.get("probability")
            if prob is None:
                continue
            rows.append((int(f["id"]), float(prob), bool(outcomes[target])))
        if rows:
            result[kind] = rows
    return result
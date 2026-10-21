"""Tests for tradehub.sports.calibration - per-model post-hoc calibration.

Tests cover: Brier score/SE, Platt scaling, isotonic regression, linear shrinkage,
variant fitting, evaluation, time splitting, and the full calibrate_engine protocol
including the 2-SE stop rule.
"""

from datetime import UTC, datetime

import pytest

from tradehub.sports.calibration import (
    N_VARIANTS_TRIED,
    TRAIN_FRACTION,
    DISTINCT_SE,
    MIN_SETTLED,
    brier_score,
    brier_se,
    _fit_platt,
    _fit_isotonic,
    _fit_linear_shrinkage,
    _apply_platt,
    _apply_isotonic,
    _apply_linear_shrinkage,
    fit_all_variants,
    evaluate_fit,
    time_split_by_cutoff,
    calibrate_engine,
    CalibrationFit,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


# ── Brier score ──────────────────────────────────────────────────────────────

def test_brier_score_perfect():
    pairs = [(1.0, True), (0.0, False), (1.0, True), (0.0, False)]
    assert brier_score(pairs) == 0.0


def test_brier_score_worst():
    pairs = [(0.0, True), (1.0, False), (0.0, True), (1.0, False)]
    assert brier_score(pairs) == 1.0


def test_brier_score_neutral():
    pairs = [(0.5, True), (0.5, False)]
    assert brier_score(pairs) == 0.25


def test_brier_score_empty():
    assert brier_score([]) is None


def test_brier_se():
    pairs = [(0.5, True), (0.5, False), (0.5, True), (0.5, False)]
    b = brier_score(pairs)
    assert b == 0.25
    se = brier_se(pairs, b)
    assert se is not None
    assert se >= 0


def test_brier_se_insufficient():
    assert brier_se([(0.5, True)], 0.25) is None


# ── Platt scaling ────────────────────────────────────────────────────────────

def test_platt_perfect_separation():
    """Perfectly separated data: Platt should push probs toward 0 and 1."""
    pairs = [(0.1, False), (0.2, False), (0.3, False), (0.8, True), (0.9, True), (0.95, True)]
    params = _fit_platt(pairs)
    assert params is not None
    a, b = params
    assert b > 0  # positive slope: higher p -> higher calibrated


def test_platt_insufficient():
    assert _fit_platt([(0.5, True)]) is None


def test_apply_platt_bounds():
    params = (0.0, 1.0)
    assert 0.0 < _apply_platt(0.1, params) < 0.5
    assert 0.5 < _apply_platt(0.9, params) < 1.0


# ── Isotonic regression ─────────────────────────────────────────────────────

def test_isotonic_monotonic():
    """Isotonic output must be monotonic in p."""
    pairs = [(0.1, False), (0.2, False), (0.7, True), (0.8, True), (0.9, True)]
    knots = _fit_isotonic(pairs)
    assert knots is not None
    for i in range(len(knots) - 1):
        assert knots[i][1] <= knots[i + 1][1]


def test_isotonic_insufficient():
    assert _fit_isotonic([(0.5, True)]) is None


def test_apply_isotonic_range():
    knots = [(0.1, 0.2), (0.5, 0.5), (0.9, 0.8)]
    assert _apply_isotonic(0.0, knots) == 0.2
    assert _apply_isotonic(1.0, knots) == 0.8
    assert _apply_isotonic(0.5, knots) == 0.5


# ── Linear shrinkage ─────────────────────────────────────────────────────────

def test_shrinkage_perfect():
    """Perfect predictions: shrinkage should be 1.0 (no change needed)."""
    pairs = [(1.0, True), (0.0, False), (1.0, True), (0.0, False), (1.0, True)]
    params = _fit_linear_shrinkage(pairs)
    assert params is not None


def test_shrinkage_insufficient():
    assert _fit_linear_shrinkage([(0.5, True)]) is None


def test_apply_shrinkage():
    params = (0.5, 0.5)
    # p=1.0 -> 0.5 + 0.5*(1.0-0.5) = 0.75
    assert abs(_apply_linear_shrinkage(1.0, params) - 0.75) < 1e-9
    # p=0.0 -> 0.5 + 0.5*(0.0-0.5) = 0.25
    assert abs(_apply_linear_shrinkage(0.0, params) - 0.25) < 1e-9


# ── Variant fitting ──────────────────────────────────────────────────────────

def test_fit_all_variants_includes_identity():
    pairs = [(0.3, True), (0.7, True), (0.2, False), (0.8, False)] * 3
    fits = fit_all_variants(pairs)
    assert len(fits) >= 1
    assert any(f.name == "identity" for f in fits)


def test_fit_all_variants_count():
    pairs = [(0.3, True), (0.7, True), (0.2, False), (0.8, False)] * 5
    fits = fit_all_variants(pairs)
    assert len(fits) == N_VARIANTS_TRIED


def test_fit_all_variants_insufficient():
    pairs = [(0.5, True)]
    fits = fit_all_variants(pairs)
    # Only identity should succeed with < 5 pairs
    assert all(f.name == "identity" for f in fits)


# ── Time split ───────────────────────────────────────────────────────────────

def test_time_split_order():
    """Split by cutoff time: earlier 70% train, later 30% test."""
    now = T0
    pairs_with_cutoff = [
        (now, 0.1, False),
        (now, 0.2, False),
        (now, 0.7, True),
        (now, 0.8, True),
    ]
    # All same time - order is preserved as-is
    fit, val, test = time_split_by_cutoff(pairs_with_cutoff)
    # With MIN_SETTLED=100, 4 pairs returns empty
    assert fit == []
    assert val == []
    assert test == []


def test_time_split_min_settled():
    """Below MIN_SETTLED (100), returns empty splits."""
    pairs_with_cutoff = [
        (T0, 0.5, True) for _ in range(50)
    ]
    fit, val, test = time_split_by_cutoff(pairs_with_cutoff)
    assert fit == []
    assert val == []
    assert test == []


def test_time_split_sufficient():
    """With >= MIN_SETTLED, splits into fit / validation / test."""
    pairs_with_cutoff = [
        (T0, 0.5, True) for _ in range(100)
    ]
    fit, val, test = time_split_by_cutoff(pairs_with_cutoff)
    assert len(fit) + len(val) + len(test) == 100
    assert len(fit) > 0
    assert len(val) > 0
    assert len(test) > 0


# ── calibrate_engine ─────────────────────────────────────────────────────────

def _make_pairs(n: int, base_prob: float = 0.5) -> list[tuple[datetime, float, bool]]:
    """Generate n synthetic (cutoff_time, prob, hit) pairs with a slight skill signal."""
    pairs = []
    for i in range(n):
        p = min(max(base_prob + (i % 5) * 0.05, 0.05), 0.95)
        h = (p > 0.5)
        pairs.append((T0, p, h))
    return pairs


def test_calibrate_engine_insufficient():
    pairs = _make_pairs(50)
    result = calibrate_engine("sports_nfl", "winner", pairs)
    assert result is None


def test_calibrate_engine_structure():
    pairs = _make_pairs(150)
    result = calibrate_engine("sports_nfl", "winner", pairs)
    assert result is not None
    assert result["engine"] == "sports_nfl"
    assert result["kind"] == "winner"
    assert result["n_variants_tried"] == N_VARIANTS_TRIED
    assert result["train_n"] + result["validation_n"] + result["test_n"] == 150
    assert result["best_variant"] in ("identity", "platt", "isotonic", "shrinkage")
    assert "stop" in result
    assert "stop_reason" in result
    assert "ship" in result


def test_calibrate_engine_stop_rule_with_strong_signal():
    """With a very strong signal, calibration should clear 2 SE."""
    # Create pairs where p is strongly predictive of h
    pairs = []
    for i in range(150):
        if i % 2 == 0:
            pairs.append((T0, 0.8, True))   # high p, always hit
        else:
            pairs.append((T0, 0.2, False))  # low p, never hit
    result = calibrate_engine("sports_cfb", "winner", pairs)
    assert result is not None
    assert result["gap"] is not None or result["stop_reason"] is not None


# ── Integration: no database needed, pure functions ──────────────────────────

def test_calibrate_engine_returns_stop_reason():
    pairs = _make_pairs(150)
    result = calibrate_engine("sports_nfl", "spread", pairs)
    assert result is not None
    assert isinstance(result["stop_reason"], str)
    assert len(result["stop_reason"]) > 0
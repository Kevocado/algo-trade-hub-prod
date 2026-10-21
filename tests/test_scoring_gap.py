"""Tests for scoring.py gap / gap_se computation.

The paired Brier gap is `brier_on_baseline - brier_baseline` (negative = better than baseline),
and its standard error is computed server-side from per-contract squared-error differences.
"""

from tradehub.journal.scoring import score


def _forecasts(probs, market_prob=0.5):
    """Build forecast rows with the fields scoring.py reads."""
    return [
        {"target": f"t-{i}", "probability": p, "market_prob": market_prob, "rebuilt": False}
        for i, p in enumerate(probs)
    ]


def _forecasts_no_market(probs):
    """Forecast rows with no market_prob and no climatology => baseline 'none'."""
    return [
        {"target": f"t-{i}", "probability": p, "rebuilt": False}
        for i, p in enumerate(probs)
    ]


def _settlements(targets, outcomes):
    return {t: int(o) for t, o in zip(targets, outcomes)}


def _calendar(targets):
    return {}


def test_gap_negative_is_better():
    """Our Brier lower than baseline's => gap < 0 (better)."""
    # Our probs vary, outcomes all 1. Baseline probs all 0.5.
    # gap = mean(our SE) - 0.25 < 0 (better).
    fc = _forecasts([0.6, 0.7, 0.5, 0.8, 0.65])
    st = _settlements(["t-0", "t-1", "t-2", "t-3", "t-4"], [1, 1, 1, 1, 1])
    result = score(fc, st, _calendar(["t-0", "t-1", "t-2", "t-3", "t-4"]), "daily", "test_model")
    assert result["gap"] is not None
    assert result["gap"] < 0, f"Expected negative gap (better), got {result['gap']}"
    assert result["gap_se"] is not None
    assert result["gap_se"] > 0


def test_gap_positive_is_worse():
    """Our Brier higher than baseline's => gap > 0 (worse)."""
    # Our probs all 0.4, outcomes all 1. Our squared error = (0.4-1)^2 = 0.36.
    # Baseline probs all 0.5, baseline squared error = 0.25.
    # gap = 0.36 - 0.25 = +0.11 (worse).
    fc = _forecasts([0.4, 0.4, 0.4, 0.4, 0.4])
    st = _settlements(["t-0", "t-1", "t-2", "t-3", "t-4"], [1, 1, 1, 1, 1])
    result = score(fc, st, _calendar(["t-0", "t-1", "t-2", "t-3", "t-4"]), "daily", "test_model")
    assert result["gap"] is not None
    assert result["gap"] > 0, f"Expected positive gap (worse), got {result['gap']}"
    assert abs(result["gap"] - 0.11) < 1e-6, f"Expected gap ≈ 0.11, got {result['gap']}"


def test_gap_zero_when_equal():
    """Our Brier equals baseline's => gap = 0."""
    fc = _forecasts([0.5, 0.5, 0.5, 0.5, 0.5])
    st = _settlements(["t-0", "t-1", "t-2", "t-3", "t-4"], [1, 1, 1, 1, 1])
    result = score(fc, st, _calendar(["t-0", "t-1", "t-2", "t-3", "t-4"]), "daily", "test_model")
    assert result["gap"] is not None
    assert abs(result["gap"]) < 1e-9, f"Expected gap ≈ 0, got {result['gap']}"


def test_gap_none_when_no_baseline_match():
    """No market_prob and no climatology => baseline is 'none', gap is None."""
    fc = _forecasts_no_market([0.6, 0.6, 0.6])
    st = _settlements(["t-0", "t-1", "t-2"], [1, 1, 1])
    result = score(fc, st, {}, "daily", "test_model")
    assert result["gap"] is None
    assert result["gap_se"] is None


def test_gap_se_positive_with_variation():
    """SE > 0 when per-contract differences vary."""
    fc = _forecasts([0.6, 0.4, 0.8, 0.2, 0.7])
    st = _settlements(["t-0", "t-1", "t-2", "t-3", "t-4"], [1, 0, 1, 0, 1])
    result = score(fc, st, _calendar(["t-0", "t-1", "t-2", "t-3", "t-4"]), "daily", "test_model")
    assert result["gap_se"] is not None
    assert result["gap_se"] > 0


def test_gap_se_none_with_single_contract():
    """SE is None with only 1 contract (can't compute variance)."""
    fc = _forecasts([0.6])
    st = _settlements(["t-0"], [1])
    result = score(fc, st, _calendar(["t-0"]), "daily", "test_model")
    assert result["gap_se"] is None
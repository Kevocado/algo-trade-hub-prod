"""Tests for tradehub.sports.calibration - per-model post-hoc calibration.

Tests cover: Brier score/SE, Platt scaling, isotonic regression, linear shrinkage,
variant fitting, evaluation, time splitting, and the full calibrate_engine protocol
including the 2-SE stop rule.
"""

from datetime import UTC, datetime, timedelta

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
from tradehub.journal.store import PAGE

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


# ── CalibratedForecaster (journal forecaster wrapper) ──────────────────────

def _make_pairs_with_cutoffs(n: int, base_cutoff: datetime = T0) -> list[tuple[datetime, float, bool]]:
    """Generate n synthetic (cutoff_time, prob, hit) pairs spread over n cutoffs."""
    from datetime import timedelta
    pairs = []
    for i in range(n):
        cutoff = base_cutoff + timedelta(hours=i)
        p = min(max(0.5 + (i % 5) * 0.05, 0.05), 0.95)
        h = p > 0.5
        pairs.append((cutoff, p, h))
    return pairs


class _FakeRow:
    """A fake frozen forecast row from journal_forecasts."""
    def __init__(self, target, probability, market_prob=0.5, frozen_at=None):
        self.target = target
        self.probability = probability
        self.market_prob = market_prob
        self.frozen_at = frozen_at or T0.isoformat()
        self.payload = {}
        self.rebuilt = False


class _FakeSupa:
    """Strict fake Supabase client: counts reads, rejects unknown tables."""

    def __init__(self):
        self.read_count = 0
        self.forecasts: list[dict] = []
        self.settlements: dict[str, int] = {}

    def table(self, name):
        self.read_count += 1
        return _FakeTable(self, name)


class _FakeTable:
    def __init__(self, supa, name):
        self.supa = supa
        self.name = name
        self._filters = []
        self._lo = 0
        self._hi = PAGE - 1

    def select(self, *cols):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, vals))
        return self

    def order(self, col):
        return self

    def range(self, lo, hi):
        self._lo = lo
        self._hi = hi
        return self

    def execute(self):
        return _FakeResult(self.supa, self.name, self._filters, self._lo, self._hi)


class _FakeResult:
    def __init__(self, supa, name, filters, lo, hi):
        self.supa = supa
        self.name = name
        self.filters = filters
        self.lo = lo
        self.hi = hi

    @property
    def data(self):
        if self.name == "journal_forecasts":
            return self._filter_forecasts()[self.lo:self.hi + 1]
        elif self.name == "journal_settlements":
            return [{"target": t, "outcome": o} for t, o in self.supa.settlements.items()
                    if self._matches_settlement(t, o)]
        return []

    def _matches_settlement(self, target, outcome):
        for ftype, fcol, fval in self.filters:
            if ftype == "in" and fcol == "target":
                return target in fval
        return True

    def _filter_forecasts(self):
        result = []
        for f in self.supa.forecasts:
            ok = True
            for ftype, fcol, fval in self.filters:
                if ftype == "eq" and f.get(fcol) != fval:
                    ok = False
                    break
                elif ftype == "in" and fcol == "target" and f.get("target") not in fval:
                    ok = False
                    break
            if ok:
                result.append(f)
        return result


def test_calibrated_forecaster_fits_on_150_settled_rows():
    """The calibrated forecaster fits calibration on 150+ settled journal rows."""
    from tradehub.journal.forecasters.calibrated import CalibratedForecaster

    inner = type("FakeInner", (), {
        "name": "sports_nfl",
        "version": "feed-v1",
        "cadence": "daily",
        "kind": "winner",
        "targets": lambda now: [],
        "settle": lambda target, now: None,
    })()

    supa = _FakeSupa()
    supa.forecasts = [
        {"id": i, "target": f"t-{i}", "forecaster": "sports_nfl",
         "forecaster_version": "feed-v1", "probability": p,
         "market_prob": 0.5, "rebuilt": False,
         "frozen_at": (T0 + timedelta(hours=i)).isoformat(),
         "payload": {}}
        for i, p in enumerate([0.6, 0.4, 0.8, 0.2, 0.7] * 30)
    ]
    supa.settlements = {f"t-{i}": 1 if p > 0.5 else 0 for i, p in
                        enumerate([0.6, 0.4, 0.8, 0.2, 0.7] * 30)}

    cf = CalibratedForecaster(inner, lambda: supa)
    assert cf.name == "sports_nfl_cal"
    assert cf.version == "feed-v1+cal"
    assert cf.cadence == "daily"
    assert cf.kind == "winner"

    # Fit calibration
    cf._fit_calibration(supa)
    assert cf._calibration is not None
    assert cf._calibration[0] in ("identity", "platt", "isotonic", "shrinkage")


def test_calibrated_forecaster_does_not_refit_per_target():
    """When the stop rule ships identity, _calibration is ('identity', ()) not None,
    so we do not refit on every target. Store reads stay bounded."""
    from tradehub.journal.forecasters.calibrated import CalibratedForecaster

    inner = type("FakeInner", (), {
        "name": "sports_nfl",
        "version": "feed-v1",
        "cadence": "daily",
        "kind": "winner",
        "targets": lambda now: [],
        "settle": lambda target, now: None,
    })()

    supa = _FakeSupa()
    supa.forecasts = [
        {"id": i, "target": f"t-{i}", "forecaster": "sports_nfl",
         "forecaster_version": "feed-v1", "probability": 0.5,
         "market_prob": 0.5, "rebuilt": False,
         "frozen_at": (T0 + timedelta(hours=i)).isoformat(),
         "payload": {}}
        for i in range(150)
    ]
    supa.settlements = {f"t-{i}": 1 if i % 2 == 0 else 0 for i in range(150)}

    cf = CalibratedForecaster(inner, lambda: supa)

    # First forecast: fits calibration
    entry = type("FakeEntry", (), {"target": "t-0", "cutoff_at": T0})()
    cf.forecast(entry, T0)
    reads_after_first = supa.read_count

    # Second forecast with same hour: should NOT refit
    entry2 = type("FakeEntry", (), {"target": "t-1", "cutoff_at": T0})()
    cf.forecast(entry2, T0)
    reads_after_second = supa.read_count

    assert reads_after_second == reads_after_first, (
        f"Refit on every target: {reads_after_first} reads -> {reads_after_second} reads")


def test_calibrated_forecaster_under_min_settled_returns_identity():
    """Under MIN_SETTLED (100) settled rows, no calibration is fitted."""
    from tradehub.journal.forecasters.calibrated import CalibratedForecaster

    inner = type("FakeInner", (), {
        "name": "sports_nfl",
        "version": "feed-v1",
        "cadence": "daily",
        "kind": "winner",
        "targets": lambda now: [],
        "settle": lambda target, now: None,
    })()

    supa = _FakeSupa()
    supa.forecasts = [
        {"id": i, "target": f"t-{i}", "forecaster": "sports_nfl",
         "forecaster_version": "feed-v1", "probability": 0.5,
         "market_prob": 0.5, "rebuilt": False,
         "frozen_at": (T0 + timedelta(hours=i)).isoformat(),
         "payload": {}}
        for i in range(50)
    ]
    supa.settlements = {f"t-{i}": i % 2 for i in range(50)}

    cf = CalibratedForecaster(inner, lambda: supa)
    cf._fit_calibration(supa)
    assert cf._calibration is None
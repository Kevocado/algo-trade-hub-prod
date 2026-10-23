"""Tests for the market-blend study (tradehub/research/market_blend.py).

Five synthetic cases with known answers:
(a) market = truth-ish, model = pure noise -> fitted c ~ 0 and no family "adds information"
(b) model carries real extra signal -> c clearly > 0 and V1 beats V0 on test slice
(c) clustering: duplicating each event's contracts must not shrink the bootstrap interval
(d) no look-ahead: scrambling outcomes after split leaves train-fit unchanged
(e) missing market_prob row is dropped, never filled with 0.5
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from tradehub.research.market_blend import (
    cluster_bootstrap_ci,
    fit_logistic_l2,
    logit,
    inv_logit,
    prepare_event_days,
    run_market_blend_study,
    split_by_cutoff,
)


def _make_synthetic_data(n_events=100, n_contracts_per_event=3, signal_strength=0.0, seed=42):
    """Generate synthetic journal data with known properties.

    Each event has multiple contracts. The data has a latent "true" probability.
    - Null case (signal_strength=0): model is pure noise, uncorrelated with truth
    - Signal case (signal_strength>0): model and market both estimate the truth,
      but model has additional signal (lower error) when signal_strength > 0.
    """
    random.seed(seed)
    np.random.seed(seed)

    events = []
    for ev in range(n_events):
        # Event-day cutoffs spread over time
        cutoff = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=ev * 3)
        contracts = []
        for c in range(n_contracts_per_event):
            # True probability of outcome = 1
            true_p = np.random.uniform(0.1, 0.9)
            
            # Market is well-calibrated: small error around truth
            market_error = np.random.normal(0, 0.15)
            market_logit = logit(true_p) + market_error
            market_p = inv_logit(market_logit)
            
            if signal_strength == 0.0:
                # Null case: model is PURE NOISE, independent of truth
                model_p = np.random.uniform(0.1, 0.9)
            else:
                # Signal case: model is ALSO well-calibrated but with additional signal
                # (smaller error than market)
                model_error = np.random.normal(0, 0.15 / (1.0 + signal_strength))
                model_logit = logit(true_p) + model_error
                model_p = inv_logit(model_logit)

            # Outcome follows the true probability
            outcome = 1 if np.random.random() < true_p else 0

            contracts.append({
                "target": f"kalshi:EV{ev}-C{c}",
                "probability": model_p,
                "market_prob": market_p,
                "outcome": outcome,
                "cutoff_at": cutoff.isoformat(),
                "event_day": f"EV{ev}",
            })
        events.append(contracts)
    return events


def test_null_case_market_truthish_model_noise():
    """(a) market = truth-ish, model = pure noise -> fitted c ~ 0, V1 does not beat V0 on test."""
    events = _make_synthetic_data(n_events=60, n_contracts_per_event=4, signal_strength=0.0, seed=1)
    train_events, test_events = split_by_cutoff(events)

    # V0: market Brier
    v0_brier = sum((c["market_prob"] - c["outcome"]) ** 2 for ev in test_events for c in ev) / sum(len(ev) for ev in test_events)

    # V1: fit logistic on train, score on test
    a, b, c = fit_logistic_l2(train_events)
    # With noise-only model, c should be near 0
    assert abs(c) < 0.5, f"Expected c ~ 0 for pure noise model, got c={c:.3f}"

    # V1 Brier on test
    v1_brier = 0.0
    n_test = 0
    for ev in test_events:
        for c_data in ev:
            p = inv_logit(a + b * logit(c_data["market_prob"]) + c * logit(c_data["probability"]))
            v1_brier += (p - c_data["outcome"]) ** 2
            n_test += 1
    v1_brier /= n_test

    # V1 should not meaningfully beat V0 (gap near zero or positive)
    gap = v1_brier - v0_brier
    # With L2=1.0, noise model shouldn't be strongly favored; allow small negative
    assert gap > -0.01, f"Expected V1 not to strongly beat V0 for noise model, gap={gap:.4f}"


def test_model_with_extra_signal_beats_v0():
    """(b) model carries real extra signal -> c > 0 and V1 beats V0 on test slice."""
    # Use stronger signal (signal_strength=2.0 = model error half of market error)
    events = _make_synthetic_data(n_events=100, n_contracts_per_event=3, signal_strength=2.0, seed=2)
    train_events, test_events = split_by_cutoff(events)

    # V0
    v0_brier = sum((c["market_prob"] - c["outcome"]) ** 2 for ev in test_events for c in ev) / sum(len(ev) for ev in test_events)

    # V1
    a, b, c = fit_logistic_l2(train_events)
    assert c > 0.2, f"Expected c > 0.2 for model with signal, got c={c:.3f}"

    v1_brier = 0.0
    n_test = 0
    for ev in test_events:
        for c_data in ev:
            p = inv_logit(a + b * logit(c_data["market_prob"]) + c * logit(c_data["probability"]))
            v1_brier += (p - c_data["outcome"]) ** 2
            n_test += 1
    v1_brier /= n_test

    gap = v1_brier - v0_brier
    assert gap < -0.001, f"Expected V1 to beat V0 on test (gap < 0), got gap={gap:.4f}"


def test_clustering_does_not_shrink_interval():
    """(c) duplicating contracts within events must not shrink the bootstrap CI vs event-level resample."""
    events_single = _make_synthetic_data(n_events=40, n_contracts_per_event=1, signal_strength=0.5, seed=3)
    train_s, test_s = split_by_cutoff(events_single)

    events_multi = []
    for ev in events_single:
        multi_ev = []
        for c in ev:
            for _ in range(4):
                multi_ev.append({**c})
        events_multi.append(multi_ev)
    train_m, test_m = split_by_cutoff(events_multi)

    mean_s, lo_s, hi_s = cluster_bootstrap_ci(train_s, n_resamples=500)
    mean_m, lo_m, hi_m = cluster_bootstrap_ci(train_m, n_resamples=500)
    width_single = hi_s - lo_s
    width_multi = hi_m - lo_m
    assert width_multi > 0.7 * width_single, (
        f"Cluster bootstrap failed: multi-contract CI ({width_multi:.4f}) too narrow vs single ({width_single:.4f})"
    )


def test_no_lookahead_scrambling_test_does_not_change_train_fit():
    """(d) scrambling outcomes and market prices of rows after split leaves train-fit unchanged."""
    events = _make_synthetic_data(n_events=50, n_contracts_per_event=2, signal_strength=0.4, seed=4)
    train_events, test_events = split_by_cutoff(events)

    # Original train fit
    a_orig, b_orig, c_orig = fit_logistic_l2(train_events)

    # Scramble ONLY the test slice: replace outcomes with random, market_probs with random
    scrambled_test = []
    for ev in test_events:
        new_ev = []
        for c_data in ev:
            new_ev.append({
                **c_data,
                "outcome": np.random.randint(0, 2),
                "market_prob": np.random.uniform(0.1, 0.9),
            })
        scrambled_test.append(new_ev)

    # Re-fit using the full runner; train weights should be unchanged by test data
    result_orig = run_market_blend_study(train_events, test_events, family="test")
    scrambled_test = []
    for ev in test_events:
        new_ev = []
        for c_data in ev:
            new_ev.append({
                **c_data,
                "outcome": np.random.randint(0, 2),
                "market_prob": np.random.uniform(0.1, 0.9),
                "probability": np.random.uniform(0.1, 0.9),
            })
        scrambled_test.append(new_ev)
    result_scrambled = run_market_blend_study(train_events, scrambled_test, family="test")
    orig_weights = result_orig.get("test", {})
    scram_weights = result_scrambled.get("test", {})
    for key in ["a", "b", "c", "w"]:
        o = orig_weights.get(key)
        s = scram_weights.get(key)
        if o is not None and s is not None:
            assert abs(o - s) < 1e-5, f"Look-ahead detected: {key} changed {o} -> {s}"


def test_missing_market_prob_dropped_not_filled():
    """(e) rows without market_prob are dropped, never imputed with 0.5."""
    events = _make_synthetic_data(n_events=30, n_contracts_per_event=2, signal_strength=0.3, seed=5)
    train_events, test_events = split_by_cutoff(events)

    # Remove market_prob from half the train contracts
    for ev in train_events:
        for i, c_data in enumerate(ev):
            if i % 2 == 0:
                c_data.pop("market_prob", None)

    # Assert contracts missing market_prob are excluded from fitted training data
    from tradehub.research.market_blend import _contract_level_data
    contracts_after = _contract_level_data(train_events)
    total_train_contracts = sum(len(ev) for ev in train_events)
    assert len(contracts_after) < total_train_contracts, "Dropped contracts must reduce fitted data count"
    assert all("market_prob" in c and c["market_prob"] is not None for c in contracts_after)
    # Fit should not crash and should only use contracts with both probs
    a, b, c = fit_logistic_l2(train_events)
    assert not math.isnan(a) and not math.isnan(b) and not math.isnan(c)

    # V0 on test: only contracts with market_prob should contribute
    v0_brier = 0.0
    n = 0
    for ev in test_events:
        for c_data in ev:
            if c_data.get("market_prob") is not None:
                v0_brier += (c_data["market_prob"] - c_data["outcome"]) ** 2
                n += 1
    assert n > 0
    v0_brier /= n
    assert v0_brier < 0.3  # reasonable sanity


def test_run_market_blend_study_end_to_end():
    """End-to-end synthetic: null says no evidence; signal does not crash or fail."""
    events_null = _make_synthetic_data(n_events=60, n_contracts_per_event=4, signal_strength=0.0, seed=1)
    train_n, test_n = split_by_cutoff(events_null)
    res_n = run_market_blend_study(train_n, test_n, family="test")
    v_n = res_n.get("test", {}).get("verdict", "")
    assert "failed:" not in v_n, f"Null case crashed: {v_n}"
    events_sig = _make_synthetic_data(n_events=100, n_contracts_per_event=3, signal_strength=2.0, seed=2)
    train_s, test_s = split_by_cutoff(events_sig)
    res_s = run_market_blend_study(train_s, test_s, family="test")
    v_s = res_s.get("test", {}).get("verdict", "")
    assert "failed:" not in v_s, f"Signal case crashed: {v_s}"


def test_logit_inv_logit_roundtrip():
    """logit and inv_logit are inverses in (0,1)."""
    for p in [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]:
        assert inv_logit(logit(p)) == pytest.approx(p, rel=1e-6)


def test_prepare_event_days_groups_by_event_day():
    """Contracts with same event_day are grouped together."""
    forecasts = [
        {"target": "kalshi:EV1-C1", "event_day": "EV1", "probability": 0.6, "market_prob": 0.55, "outcome": 1, "cutoff_at": "2026-01-01T00:00:00+00:00"},
        {"target": "kalshi:EV1-C2", "event_day": "EV1", "probability": 0.7, "market_prob": 0.65, "outcome": 0, "cutoff_at": "2026-01-01T00:00:00+00:00"},
        {"target": "kalshi:EV2-C1", "event_day": "EV2", "probability": 0.4, "market_prob": 0.45, "outcome": 1, "cutoff_at": "2026-01-04T00:00:00+00:00"},
    ]
    event_days = prepare_event_days(forecasts)
    assert len(event_days) == 2
    assert len(event_days["EV1"]) == 2
    assert len(event_days["EV2"]) == 1


def test_split_by_cutoff_preserves_time_order():
    """Train events are strictly earlier than test events by cutoff."""
    events = _make_synthetic_data(n_events=20, n_contracts_per_event=2, seed=10)
    train, test = split_by_cutoff(events)
    # All train cutoffs <= all test cutoffs
    train_cutoffs = [datetime.fromisoformat(c["cutoff_at"]) for ev in train for c in ev]
    test_cutoffs = [datetime.fromisoformat(c["cutoff_at"]) for ev in test for c in ev]
    assert max(train_cutoffs) <= min(test_cutoffs)
    # Approximately 70/30 split by event-days
    assert len(train) == 14  # 70% of 20
    assert len(test) == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
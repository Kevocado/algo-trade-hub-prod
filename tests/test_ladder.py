import pytest

from tradehub.engines.ladder import (
    implied_mean,
    implied_median,
    isotonic_survival,
    ladder_brier,
    ladder_crps,
    normal_ladder,
    usable_mid,
)


def test_usable_mid_drops_one_sided_and_wide_quotes():
    assert usable_mid(0.40, 0.44) == pytest.approx(0.42)
    assert usable_mid(None, 0.44) is None
    assert usable_mid(0.01, 0.99) is None  # no real market


def test_isotonic_survival_pools_violations():
    ladder = isotonic_survival([(100.0, 0.30), (0.0, 0.90), (50.0, 0.40), (75.0, 0.50)])
    assert [c for c, _ in ladder] == [0.0, 50.0, 75.0, 100.0]
    assert [p for _, p in ladder] == pytest.approx([0.90, 0.45, 0.45, 0.30])


def test_implied_mean_and_median_hand_computed():
    ladder = [(0.0, 0.9), (50.0, 0.5), (100.0, 0.1)]
    # gap 50: 0.1 @ -25, 0.4 @ 25, 0.4 @ 75, 0.1 @ 125
    assert implied_mean(ladder) == pytest.approx(0.1 * -25 + 0.4 * 25 + 0.4 * 75 + 0.1 * 125)
    assert implied_median(ladder) == pytest.approx(50.0)
    assert implied_median([(0.0, 0.9), (100.0, 0.3)]) == pytest.approx(0.0 + (0.9 - 0.5) / 0.6 * 100)


def test_ladder_brier_and_crps_hand_computed():
    ladder = [(0.0, 0.9), (50.0, 0.5), (100.0, 0.1)]
    outcome = 60.0  # yes, yes, no
    assert ladder_brier(ladder, outcome) == pytest.approx((0.01 + 0.25 + 0.01) / 3)
    # widths 50 each (edges -25, 25, 75, 125)
    assert ladder_crps(ladder, outcome) == pytest.approx(50 * (0.01 + 0.25 + 0.01))


def test_normal_ladder_is_survival():
    ladder = normal_ladder([100.0, 0.0], mu=0.0, sigma=10.0)
    assert [c for c, _ in ladder] == [0.0, 100.0]
    assert ladder[0][1] == pytest.approx(0.5)
    assert ladder[1][1] < 1e-6

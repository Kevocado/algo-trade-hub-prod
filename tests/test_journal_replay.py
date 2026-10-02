import random
from datetime import date, timedelta

import pytest

from tradehub.journal.replay import replay


def _closes(n=1500, seed=3, drift=0.0004):
    rng, day, price, out = random.Random(seed), date(2019, 1, 1), 100.0, {}
    while len(out) < n:
        if day.weekday() < 5:
            price *= 1 + drift + rng.gauss(0, 0.01)
            out[day] = price
        day += timedelta(days=1)
    return out


class Const:
    def __init__(self, p):
        self.p = p

    def predict(self, row):
        return self.p


def test_the_model_for_a_session_is_fitted_only_on_sessions_before_that_months_first_day():
    closes, seen = _closes(), []

    def spy_fit(x, y, days):
        seen.append(max(days))
        return Const(0.5)

    result = replay(closes, start=date(2022, 3, 1), end=date(2022, 5, 31), fit_fn=spy_fit)
    assert result["n"] > 40
    assert len(seen) == 3                                                    # one refit per month, as live
    assert [d < date(2022, m, 1) for d, m in zip(seen, (3, 4, 5))] == [True] * 3


def test_brier_and_skill_are_computed_on_the_same_sessions_against_climatology():
    closes = _closes()
    r = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30), fit_fn=lambda x, y, d: Const(0.5))
    days = sorted(d for d in closes if date(2022, 3, 1) <= d <= date(2022, 4, 30))
    prev = {d: closes[p] for p, d in zip(sorted(closes), sorted(closes)[1:])}
    outcomes = [closes[d] > prev[d] for d in days]
    assert r["n"] == len(days)
    assert r["brier"] == pytest.approx(0.25)                                 # a constant 0.5
    assert r["up_rate"] == pytest.approx(sum(outcomes) / len(outcomes))
    assert r["brier_baseline"] > 0 and r["bss"] == pytest.approx(1 - r["brier"] / r["brier_baseline"], abs=1e-5)


def test_each_forecast_is_graded_on_its_own_session_using_only_closes_before_it():
    """A momentum rule (up if yesterday was up), computed here independently from the raw closes."""
    closes = _closes()
    ordered = sorted(closes)

    class Momentum:
        def predict(self, row):
            return 0.9 if row["r1"] > 0 else 0.1

    r = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30), fit_fn=lambda x, y, d: Momentum())
    losses = []
    for i, day in enumerate(ordered):
        if date(2022, 3, 1) <= day <= date(2022, 4, 30):
            yesterday_up = closes[ordered[i - 1]] > closes[ordered[i - 2]]
            p, y = (0.9 if yesterday_up else 0.1), float(closes[day] > closes[ordered[i - 1]])
            losses.append((p - y) ** 2)
    assert r["n"] == len(losses) and r["brier"] == pytest.approx(sum(losses) / len(losses))


def test_skill_is_reported_per_year_so_one_lucky_year_cannot_carry_the_headline():
    r = replay(_closes(), start=date(2021, 6, 1), end=date(2022, 12, 31), fit_fn=lambda x, y, d: Const(0.5))
    assert set(r["by_year"]) == {"2021", "2022"}
    assert all({"n", "brier", "brier_baseline", "bss"} <= set(v) for v in r["by_year"].values())


def test_a_window_with_too_little_history_is_empty_not_a_guess():
    r = replay(_closes(n=150), start=date(2019, 3, 1), end=date(2019, 5, 31), fit_fn=lambda x, y, d: Const(0.5))
    assert r["n"] == 0 and r["bss"] is None and r["brier"] is None
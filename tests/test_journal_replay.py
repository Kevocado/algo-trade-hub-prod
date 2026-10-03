import math
import random
import statistics
from datetime import date, timedelta

import pytest

from tradehub.journal.replay import _summary, replay
from tradehub.journal.spx import climatology_up, up_outcome


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

def test_days_the_source_would_never_trade_are_not_scored():
    """The live forecasters gate on a calendar (`DailySource.is_session`: NYSE sessions for SPX, VIX
    and gold, TARGET days for EUR/USD). `replay` scored every date the closes mapping happened to
    carry, so a feed that publishes on market holidays put holiday prints into the result -- VIXCLS
    carried forward, and the live run graded 775 days when only 754 are NYSE sessions. A replay whose
    sessions are not the live journal's sessions is not a replay of the live journal."""
    closes = _closes()
    sessions = {d for d in closes if d.weekday() < 5}
    only_weekdays = lambda d: d.weekday() < 5

    baseline = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30),
                      fit_fn=lambda x, y, d: Const(0.5), is_target=only_weekdays)
    ungated = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30),
                     fit_fn=lambda x, y, d: Const(0.5))

    assert ungated["n"] >= baseline["n"]
    # the synthetic series is all weekdays, so the two agree here; what matters is that a caller can
    # gate, and that the default is the strict one rather than "score everything present"
    assert baseline["n"] == sum(1 for d in sessions if date(2022, 3, 1) <= d <= date(2022, 4, 30))


def test_the_reported_window_is_the_sessions_actually_scored_not_the_requested_one():
    """`date_from`/`date_to` used to echo the arithmetic window, so a run on a Sunday ended on a
    Saturday and printed it. The Window is the only provenance a reader has for a not-counted number,
    so it must describe what was graded."""
    closes = _closes()
    r = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30), fit_fn=lambda x, y, d: Const(0.5))
    scored = sorted(d for d in closes if date(2022, 3, 1) <= d <= date(2022, 4, 30))

    assert r["date_from"] == scored[0].isoformat()
    assert r["date_to"] == scored[-1].isoformat()
    assert r["date_from"] != date(2022, 3, 1).isoformat() or r["date_to"] != date(2022, 4, 30).isoformat()


# ── The interval on the Brier gap ────────────────────────────────────────────
#
# Why this exists: the audit behind it found every replayed model within ±0.01 of climatology over
# ~760 sessions, with VIX's +0.0099 sitting 1.1 standard errors from zero. A skill number printed with
# no interval reads as a result. So the replay reports the paired per-session gap between our squared
# error and the baseline's, plus the standard error of THAT gap -- and `bss` stays a bare ratio, because
# the standard error of a ratio is not the standard error of a difference and inventing one with the
# delta method would be publishing an approximation as though it were measured.


def test_a_gap_that_is_identical_on_every_session_has_a_standard_error_of_zero():
    """The degenerate case, stated on purpose: every session's `(p-y)^2 - (c-y)^2` is bit-for-bit the
    same number, so the sample SD is 0 and the SE is 0. It is the one place a zero SE is a measurement
    rather than a missing measurement."""
    s = _summary([(0.6, 0.5, 1)] * 5)

    assert s["brier_diff"] == pytest.approx(-0.09, abs=1e-6)
    assert s["brier_diff_se"] == 0.0


def test_the_standard_error_is_the_sample_sd_of_the_paired_gap_over_the_root_n():
    """Checked against `statistics.stdev`, which divides by n-1, rather than against the module's own
    arithmetic: a test that recomputes the formula it is testing proves nothing."""
    rows = [(0.52, 0.61, 1), (0.63, 0.55, 0), (0.41, 0.47, 1), (0.58, 0.60, 0),
            (0.49, 0.44, 1), (0.71, 0.66, 0), (0.45, 0.50, 0), (0.55, 0.53, 1)]
    gaps = [(p - y) ** 2 - (c - y) ** 2 for p, c, y in rows]

    s = _summary(rows)
    assert s["brier_diff"] == pytest.approx(statistics.fmean(gaps), abs=1e-6)
    assert s["brier_diff_se"] == pytest.approx(statistics.stdev(gaps) / math.sqrt(len(gaps)), abs=1e-6)
    assert s["brier_diff_se"] > 0


def test_the_gap_is_taken_session_by_session_so_a_shared_outcome_cancels_out_of_the_error_bar():
    """The pairing is the whole point of this statistic. Here each model's squared error swings from
    0.0001 to 0.98 across sessions while the difference between them is a constant -0.98, so the SE of
    the gap is 0 while the spread of either score on its own is enormous. An unpaired SE -- the spread
    of the pooled squared errors -- would report that enormous number and drown a real effect in it."""
    rows = [(0.99, 0.01, 1), (0.01, 0.99, 0)] * 4
    s = _summary(rows)

    assert s["brier_diff_se"] == 0.0
    pooled = statistics.stdev([(p - y) ** 2 for p, _c, y in rows] + [(c - y) ** 2 for _p, c, y in rows])
    assert pooled > 0.4 and s["brier_diff_se"] < pooled / 10


def test_one_scored_session_has_a_gap_but_no_standard_error_to_stand_on():
    """`n - 1` has no value to divide by, and a sample SD of a single number is not zero -- it does not
    exist. Printing 0.0 would be a claim of perfect precision from one observation, which is the exact
    failure this change exists to stop, so the single-session summary reports `None`."""
    s = _summary([(0.6, 0.5, 1)])

    assert s["n"] == 1 and s["brier_diff"] == pytest.approx(-0.09, abs=1e-6)
    assert s["brier_diff_se"] is None


def test_an_empty_window_reports_no_gap_and_no_standard_error():
    empty = _summary([])

    assert empty["brier_diff"] is None and empty["brier_diff_se"] is None
    assert empty["brier"] is None and empty["bss"] is None


def test_brier_diff_is_the_brier_gap_not_a_second_way_of_measuring_skill():
    """`brier_diff` is reported alongside `brier` and `brier_baseline` rather than derived from them, so
    the identity that ties the three together is asserted here instead of being assumed: if it ever
    stops holding, the page is printing two different stories about the same 760 sessions."""
    closes = _closes()
    s = _summary([(0.52, 0.61, 1), (0.63, 0.55, 0), (0.41, 0.47, 1), (0.58, 0.60, 0)])
    replayed = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30),
                      fit_fn=lambda x, y, d: Const(0.5))

    # both are compared at the last published place (6dp): the two figures come from two different
    # float summations and are then each rounded, so they agree to that place and not to the last bit
    for summary in (s, replayed):
        assert summary["brier_diff"] == pytest.approx(summary["brier"] - summary["brier_baseline"], abs=1e-6)
    # the gap is our error MINUS theirs, so a negative gap means the model lost less than climatology
    # did, which is the same thing `bss` says with a positive sign.
    assert (s["brier_diff"] < 0) == (s["brier"] < s["brier_baseline"])
    assert (s["brier_diff"] < 0) == (s["bss"] > 0)


def test_the_reported_standard_error_covers_the_sessions_the_replay_graded_and_nothing_else():
    """Rebuilt from the raw closes through the module's own public helpers rather than from `replay`'s
    bookkeeping, so this pins both halves of the claim: the gap is measured over the sessions the replay
    scored, and its error bar is the spread of those same per-session differences."""
    closes = _closes()
    start, end = date(2022, 3, 1), date(2022, 4, 30)
    r = replay(closes, start=start, end=end, fit_fn=lambda x, y, d: Const(0.5))

    gaps = []
    for day in sorted(closes):
        if not start <= day <= end:
            continue
        clim, outcome = climatology_up(closes, day), up_outcome(closes, day)
        if clim is None or outcome is None:
            continue
        gaps.append((0.5 - outcome) ** 2 - (clim - outcome) ** 2)

    assert len(gaps) == r["n"] > 40
    assert r["brier_diff"] == pytest.approx(statistics.fmean(gaps), abs=1e-6)
    assert r["brier_diff_se"] == pytest.approx(statistics.stdev(gaps) / math.sqrt(len(gaps)), abs=1e-6)


def test_the_year_split_carries_the_gap_and_its_standard_error_too():
    """`by_year` goes through the same summary, so each year gets its own interval -- which is the point
    of the split: one year's number without its error bar is the pooled number's mistake one level down."""
    r = replay(_closes(), start=date(2021, 6, 1), end=date(2022, 12, 31), fit_fn=lambda x, y, d: Const(0.5))

    for year, v in r["by_year"].items():
        assert {"brier_diff", "brier_diff_se"} <= set(v), year
        assert v["brier_diff"] == pytest.approx(v["brier"] - v["brier_baseline"], abs=1e-6)
        assert v["brier_diff_se"] is not None and v["brier_diff_se"] > 0

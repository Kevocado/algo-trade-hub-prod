from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.pit import Decision, check_no_lookahead
from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import (
    CORE_FEATURES,
    MIN_PAYROLL_SIGMA,
    LaborFeatures,
    add_months,
    fit_payroll_model,
    is_trainable,
    labor_features,
    month_end,
    training_rows,
)

PAYEMS = parse_alfred_csv(
    (Path(__file__).resolve().parent / "fixtures" / "labor" / "payems_2024_2025.csv").read_text(encoding="utf-8"))


def _weekly(start, weeks, value_fn):
    return {start + timedelta(days=7 * i): value_fn(i) for i in range(weeks)}


def test_labor_features_are_point_in_time():
    month = date(2025, 1, 1)
    end = month_end(month)
    icsa = {end: _weekly(date(2024, 11, 2), 16, lambda i: 200000.0 + 1000 * i)}
    ccsa = {end: _weekly(date(2024, 11, 2), 16, lambda i: 1800000.0 + 5000 * i)}
    jolts = {end: {date(2024, m, 1): 5000.0 + m for m in range(1, 13)}}
    adp_vintage = {date(2024, 12, 1): 150000.0, date(2025, 1, 1): 150183.0}
    feats = labor_features(month, payems=PAYEMS, icsa=icsa, ccsa=ccsa, hires=jolts, openings=jolts,
                           adp={date(2025, 2, 6): adp_vintage}, release=date(2025, 2, 7))
    assert feats.values["pay_last"] == 256.0  # Dec first print, from the 2025-01-31 vintage
    assert feats.values["pay_3m"] == pytest.approx((256.0 + 212.0 + 43.0) / 3)  # Dec, Nov, Oct in that vintage
    assert feats.values["icsa_ref_chg"] == pytest.approx(5.0)   # weeks ending Jan 18 vs Dec 14
    assert feats.values["adp_chg"] == 183.0 and feats.values["adp_missing"] == 0.0
    decided = datetime(2025, 2, 7, 12, 29, tzinfo=timezone.utc)
    check_no_lookahead(Decision("KXPAYROLLS-25JAN-T0", decided, 0.5, feats.sources))
    assert max(o.published_at for o in feats.sources if not o.name.startswith("ADP")) <= datetime(
        2025, 2, 1, 5, 0, tzinfo=timezone.utc)


def test_labor_features_missing_vintage_is_none():
    assert labor_features(date(2020, 1, 1), payems=PAYEMS, icsa={}, ccsa={}, hires={}, openings={}, adp={},
                          release=date(2020, 2, 7)) is None


def _row(month, pay_last, icsa_chg, target):
    values = {f: 0.0 for f in CORE_FEATURES}
    values.update(pay_last=pay_last, pay_3m=pay_last, icsa_ref_chg=icsa_chg)
    return LaborFeatures(month, values, ()), target


def test_fit_payroll_model_learns_and_skips_covid():
    rows = []
    month = date(2010, 1, 1)
    for i in range(60):
        pay_last = 100.0 + (i % 7) * 20
        icsa = float((i % 5) - 2)
        rows.append(_row(month, pay_last, icsa, pay_last - 10.0 * icsa))
        month = add_months(month, 1)
    rows.append(_row(date(2020, 4, 1), 0.0, 0.0, -20000.0))  # COVID month: must be ignored
    model = fit_payroll_model(rows, lam=0.01)
    assert model.n_train == 60
    probe = {f: 0.0 for f in CORE_FEATURES} | {"pay_last": 150.0, "pay_3m": 150.0, "icsa_ref_chg": 2.0}
    assert model.predict(probe) == pytest.approx(130.0, abs=1.0)
    assert model.sigma == MIN_PAYROLL_SIGMA  # perfect fit -> floor


def test_fit_payroll_model_needs_history_and_training_rows_is_walk_forward():
    with pytest.raises(ValueError):
        fit_payroll_model([_row(date(2015, 1, 1), 1.0, 0.0, 1.0)])
    table = {date(2015, m, 1): _row(date(2015, m, 1), 1.0, 0.0, 1.0)[0] for m in range(1, 7)}
    targets = {m: 1.0 for m in table}
    assert [f.month for f, _ in training_rows(table, targets, before=date(2015, 4, 1))] == [
        date(2015, 1, 1), date(2015, 2, 1), date(2015, 3, 1)]
    assert not is_trainable(date(2021, 6, 1)) and is_trainable(date(2021, 7, 1)) and not is_trainable(date(2009, 12, 1))


# ── the weekly series must be read at the month's own vintage ─────────────────
#
# `load_labor_inputs` used to hand ICSA/CCSA/JOLTS over from ONE latest vintage, so every
# historical month was described with data revised months or years later. `check_no_lookahead`
# could not see it: the Observation timestamps are the weeks' nominal publication dates, which are
# honest-looking, while the values behind them came from a much later vintage. Every historical
# backtest month was therefore fitted on knowledge it did not have.

def _vintaged_weekly(values_by_week: dict, vintage_day: date) -> dict:
    return {vintage_day: values_by_week}


def test_a_value_revised_after_the_month_does_not_reach_that_months_features():
    month = date(2025, 1, 1)
    end = month_end(month)
    weeks = _weekly(date(2024, 11, 2), 16, lambda i: 200000.0 + 1000 * i)
    # The latest vintage revises every ICSA week down by 20k; the month's own vintage does not.
    latest = {end + timedelta(days=31): {w: v - 20000.0 for w, v in weeks.items()}}
    icsa = {**latest, **_vintaged_weekly(weeks, end)}
    ccsa = {**_vintaged_weekly(_weekly(date(2024, 11, 2), 16, lambda i: 1800000.0 + 5000 * i), end)}
    jolts = {end: {date(2024, m, 1): 5000.0 + m for m in range(1, 13)}}
    feats = labor_features(month, payems=PAYEMS, icsa=icsa, ccsa=ccsa, hires=jolts, openings=jolts,
                           adp={}, release=date(2025, 2, 7))
    assert feats is not None
    assert feats.values["icsa_ref_chg"] == pytest.approx(5.0), (
        f"January's claims change used a later vintage's revision: {feats.values}"
    )


def test_features_are_none_when_the_months_own_weekly_vintage_is_absent():
    """A missing month_end vintage is a feature gap, not a reason to fall back on today's data."""
    month = date(2025, 1, 1)
    weeks = _weekly(date(2024, 11, 2), 16, lambda i: 200000.0 + 1000 * i)
    later = date(2025, 2, 28)
    assert labor_features(month, payems=PAYEMS,
                          icsa={later: weeks}, ccsa={later: weeks}, hires={}, openings={}, adp={},
                          release=date(2025, 2, 7)) is None


def test_the_weekly_series_take_a_vintage_each():
    """Signature guard: a flat {week: value} map is the leak, so the parameter type is the
    fix that stops it being reintroduced."""
    import inspect
    params = inspect.signature(labor_features).parameters
    for name in ("icsa", "ccsa", "hires", "openings"):
        assert "Vintage" in str(params[name].annotation), f"{name} still takes a flat series: {params[name]}"

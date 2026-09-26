from datetime import date

from labor_fakes import synthetic_inputs, true_change
from tradehub.data.labor_inputs import (
    guess_release_date,
    load_labor_inputs,
    payroll_nowcasts,
    release_date,
)


def test_guess_release_date_is_first_friday_of_next_month():
    assert guess_release_date(date(2026, 8, 1)) == date(2026, 9, 4)
    assert guess_release_date(date(2025, 7, 1)) == date(2025, 8, 1)
    assert release_date(date(2025, 11, 1), {date(2025, 11, 1): date(2025, 12, 16)}) == date(2025, 12, 16)


def test_load_labor_inputs_requests_point_in_time_vintages():
    calls = {}

    def fetch(series, days, *, cache_dir, today, deadline=None):
        calls[series] = (days, today)
        return {d: {date(2000, 1, 1): 1.0} for d in days}

    inputs = load_labor_inputs(first_month=date(2026, 6, 1), last_month=date(2026, 8, 1),
                               releases={date(2026, 8, 1): date(2026, 9, 4)}, as_of=date(2026, 9, 25),
                               fetch=fetch, cache_dir=None)
    assert calls["PAYEMS"][0] == [date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
                                  date(2026, 9, 24)]
    assert calls["ADPMNUSNERSA"][0] == [date(2026, 7, 2), date(2026, 8, 6), date(2026, 9, 3)]  # release - 1 day
    # The weekly series are fetched at the SAME month-end vintages as PAYEMS. They used to be
    # fetched once, at the latest vintage, which fed every historical month with data revised
    # after it -- a lookahead the leakage guard cannot see.
    for series in ("ICSA", "CCSA", "JTSHIL", "JTSJOL"):
        assert calls[series][0] == calls["PAYEMS"][0], (
            f"{series} is not fetched per month-end vintage: {calls[series][0]}"
        )
    assert "UNRATE" not in calls and inputs.unrate == {}
    assert all(today == date(2026, 9, 25) for _, today in calls.values())


def test_point_in_time_ok_requires_every_months_own_vintage():
    """The interlock behind `backtest_labor --record`: a run whose weekly features came from
    anywhere but that month's own vintage must not be able to promote the engine."""
    from dataclasses import replace

    from tradehub.data.labor_inputs import point_in_time_ok

    inputs = load_labor_inputs(first_month=date(2026, 6, 1), last_month=date(2026, 8, 1), releases={},
                               as_of=date(2026, 9, 25),
                               fetch=lambda series, days, **kw: {d: {date(2026, 1, 1): 1.0} for d in days},
                               cache_dir=None)
    months = [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    assert point_in_time_ok(inputs, months) is True, sorted(inputs.icsa)

    # A month with no vintage of its own (an ALFRED gap, say) is not point-in-time.
    assert point_in_time_ok(inputs, months + [date(2026, 9, 1)]) is False

    # The pre-fix shape: one latest vintage only, no month-end vintages at all.
    leaky = replace(inputs, icsa={date(2026, 9, 24): {date(2026, 8, 1): 1.0}}, ccsa={})
    assert point_in_time_ok(leaky, months) is False


def test_load_labor_inputs_fetches_unrate_when_asked():
    seen = {}

    def fetch(series, days, *, cache_dir, today, deadline=None):
        seen[series] = days
        return {}

    load_labor_inputs(first_month=date(2026, 7, 1), last_month=date(2026, 8, 1), releases={},
                      as_of=date(2026, 9, 25), unrate_from=date(2026, 7, 1), fetch=fetch, cache_dir=None)
    assert seen["UNRATE"] == [date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 24)]


def test_load_labor_inputs_can_skip_adp():
    seen = {}

    def fetch(series, days, *, cache_dir, today, deadline=None):
        seen[series] = days
        return {}

    inputs = load_labor_inputs(first_month=date(2026, 7, 1), last_month=date(2026, 8, 1), releases={},
                               as_of=date(2026, 9, 25), with_adp=False, fetch=fetch, cache_dir=None)
    assert "ADPMNUSNERSA" not in seen and inputs.adp == {}


def test_payroll_nowcasts_walk_forward_on_synthetic_inputs():
    inputs = synthetic_inputs()
    target = date(2013, 6, 1)
    nowcasts = payroll_nowcasts(inputs, [target], {}, train_from=date(2010, 1, 1))
    nc = nowcasts[target]
    assert nc.model.n_train == 41  # 2010-01 .. 2013-05: never the target month itself
    naive = abs(nc.features.values["pay_3m"] - true_change(target))
    assert abs(nc.mu - true_change(target)) < naive  # claims carry the surprise
    assert nc.sigma >= 40.0

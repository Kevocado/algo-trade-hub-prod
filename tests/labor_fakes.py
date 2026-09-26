"""Synthetic, internally consistent labor inputs for labor_nowcast tests (no network)."""

from __future__ import annotations

import math
from datetime import date, timedelta

from tradehub.data.labor_inputs import LaborInputs
from tradehub.engines.labor import add_months, month_end

FIRST = date(2009, 1, 1)
LAST = date(2014, 6, 1)


def true_change(month: date) -> float:
    i = (month.year - 2009) * 12 + month.month
    return round(150 + 60 * math.sin(i / 3.0))


def _months(first: date, last: date) -> list[date]:
    out, m = [], first
    while m <= last:
        out.append(m)
        m = add_months(m, 1)
    return out


def synthetic_inputs() -> LaborInputs:
    """PAYEMS vintages at each month end hold data through the prior month (first prints never revised).

    Initial claims in each reference week are 400k - 500 * that month's change, so
    the claims change carries the surprise in the payroll change.
    """
    months = _months(FIRST, LAST)
    levels, level = {}, 130000.0
    for m in months:
        level += true_change(m)
        levels[m] = level
    payems = {}
    for m in months[1:]:
        payems[month_end(m)] = {o: levels[o] for o in months if o < m}
    icsa, ccsa = {}, {}
    saturday = date(2008, 12, 6)
    while saturday <= date(2014, 9, 1):
        ref = saturday.replace(day=1)
        icsa[saturday] = 400000.0 - 500.0 * true_change(ref)
        ccsa[saturday] = 1800000.0
        saturday += timedelta(days=7)
    hires = {m: 5000.0 for m in months}
    openings = {m: 6000.0 for m in months}
    return LaborInputs(payems=payems, unrate={}, adp={}, icsa=icsa, ccsa=ccsa, hires=hires, openings=openings)

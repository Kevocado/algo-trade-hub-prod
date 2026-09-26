"""Everything labor_nowcast reads, fetched once per run from keyless ALFRED vintages.

- PAYEMS: one vintage per month end (what was known the day before the
  earliest possible release), plus the latest vintage for revisions.
- UNRATE: the same month-end vintages, for the Jobs Scorecard's U3 panel.
- ADPMNUSNERSA: the vintage the day before each jobs release (vintages start 2022-09).
- ICSA, CCSA, JTSHIL, JTSJOL: the latest vintage; their publication lags
  are applied in tradehub.engines.labor.labor_features.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence

from tradehub.data.alfred_vintages import DEFAULT_CACHE_DIR, Vintage, fetch_vintages
from tradehub.engines.labor import (
    CORE_FEATURES,
    LaborFeatures,
    PayrollModel,
    add_months,
    first_prints,
    fit_payroll_model,
    labor_features,
    month_end,
    training_rows,
)

ADP_FIRST_MONTH = date(2022, 9, 1)
CACHE_ENV = "TRADEHUB_ALFRED_CACHE"


@dataclass(frozen=True)
class LaborInputs:
    payems: dict[date, Vintage]
    unrate: dict[date, Vintage]
    adp: dict[date, Vintage]
    icsa: Vintage
    ccsa: Vintage
    hires: Vintage
    openings: Vintage


def cache_dir_from_env() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR)


def guess_release_date(month: date) -> date:
    """First Friday of the following month -- the usual Employment Situation date."""
    first = add_months(month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7)


def release_date(month: date, releases: Mapping[date, date]) -> date:
    return releases.get(month) or guess_release_date(month)


def _months(first: date, last: date) -> list[date]:
    out, month = [], first
    while month <= last:
        out.append(month)
        month = add_months(month, 1)
    return out


def load_labor_inputs(
    *,
    first_month: date,
    last_month: date,
    releases: Mapping[date, date],
    as_of: date,
    unrate_from: date | None = None,
    with_adp: bool = True,
    fetch: Callable[..., dict[date, Vintage]] = fetch_vintages,
    cache_dir: Path | None = None,
) -> LaborInputs:
    """Fetch the vintages needed for reference months first_month..last_month, as known on `as_of`.

    UNRATE (Jobs Scorecard only) is fetched from `unrate_from` on; None skips it.
    with_adp=False skips ADP (the core feature set does not use it; each month is a vintage).
    """
    cache = cache_dir if cache_dir is not None else cache_dir_from_env()
    latest = as_of - timedelta(days=1)
    month_ends = [month_end(m) for m in _months(add_months(first_month, -1), last_month) if month_end(m) < as_of]
    unrate_ends = [] if unrate_from is None else [d for d in month_ends if d >= month_end(unrate_from)]
    adp_days = [release_date(m, releases) - timedelta(days=1)
                for m in _months(max(first_month, ADP_FIRST_MONTH), last_month)]

    def get(series: str, days: list[date]) -> dict[date, Vintage]:
        return fetch(series, sorted({d for d in days if d < as_of}), cache_dir=cache, today=as_of)

    def latest_of(series: str) -> Vintage:
        return get(series, [latest]).get(latest, {})

    return LaborInputs(
        payems=get("PAYEMS", month_ends + [latest]),
        unrate=get("UNRATE", unrate_ends + [latest]) if unrate_from is not None else {},
        adp=get("ADPMNUSNERSA", adp_days) if with_adp else {},
        icsa=latest_of("ICSA"),
        ccsa=latest_of("CCSA"),
        hires=latest_of("JTSHIL"),
        openings=latest_of("JTSJOL"),
    )


@dataclass(frozen=True)
class Nowcast:
    month: date
    mu: float  # thousands of jobs, first print
    sigma: float
    model: PayrollModel
    features: LaborFeatures


def feature_table(inputs: LaborInputs, months: Sequence[date], releases: Mapping[date, date]) -> dict[date, LaborFeatures]:
    out = {}
    for month in months:
        feats = labor_features(month, payems=inputs.payems, icsa=inputs.icsa, ccsa=inputs.ccsa, hires=inputs.hires,
                               openings=inputs.openings, adp=inputs.adp, release=release_date(month, releases))
        if feats is not None:
            out[month] = feats
    return out


def payroll_nowcasts(
    inputs: LaborInputs,
    targets_months: Sequence[date],
    releases: Mapping[date, date],
    *,
    train_from: date,
    features: Sequence[str] = CORE_FEATURES,
) -> dict[date, Nowcast]:
    """Walk-forward nowcast of each target month, fit only on months before it."""
    table = feature_table(inputs, _months(train_from, max(targets_months)), releases)
    prints = first_prints(inputs.payems)
    out = {}
    for month in targets_months:
        feats = table.get(month)
        if feats is None:
            continue
        model = fit_payroll_model(training_rows(table, prints, before=month), features)
        out[month] = Nowcast(month, model.predict(feats.values), model.sigma, model, feats)
    return out

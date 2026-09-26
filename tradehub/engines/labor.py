"""labor_nowcast engine (pure): P(first-print payrolls > strike) for Kalshi KXPAYROLLS.

Kalshi settles on the BLS *first print* of the seasonally adjusted change in
nonfarm payrolls ("revisions ... after Expiration will not be accounted
for"), so the model is trained on ALFRED first-release vintages, never on
revised history. The nowcast is a small ridge regression on inputs that were
public by the end of the reference month; its residual spread sets sigma.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, parse_market, prob_in_interval

LABOR_ENGINE_VERSION = "labor-v1"
PAYROLL_SERIES = "KXPAYROLLS"
U3_SERIES = "KXU3"
PAYROLL_RESOLUTION = 1000.0  # BLS prints the payroll change in whole thousands of jobs
U3_RESOLUTION = 0.1  # percentage points
COVID_EXCLUDED = (date(2020, 3, 1), date(2021, 6, 1))  # inclusive; months dropped from training
POST_2021 = date(2021, 7, 1)
GHOST_DISCOUNT = 0.5  # weight on JOLTS openings after 2021 ("ghost jobs")
TRAIN_START = date(2010, 1, 1)
MIN_TRAIN_ROWS = 24
RIDGE_LAMBDA = 20.0
SIGMA_WINDOW = 36
MIN_PAYROLL_SIGMA = 40.0  # thousands
JOLTS_LAG_DAYS = 40
CORE_FEATURES = ("pay_last", "pay_3m", "icsa_ref_chg", "ccsa_ref_chg")
ALL_FEATURES = CORE_FEATURES + ("adp_chg", "adp_missing", "jolts_hires_3m", "ghost_gap_3m", "post_2021")

_ET = ZoneInfo("America/New_York")
_STRIKE_SUFFIX = re.compile(r"-T(-?\d+(?:\.\d+)?)$")

Vintage = Mapping[date, float]  # observation month -> value, as published on one vintage date


# ── months ───────────────────────────────────────────────────────────────────

def add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def month_end(month: date) -> date:
    return add_months(month, 1) - timedelta(days=1)


def end_of_day_et(day: date) -> datetime:
    return datetime.combine(day, time(23, 59), _ET)


RELEASE_TIME_ET = time(8, 30)
DECISION_LEAD = timedelta(hours=1)


def _release_moment(market: KalshiMarket) -> datetime:
    release_day = market.close_time.astimezone(_ET).date()
    return datetime.combine(release_day, RELEASE_TIME_ET, _ET).astimezone(market.close_time.tzinfo)


def pre_release_time(market: KalshiMarket) -> datetime:
    """The market's close, but never after the 8:30 ET release on its closing day.

    Most ladders close at 8:25/8:29 ET; a few (e.g. KXPAYROLLS-26JAN, closed
    10:00 ET) kept trading after the number was out.
    """
    return min(market.close_time, _release_moment(market) - timedelta(minutes=1))


def decision_time(market: KalshiMarket) -> datetime:
    """One hour before min(close, 8:30 ET release): 7:29 ET for a normal 8:29 close."""
    return min(market.close_time, _release_moment(market)) - DECISION_LEAD


# ── Kalshi markets ───────────────────────────────────────────────────────────

def labor_market(raw: dict[str, Any]) -> KalshiMarket:
    """parse_market, tolerating older rows with no strike fields (the ticker's -T<k> is a 'greater' floor)."""
    if raw.get("strike_type") is None or raw.get("floor_strike") is None:
        match = _STRIKE_SUFFIX.search(raw["ticker"])
        if match is None:
            raise ValueError(f"no strike in {raw['ticker']!r}")
        raw = {**raw, "strike_type": "greater", "floor_strike": float(match.group(1))}
    return parse_market(raw)


def greater_threshold(floor: float, resolution: float) -> float:
    """Continuous cut for 'strictly greater than floor' on a value printed on a `resolution` grid.

    Kalshi floors sit on the grid (200000, 4.1 -- sometimes stored as 4.099999)
    or one unit below it (199999 means "200,000 or above"). Floats within 1e-4
    grid units of a grid point snap to it; anything else rounds down.
    """
    units = floor / resolution
    nearest = round(units)
    base = nearest if abs(units - nearest) < 1e-4 else math.floor(units)
    return (base + 0.5) * resolution


def payroll_prob(market: KalshiMarket, mu_k: float, sigma_k: float) -> float:
    """P(YES) for a KXPAYROLLS 'greater' market; mu/sigma are in thousands of jobs, strikes in jobs."""
    if market.strike_type != "greater":
        raise ValueError(f"unsupported strike_type {market.strike_type!r} for {market.ticker}")
    cut_k = greater_threshold(market.floor_strike, PAYROLL_RESOLUTION) / 1000.0
    return prob_in_interval(mu_k, sigma_k, (cut_k, math.inf))


def parse_expiration_value(value: Any) -> float | None:
    """Kalshi's expiration_value comes as '162000', '119,000', '-23000', '4.10', '4.4%' or ''."""
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    return float(text) if text else None


# ── ALFRED vintages -> first prints and revisions ──────────────────────────────

def _change(vintage: Vintage, month: date) -> float | None:
    prev = add_months(month, -1)
    if month in vintage and prev in vintage:
        return vintage[month] - vintage[prev]
    return None


def first_prints(vintages: Mapping[date, Vintage], *, change: bool = True) -> dict[date, float]:
    """{month: its value in the vintage where it first appeared} -- the first print.

    Only months newer than the previous vintage's newest month count, so the
    back history inside the earliest vintage (already revised) is never
    mistaken for a first print. change=True gives the month-over-month change
    (payrolls); False gives the level (unemployment rate).
    """
    out: dict[date, float] = {}
    newest: date | None = None
    for _, vintage in sorted(vintages.items()):
        if not vintage:
            continue
        top = max(vintage)
        fresh = [top] if newest is None else [m for m in vintage if newest < m <= top]
        for month in fresh:
            value = _change(vintage, month) if change else vintage[month]
            if value is not None:
                out[month] = value
        newest = top if newest is None else max(newest, top)
    return out


@dataclass(frozen=True)
class EstimatePath:
    first: float | None = None
    first_vintage: date | None = None
    second: float | None = None
    second_vintage: date | None = None
    third: float | None = None
    third_vintage: date | None = None
    benchmark: float | None = None
    benchmark_vintage: date | None = None
    latest: float | None = None
    latest_vintage: date | None = None


def estimate_path(vintages: Mapping[date, Vintage], month: date, *, change: bool = True) -> EstimatePath:
    """First print, 2nd and 3rd monthly estimates, first annual benchmark, and latest value of one month.

    The k-th estimate is the value in the first vintage whose newest month is
    at least month + (k-1). The benchmark is the value in the first vintage
    dated on/after Feb 20 of the following year (BLS benchmarks in the
    February release).
    """
    ordered = sorted(vintages.items())

    def value(vintage: Vintage) -> float | None:
        return _change(vintage, month) if change else vintage.get(month)

    def first_where(predicate) -> tuple[float | None, date | None]:
        for vintage_date, vintage in ordered:
            if vintage and predicate(vintage_date, vintage):
                found = value(vintage)
                if found is not None:
                    return found, vintage_date
        return None, None

    first = first_where(lambda _d, v: max(v) >= month)
    earliest = [v for _, v in ordered if v]
    if earliest and max(earliest[0]) > month:  # already revised in the oldest vintage we hold
        first = (None, None)
    second = first_where(lambda _d, v: max(v) >= add_months(month, 1))
    third = first_where(lambda _d, v: max(v) >= add_months(month, 2))
    bench = first_where(lambda d, _v: d >= date(month.year + 1, 2, 20))
    latest: tuple[float | None, date | None] = (None, None)
    for vintage_date, vintage in reversed(ordered):
        found = value(vintage)
        if found is not None:
            latest = (found, vintage_date)
            break
    return EstimatePath(first[0], first[1], second[0], second[1], third[0], third[1],
                        bench[0], bench[1], latest[0], latest[1])



# ── point-in-time features ───────────────────────────────────────────────────

@dataclass(frozen=True)
class LaborFeatures:
    month: date
    values: dict[str, float]
    sources: tuple[Observation, ...]  # every input with the moment it became public


def _reference_week(series: Mapping[date, float], month: date, publish_lag_days: int,
                    as_of: datetime) -> tuple[date, float] | None:
    """Latest weekly value for a week ending on/before the 12th-18th reference Saturday and public by `as_of`."""
    candidates = [
        week for week in series
        if week <= date(month.year, month.month, 18)
        and datetime.combine(week + timedelta(days=publish_lag_days), time(8, 30), _ET) <= as_of
    ]
    if not candidates:
        return None
    week = max(candidates)
    return week, series[week]


def _weekly_obs(name: str, week: date, value: float, lag: int) -> Observation:
    return Observation(f"{name}:{week.isoformat()}", value,
                       datetime.combine(week + timedelta(days=lag), time(8, 30), _ET))


def labor_features(
    month: date,
    *,
    payems: Mapping[date, Vintage],
    icsa: Mapping[date, Vintage],
    ccsa: Mapping[date, Vintage],
    hires: Mapping[date, Vintage],
    openings: Mapping[date, Vintage],
    adp: Mapping[date, Vintage],
    release: date,
) -> LaborFeatures | None:
    """Features for reference month `month`, using only what was public by the end of that month.

    EVERY series is keyed by the vintage it is read from, and the vintage used is always
    `month_end(month)` — the same rule for claims and JOLTS as for payrolls. Reading the weekly
    series from one latest vintage instead would describe every historical month with data
    revised months or years later, and the leakage guard cannot see it: the Observation
    timestamps are the weeks' nominal publication dates, which are honest-looking, while the
    values behind them came from a later vintage.

    A missing month_end vintage returns None (a feature gap the caller must handle) rather than
    falling back on today's data. ADP for `month` itself comes from the vintage the day before
    the jobs release (ADP publishes two days earlier).
    """
    vintage_day = month_end(month)
    as_of = end_of_day_et(vintage_day)
    pay = payems.get(vintage_day)
    if not pay:
        return None
    latest = max(pay)
    changes = [_change(pay, add_months(latest, -k)) for k in range(3)]
    if any(c is None for c in changes):
        return None
    sources = [Observation(f"PAYEMS@{vintage_day.isoformat()}:{latest.isoformat()}", pay[latest], as_of)]
    icsa_v, ccsa_v = icsa.get(vintage_day), ccsa.get(vintage_day)
    hires_v, openings_v = hires.get(vintage_day), openings.get(vintage_day)
    if not icsa_v or not ccsa_v:
        return None
    icsa_now = _reference_week(icsa_v, month, 5, as_of)
    icsa_prev = _reference_week(icsa_v, add_months(month, -1), 5, as_of)
    ccsa_now = _reference_week(ccsa_v, month, 12, as_of)
    ccsa_prev = None
    if ccsa_now is not None:
        week_prev = ccsa_now[0] - timedelta(days=28)
        if week_prev in ccsa_v:
            ccsa_prev = (week_prev, ccsa_v[week_prev])
    if icsa_now is None or icsa_prev is None or ccsa_now is None or ccsa_prev is None:
        return None
    for name, lag, point in (("ICSA", 5, icsa_now), ("ICSA", 5, icsa_prev), ("CCSA", 12, ccsa_now), ("CCSA", 12, ccsa_prev)):
        sources.append(_weekly_obs(name, point[0], point[1], lag))

    jolts_known = [m for m in (hires_v or {}) if m in (openings_v or {})
                   and end_of_day_et(month_end(m) + timedelta(days=JOLTS_LAG_DAYS)) <= as_of]
    hires_3m = ghost_3m = 0.0
    if jolts_known:
        j = max(jolts_known)
        j3 = add_months(j, -3)
        if j3 in hires_v and j3 in openings_v:
            def gap(m: date) -> float:
                weight = GHOST_DISCOUNT if m >= POST_2021 else 1.0
                return weight * openings_v[m] - hires_v[m]
            hires_3m = hires_v[j] - hires_v[j3]
            ghost_3m = gap(j) - gap(j3)
            sources.append(Observation(f"JTSHIL:{j.isoformat()}", hires_v[j],
                                       end_of_day_et(month_end(j) + timedelta(days=JOLTS_LAG_DAYS))))

    adp_vintage_day = release - timedelta(days=1)
    adp_values = adp.get(adp_vintage_day) or {}
    adp_change = _change(adp_values, month) if month == max(adp_values, default=None) else None
    if adp_change is not None:
        sources.append(Observation(f"ADP@{adp_vintage_day.isoformat()}:{month.isoformat()}",
                                   adp_values[month], end_of_day_et(adp_vintage_day)))

    values = {
        "pay_last": changes[0],
        "pay_3m": sum(changes) / 3.0,
        "icsa_ref_chg": (icsa_now[1] - icsa_prev[1]) / 1000.0,
        "ccsa_ref_chg": (ccsa_now[1] - ccsa_prev[1]) / 1000.0,
        "adp_chg": 0.0 if adp_change is None else adp_change,
        "adp_missing": 1.0 if adp_change is None else 0.0,
        "jolts_hires_3m": hires_3m,
        "ghost_gap_3m": ghost_3m,
        "post_2021": 1.0 if month >= POST_2021 else 0.0,
    }
    return LaborFeatures(month, values, tuple(sources))


# ── ridge nowcast ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PayrollModel:
    features: tuple[str, ...]
    center: tuple[float, ...]
    scale: tuple[float, ...]
    intercept: float
    coef: tuple[float, ...]
    sigma: float
    n_train: int

    def predict(self, values: Mapping[str, float]) -> float:
        z = [(values[f] - c) / s for f, c, s in zip(self.features, self.center, self.scale)]
        return self.intercept + float(np.dot(self.coef, z))


def is_trainable(month: date) -> bool:
    return month >= TRAIN_START and not (COVID_EXCLUDED[0] <= month <= COVID_EXCLUDED[1])


def fit_payroll_model(
    rows: Sequence[tuple[LaborFeatures, float]],
    features: Sequence[str] = CORE_FEATURES,
    lam: float = RIDGE_LAMBDA,
) -> PayrollModel:
    """Ridge on standardized features; sigma = RMS of the last SIGMA_WINDOW in-sample residuals."""
    usable = sorted((r for r in rows if is_trainable(r[0].month)), key=lambda r: r[0].month)
    if len(usable) < MIN_TRAIN_ROWS:
        raise ValueError(f"need >= {MIN_TRAIN_ROWS} training months, got {len(usable)}")
    x = np.array([[feats.values[f] for f in features] for feats, _ in usable], dtype=float)
    y = np.array([target for _, target in usable], dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    z = (x - center) / scale
    intercept = float(y.mean())
    coef = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - intercept))
    residuals = y - (intercept + z @ coef)
    recent = residuals[-SIGMA_WINDOW:]
    sigma = max(MIN_PAYROLL_SIGMA, float(np.sqrt(np.mean(recent ** 2))))
    return PayrollModel(tuple(features), tuple(center.tolist()), tuple(scale.tolist()), intercept,
                        tuple(coef.tolist()), sigma, len(usable))


def training_rows(
    features_by_month: Mapping[date, LaborFeatures],
    targets: Mapping[date, float],
    before: date,
) -> list[tuple[LaborFeatures, float]]:
    """(features, first print) for months strictly before `before` -- walk-forward safe."""
    return [(features_by_month[m], targets[m]) for m in sorted(features_by_month)
            if m < before and m in targets]

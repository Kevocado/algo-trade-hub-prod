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
from typing import Any, Mapping
from zoneinfo import ZoneInfo

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

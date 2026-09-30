"""Wave 2 daily-direction forecasters (v2 spec §8): VIX, Gold, EUR/USD.

All three share the same freeze cadence (08:00 CT, 3h lead before market close) and settlement
logic (next session's close). The infrastructure lives in `tradehub/journal/daily.py`.

- VIX: FRED `VIXCLS` daily close — already available on the VPS FRED key.
- Gold: Stooq `XAUUSD` daily close (Yahoo: GC=F; Stooq preferred per spec).
- EUR/USD: Stooq `EURUSD` daily close.

Naive baseline: previous-close persistence + climatology. A production model must beat its own
baseline's posted Brier to graduate from provisional.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.data.stooq import fetch_stooq_daily
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.nyse import is_session, next_session
from tradehub.journal.spx import (
    CT,
    FREEZE_LEAD,
    FREEZE_TIME_CT,
    HISTORY_DAYS,
    CLIMATOLOGY_BOUNDS,
    CLIMATOLOGY_SESSIONS,
    SpxCloses,
    freeze_at,
    next_target_day,
)

# ---------------------------------------------------------------------------
# Generic daily-direction target plumbing (lives in daily.py)
# ---------------------------------------------------------------------------

DAILY_LOOKBACK_DAYS = 1920  # ~8 years for Stooq / FRED
DAILY_FAMILIES = {"vix": "VIX", "gold": "GOLD", "eurusd": "EURUSD"}


@dataclass(frozen=True)
class DailySeries:
    """A daily close series with a family tag for target naming."""
    family: str
    series_id: str  # FRED ID or Stooq symbol
    source: str  # "fred" or "stooq"


# FRED-based series (VIX)
VIX_SERIES = DailySeries("vix", "VIXCLS", "fred")
# Stooq-based series (Gold, EUR/USD)
GOLD_SERIES = DailySeries("gold", "XAUUSD", "stooq")
EURUSD_SERIES = DailySeries("eurusd", "EURUSD", "stooq")


def daily_target(series: DailySeries, day: date) -> str:
    return f"{series.family}:{day.isoformat()}:up"


def daily_target_day(target: str) -> tuple[str, date]:
    parts = target.split(":")
    return parts[0], date.fromisoformat(parts[1])


def daily_entry(now: datetime, closes: "DailyCloses", series: DailySeries) -> list[CalendarEntry]:
    """Register the next daily-direction target if its freeze is within the freeze lead."""
    day = next_target_day(now)
    if day is None:
        return []
    closes_for_month = closes.get(now, series)
    clim = daily_climatology(closes_for_month, day)
    return [CalendarEntry(daily_target(series, day), series.family, "daily", freeze_at(day),
                          climatology_prob=clim)]


def daily_climatology(closes: Mapping[date, float], before: date) -> float | None:
    days = sorted(d for d in closes if d < before)[-(CLIMATOLOGY_SESSIONS + 1):]
    if len(days) < 253:
        return None
    ups = [closes[b] > closes[a] for a, b in pairwise(days)]
    lo, hi = CLIMATOLOGY_BOUNDS
    return min(hi, max(lo, sum(ups) / len(ups)))


def daily_outcome(closes: Mapping[date, float], day: date) -> int | None:
    if day not in closes:
        return None
    earlier = [d for d in closes if d < day]
    return int(closes[day] > closes[max(earlier)]) if earlier else None


def settle_daily(target: str, closes: Mapping[date, float], now: datetime) -> Settlement | None:
    family, day = daily_target_day(target)
    outcome = daily_outcome(closes, day) if is_session(day) else None
    if outcome is None:
        return None
    return Settlement(target, outcome, f"{'fred' if family == 'vix' else 'stooq'}:{daily_series_for(family)}",
                    realized_value=closes[day])


def daily_series_for(family: str) -> str:
    return {"vix": "VIXCLS", "gold": "XAUUSD", "eurusd": "EURUSD"}[family]


# ---------------------------------------------------------------------------
# Shared daily closes cache
# ---------------------------------------------------------------------------


class DailyCloses:
    """FRED / Stooq closes for a given series, fetched at most once per hourly run."""

    def __init__(self, fred: Callable[..., Mapping[date, float]] = fetch_fred_daily,
                 stooq: Callable[..., Mapping[date, float]] = fetch_stooq_daily):
        self._fred, self._stooq = fred, stooq
        self._hour: datetime | None = None
        self._cache: dict[str, Mapping[date, float]] = {}

    def get(self, now: datetime, series: DailySeries) -> Mapping[date, float]:
        hour = now.astimezone(CT).replace(minute=0, second=0, microsecond=0)
        key = f"{series.source}:{series.series_id}"
        if self._hour != hour or key not in self._cache:
            start = hour.date() - timedelta(days=DAILY_LOOKBACK_DAYS)
            if series.source == "fred":
                self._cache = {key: self._fred(series.series_id, start)}
            else:
                self._cache[key] = self._stooq(series.series_id, start)
            self._hour = hour
        return self._cache[key]


# ---------------------------------------------------------------------------
# Naive baselines: persistence + climatology
# ---------------------------------------------------------------------------

PERSISTENCE_BLEND = 0.33  # weight on yesterday's direction (rest is climatology)


def baseline_prob(closes: Mapping[date, float], day: date) -> float | None:
    """P(up tomorrow) = blend of yesterday's direction and climatology."""
    clim = daily_climatology(closes, day)
    earlier = sorted(d for d in closes if d < day)
    if not earlier or clim is None:
        return None
    prev = earlier[-1]
    persistence = 1.0 if closes[prev] > (closes[max(d for d in earlier if d < prev)] if len(earlier) >= 2
                                          else float("-inf")) else 0.0
    return PERSISTENCE_BLEND * persistence + (1 - PERSISTENCE_BLEND) * clim


# ---------------------------------------------------------------------------
# Wave 2 forecasters
# ---------------------------------------------------------------------------


class VixForecaster:
    """VIX next-day direction, FRED VIXCLS (spec §8)."""
    name = "vix_direction"
    version = "v1"
    cadence = "daily"

    def __init__(self, closes: DailyCloses | None = None):
        self._closes = closes or DailyCloses()
        self._series = VIX_SERIES

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes, self._series)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = daily_target_day(entry.target)[1]
        closes = self._closes.get(now, self._series)
        # Filter to only observations strictly before target day
        obs = {d: c for d, c in closes.items() if d < day}
        prob = baseline_prob(obs, day)
        if prob is None:
            return None
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"baseline": "persistence+climatology", "provisional": True})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        closes = self._closes.get(now, self._series)
        return settle_daily(target, closes, now)


class GoldForecaster:
    """Gold next-day direction, Stooq XAUUSD (spec §8)."""
    name = "gold_direction"
    version = "v1"
    cadence = "daily"

    def __init__(self, closes: DailyCloses | None = None):
        self._closes = closes or DailyCloses()
        self._series = GOLD_SERIES

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes, self._series)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = daily_target_day(entry.target)[1]
        closes = self._closes.get(now, self._series)
        obs = {d: c for d, c in closes.items() if d < day}
        prob = baseline_prob(obs, day)
        if prob is None:
            return None
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"baseline": "persistence+climatology", "provisional": True})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        closes = self._closes.get(now, self._series)
        return settle_daily(target, closes, now)


class EurusdForecaster:
    """EUR/USD next-day direction, Stooq EURUSD (spec §8)."""
    name = "eurusd_direction"
    version = "v1"
    cadence = "daily"

    def __init__(self, closes: DailyCloses | None = None):
        self._closes = closes or DailyCloses()
        self._series = EURUSD_SERIES

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes, self._series)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = daily_target_day(entry.target)[1]
        closes = self._closes.get(now, self._series)
        obs = {d: c for d, c in closes.items() if d < day}
        prob = baseline_prob(obs, day)
        if prob is None:
            return None
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"baseline": "persistence+climatology", "provisional": True})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        closes = self._closes.get(now, self._series)
        return settle_daily(target, closes, now)

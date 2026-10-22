"""ERCOT daily peak-demand forecaster (KXTXERCOTPEAKD), graded against the market and a weekday baseline.

The target is the highest hourly total system load ERCOT reports for the operating day. The model
(`ercot_peak`, `ls-v1`) is a plain least-squares regression of the peak on the population-weighted
daily max temperature, its square (the heat and cold curve), a weekend flag, a holiday flag and a
linear year trend; the residual standard deviation is the Normal sigma. It refits monthly on days
strictly before the target's month, so nothing from the target month -- let alone the target day -- is
ever used. Each market is one rung of a 500 MW "above N MW" ladder; every rung is graded (a ladder is a
single distribution, not independent bets).

Beside it the journal grades the Kalshi mid on the same contract (`KalshiImplied`) and a same-weekday
baseline (`baseline_climatology_ercot_peak`): the empirical share of the past four same-weekday peaks
above the strike. All settle on Kalshi's own result.

ponytail: no fitted temperature bias, no ensemble spread, one temperature with fixed metro weights.
Fit those (a new version) once a few hundred contracts have settled.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from tradehub.backtest.http import default_get_json, default_get_text
from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.ercot import (
    FIRST_DAY,
    MIN_DAHEAD_TRAIN,
    central_today,
    fetch_forecast_temps,
    fetch_historical_temps,
    load_day_ahead_forecast,
    load_peaks,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.baselines import CLIMATOLOGY, baseline_name
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.journal.nyse import holidays
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

FAMILY = "ercot_peak"
SERIES = "KXTXERCOTPEAKD"
VERSION = "ls-v1"
MW_RESOLUTION = 0.0      # MW settle continuously; "above N" is YES for load > N
MIN_LEAD = timedelta(hours=20)   # freeze near the start of the operating day, before the morning ramp
MIN_TRAIN = 20           # fewer past days than this is a gap, never a made-up fit
SIGMA_FLOOR = 1.0        # MW; a zero-variance fit must not divide by zero
TEMP_CENTER = 70.0       # conditioning: center and scale the temperature feature for lstsq
TEMP_SCALE = 20.0
EPOCH = date(2024, 1, 1)
BASELINE_WEEKS = 4

# Day-ahead forecast feature (ls-v2): ERCOT's published day-ahead load forecast peak MW
DAHEAD_CENTER = 70000.0   # MW; the centre of ERCOT's day-ahead forecast range
DAHEAD_SCALE = 10000.0    # MW; its scale, so the column is O(1)


def operating_day(market: KalshiMarket) -> date:
    """The day whose peak the market settles: the ticker's date is the settlement day, one day later."""
    return event_date(market.event_ticker) - timedelta(days=1)


def is_holiday(day: date) -> bool:
    """A US market holiday; ERCOT demand drops on these, and they are ERCOT's low-load days too."""
    return day in holidays(day.year)


def features(temp: float, day: date) -> list[float]:
    """[1, z, z^2, weekend, holiday, years] for a population-weighted max temperature `temp` (F)."""
    z = (temp - TEMP_CENTER) / TEMP_SCALE
    return [1.0, z, z * z, 1.0 if day.weekday() >= 5 else 0.0, 1.0 if is_holiday(day) else 0.0,
            (day - EPOCH).days / 365.25]


def fit(samples: Iterable[tuple[date, float, float]]) -> tuple[list[float], float]:
    """Least-squares (beta, sigma) from (day, peak MW, max-temp F) rows; sigma is the residual SD."""
    rows = [(d, float(p), float(t)) for d, p, t in samples]
    if len(rows) < MIN_TRAIN:
        raise ValueError(f"need at least {MIN_TRAIN} training days, got {len(rows)}")
    matrix = np.array([features(t, d) for d, _p, t in rows], dtype=float)
    target = np.array([p for _d, p, _t in rows], dtype=float)
    beta, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    residual = target - matrix @ beta
    dof = max(len(rows) - matrix.shape[1], 1)
    sigma = math.sqrt(float(residual @ residual) / dof)
    return beta.tolist(), max(sigma, SIGMA_FLOOR)


def mean_load(beta: list[float], temp: float, day: date) -> float:
    return float(sum(b * x for b, x in zip(beta, features(temp, day), strict=True)))


def prob_for(market: KalshiMarket, temp: float, day: date, beta: list[float], sigma: float) -> float:
    """P(peak > the market's strike): the Normal tail above the fitted mean."""
    return prob_in_interval(mean_load(beta, temp, day), sigma, yes_interval(market, MW_RESOLUTION))


# ── ls-v2: ls-v1's regression plus ERCOT's own published day-ahead load forecast ───
# A separate feature set and fit, so ls-v1 stays byte-for-byte what it always was.
# The day-ahead column is only trained on days where we have a recorded (cached) value.
def features_v2(temp: float, day: date, dahead: float | None) -> list[float]:
    """ls-v1's features plus the day-ahead forecast peak, centred and scaled.

    `dahead` is ERCOT's recorded day-ahead forecast peak MW for the operating day.
    It is None when no cached value exists for that day; the column is left at the
    centre (dahead_z = 0), so the model is exactly ls-v1 for that row.
    """
    z = (temp - TEMP_CENTER) / TEMP_SCALE
    dahead_z = 0.0 if dahead is None else (dahead - DAHEAD_CENTER) / DAHEAD_SCALE
    return [1.0, z, z * z, 1.0 if day.weekday() >= 5 else 0.0, 1.0 if is_holiday(day) else 0.0,
            (day - EPOCH).days / 365.25, dahead_z]


def fit_v2(samples: Iterable[tuple[date, float, float, float | None]]) -> tuple[list[float], float]:
    """Least squares over (day, peak MW, max-temp F, day-ahead MW or None) rows."""
    rows = [(d, float(p), float(t), da) for d, p, t, da in samples]
    if len(rows) < MIN_TRAIN:
        raise ValueError(f"need at least {MIN_TRAIN} training days, got {len(rows)}")
    matrix = np.array([features_v2(t, d, da) for d, _p, t, da in rows], dtype=float)
    target = np.array([p for _d, p, _t, _da in rows], dtype=float)
    beta, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    residual = target - matrix @ beta
    dof = max(len(rows) - matrix.shape[1], 1)
    sigma = math.sqrt(float(residual @ residual) / dof)
    return beta.tolist(), max(sigma, SIGMA_FLOOR)


def mean_load_v2(beta: list[float], temp: float, day: date, dahead: float | None) -> float:
    return float(sum(b * x for b, x in zip(beta, features_v2(temp, day, dahead), strict=True)))


def prob_for_v2(market: KalshiMarket, temp: float, day: date, beta: list[float], sigma: float,
                 dahead: float | None) -> float:
    """P(peak > the market's strike) under ls-v2."""
    return prob_in_interval(mean_load_v2(beta, temp, day, dahead), sigma,
                            yes_interval(market, MW_RESOLUTION))


class ErcotInputs:
    """ERCOT peaks, Open-Meteo temperatures, and cached day-ahead forecasts."""

    def __init__(self, *, get_json: Callable[..., Any] = default_get_json,
                 get_text: Callable[..., Any] = default_get_text, cache_dir=None):
        self._get_json, self._get_text, self._cache = get_json, get_text, cache_dir
        self._peaks: dict[date, float] | None = None
        self._temps: dict[date, float] | None = None
        self._forecast: dict[date, float] | None = None
        self._dahead: dict[date, float] | None = None

    def _load(self) -> None:
        today = central_today()
        if self._peaks is None:
            self._peaks = load_peaks(FIRST_DAY, today, get_text=self._get_text, cache_dir=self._cache, today=today)
        if self._temps is None:
            self._temps = fetch_historical_temps(FIRST_DAY, today, get_json=self._get_json)

    def peaks(self, first: date, last: date) -> dict[date, float]:
        self._load()
        return {d: v for d, v in self._peaks.items() if first <= d <= last}

    def temp(self, day: date, now: datetime) -> float | None:
        self._load()
        if self._forecast is None:
            self._forecast = fetch_forecast_temps(get_json=self._get_json)
        return self._forecast.get(day, self._temps.get(day))

    def dahead(self, day: date) -> float | None:
        """Cached day-ahead forecast peak MW for `day`, or None if not yet recorded.

        ERCOT publishes no archive of past day-ahead forecasts. We record each day's
        forecast as it's published (first value wins, frozen). This returns the cached
        value, or None if we haven't recorded that day yet.
        """
        if self._dahead is None:
            self._dahead = load_day_ahead_forecast(get_json=self._get_json, cache_dir=self._cache)
        return self._dahead.get(day)

    def history(self, day: date, now: datetime) -> dict[date, tuple[float, float]]:
        self._load()
        peaks = {d: v for d, v in self._peaks.items() if d < day}
        return {d: (p, self._temps[d]) for d, p in peaks.items() if d in self._temps}

    def history_v2(self, day: date, now: datetime) -> dict[date, tuple[float, float, float | None]]:
        """History including day-ahead forecast for ls-v2 training.

        Only days where we have a cached day-ahead value are included (so the column
        is never constant-zero). Returns {day: (peak, temp, dahead)}.
        """
        self._load()
        dahead_map = self._dahead or load_day_ahead_forecast(get_json=self._get_json, cache_dir=self._cache)
        peaks = {d: v for d, v in self._peaks.items() if d < day}
        out: dict[date, tuple[float, float, float | None]] = {}
        for d, p in peaks.items():
            if d in self._temps and d in dahead_map:
                out[d] = (p, self._temps[d], dahead_map[d])
        return out


class _ErcotBase:
    cadence = "daily"

    def __init__(self, live, fetch: Callable[[str], Any], inputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(SERIES)
                      if in_freeze_window(lm, now) and lm.market.close_time - now >= MIN_LEAD}
        return [entry_for(lm, self.name, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class ErcotPeak(_ErcotBase):
    name, version = FAMILY, VERSION

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        day = operating_day(lm.market)
        target_temp = self._inputs.temp(day, now)
        samples = [(d, p, t) for d, (p, t) in self._inputs.history(day, now).items()
                   if d < day.replace(day=1)]   # monthly refit: strictly before the target's month
        if target_temp is None or len(samples) < MIN_TRAIN:
            return None
        beta, sigma = fit(samples)
        return Forecast(self.name, self.version, entry.target, prob_for(lm.market, target_temp, day, beta, sigma),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "operating_day": day.isoformat(),
                                 "target_temp_f": round(target_temp, 2), "n_train": len(samples),
                                 "sigma_mw": round(sigma, 1)})


class ErcotPeakV2(_ErcotBase):
    """`ercot_peak` version `ls-v2`: ls-v1's regression plus ERCOT's cached day-ahead load forecast.

    Ships BESIDE ls-v1, never replacing it. The day-ahead feature is only trained on days
    where we have a recorded (cached) day-ahead value. Returns None until >= MIN_DAHEAD_TRAIN
    recorded days exist. ERCOT publishes no archive, so the cache builds prospectively.
    """
    name, version = FAMILY, "ls-v2"

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        day = operating_day(lm.market)
        target_temp = self._inputs.temp(day, now)
        target_dahead = self._inputs.dahead(day)
        # Only train on days where we have a recorded day-ahead value
        samples = [(d, p, t, da) for d, (p, t, da) in self._inputs.history_v2(day, now).items()
                   if d < day.replace(day=1)]   # monthly refit: strictly before the target's month
        if target_temp is None or len(samples) < MIN_DAHEAD_TRAIN:
            return None
        beta, sigma = fit_v2(samples)
        return Forecast(self.name, self.version, entry.target,
                        prob_for_v2(lm.market, target_temp, day, beta, sigma, target_dahead),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "operating_day": day.isoformat(),
                                 "target_temp_f": round(target_temp, 2), "n_train": len(samples),
                                 "sigma_mw": round(sigma, 1),
                                 "dahead_mw": round(target_dahead, 1) if target_dahead is not None else None,
                                 "basis": "ls-v1 regression plus ERCOT cached day-ahead load forecast"})


class ErcotClimatology(_ErcotBase):
    version = "v1"

    def __init__(self, live, fetch, inputs):
        super().__init__(live, fetch, inputs)
        self.name = baseline_name(CLIMATOLOGY, FAMILY)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None or lm.market.floor_strike is None:
            return None
        day = operating_day(lm.market)
        window = self._inputs.peaks(day - timedelta(days=7 * BASELINE_WEEKS), day - timedelta(days=7))
        same = {d: p for d, p in window.items() if d.weekday() == day.weekday()}
        if not same:
            return None
        hits = sum(1 for p in same.values() if p > lm.market.floor_strike)
        return Forecast(self.name, self.version, entry.target, (hits + 0.5) / (len(same) + 1),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "operating_day": day.isoformat(), "n_weeks": len(same),
                                 "basis": f"same weekday, past {BASELINE_WEEKS} weeks"})


def build_ercot(live, fetch: Callable[[str], Any] = fetch_market, inputs: ErcotInputs | None = None) -> list:
    inputs = inputs or ErcotInputs()
    return [ErcotPeak(live, fetch, inputs),
            ErcotPeakV2(live, fetch, inputs),
            KalshiImplied(FAMILY, (SERIES,), "daily", live, fetch),
            ErcotClimatology(live, fetch, inputs)]

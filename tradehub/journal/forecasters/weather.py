"""Kalshi daily weather markets (highs, lows, rain), forecast from NOAA and ECMWF ensembles.

For each open market inside the journal's 24h freeze window, the forecast is the share of ensemble members
that land in the market's YES range: each member's climate-day high or low is smoothed by a fixed Normal
kernel (KERNEL_SIGMA, set before any result was seen; a different value is a new version), and rain is the
share of members with a reportable total. Beside it the journal grades the Kalshi mid on the same contract
(KalshiImplied) and a climatology baseline from the station's own history, the same week in past years.
All three settle on Kalshi's result.

ponytail: no bias correction or fitted spread; ens-v1 is the raw ensemble. Fit both walk-forward from
journal results (a new version) once a few hundred contracts have settled.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tradehub.backtest.http import default_get_json
from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.acis import fetch_station, parse_station
from tradehub.data.ensemble import MODELS, day_members, fetch_ensemble, parse_members
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
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

VERSION = "ens-v1"
KERNEL_SIGMA = 2.0       # degrees F
RAIN_MEASURABLE = 0.005  # inches; reported to 0.01, and a trace settles NO
CLIMATOLOGY_YEARS = 30
CLIMATOLOGY_WINDOW = 7   # days either side of the target date
TEMP_RESOLUTION = 1.0
# Freeze only in the first hours of the climate day. Later, part of the day has already been observed and
# the ensemble is "forecasting" a high or low that may already have happened, so a late freeze is a gap.
MIN_LEAD = timedelta(hours=20)

# Series with traded markets on 2026-10-08, and the station each one's rules name (verified from the
# market rules text). KXRAIN is one series across many cities: the station is the ticker suffix,
# except where Kalshi's city code differs from the station id.
STATIONS: dict[str, tuple[str, str]] = {
    "KXHIGHNY": ("high", "NYC"), "KXHIGHLAX": ("high", "LAX"), "KXHIGHPHIL": ("high", "PHL"),
    "KXHIGHTNOLA": ("high", "MSY"),
    "KXLOWTAUS": ("low", "AUS"), "KXLOWTOKC": ("low", "OKC"), "KXLOWTATL": ("low", "ATL"),
    "KXLOWTDEN": ("low", "DEN"), "KXLOWTEWR": ("low", "EWR"), "KXLOWTSDF": ("low", "SDF"),
}
RAIN_SERIES = "KXRAIN"
RAIN_STATION = {"SATX": "SAT", "PHIL": "PHL", "NOLA": "MSY", "MIN": "MSP", "LV": "LAS", "DC": "DCA",
                "DAL": "DFW", "CHI": "ORD"}
KINDS = ("high", "low", "rain")


def series_for(kind: str) -> tuple[str, ...]:
    return (RAIN_SERIES,) if kind == "rain" else tuple(s for s, (k, _sid) in STATIONS.items() if k == kind)


def station_for(market: KalshiMarket) -> str | None:
    if market.series_ticker == RAIN_SERIES:
        suffix = market.ticker.rsplit("-", 1)[-1]
        return RAIN_STATION.get(suffix, suffix)
    found = STATIONS.get(market.series_ticker)
    return found[1] if found else None


def _shrunk_share(hits: int, n: int) -> float:
    """(k + 1/2) / (n + 1): a share that is never exactly 0 or 1, so one surprise cannot cost a Brier of 1."""
    return (hits + 0.5) / (n + 1)


def ensemble_prob(market: KalshiMarket, kind: str, members: list[float]) -> float:
    if kind == "rain":
        return _shrunk_share(sum(v >= RAIN_MEASURABLE for v in members), len(members))
    interval = yes_interval(market, TEMP_RESOLUTION)
    return statistics.fmean(prob_in_interval(v, KERNEL_SIGMA, interval) for v in members)


def climatology_prob(market: KalshiMarket, kind: str, days: dict[date, dict[str, float | None]],
                     target: date) -> float | None:
    """The share of past years' days within +/-CLIMATOLOGY_WINDOW of the target's date that were YES."""
    lo, hi = (0.0, float("inf")) if kind == "rain" else yes_interval(market, TEMP_RESOLUTION)
    hits = n = 0
    for back in range(1, CLIMATOLOGY_YEARS + 1):
        try:
            centre = target.replace(year=target.year - back)
        except ValueError:  # Feb 29
            centre = target.replace(year=target.year - back, day=28)
        for shift in range(-CLIMATOLOGY_WINDOW, CLIMATOLOGY_WINDOW + 1):
            value = (days.get(centre + timedelta(days=shift)) or {}).get(kind)
            if value is None:
                continue
            n += 1
            hits += value >= RAIN_MEASURABLE if kind == "rain" else lo < value < hi
    return _shrunk_share(hits, n) if n else None


def target_day(market: KalshiMarket) -> date:
    return datetime.strptime(market.event_ticker.split("-")[1], "%y%b%d").replace(tzinfo=UTC).date()


class WeatherInputs:
    """Station history and ensembles, each fetched at most once per station per process (one journal run)."""

    def __init__(self, get_json: Callable[..., Any] | None = default_get_json):
        self._get_json = get_json
        self._stations: dict[str, tuple[float, float, dict]] = {}
        self._ensembles: dict[str, Any] = {}

    def _fetch_station(self, sid: str, start: date, end: date) -> dict[str, Any]:
        return fetch_station(sid, start, end, self._get_json)

    def _fetch_ensemble(self, lat: float, lon: float) -> dict[str, Any]:
        return fetch_ensemble(lat, lon, self._get_json)

    def station(self, sid: str, today: date) -> tuple[float, float, dict]:
        if sid not in self._stations:
            start = today.replace(year=today.year - CLIMATOLOGY_YEARS - 1)
            self._stations[sid] = parse_station(self._fetch_station(sid, start, today))
        return self._stations[sid]

    def members(self, sid: str, today: date):
        if sid not in self._ensembles:
            lat, lon, _days = self.station(sid, today)
            self._ensembles[sid] = parse_members(self._fetch_ensemble(lat, lon))
        return self._ensembles[sid]


class _WeatherBase:
    cadence = "daily"

    def __init__(self, kind: str, live, fetch: Callable[[str], Any], inputs: WeatherInputs):
        if kind not in KINDS:
            raise ValueError(f"unknown weather kind {kind!r}")
        self.kind, self._live, self._fetch_market, self._inputs = kind, live, fetch, inputs
        self.family = f"weather_{kind}"
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for s in series_for(self.kind)
                      for lm in self._live.open_markets(s)
                      if in_freeze_window(lm, now) and lm.market.close_time - now >= MIN_LEAD
                      and station_for(lm.market)}
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class WeatherEnsemble(_WeatherBase):
    version = VERSION

    def __init__(self, kind, live, fetch, inputs):
        super().__init__(kind, live, fetch, inputs)
        self.name = self.family

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        sid = station_for(lm.market)
        values = day_members(self._inputs.members(sid, now.date()), lm.market.close_time, self.kind)
        if not values:
            return None
        return Forecast(self.name, self.version, entry.target, ensemble_prob(lm.market, self.kind, values),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "station": sid, "n_members": len(values),
                                 "ensemble_mean": round(statistics.fmean(values), 3), "models": list(MODELS),
                                 "kernel_sigma": KERNEL_SIGMA})


class WeatherClimatology(_WeatherBase):
    version = "v1"

    def __init__(self, kind, live, fetch, inputs):
        super().__init__(kind, live, fetch, inputs)
        self.name = baseline_name(CLIMATOLOGY, self.family)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        sid = station_for(lm.market)
        _lat, _lon, days = self._inputs.station(sid, now.date())
        prob = climatology_prob(lm.market, self.kind, days, target_day(lm.market))
        if prob is None:
            return None
        return Forecast(self.name, self.version, entry.target, prob, market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "station": sid, "years": CLIMATOLOGY_YEARS,
                                 "window_days": CLIMATOLOGY_WINDOW})


def build_weather(live, fetch: Callable[[str], Any] = fetch_market, inputs: WeatherInputs | None = None) -> list:
    inputs = inputs or WeatherInputs()
    out: list = []
    for kind in KINDS:
        out += [WeatherEnsemble(kind, live, fetch, inputs),
                KalshiImplied(f"weather_{kind}", series_for(kind), "daily", live, fetch,
                              keep=lambda lm: station_for(lm.market) is not None),
                WeatherClimatology(kind, live, fetch, inputs)]
    return out

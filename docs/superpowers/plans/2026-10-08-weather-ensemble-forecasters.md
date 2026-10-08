# Weather Ensemble Forecasters (highs, lows, rain) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forecast every traded Kalshi daily weather market (city highs, lows and rain) from the NOAA and ECMWF ensembles, frozen at the start of the climate day and graded in the journal against the Kalshi price and the station's own climatology.

**Architecture:** Two keyless data sources: NOAA ACIS (each station's daily record and its coordinates) and the Open-Meteo ensemble API (82 members: GEFS 0.5 and ECMWF IFS 0.25). A market's climate day is the 24 hours ending at its close, because Kalshi closes each daily weather market at local-standard midnight, so no time-zone table is needed. The model forecaster is the kernel-smoothed share of members whose high or low lands in the YES range, or the share with reportable rain. Beside it run the existing `KalshiImplied` baseline and a new climatology baseline: the same week in the past 30 years at the same station. All settle on Kalshi's own result.

**Tech Stack:** Python 3.12, existing journal stack, pytest; small frontend label change.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 new forecaster families, §10 gates). **Depends on:** nothing (independent).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1,528 passed at both clocks; new files ruff-clean; frontend vitest 328, tsc clean; a live smoke run against the real APIs forecast 24 high, 36 low and 31 rain markets). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`.
- **The data is proven to match settlement.** On 2026-10-08 ACIS station data reproduced Kalshi's result on all 3,996 settled weather markets checked (1,320 highs, 1,824 lows, 852 rain, August to October). Kalshi now settles on The Weather Company's reading at the NWS station named in the rules (for example CLINYC); a trace of rain settled NO on 103 of 104 trace days, so trace is read as 0.0.
- **Only the series that trade.** Of 109 daily weather series, 11 had traded open markets on 2026-10-08: `KXRAIN` (32 cities in one series), highs `KXHIGHNY`, `KXHIGHLAX`, `KXHIGHPHIL`, `KXHIGHTNOLA`, and lows `KXLOWTAUS`, `KXLOWTOKC`, `KXLOWTATL`, `KXLOWTDEN`, `KXLOWTEWR`, `KXLOWTSDF`. Station ids come from each series' rules text and are listed in `STATIONS`. Adding a city is one line.
- **Freeze at the start of the climate day only** (`MIN_LEAD = 20h` before close). Later in the day part of the outcome has been observed, and a live test showed the ensemble "forecasting" an Austin low that had already happened. A later run is a gap, not a late forecast.
- **ens-v1 is the raw ensemble, deliberately.** No bias correction and a fixed `KERNEL_SIGMA = 2.0` F chosen before any result. Fit bias and spread walk-forward from the journal's own settled results later, as a new version string (`ens-v2`). Never tune ens-v1 on its results.
- **Not wrapped by the cautious copies** (the registry only wraps CPI, FOMC, labor and sports). The old weather scan engine (`tradehub/engines/weather*.py`, 3 cities, two of them no longer traded) is left alone here; retire it in a follow-up once ens-v1 has settled results.
- No migration. Expect about 90 targets a day across the three families, so the 200-target gate is a few days away for each family.

---
## Files

- Create: `tradehub/data/acis.py`, `tradehub/data/ensemble.py`, `tradehub/journal/forecasters/weather.py`, `tests/test_journal_weather.py`
- Modify: `tradehub/journal/registry.py` (two lines), `market_sentiment_tool/src/lib/forecasterLabels.ts`, `market_sentiment_tool/src/lib/journal.ts`, `market_sentiment_tool/src/lib/journalView.test.ts`

---

### Task 1: Station data, ensembles and the three forecasters

**Interfaces:**
- Consumes: `tradehub.journal.kalshi_linked.{KalshiImplied, entry_for, in_freeze_window, kalshi_target, quote_mid, quote_payload, settle_on_kalshi}`, `tradehub.journal.forecasters.baselines.{CLIMATOLOGY, baseline_name}`, `tradehub.markets.{prob_in_interval, yes_interval}`, `tests/journal_fakes.FakeJournalDB`.
- Produces: `parse_station(payload) -> (lat, lon, {date: {high, low, rain}})`; `parse_members(payload)`, `day_members(members, close, kind) -> list[float]`; `WeatherEnsemble(kind, live, fetch, inputs)` (name `weather_<kind>`, version `ens-v1`); `WeatherClimatology` (name `baseline_climatology_weather_<kind>`, version `v1`); `build_weather(live, fetch=fetch_market, inputs=None)` returning 9 forecasters for kinds `high`, `low`, `rain`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_weather.py`)

```python
from datetime import UTC, date, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.acis import parse_station
from tradehub.data.ensemble import day_members, parse_members
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.weather import (
    KERNEL_SIGMA,
    STATIONS,
    WeatherClimatology,
    WeatherEnsemble,
    WeatherInputs,
    build_weather,
    climatology_prob,
    ensemble_prob,
    station_for,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_market

CLOSE = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)  # end of the Oct 9 climate day in NYC (local standard time)
NOW = CLOSE - timedelta(hours=20)


def _lm(ticker, strike_type, floor=None, cap=None, bid=0.40, ask=0.44, close=CLOSE):
    event = ticker.rsplit("-", 1)[0]
    raw = {"ticker": ticker, "event_ticker": event, "strike_type": strike_type, "floor_strike": floor,
           "cap_strike": cap, "open_time": "2026-10-07T14:00:00Z", "close_time": close.isoformat(), "title": ticker}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _hourly(start, temps, rains):
    """An Open-Meteo ensemble payload: one row per hour from `start`, one column per member."""
    n = len(temps[0])
    hourly = {"time": [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]}
    for i, (t, r) in enumerate(zip(temps, rains, strict=True)):
        suffix = "ncep_gefs05" if i == 0 else f"member{i:02d}_ncep_gefs05"
        hourly[f"temperature_2m_{suffix}"] = t
        hourly[f"precipitation_{suffix}"] = r
    return {"hourly": hourly}


ACIS = {"meta": {"ll": [-73.96925, 40.77898], "name": "NY CITY CENTRAL PARK"},
        "data": [["2025-10-09", "70", "55", "0.00"], ["2024-10-09", "80", "60", "T"], ["2023-10-09", "72", "M", "0.20"],
                 ["2022-10-12", "65", "50", "0.05"], ["2022-10-30", "99", "90", "1.00"]]}


def test_acis_parses_trace_as_zero_and_missing_as_none():
    lat, lon, days = parse_station(ACIS)
    assert (lat, lon) == (40.77898, -73.96925)
    assert days[date(2024, 10, 9)] == {"high": 80.0, "low": 60.0, "rain": 0.0}   # trace settles as NO rain
    assert days[date(2023, 10, 9)]["low"] is None


def test_ensemble_members_are_the_climate_day_max_min_and_total():
    start = CLOSE - timedelta(hours=26)
    # hours 0-2 end at or before the climate day starts, 3-26 are inside it (the last ends at close), 27 is after
    temps = [[60.0] * 3 + [70.0] * 24 + [99.0], [61.0] * 3 + [75.0] * 12 + [65.0] * 12 + [99.0]]
    rains = [[0.5] * 3 + [0.0] * 25, [0.0] * 3 + [0.1] * 3 + [0.0] * 22]
    members = parse_members(_hourly(start, temps, rains))
    assert len(members) == 2
    assert day_members(members, CLOSE, "high") == [70.0, 75.0]        # the hours either side are outside
    assert day_members(members, CLOSE, "low") == [70.0, 65.0]
    assert day_members(members, CLOSE, "rain") == [0.0, pytest.approx(0.3)]


def test_a_temperature_probability_is_the_kernel_smoothed_share_of_members_in_the_yes_interval():
    m = _lm("KXHIGHNY-26OCT09-T76", "greater", floor=76).market   # YES = high of 77 or more
    assert ensemble_prob(m, "high", [90.0] * 10) > 0.99
    assert ensemble_prob(m, "high", [60.0] * 10) < 0.01
    assert ensemble_prob(m, "high", [76.5] * 10) == pytest.approx(0.5)  # on the boundary
    assert KERNEL_SIGMA == 2.0


def test_rain_is_the_share_of_members_with_measurable_rain_never_exactly_zero_or_one():
    m = _lm("KXRAIN-26OCT09-NYC", "greater", floor=0).market
    assert ensemble_prob(m, "rain", [0.0] * 9 + [0.2]) == pytest.approx((1 + 0.5) / (10 + 1))
    assert 0 < ensemble_prob(m, "rain", [0.0] * 10) < 0.05
    assert 0.95 < ensemble_prob(m, "rain", [1.0] * 10) < 1
    assert ensemble_prob(m, "rain", [0.004] * 10) < 0.05   # below a reportable 0.01 inch


def test_climatology_is_the_same_week_in_past_years_never_using_the_target_year():
    _lat, _lon, days = parse_station(ACIS)
    m = _lm("KXHIGHNY-26OCT09-T76", "greater", floor=76).market
    # 2025-10-09 (70), 2024-10-09 (80), 2023-10-09 (72), 2022-10-12 (65) are within +/-7 days; Oct 30 is not.
    assert climatology_prob(m, "high", days, date(2026, 10, 9)) == pytest.approx((1 + 0.5) / (4 + 1))
    rain = _lm("KXRAIN-26OCT09-NYC", "greater", floor=0).market
    assert climatology_prob(rain, "rain", days, date(2026, 10, 9)) == pytest.approx((2 + 0.5) / (4 + 1))
    assert climatology_prob(m, "high", {date(2026, 10, 8): {"high": 99.0}}, date(2026, 10, 9)) is None


def test_the_station_comes_from_the_series_and_the_rain_suffix():
    assert station_for(_lm("KXHIGHNY-26OCT09-T76", "greater", 76).market) == "NYC"
    assert station_for(_lm("KXRAIN-26OCT09-PHIL", "greater", 0).market) == "PHL"
    assert station_for(_lm("KXRAIN-26OCT09-TTN", "greater", 0).market) == "TTN"
    assert station_for(_lm("KXHIGHZZZ-26OCT09-T1", "greater", 1).market) is None
    assert STATIONS["KXLOWTAUS"] == ("low", "AUS")


class Inputs(WeatherInputs):
    def __init__(self, ensemble, acis):
        super().__init__(get_json=None)
        self.ens, self.acis, self.calls = ensemble, acis, []

    def _fetch_ensemble(self, lat, lon):
        self.calls.append(("ens", lat, lon))
        return self.ens

    def _fetch_station(self, sid, start, end):
        self.calls.append(("acis", sid))
        return self.acis


def _inputs():
    start = CLOSE - timedelta(hours=24)
    temps = [[80.0] * 24 for _ in range(10)]
    rains = [[0.0] * 24 for _ in range(10)]
    return Inputs(_hourly(start, temps, rains), ACIS)


def _final(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_the_forecaster_freezes_inside_24h_records_how_it_was_made_and_never_refetches_in_a_run():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76),
                     _lm("KXHIGHNY-26OCT11-T76", "greater", floor=76, close=CLOSE + timedelta(days=2))])
    inputs = _inputs()
    fc = WeatherEnsemble("high", live, _final("yes"), inputs)
    [entry] = fc.targets(NOW)                       # the Oct 11 market is not inside 24h yet
    assert (fc.name, fc.version, fc.family) == ("weather_high", "ens-v1", "weather_high")
    f = fc.forecast(entry, NOW)
    # every member at 80F against YES = 77 or more: Phi((80 - 76.5) / 2) = 0.96
    assert f.probability == pytest.approx(0.9599, abs=1e-4) and f.market_prob == pytest.approx(0.42)
    assert f.payload["station"] == "NYC" and f.payload["n_members"] == 10 and f.payload["kernel_sigma"] == 2.0
    assert f.payload["yes_bid"] == 0.40 and f.payload["ensemble_mean"] == pytest.approx(80.0)
    fc.forecast(entry, NOW)
    assert [c[0] for c in inputs.calls] == ["acis", "ens"]   # coordinates once, ensemble once


def test_a_market_already_part_way_through_its_climate_day_is_not_forecast():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    for cls in (WeatherEnsemble, WeatherClimatology):
        fc = cls("high", live, _final("yes"), _inputs())
        assert fc.targets(CLOSE - timedelta(hours=21)) and fc.targets(CLOSE - timedelta(hours=19)) == []


def test_no_members_in_the_window_is_a_gap_not_a_guess():
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76)])
    inputs = Inputs({"hourly": {"time": []}}, ACIS)
    fc = WeatherEnsemble("high", live, _final("yes"), inputs)
    assert fc.forecast(fc.targets(NOW)[0], NOW) is None


def test_end_to_end_the_model_its_climatology_and_the_market_are_scored_on_the_same_contracts():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_lm("KXHIGHNY-26OCT09-T76", "greater", floor=76), _lm("KXRAIN-26OCT09-NYC", "greater", floor=0)])
    fcs = build_weather(live, _final("no"), _inputs())
    run_journal(db, fcs, clock[0])
    clock[0] = CLOSE + timedelta(hours=1)
    out = run_journal(db, fcs, clock[0])
    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    for kind in ("high", "rain"):
        assert cards[f"weather_{kind}"]["n_settled"] == 1 and cards[f"weather_{kind}"]["baseline"] == "market"
        assert cards[f"baseline_climatology_weather_{kind}"]["n_settled"] == 1
        assert cards[f"kalshi_implied_weather_{kind}"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_every_weather_family_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for kind in ("high", "low", "rain"):
        for name in (f"weather_{kind}", f"kalshi_implied_weather_{kind}", f"baseline_climatology_weather_{kind}"):
            assert any(k[0] == name for k in keys), name
    assert len(set(keys)) == len(keys)
    assert not any(k[0].startswith("weather_") and k[0].endswith("_cautious") for k in keys)
    assert isinstance(WeatherClimatology, type)
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_weather.py` — Expected: FAIL with an ImportError (`tradehub.data.acis` does not exist).

- [ ] **Step 3: Implement**

`tradehub/data/acis.py`:

```python
"""Daily station observations from NOAA's Applied Climate Information System (ACIS), keyless.

Kalshi's daily weather markets name an NWS climate station (CLINYC, CLIAUS, ...) and settle on its reported
high, low or precipitation. ACIS serves the same station's daily record back decades, plus its coordinates.
Checked 2026-10-08 against 3,996 settled Kalshi markets (highs, lows, rain): ACIS reproduced every outcome,
with a trace of rain ("T") settling NO, so trace is read as 0.0.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

ACIS_URL = "https://data.rcc-acis.org/StnData"
FIELDS = ("high", "low", "rain")


def _value(raw: str) -> float | None:
    if raw == "T":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):  # "M" (missing), "S"/"A" flags
        return None


def parse_station(payload: dict[str, Any]) -> tuple[float, float, dict[date, dict[str, float | None]]]:
    """(latitude, longitude, {day: {high, low, rain}}) from an ACIS StnData response."""
    lon, lat = payload["meta"]["ll"]
    days = {date.fromisoformat(row[0]): {f: _value(v) for f, v in zip(FIELDS, row[1:], strict=True)}
            for row in payload.get("data") or []}
    return lat, lon, days


def fetch_station(sid: str, start: date, end: date, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    return get_json(ACIS_URL, {"sid": sid, "sdate": start.isoformat(), "edate": end.isoformat(),
                               "elems": "maxt,mint,pcpn", "output": "json"})
```

`tradehub/data/ensemble.py`:

```python
"""Ensemble weather forecasts from Open-Meteo (NOAA GEFS 0.5 and ECMWF IFS 0.25), keyless.

One request returns every member's hourly temperature and precipitation, in UTC. A member's value for a
Kalshi market is its max, min or total over the market's climate day, which is the 24 hours ending at the
market's close (Kalshi closes each daily weather market at midnight local standard time).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.backtest.http import default_get_json

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODELS = ("gfs05", "ecmwf_ifs025")
CLIMATE_DAY = timedelta(hours=24)
Members = list[tuple[list[datetime], list[float | None], list[float | None]]]


def fetch_ensemble(lat: float, lon: float, get_json: Callable[..., Any] = default_get_json) -> dict[str, Any]:
    return get_json(ENSEMBLE_URL, {"latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation",
                                   "models": ",".join(MODELS), "temperature_unit": "fahrenheit",
                                   "precipitation_unit": "inch", "timezone": "GMT", "forecast_days": 3})


def parse_members(payload: dict[str, Any]) -> Members:
    """[(hours, temperatures, precipitation)] per member, control runs included."""
    hourly = payload.get("hourly") or {}
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly.get("time") or []]
    out = []
    for key in hourly:
        if key.startswith("temperature_2m_"):
            rain = hourly.get("precipitation_" + key.removeprefix("temperature_2m_")) or [None] * len(times)
            out.append((times, hourly[key], rain))
    return out


def day_members(members: Members, close: datetime, kind: str) -> list[float]:
    """Each member's high, low or rain total over (close - 24h, close]; members with no data drop out."""
    start = close - CLIMATE_DAY
    out = []
    for times, temps, rains in members:
        series = rains if kind == "rain" else temps
        values = [v for t, v in zip(times, series, strict=True) if start < t <= close and v is not None]
        if not values:
            continue
        out.append(sum(values) if kind == "rain" else max(values) if kind == "high" else min(values))
    return out
```

`tradehub/journal/forecasters/weather.py`:

```python
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
```

`tradehub/journal/registry.py`:

```diff
diff --git a/tradehub/journal/registry.py b/tradehub/journal/registry.py
index 99af85d..5333c97 100644
--- a/tradehub/journal/registry.py
+++ b/tradehub/journal/registry.py
@@ -20,6 +20,7 @@ from tradehub.journal.forecasters.sentiment import SentimentMeter
 from tradehub.journal.forecasters.shrunk import MarketShrunk
 from tradehub.journal.forecasters.sports import build_sports
 from tradehub.journal.forecasters.spy_quant import SpyQuant
+from tradehub.journal.forecasters.weather import build_weather
 from tradehub.journal.kalshi_linked import KalshiImplied
 from tradehub.journal.spx import SpxCloses
 
@@ -57,6 +58,8 @@ FORECASTERS: list[Forecaster] = [
     *build_baselines(_SPX, _WAVE2, _HOUSING),
     # wave 3 (spec §8): NFL and CFB feed consumers, each beside its Kalshi-implied baseline
     *build_sports(),
+    # daily weather (highs, lows, rain): NOAA/ECMWF ensembles beside the Kalshi mid and station climatology
+    *build_weather(_LIVE),
 ]
 
 # plan 15: the market-linked models again, each pulled toward the Kalshi price (see forecasters/shrunk.py).
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_weather.py tests/test_journal_runner.py tests/test_journal_sports.py` — Expected: pass (11 in the new file).

- [ ] **Step 5: Live smoke run, no database** (prints targets and sample probabilities; every family should forecast every target it lists, and the Kalshi baseline fewer, because some markets have no two-sided quote):

```bash
.venv/bin/python - <<'E'
from datetime import UTC, datetime
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.forecasters.weather import build_weather
now = datetime.now(UTC)
for fc in build_weather(KalshiLive()):
    entries = fc.targets(now)
    ok = [f for f in (fc.forecast(e, now) for e in entries) if f]
    print(f"{fc.name:40s} targets={len(entries):3d} forecast={len(ok):3d}")
E
```

Run it within the first few hours after local midnight in the US (05:00-09:00 UTC) or it lists few targets: the `MIN_LEAD` rule is doing its job.

- [ ] **Step 6: Commit**

```bash
git add tradehub/data/acis.py tradehub/data/ensemble.py tradehub/journal/forecasters/weather.py tradehub/journal/registry.py tests/test_journal_weather.py
git commit -m "feat(journal): weather ensemble forecasters for Kalshi highs, lows and rain"
```

---

### Task 2: Names and baselines on the page

- [ ] **Step 1: Add the test and the labels** (the diff includes the new `journalView.test.ts` case):

```diff
diff --git a/market_sentiment_tool/src/lib/forecasterLabels.ts b/market_sentiment_tool/src/lib/forecasterLabels.ts
index 360326d..5d3c4f9 100644
--- a/market_sentiment_tool/src/lib/forecasterLabels.ts
+++ b/market_sentiment_tool/src/lib/forecasterLabels.ts
@@ -21,6 +21,12 @@ const BASE: Record<string, string> = {
   sports_cfb_total: "College football game totals",
   // Spec §8 naive baselines. Named so a visitor cannot mistake "yesterday again" for a prediction:
   // every one carries "(baseline)", and none of them is called a model.
+  weather_high: "Daily high temperatures",
+  weather_low: "Daily low temperatures",
+  weather_rain: "Rain today",
+  baseline_climatology_weather_high: "Daily highs: the usual for this week (baseline)",
+  baseline_climatology_weather_low: "Daily lows: the usual for this week (baseline)",
+  baseline_climatology_weather_rain: "Rain: the usual for this week (baseline)",
   baseline_persistence_spx: "S&P 500 tomorrow: yesterday again (baseline)",
   baseline_climatology_spx: "S&P 500 tomorrow: the usual rate (baseline)",
   baseline_persistence_vix: "Volatility (VIX) tomorrow: yesterday again (baseline)",
diff --git a/market_sentiment_tool/src/lib/journal.ts b/market_sentiment_tool/src/lib/journal.ts
index ef23211..52fa8fc 100644
--- a/market_sentiment_tool/src/lib/journal.ts
+++ b/market_sentiment_tool/src/lib/journal.ts
@@ -91,6 +91,9 @@ export const MARKET_PAIR: Record<string, string> = {
   fomc_mapped: "kalshi_implied_fomc",
   labor_nowcast: "kalshi_implied_labor",
   sports_nfl: "kalshi_implied_sports_nfl",
+  weather_high: "kalshi_implied_weather_high",
+  weather_low: "kalshi_implied_weather_low",
+  weather_rain: "kalshi_implied_weather_rain",
   sports_cfb: "kalshi_implied_sports_cfb",
   sports_nfl_spread: "kalshi_implied_sports_nfl_spread",
   sports_nfl_total: "kalshi_implied_sports_nfl_total",
diff --git a/market_sentiment_tool/src/lib/journalView.test.ts b/market_sentiment_tool/src/lib/journalView.test.ts
index b9ed06f..8931627 100644
--- a/market_sentiment_tool/src/lib/journalView.test.ts
+++ b/market_sentiment_tool/src/lib/journalView.test.ts
@@ -75,6 +75,15 @@ describe("view", () => {
     score({ forecaster: "housing_direction", forecaster_version: "housing-wf-v1", cadence: "monthly", calibration_ready: true }),
   ];
 
+  it("pairs each weather family with its own Kalshi baseline and names it plainly", () => {
+    const rows = viewRows([
+      score({ forecaster: "weather_rain", forecaster_version: "ens-v1", baseline: "market", n_settled: 2, n_targets: 3 }),
+      score({ forecaster: "kalshi_implied_weather_rain", forecaster_version: "v1", n_settled: 2, n_targets: 3 }),
+    ]);
+    expect(rows.map((r) => r.label)).toEqual(["Rain today"]);
+    expect(rows[0].market?.forecaster).toBe("kalshi_implied_weather_rain");
+  });
+
   it("folds the Kalshi baseline into its model's row and orders scored rows first", () => {
     const { results, waiting } = split(viewRows(scores));
     expect(results.map((r) => r.label)).toEqual(["NFL winners"]);
```

- [ ] **Step 2: Run** — `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add market_sentiment_tool/src/lib/forecasterLabels.ts market_sentiment_tool/src/lib/journal.ts market_sentiment_tool/src/lib/journalView.test.ts
git commit -m "feat(ui): plain names and Kalshi baselines for the weather rows"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline 1,528).

- [ ] `.venv/bin/python -m ruff check tradehub/data/acis.py tradehub/data/ensemble.py tradehub/journal/forecasters/weather.py tests/test_journal_weather.py` → `All checks passed!`
- [ ] Open the PR titled `feat(journal): weather ensemble forecasters (highs, lows, rain)`. Body: the smoke-run output, the verification output, "no migration". Self-review, merge with the explicit PR number, and the next hourly journal run starts freezing.
- [ ] After two days, check `journal_scores` for `weather_high`, `weather_low`, `weather_rain` and their baselines, and report n settled and skill vs the market in 4 lines.

---

## Self-Review

- **Settlement correctness:** the 3,996-market ACIS check is in the constraints; the forecasters still settle on Kalshi's result, so a station-data error can only hurt the model, never the score.
- **No look-ahead:** the climatology test proves the target year is never used; the `MIN_LEAD` test proves nothing freezes once the climate day is under way.
- **Honest baselines:** each family is graded against the Kalshi mid on the same contracts and against climatology; neither baseline can be promoted.
- **Skipped on purpose:** bias correction, fitted spread, a persistence baseline, more cities and the old engine's retirement. Each is a later, separate version or PR.

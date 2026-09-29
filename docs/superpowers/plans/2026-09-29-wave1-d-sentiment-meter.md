# Sentiment Meter v1 (Wave 1, Plan d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily composite sentiment score and probability for next-session S&P 500 direction, frozen at 08:00 CT, settled on the close.

**Architecture:** Shared daily plumbing lands first: `tradehub/data/fred_daily.py` (keyed FRED current vintage), `tradehub/journal/nyse.py` (rule-based session calendar), `tradehub/journal/spx.py` (the `spx:<day>:up` target, 3h freeze lead before 08:00 CT, climatology, FRED SP500 settlement, an hourly-memoised `SpxCloses`). The meter (`tradehub/journal/forecasters/sentiment.py`) z-scores VIXCLS, BAMLH0A0HYM2 and GDELT tone against their own history and maps a weighted score to a probability through a documented prior logistic.

**Tech Stack:** Python 3.12, FRED API (key already on the VPS), GDELT DOC 2.1 (keyless), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§6 Sentiment meter v1). **Depends on:** plan (a) merged. Independent of (b)/(c).

> **Provenance:** every code block below was implemented and run by the reviewer on top of plan (a) in a scratch worktree before this plan was written (full backend suite 1383 passed with `time.monotonic` forced to 5.0 and to 1e7; frontend vitest 462 passed, tsc, eslint and build clean; new Python files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- A forecaster is a class implementing `tradehub.journal.contract.Forecaster`; its `(name, version)` is its journal key and must be unique in `tradehub/journal/registry.py`.
- Constructing a forecaster must not touch the network; network happens only inside `targets` / `forecast` / `settle`.
- `forecast()` returns `None` when an input is missing (a recorded gap), never a guess or a default.
- **Spec deviations, decided by the reviewer on 2026-09-29 and to be confirmed by Kevin in the PR:**
  1. Settlement and target use **FRED `SP500` (S&P 500 index close)** instead of Stooq SPY adjusted close: Stooq now serves a JavaScript proof-of-work wall to scripts, and the journal does not bypass bot checks. Direction differs from SPY only on rare dividend-driven days.
  2. **CNN Fear & Greed, Stooq breadth and put/call are not in v1**: CNN answers scripts with HTTP 418, breadth sits behind the same Stooq wall, and no free put/call endpoint had evidence of free access. The spec already made these optional; the meter runs on the FRED components as required.
  3. **GDELT tone uses GDELT's own `timelinetone`**, not `vaderSentiment` over titles: same source, no new dependency or lexicon on the VPS. The DOC API reaches back ~3 months, so its z-window is 60 observations.
- Target, exactly: `spx:<t>:up` = 1 iff close(t) > close(previous session); unchanged is not up; t is the first NYSE session whose 08:00 CT freeze is ahead; no targets on non-session days.
- Point-in-time: only observations dated strictly before t are used; the live fetch is the current vintage at freeze time, so nothing unpublished is visible.
- `meter-v1` is `provisional` for its whole life. Calibration arrives as a new version (`meter-v2`) fitted only on `meter-v1`'s settled history — no version is re-fit on the period it is scored on.
- Before merging: run `curl -s -o /dev/null -w '%{http_code}' 'https://api.gdeltproject.org/api/v2/doc/doc?query=%22stock%20market%22&mode=timelinetone&timespan=3m&format=json'` **on the VPS** and record the status in the PR (spec: reachability is checked from the VPS, not a laptop). FRED is already proven from the VPS by the labor engine.

---
### Task 1: Daily plumbing and the sentiment meter

**Files:**
- Create: `tradehub/data/fred_daily.py`, `tradehub/journal/nyse.py`, `tradehub/journal/spx.py`, `tradehub/data/gdelt.py`, `tradehub/journal/forecasters/sentiment.py`
- Test: `tests/test_journal_spx_sentiment.py`

**Interfaces:**
- Produces: `fetch_fred_daily(series_id, start, *, get_text=..., api_key=None, deadline=None) -> {date: float}`; `holidays(year)`, `is_session(day)`, `next_session(day)`; `spx_target(day)`, `target_day(target)`, `freeze_at(day)`, `next_target_day(now)`, `up_outcome(closes, day)`, `climatology_up(closes, before)`, `SpxCloses(fetch=...)` with `.get(now)`, `spx_entry(now, closes, family)`, `settle_spx(target, now, closes)`, `FREEZE_LEAD = 3h`; `parse_tone_timeline(payload)`, `fetch_market_tone(get_json=...)`; `COMPONENTS`, `Component`, `component(name, series, day, window)`, `meter(parts) -> (score, prob) | None`, `SentimentMeter(closes, *, fred=..., tone=...)` (name `sentiment_meter`, version `meter-v1`, cadence `daily`). Plan (e) consumes `spx.py` unchanged.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_spx_sentiment.py`)

```python
from datetime import UTC, date, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.data.gdelt import parse_tone_timeline
from tradehub.journal.forecasters.sentiment import Component, SentimentMeter, component, meter
from tradehub.journal.nyse import holidays, is_session, next_session
from tradehub.journal.runner import run_journal
from tradehub.journal.spx import SpxCloses, climatology_up, next_target_day, up_outcome

CT_0700 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # Thu 07:00 CDT, before the 08:00 freeze


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if is_session(day):
            out.append(day)
        day += timedelta(days=1)
    return out


def _closes(days, step=1.0):
    return {d: 5000.0 + step * i * (1 if i % 2 else -0.5) for i, d in enumerate(days)}


def test_nyse_rules_match_the_published_2026_and_2027_calendars():
    assert holidays(2026) == {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
                              date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
                              date(2026, 11, 26), date(2026, 12, 25)}
    assert date(2027, 3, 26) in holidays(2027) and date(2027, 12, 24) in holidays(2027)
    assert date(2027, 12, 31) not in holidays(2027)  # New Year 2028 is a Saturday: not observed on Friday
    assert next_session(date(2026, 11, 26)) == date(2026, 11, 27)


def test_the_target_is_the_next_session_whose_freeze_is_still_ahead():
    assert next_target_day(CT_0700) == date(2026, 10, 1)
    assert next_target_day(CT_0700 - timedelta(hours=3)) is None  # 04:00 CT: outside the 3h lead
    assert next_target_day(CT_0700 + timedelta(hours=2)) is None  # past today's freeze; tomorrow's is 23h out
    assert next_target_day(datetime(2026, 10, 2, 11, 0, tzinfo=UTC)) == date(2026, 10, 2)
    assert next_target_day(datetime(2026, 10, 4, 14, 0, tzinfo=UTC)) is None  # Sunday
    assert next_target_day(datetime(2026, 10, 5, 11, 30, tzinfo=UTC)) == date(2026, 10, 5)


def test_up_means_strictly_above_the_previous_session_close():
    closes = {date(2026, 9, 30): 100.0, date(2026, 10, 1): 100.0, date(2026, 10, 2): 101.0}
    assert up_outcome(closes, date(2026, 10, 1)) == 0  # unchanged is not up
    assert up_outcome(closes, date(2026, 10, 2)) == 1
    assert up_outcome(closes, date(2026, 10, 5)) is None  # no close yet


def test_climatology_is_the_trailing_up_share_and_needs_a_year():
    days = _weekdays(date(2024, 1, 2), 400)
    closes = {d: float(i) for i, d in enumerate(days)}  # always up
    assert climatology_up(closes, days[-1]) == 0.98
    assert climatology_up(dict(list(closes.items())[:100]), days[-1]) is None


def test_component_uses_only_values_before_the_day_and_flags_staleness():
    days = _weekdays(date(2025, 1, 2), 300)
    series = {d: 20.0 + (i % 5) for i, d in enumerate(days)}
    series[days[-1]] = 40.0  # a spike ON the target day must not be visible
    part = component("VIXCLS", series, days[-1], 252)
    assert part.observed == days[-2].isoformat() and abs(part.z) < 3
    later = component("VIXCLS", series, days[-1] + timedelta(days=10), 252)
    assert later.stale is True


def test_meter_needs_a_fresh_fred_component_and_renormalises_weights():
    fear = Component("VIXCLS", 35.0, "2026-09-30", 3.0, False)
    tone = Component("gdelt_tone", 1.0, "2026-09-30", 3.0, False)
    assert meter([tone]) is None  # GDELT alone is not enough
    score, prob = meter([fear])
    assert score == -100.0 and prob < 0.53
    score, _ = meter([fear, tone])
    assert score == -33.3  # (0.4 x -3 + 0.2 x +3) / 0.6 = -1 z -> -33.3 on the display scale


def test_gdelt_parser_reads_the_average_tone_series():
    payload = {"timeline": [{"series": "Average Tone", "data": [{"date": "20260705T000000Z", "value": 0.18}]}]}
    assert parse_tone_timeline(payload) == {date(2026, 7, 5): 0.18}


def test_meter_freezes_before_the_open_and_settles_on_the_close():
    days = _weekdays(date(2025, 6, 2), 340)
    closes = _closes(days + [date(2026, 10, 1)])
    fred = {name: {d: 20.0 + (i % 7) for i, d in enumerate(days)} for name in ("VIXCLS", "BAMLH0A0HYM2")}
    spx = SpxCloses(fetch=lambda series, start: {d: v for d, v in closes.items() if d < clock[0].date()})
    fc = SentimentMeter(spx, fred=lambda name, start: fred[name], tone=lambda: (_ for _ in ()).throw(OSError("429")))
    clock = [CT_0700]
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["sentiment_meter@meter-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == "spx:2026-10-01:up" and row["payload"]["missing"] == ["gdelt_tone: OSError"]
    assert db.tables["journal_calendars"][0]["climatology_prob"] is not None
    clock[0] = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)  # next morning: FRED has Oct 1's close
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["sentiment_meter@meter-v1"]["settled"] == 1
    assert db.tables["journal_scores"][0]["baseline"] == "climatology"



def test_the_registry_runs_the_meter():
    from tradehub.journal.registry import FORECASTERS

    assert ("sentiment_meter", "meter-v1") in {(f.name, f.version) for f in FORECASTERS}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_spx_sentiment.py -v`
Expected: FAIL — `No module named 'tradehub.data.gdelt'`.

- [ ] **Step 3: Implement**

`tradehub/data/fred_daily.py`:

```python
"""A FRED daily series as it stands now (current vintage), via the keyed API the VPS can reach.

The live journal freezes at a moment and reads the current vintage at that moment, so everything it
sees was, by construction, published before the freeze. Callers still filter observation dates
strictly before the target day, which is the same rule a replay must apply.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date

from tradehub.data.alfred_vintages import (
    FRED_API_KEY_ENV,
    FRED_SERIES_OBSERVATIONS,
    Vintage,
    default_get_text,
    parse_fred_observations_json,
)


def fetch_fred_daily(series_id: str, start: date, *, get_text: Callable[..., str] = default_get_text,
                     api_key: str | None = None, deadline: float | None = None) -> Vintage:
    key = (api_key if api_key is not None else os.getenv(FRED_API_KEY_ENV, "")).strip()
    if not key:
        raise RuntimeError(f"{FRED_API_KEY_ENV} is not set; the journal's daily series need the keyed FRED API")
    params = {"series_id": series_id, "observation_start": start.isoformat(), "file_type": "json", "api_key": key}
    extra = {} if deadline is None else {"deadline": deadline}
    return parse_fred_observations_json(get_text(FRED_SERIES_OBSERVATIONS, params, secret=key, **extra))
```

`tradehub/journal/nyse.py`:

```python
"""NYSE full-day closures by rule (v2 spec §6: no freeze on non-session days).

Rules: New Year's Day (Saturday -> not observed; Sunday -> Monday), MLK Day, Washington's Birthday,
Good Friday, Memorial Day, Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving,
Christmas (Saturday -> Friday, Sunday -> Monday). Unscheduled closures (e.g. a national day of
mourning) are not predictable; such a day simply never settles, because it has no close.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    out = {
        _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0), _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25)),
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:
        out.add(_observed(new_year))
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))
    return frozenset(out)


def is_session(day: date) -> bool:
    return day.weekday() < 5 and day not in holidays(day.year)


def next_session(day: date) -> date:
    """`day` itself if it is a session, else the next one."""
    while not is_session(day):
        day += timedelta(days=1)
    return day
```

`tradehub/journal/spx.py`:

```python
"""S&P 500 next-session direction: the target the sentiment meter (§6) and the quant (§7) share.

Target, exactly: `spx:<t>:up` is 1 iff the S&P 500 close on session t (FRED `SP500`) is strictly
above the previous session's close; an unchanged close is not up. t is the first NYSE session whose
08:00 CT freeze is still ahead. Settlement source is FRED `SP500` rather than Stooq SPY: Stooq now
serves a JavaScript proof-of-work wall to scripts, and the journal does not bypass bot checks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.contract import CalendarEntry, Settlement
from tradehub.journal.nyse import is_session, next_session

CT = ZoneInfo("America/Chicago")
FREEZE_TIME_CT = time(8, 0)
# Frozen on the morning of t (05:00-08:00 CT), after FRED has the previous close: a 24h lead would
# freeze on the morning of t-1 and every forecast would be a day stale.
FREEZE_LEAD = timedelta(hours=3)
SPX_SERIES = "SP500"
HISTORY_DAYS = 3700  # FRED licenses about ten years of SP500
CLIMATOLOGY_SESSIONS = 1260  # five years of sessions
CLIMATOLOGY_BOUNDS = (0.02, 0.98)
SETTLEMENT_SOURCE = "fred:SP500"


def spx_target(day: date) -> str:
    return f"spx:{day.isoformat()}:up"


def target_day(target: str) -> date:
    return date.fromisoformat(target.split(":")[1])


def freeze_at(day: date) -> datetime:
    return datetime.combine(day, FREEZE_TIME_CT, CT)


def next_target_day(now: datetime) -> date | None:
    """The session whose freeze is the next one ahead, if that freeze is within FREEZE_LEAD."""
    day = next_session(now.astimezone(CT).date())
    if freeze_at(day) <= now:
        day = next_session(day + timedelta(days=1))
    return day if freeze_at(day) - now <= FREEZE_LEAD else None


def up_outcome(closes: Mapping[date, float], day: date) -> int | None:
    if day not in closes:
        return None
    earlier = [d for d in closes if d < day]
    return int(closes[day] > closes[max(earlier)]) if earlier else None


def climatology_up(closes: Mapping[date, float], before: date) -> float | None:
    days = sorted(d for d in closes if d < before)[-(CLIMATOLOGY_SESSIONS + 1):]
    if len(days) < 253:
        return None
    ups = [closes[b] > closes[a] for a, b in pairwise(days)]
    lo, hi = CLIMATOLOGY_BOUNDS
    return min(hi, max(lo, sum(ups) / len(ups)))


class SpxCloses:
    """FRED SP500 closes, fetched at most once per hourly run and shared by every SPX forecaster."""

    def __init__(self, fetch: Callable[..., Mapping[date, float]] = fetch_fred_daily):
        self._fetch = fetch
        self._hour: datetime | None = None
        self._closes: Mapping[date, float] = {}

    def get(self, now: datetime) -> Mapping[date, float]:
        hour = now.astimezone(CT).replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            self._closes = self._fetch(SPX_SERIES, hour.date() - timedelta(days=HISTORY_DAYS))
            self._hour = hour
        return self._closes


def spx_entry(now: datetime, closes: SpxCloses, family: str) -> list[CalendarEntry]:
    day = next_target_day(now)
    if day is None:
        return []
    return [CalendarEntry(spx_target(day), family, "daily", freeze_at(day),
                          climatology_prob=climatology_up(closes.get(now), day))]


def settle_spx(target: str, now: datetime, closes: SpxCloses) -> Settlement | None:
    day = target_day(target)
    outcome = up_outcome(closes.get(now), day) if is_session(day) else None
    if outcome is None:
        return None
    return Settlement(target, outcome, SETTLEMENT_SOURCE, realized_value=closes.get(now)[day])
```

`tradehub/data/gdelt.py`:

```python
"""GDELT DOC 2.1 average news tone, one value per day (keyless; optional sentiment component).

GDELT computes the tone itself (`mode=timelinetone`), so no sentiment lexicon ships on the VPS. The
DOC API covers a rolling ~3 months and allows one request every 5 seconds; the meter makes one call
per daily freeze.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MARKET_QUERY = '"stock market" sourcelang:english'


def parse_tone_timeline(payload: dict[str, Any]) -> dict[date, float]:
    out: dict[date, float] = {}
    for series in payload.get("timeline") or []:
        if series.get("series") != "Average Tone":
            continue
        for point in series.get("data") or []:
            stamp = point["date"]  # "20260705T000000Z"
            out[date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))] = float(point["value"])
    return out


def fetch_market_tone(get_json: Callable[..., Any] = default_get_json) -> dict[date, float]:
    params = {"query": MARKET_QUERY, "mode": "timelinetone", "timespan": "3m", "format": "json"}
    return parse_tone_timeline(get_json(GDELT_DOC_URL, params))
```

`tradehub/journal/forecasters/sentiment.py`:

```python
"""Sentiment meter v1 (v2 spec §6): a daily composite for next-session S&P 500 direction.

Components (each z-scored against its own trailing history, clipped to +/-3):
    VIXCLS        FRED, required-class  weight 0.4  sign -1 (fear)
    BAMLH0A0HYM2  FRED, required-class  weight 0.4  sign -1 (credit stress)
    GDELT tone    optional              weight 0.2  sign +1
Only values observed strictly before the target day are used. A component whose newest value is
older than STALE_DAYS is dropped and flagged. Weights renormalise over the components present; the
meter needs at least one FRED component or it records a gap.

Not in v1, with reasons (spec's weakest-dependency rule): CNN Fear & Greed answers scripts with HTTP
418; Stooq breadth sits behind a JavaScript proof-of-work wall; no free put/call endpoint was found
with evidence of free access. They are listed so their absence is a decision, not an oversight.

Output: `score` in [-100, 100] for display; probability = logistic(logit(PRIOR_UP) + SLOPE x s) with
s the weighted z in [-3, 3]. The constants are a documented prior, not a fit: v1 is `provisional`
throughout. A calibrated mapping ships as a new version (`meter-v2`) fitted only on meter-v1's
settled history, so no version is ever re-fit on the period it is scored on.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.data.gdelt import fetch_market_tone
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.spx import SpxCloses, settle_spx, spx_entry, target_day

# name -> (weight, sign, trailing window in observations, required-class)
COMPONENTS = {
    "VIXCLS": (0.4, -1.0, 252, True),
    "BAMLH0A0HYM2": (0.4, -1.0, 252, True),
    "gdelt_tone": (0.2, 1.0, 60, False),  # the DOC API only reaches back ~3 months
}
Z_CLIP = 3.0
STALE_DAYS = 5
PRIOR_UP = 0.53  # long-run share of S&P 500 up sessions
SLOPE = 0.10  # logit units per unit of weighted z: a deliberately weak prior
FRED_LOOKBACK_DAYS = 500


@dataclass(frozen=True)
class Component:
    name: str
    value: float
    observed: str
    z: float
    stale: bool


def component(name: str, series: Mapping[date, float], day: date, window: int) -> Component | None:
    known = sorted(d for d in series if d < day)
    if len(known) < window + 1:
        return None
    latest = known[-1]
    history = [series[d] for d in known[-window - 1:-1]]
    spread = statistics.pstdev(history)
    if spread == 0:
        return None
    z = max(-Z_CLIP, min(Z_CLIP, (series[latest] - statistics.fmean(history)) / spread))
    return Component(name, series[latest], latest.isoformat(), z, (day - latest).days > STALE_DAYS)


def meter(parts: list[Component]) -> tuple[float, float] | None:
    """(score in [-100, 100], P(up)) from the fresh components, or None without a fresh FRED one."""
    fresh = [c for c in parts if not c.stale]
    if not any(COMPONENTS[c.name][3] for c in fresh):
        return None
    weight = sum(COMPONENTS[c.name][0] for c in fresh)
    s = sum(COMPONENTS[c.name][0] * COMPONENTS[c.name][1] * c.z for c in fresh) / weight
    logit = math.log(PRIOR_UP / (1.0 - PRIOR_UP)) + SLOPE * s
    return round(100.0 * s / Z_CLIP, 1), 1.0 / (1.0 + math.exp(-logit))


class SentimentMeter:
    name = "sentiment_meter"
    version = "meter-v1"
    cadence = "daily"

    def __init__(self, closes: SpxCloses, *, fred: Callable[..., Mapping[date, float]] = fetch_fred_daily,
                 tone: Callable[[], Mapping[date, float]] = fetch_market_tone):
        self._closes, self._fred, self._tone = closes, fred, tone

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return spx_entry(now, self._closes, "spx")

    def _series(self, name: str, day: date) -> Mapping[date, float]:
        if name == "gdelt_tone":
            return self._tone()
        return self._fred(name, day - timedelta(days=FRED_LOOKBACK_DAYS))

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        parts, missing = [], []
        for name, (_, _, window, _) in COMPONENTS.items():
            try:
                part = component(name, self._series(name, day), day, window)
            except Exception as exc:  # noqa: BLE001 - a source failing is recorded, not fatal
                missing.append(f"{name}: {type(exc).__name__}")
                continue
            if part is None:
                missing.append(name)
            else:
                parts.append(part)
        result = meter(parts)
        if result is None:
            return None
        score, prob = result
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"score": score, "provisional": True, "components": [asdict(c) for c in parts],
                                 "missing": missing})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_spx(target, now, self._closes)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_spx_sentiment.py -v`
Expected: all pass except `test_the_registry_runs_the_meter` (Task 2).

- [ ] **Step 5: Commit**

```bash
git add tradehub/data/fred_daily.py tradehub/journal/nyse.py tradehub/journal/spx.py tradehub/data/gdelt.py tradehub/journal/forecasters/sentiment.py tests/test_journal_spx_sentiment.py
git commit -m "feat(journal): S&P 500 direction target and sentiment meter v1"
```

---
### Task 2: Register the meter

**Files:**
- Modify: `tradehub/journal/registry.py` (replace the whole file). The file below assumes plans (b) and (c) are merged; if they are not, keep only the lines this plan adds (`SpxCloses` import and `_SPX`, the `SentimentMeter` import and entry).

**Interfaces:**
- Produces: `sentiment_meter@meter-v1`; the module-level `_SPX = SpxCloses()` is shared with plan (e).

- [ ] **Step 1: Write the failing test** (`tests/test_journal_spx_sentiment.py`)

```python
# `test_the_registry_runs_the_meter` was written in Task 1.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_spx_sentiment.py -k registry -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`tradehub/journal/registry.py` (whole file):

```python
"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each.

Constructing a forecaster must not touch the network: clients are built here, used only when the
runner calls `targets`/`forecast`/`settle`.
"""

from __future__ import annotations

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.contract import Forecaster
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
from tradehub.journal.forecasters.sentiment import SentimentMeter
from tradehub.journal.kalshi_linked import KalshiImplied
from tradehub.journal.spx import SpxCloses

_LIVE = KalshiLive()
_LABOR = LaborData()
_SPX = SpxCloses()

FORECASTERS: list[Forecaster] = [
    # plan (b): CPI + FOMC, each beside its Kalshi pseudo-forecaster (spec §5, ruling Q5)
    CpiForecaster("KXCPI", _LIVE, fetch_market),
    CpiForecaster("KXCPICORE", _LIVE, fetch_market),
    KalshiImplied("cpi", ("KXCPI", "KXCPICORE"), "monthly", _LIVE, fetch_market),
    FomcMapped(_LIVE, fetch_market),
    KalshiImplied("fomc", (FOMC_SERIES,), "meeting", _LIVE, fetch_market, keep=is_hold_market),
    # plan (c): labor (spec §5); payrolls beside the market, the direction fits vs climatology
    PayrollsForecaster(_LIVE, fetch_market, _LABOR),
    KalshiImplied("labor", ("KXPAYROLLS",), "monthly", _LIVE, fetch_market),
    UnrateDirection(_LIVE, _LABOR),
    QuitsDirection(_LABOR),
    # plan (d): sentiment meter (spec §6)
    SentimentMeter(_SPX),
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_*.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/registry.py
git commit -m "feat(journal): run the sentiment meter"
```

---
### Final task: verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on the files this plan created: `.venv/bin/python -m ruff check <those files>` → `All checks passed!`
- [ ] Open one PR from a fresh branch off `main` (after plan (a) is merged). Body: what the forecaster(s) predict, their `(name, version)` keys, and "no migration needed".

## Self-Review

- **Spec §6:** daily composite, 08:00 CT freeze, z-scored components with fixed documented weights, stale flags (`stale=true`, never silent), renormalisation when optional components are missing, FRED-only operation, score (−100..100) plus logistic probability, provisional labelling, the exact up/unchanged/non-session target definition. Deviations are listed in Global Constraints for Kevin's confirmation.
- **Freeze timing:** 3h lead so the freeze happens on the morning of t with t−1's close available (a 24h lead would freeze a day stale); `SpxCloses` refreshes hourly for the same reason.
- **Type consistency:** `spx.py` names are exactly what plan (e) imports.

# Housing Forecaster (Wave 3, Plan g) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal the S&P Cotality Case-Shiller US National HPI month-over-month direction, frozen before each release and settled on the first print.

**Architecture:** `tradehub/models/monthly_direction.py` gives monthly features and a walk-forward training set; the existing logistic `fit` and hashed `ArtifactStore` are reused (`fit` gains `features` and `min_train` keywords, defaults unchanged). `HousingForecaster` targets the first unpublished month, registers it only in the five days before its release (last Tuesday of month m+2, 09:00 ET), forecasts from months strictly before it, and settles on the ALFRED vintage of release day.

**Tech Stack:** Python 3.12, numpy, FRED API (key already on the VPS), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 Wave 3 Housing, §10 gates). **Depends on:** plans (a) and (e) merged (they are). Independent of plans (h)–(l).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1400 passed at monotonic 5.0 and at 1e7; new files ruff-clean; the release rule reproduces all 30 real FRED vintage dates of CSUSHPISA from 2024-03 to 2026-08, checked from the VPS on 2026-09-30). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- Series: FRED `CSUSHPISA` (seasonally adjusted national index). Target, exactly: `housing:<YYYY-MM>:up` is 1 iff month m's FIRST PRINT exceeds month m-1 as printed in that same release; unchanged is not up.
- **Data lag stated on the tile:** the index for month m is published about two months later. No intra-month nowcasting (spec §8).
- Point-in-time: only months strictly before m feed the forecast. If month m is already in the fetched series, or any of the 12 months behind it is missing, `forecast()` returns `None` (a gap, never a guess).
- **Stated approximation:** training uses the current (revised) history. Case-Shiller revises the two prior months at each release, and a first-print history before 2012 is not reconstructible from a keyless pull. Settlement always uses the first print.
- Cadence `monthly`: the gate needs 50 settled targets, i.e. about four years of live journaling. The forecaster stays `provisional` until then.
- Settlement asks ALFRED for exactly two vintages (release day minus one, release day), both disk-cached after the first fetch. Do not widen this to a daily vintage search like the labor engine's: the release date is known, so a search would only add FRED calls.
- No Kalshi housing series is wired into the journal, so this forecaster grades against climatology, not a market baseline.
- Earnings and crypto stay deferred to v1.x.

---
### Task 1: Monthly model plumbing and the housing forecaster

**Files:**
- Modify: `tradehub/models/spy_direction/model.py` (`fit` gains two keyword parameters)
- Create: `tradehub/models/monthly_direction.py`, `tradehub/journal/forecasters/housing.py`
- Test: `tests/test_journal_housing.py`

**Interfaces:**
- Consumes: plan (e) `ArtifactStore`, `Artifact`, `fit`; plan (a) `CalendarEntry`, `Forecast`, `Settlement`, `run_journal`, `tests/journal_fakes.FakeJournalDB`; `tradehub.engines.labor.first_prints`; `tradehub.data.alfred_vintages.fetch_vintages`; `tradehub.data.fred_daily.fetch_fred_daily`.
- Produces: `monthly_direction.{FEATURES, MIN_HISTORY, feature_row, features_for, training_set, climatology}`; `fit(x, y, days, l2=L2, *, features=FEATURES, min_train=MIN_TRAIN)`; `housing.{add_months, release_day, release_cutoff, target_for, target_month, HousingForecaster}` (name `housing_direction`, version `housing-wf-v1`, cadence `monthly`, target `housing:<YYYY-MM>:up`).

- [ ] **Step 1: Write the failing test** (`tests/test_journal_housing.py`)

```python
import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.housing import (
    HousingForecaster,
    add_months,
    release_cutoff,
    release_day,
    target_for,
)
from tradehub.journal.runner import run_journal
from tradehub.models.monthly_direction import climatology, features_for, training_set
from tradehub.models.spy_direction.model import ArtifactStore

# The 30 real FRED vintage dates of CSUSHPISA seen on 2026-09-30 (2024-03 .. 2026-08): every one is the
# last Tuesday of its month, and each published the index for two months earlier.
REAL_RELEASES = [
    "2024-03-26", "2024-04-30", "2024-05-28", "2024-06-25", "2024-07-30", "2024-08-27", "2024-09-24",
    "2024-10-29", "2024-11-26", "2024-12-31", "2025-01-28", "2025-02-25", "2025-03-25", "2025-04-29",
    "2025-05-27", "2025-06-24", "2025-07-29", "2025-08-26", "2025-09-30", "2025-10-28", "2025-11-25",
    "2025-12-30", "2026-01-27", "2026-02-24", "2026-03-31", "2026-04-28", "2026-05-26", "2026-06-30",
    "2026-07-28", "2026-08-25",
]


def _levels(last=date(2026, 6, 1), seed=11):
    rng, level, out, month = random.Random(seed), 60.0, {}, date(1987, 1, 1)
    while month <= last:
        level *= 1.0 + (0.004 if rng.random() < 0.72 else -0.003) + rng.gauss(0, 0.001)
        out[month] = level
        month = add_months(month, 1)
    return out


def test_the_release_rule_reproduces_every_real_release_date():
    for text in REAL_RELEASES:
        published = date.fromisoformat(text)
        data_month = add_months(date(published.year, published.month, 1), -2)
        assert release_day(data_month) == published, text
    assert release_day(date(2026, 7, 1)) == date(2026, 9, 29)
    assert release_cutoff(date(2026, 8, 1)) == datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def test_features_and_training_use_only_months_before_the_target():
    levels = _levels()
    month = date(2026, 7, 1)
    row, newest = features_for(levels, month)
    assert newest == date(2026, 6, 1)
    assert features_for({**levels, month: levels[date(2026, 6, 1)] * 5}, month)[0] == row  # its own value is invisible
    x, y, days = training_set(levels, before=month)
    assert max(days) < month and len(x) == len(y) > 300
    assert climatology(levels, month) == pytest.approx(0.72, abs=0.1)
    assert climatology({m: v for m, v in list(levels.items())[:40]}, month) is None


def _forecaster(tmp_path, levels, vintages=None):
    calls = []

    def vintages_fn(series, days, **kwargs):
        calls.append((series, list(days)))
        return (vintages or {})

    fc = HousingForecaster(levels_fn=lambda start: dict(levels), vintages_fn=vintages_fn,
                           store=ArtifactStore(tmp_path, "housing_direction"))
    return fc, calls


def test_the_target_is_the_first_unpublished_month_and_freezes_only_just_before_its_release(tmp_path):
    fc, _ = _forecaster(tmp_path, _levels())  # published through June (released 2026-08-25)
    et = ZoneInfo("America/New_York")
    assert fc.targets(datetime(2026, 8, 26, 12, tzinfo=et)) == []  # a month early
    [entry] = fc.targets(datetime(2026, 9, 25, 12, tzinfo=et))  # inside the five days before Sep 29
    assert entry.target == "housing:2026-07:up" and entry.cadence == "monthly" and not entry.market_linked
    assert entry.cutoff_at == datetime(2026, 9, 29, 9, 0, tzinfo=et) and entry.climatology_prob is not None
    assert fc.targets(datetime(2026, 9, 29, 10, tzinfo=et)) == []  # the cutoff has passed


def test_a_month_that_is_already_published_or_has_a_hole_is_a_gap_not_a_guess(tmp_path):
    levels = _levels(last=date(2026, 7, 1))  # July is already out
    fc, _ = _forecaster(tmp_path, levels)
    entry = type("E", (), {"target": target_for(date(2026, 7, 1))})()
    assert fc.forecast(entry, datetime(2026, 9, 25, tzinfo=UTC)) is None  # never forecast a known value
    holed = _levels()
    del holed[date(2026, 5, 1)]
    fc, _ = _forecaster(tmp_path, holed)
    entry = type("E", (), {"target": target_for(date(2026, 7, 1))})()
    assert fc.forecast(entry, datetime(2026, 9, 25, tzinfo=UTC)) is None


def test_settlement_is_the_first_print_and_waits_for_release_day(tmp_path):
    before = {date(2026, 5, 1): 100.0, date(2026, 6, 1): 101.0}
    on_release = {**before, date(2026, 7, 1): 101.5}  # the first print says up
    fc, calls = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): on_release})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 29, 15, tzinfo=UTC)) is None  # release day itself: too early
    assert calls == []
    settlement = fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC))
    assert settlement.outcome == 1 and settlement.realized_value == pytest.approx(0.5)
    assert calls[-1][1] == [date(2026, 9, 28), date(2026, 9, 29)]  # exactly the two vintages needed
    flat = {**before, date(2026, 7, 1): 101.0}
    fc, _ = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): flat})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC)).outcome == 0  # unchanged is not up
    fc, _ = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): before})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC)) is None  # not printed yet


def test_housing_freezes_before_the_release_and_settles_after_it(tmp_path):
    et = ZoneInfo("America/New_York")
    levels = _levels()
    before = {date(2026, 5, 1): levels[date(2026, 5, 1)], date(2026, 6, 1): levels[date(2026, 6, 1)]}
    vintages = {date(2026, 9, 28): before,
                date(2026, 9, 29): {**before, date(2026, 7, 1): levels[date(2026, 6, 1)] * 1.004}}
    fc, _ = _forecaster(tmp_path, levels, vintages)
    clock = [datetime(2026, 9, 25, 12, tzinfo=et)]
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["housing_direction@housing-wf-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == "housing:2026-07:up" and row["payload"]["release_day"] == "2026-09-29"
    assert row["payload"]["train_end"] < "2026-07-01" and len(row["payload"]["artifact_sha256"]) == 64
    clock[0] = datetime(2026, 9, 30, 12, tzinfo=et)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["housing_direction@housing-wf-v1"]["settled"] == 1
    assert db.tables["journal_settlements"][0]["outcome"] == 1
    assert db.tables["journal_scores"][0]["baseline"] == "climatology"


def test_the_registry_runs_housing():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert ("housing_direction", "housing-wf-v1") in keys and len(set(keys)) == len(keys)
    assert timedelta(days=5) > timedelta(0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_housing.py -v`
Expected: FAIL — `No module named 'tradehub.journal.forecasters.housing'`.

- [ ] **Step 3: Implement**

`tradehub/models/spy_direction/model.py` (apply this change; wave-1 and wave-2 behaviour is unchanged because the defaults are the old constants):

```diff
diff --git a/tradehub/models/spy_direction/model.py b/tradehub/models/spy_direction/model.py
index 26eecc2..579b02a 100644
--- a/tradehub/models/spy_direction/model.py
+++ b/tradehub/models/spy_direction/model.py
@@ -44,9 +44,10 @@ class Artifact:
         return json.dumps(asdict(self), sort_keys=True, indent=1)
 
 
-def fit(x: list[list[float]], y: list[int], days: list[date], l2: float = L2) -> Artifact:
-    if len(y) < MIN_TRAIN:
-        raise ValueError(f"need >= {MIN_TRAIN} training sessions, got {len(y)}")
+def fit(x: list[list[float]], y: list[int], days: list[date], l2: float = L2, *,
+        features: tuple[str, ...] = FEATURES, min_train: int = MIN_TRAIN) -> Artifact:
+    if len(y) < min_train:
+        raise ValueError(f"need >= {min_train} training rows, got {len(y)}")
     xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
     center, scale = xa.mean(axis=0), xa.std(axis=0)
     scale[scale == 0] = 1.0
@@ -58,7 +59,7 @@ def fit(x: list[list[float]], y: list[int], days: list[date], l2: float = L2) ->
         grad = z.T @ (p - ya) + penalty @ w
         hess = (z.T * (p * (1.0 - p))) @ z + penalty
         w -= np.linalg.solve(hess, grad)
-    return Artifact(FEATURES, tuple(center.tolist()), tuple(scale.tolist()), float(w[0]), tuple(w[1:].tolist()),
+    return Artifact(features, tuple(center.tolist()), tuple(scale.tolist()), float(w[0]), tuple(w[1:].tolist()),
                     min(days).isoformat(), max(days).isoformat(), len(ya))
 
 
```

`tradehub/models/monthly_direction.py`:

```python
"""Monthly-series direction features and training set (v2 spec §8, housing).

Same walk-forward discipline as `spy_direction`: the row for month t uses levels strictly before t, the
label is `level[t] > level[t-1]`, and a model for month m is trained only on months before m. Fitting and
the hashed artifact store are shared (`tradehub.models.spy_direction.model`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from itertools import pairwise

FEATURES = ("g1", "g3", "g6", "g12", "accel")
MIN_HISTORY = 14  # levels needed before a month to compute every feature


def _add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def feature_row(levels: list[float]) -> dict[str, float] | None:
    """Features from `levels` (oldest first), all known before the target month."""
    if len(levels) < MIN_HISTORY:
        return None
    def g(k: int) -> float:
        return math.log(levels[-1] / levels[-1 - k])
    g1, g3 = g(1), g(3)
    return {"g1": g1, "g3": g3, "g6": g(6), "g12": g(12), "accel": g1 - g3 / 3.0}


def features_for(levels: Mapping[date, float], month: date) -> tuple[dict[str, float], date] | None:
    """(features, date of the newest level used) for target `month`; None without enough history."""
    months = sorted(m for m in levels if m < month)
    row = feature_row([levels[m] for m in months])
    return (row, months[-1]) if row is not None else None


def training_set(levels: Mapping[date, float], before: date) -> tuple[list[list[float]], list[int], list[date]]:
    """One row per month t < `before`: features from levels before t, label = level[t] > level[t-1]."""
    months = sorted(m for m in levels if m < before)
    values = [levels[m] for m in months]
    x, y, used = [], [], []
    for i in range(MIN_HISTORY, len(months)):
        row = feature_row(values[:i])
        if row is None:
            continue
        x.append([row[f] for f in FEATURES])
        y.append(int(values[i] > values[i - 1]))
        used.append(months[i])
    return x, y, used


def climatology(levels: Mapping[date, float], before: date, window: int = 120, minimum: int = 60) -> float | None:
    """Share of the last `window` month-over-month changes before `before` that were up; clamped away from 0/1."""
    months = sorted(m for m in levels if m < before)[-(window + 1):]
    if len(months) - 1 < minimum:
        return None
    ups = sum(levels[b] > levels[a] for a, b in pairwise(months))
    return min(0.98, max(0.02, ups / (len(months) - 1)))
```

`tradehub/journal/forecasters/housing.py`:

```python
"""Housing: S&P Cotality Case-Shiller US National HPI (seasonally adjusted) month-over-month direction.

Spec §8 wave 3: frozen monthly on the release calendar, data lag stated, no nowcasting.

Target, exactly: `housing:<YYYY-MM>:up` is 1 iff the FIRST PRINT of month m's index level exceeds
month m-1's level as printed in that same release. The index is published on the last Tuesday of month
m+2 at 09:00 ET (FRED `CSUSHPISA`; checked against the 30 real vintage dates 2024-03..2026-08, all last
Tuesdays), so the tile reads "two months behind". It is revised afterwards; settlement is the first print
from the ALFRED vintage of release day, never the revised value.

Point-in-time: the forecast uses only months strictly before m. If month m is already present in the
series fetched at freeze time (an early or off-calendar release), no forecast is made: a gap, not a leak.
Training history is the current (revised) vintage; that is a stated approximation, because pre-2012
first prints are not reconstructible from a keyless vintage pull.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.data.alfred_vintages import Vintage, fetch_vintages
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.engines.labor import first_prints
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.models.monthly_direction import FEATURES, climatology, features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

ET = ZoneInfo("America/New_York")
SERIES = "CSUSHPISA"
FAMILY = "housing"
RELEASE_TIME_ET = time(9, 0)
FREEZE_WINDOW = timedelta(days=5)  # register and freeze inside the five days before the release
MIN_TRAIN_MONTHS = 120
HISTORY_START = date(1987, 1, 1)
SETTLEMENT_SOURCE = "fred:CSUSHPISA:first_print"


def add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def release_day(month: date) -> date:
    """The last Tuesday of month m+2: when month m's index is first published."""
    published = add_months(month, 2)
    last = add_months(published, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 1) % 7)


def release_cutoff(month: date) -> datetime:
    return datetime.combine(release_day(month), RELEASE_TIME_ET, ET)


def target_for(month: date) -> str:
    return f"{FAMILY}:{month:%Y-%m}:up"


def target_month(target: str) -> date:
    return date.fromisoformat(target.split(":")[1] + "-01")


class HousingForecaster:
    name = "housing_direction"
    version = "housing-wf-v1"
    cadence = "monthly"

    def __init__(self, *, levels_fn: Callable[[date], Mapping[date, float]] = lambda start: fetch_fred_daily(SERIES, start),
                 vintages_fn: Callable[..., dict[date, Vintage]] = fetch_vintages,
                 store: ArtifactStore | None = None):
        self._levels_fn, self._vintages_fn = levels_fn, vintages_fn
        self._store = store or ArtifactStore(namespace="housing_direction")
        self._levels: Mapping[date, float] | None = None

    def _history(self) -> Mapping[date, float]:
        if self._levels is None:
            self._levels = self._levels_fn(HISTORY_START)
        return self._levels

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._levels = None  # refetched once per run
        levels = self._history()
        month = add_months(max(levels), 1)  # the first month not yet published
        cutoff = release_cutoff(month)
        if not now < cutoff <= now + FREEZE_WINDOW:
            return []
        return [CalendarEntry(target_for(month), FAMILY, self.cadence, cutoff,
                              climatology_prob=climatology(levels, month))]

    def model_for(self, month: date) -> tuple[Artifact, str]:
        name = f"housing-dir-{month:%Y-%m}"
        found = self._store.load(name)
        if found is not None:
            return found
        x, y, days = training_set(self._history(), before=month)
        artifact = fit(x, y, days, features=FEATURES, min_train=MIN_TRAIN_MONTHS)
        return artifact, self._store.save(name, artifact)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        month = target_month(entry.target)
        levels = self._history()
        if month in levels:  # already published: never forecast a known value
            return None
        found = features_for(levels, month)
        if found is None:
            return None
        row, newest = found
        # The 12-month feature looks back 12 months: a hole anywhere in them is a gap, not a guess.
        if add_months(newest, 1) != month or any(add_months(newest, -k) not in levels for k in range(13)):
            return None
        artifact, digest = self.model_for(month)
        return Forecast(self.name, self.version, entry.target, artifact.predict(row),
                        payload={"features": row, "newest_level": newest.isoformat(), "artifact_sha256": digest,
                                 "train_end": artifact.train_end, "n_train": artifact.n_train,
                                 "release_day": release_day(month).isoformat(), "provisional": True,
                                 "source": SETTLEMENT_SOURCE})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        month = target_month(target)
        released = release_day(month)
        today = now.astimezone(ET).date()
        if today <= released:
            return None
        vintages = self._vintages_fn(SERIES, [released - timedelta(days=1), released], today=today)
        change = first_prints(vintages, change=True).get(month)
        if change is None:
            return None
        return Settlement(target, int(change > 0), SETTLEMENT_SOURCE, realized_value=change)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_housing.py -v`
Expected: 6 passed, 1 failed (`test_the_registry_runs_housing`, Task 2).

- [ ] **Step 5: Commit**

```bash
git add tradehub/models tradehub/journal/forecasters/housing.py tests/test_journal_housing.py
git commit -m "feat(journal): Case-Shiller national HPI direction forecaster"
```

---

### Task 2: Register housing

**Files:**
- Modify: `tradehub/journal/registry.py`

**Interfaces:**
- Produces: `FORECASTERS` gains `housing_direction@housing-wf-v1`; keys stay unique.

- [ ] **Step 1:** `test_the_registry_runs_housing` was written in Task 1 and is red. Run `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_housing.py -k registry -v` → FAIL.

- [ ] **Step 2: Implement** — apply to `tradehub/journal/registry.py`:

```diff
diff --git a/tradehub/journal/registry.py b/tradehub/journal/registry.py
index 3240aac..6e104f3 100644
--- a/tradehub/journal/registry.py
+++ b/tradehub/journal/registry.py
@@ -12,6 +12,7 @@ from tradehub.journal.contract import Forecaster
 from tradehub.journal.forecasters.cpi import CpiForecaster
 from tradehub.journal.forecasters.daily_direction import build_wave2
 from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
+from tradehub.journal.forecasters.housing import HousingForecaster
 from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
 from tradehub.journal.forecasters.sentiment import SentimentMeter
 from tradehub.journal.forecasters.spy_quant import SpyQuant
@@ -40,4 +41,6 @@ FORECASTERS: list[Forecaster] = [
     SpyQuant(_SPX),
     # wave 2 (spec §8): VIX, gold (GLD) and EUR/USD daily direction, same walk-forward model
     *build_wave2(),
+    # wave 3 (spec §8): Case-Shiller national HPI month-over-month direction
+    HousingForecaster(),
 ]
```

- [ ] **Step 3: Run**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_*.py -v` — Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tradehub/journal/registry.py
git commit -m "feat(journal): run the housing forecaster"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] Live check, paste in the PR body (the FRED key is on the VPS and must never be printed): run the release-rule probe against `fred/series/vintagedates` for `CSUSHPISA` from the VPS container and confirm every recent vintage is a last Tuesday.
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §8 Housing:** national HPI m/m direction, frozen monthly on the FRED release calendar, data lag stated on the tile, no nowcasting. Earnings stays deferred (v1.x).
- **Leak guards tested:** features ignore the target month's own value; an already-published month and a hole in the last 12 months are recorded gaps; settlement uses the first print, asserted with a release-day-minus-one and a release-day vintage.
- **Type consistency:** target ids `housing:<YYYY-MM>:up` are produced by `target_for` and parsed by `target_month`; `fit(..., features=FEATURES, min_train=120)` uses the monthly `FEATURES`, and the artifact stores that tuple.

# Labor Forecasters (Wave 1, Plan c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal the payrolls nowcast as-is and add UNRATE and JOLTS-quits direction forecasters on the same ridge pattern, all settling on FRED first prints.

**Architecture:** `tradehub/engines/labor_direction.py` (pure) reuses `fit_payroll_model` (now with a `min_sigma` floor per target unit) on the existing point-in-time `labor_features`. `tradehub/journal/forecasters/labor.py` wraps it: `LaborData` loads vintages at most once per ET day and computes first-print changes for settlement; `PayrollsForecaster` is Kalshi-linked; `UnrateDirection` freezes before the jobs release (the KXPAYROLLS close is its calendar); `QuitsDirection` freezes by a conservative day-25 cutoff because JOLTS has no market.

**Tech Stack:** Python 3.12, numpy, existing ALFRED/FRED vintage loader, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§5 Labor). **Depends on:** plans (a) and (b) merged (this plan uses `tradehub/journal/kalshi_linked.py` from (b)).

> **Provenance:** every code block below was implemented and run by the reviewer on top of plan (a) in a scratch worktree before this plan was written (full backend suite 1383 passed with `time.monotonic` forced to 5.0 and to 1e7; frontend vitest 462 passed, tsc, eslint and build clean; new Python files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- A forecaster is a class implementing `tradehub.journal.contract.Forecaster`; its `(name, version)` is its journal key and must be unique in `tradehub/journal/registry.py`.
- Constructing a forecaster must not touch the network; network happens only inside `targets` / `forecast` / `settle`.
- `forecast()` returns `None` when an input is missing (a recorded gap), never a guess or a default.
- Target, exactly: `labor:<unrate|quits>:<YYYY-MM>:up` is 1 iff the **first print** of month m minus month m-1 **in that same release** is at least one printed unit (UNRATE +0.1pp → threshold 0.05; quits +1k → threshold 0.5). No consensus feed anywhere.
- Walk-forward only: every fit uses months strictly before the target month (`training_rows(..., before=month)`); COVID months stay excluded (`is_trainable`).
- Direction targets are **not** market-linked: `climatology_prob` (trailing share of up months, clamped to [0.02, 0.98]) is written on the calendar row and is their BSS baseline.
- Payrolls keep name `labor_nowcast` and version `labor-v1` (no model change).

---
### Task 1: Direction model and the labor forecasters

**Files:**
- Modify: `tradehub/engines/labor.py` (`fit_payroll_model` gains `min_sigma`)
- Create: `tradehub/engines/labor_direction.py`, `tradehub/journal/forecasters/labor.py`
- Test: `tests/test_journal_labor.py`

**Interfaces:**
- Consumes: plan (b) `kalshi_linked`; `tradehub.data.labor_inputs.{load_labor_inputs, feature_table, payroll_nowcasts, cache_dir_from_env}`; `tradehub.data.alfred_vintages.fetch_vintages`.
- Produces: `fit_payroll_model(rows, features=CORE_FEATURES, lam=RIDGE_LAMBDA, min_sigma=MIN_PAYROLL_SIGMA)`; `UNRATE_UP=0.05`, `QUITS_UP=0.5`, `MIN_UNRATE_SIGMA=0.05`, `MIN_QUITS_SIGMA=20.0`, `QUITS_FEATURES`; `DirectionNowcast(month, mu, sigma, prob_up, climatology, model)`; `up_probability`, `climatology`, `with_quits_feature`, `direction_nowcast`; `LaborData(load=..., fetch=...)` with `.inputs(now)`, `.quits(now)`, `.first_print_change(series, month, now)`; `PayrollsForecaster(live, fetch_market, data, *, nowcasts_fn=None)`; `UnrateDirection(live, data, *, nowcast_fn=..., settle_fn=...)`; `QuitsDirection(data, *, nowcast_fn=..., settle_fn=...)`; `last_completed_month(now)`; `QUITS_CUTOFF_DAYS = 25`; `SETTLE_SEARCH_DAYS = 75`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_labor.py`)

```python
import random
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.labor import CORE_FEATURES, LaborFeatures, add_months
from tradehub.engines.labor_direction import (
    UNRATE_UP,
    DirectionNowcast,
    climatology,
    direction_nowcast,
    up_probability,
    with_quits_feature,
)
from tradehub.journal.forecasters.labor import (
    LaborData,
    PayrollsForecaster,
    QuitsDirection,
    UnrateDirection,
    last_completed_month,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_market

NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)  # 09:00 ET; September has ended
RELEASE = "2026-10-02T12:25:00Z"  # the KXPAYROLLS close, 5 minutes before the 08:30 ET release


def _pay(floor, bid=0.40, ask=0.44, close=RELEASE):
    event = "KXPAYROLLS-26SEP"
    market = parse_market({"ticker": f"{event}-T{floor}", "event_ticker": event, "strike_type": "greater",
                           "floor_strike": floor, "open_time": "2026-09-01T00:00:00Z", "close_time": close,
                           "title": f"payrolls > {floor}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=10.0, yes_ask_size=10.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _table(n=96, seed=7):  # 2012-01..2019-12: clear of the COVID exclusion
    """Synthetic point-in-time features whose target is a known linear function plus noise."""
    rng = random.Random(seed)
    table, prints, month = {}, {}, date(2012, 1, 1)
    for _ in range(n):
        values = {f: rng.gauss(0, 1) for f in CORE_FEATURES}
        table[month] = LaborFeatures(month, values, ())
        prints[month] = 0.08 * values["icsa_ref_chg"] + rng.gauss(0, 0.05)
        month = add_months(month, 1)
    return table, prints, month


def test_up_probability_is_the_normal_tail_and_never_certain():
    assert up_probability(0.05, 0.1, 0.05) == pytest.approx(0.5)
    assert up_probability(10.0, 0.01, 0.05) < 1.0 and up_probability(-10.0, 0.01, 0.05) > 0.0


def test_climatology_needs_history_and_is_bounded():
    prints = {add_months(date(2012, 1, 1), k): 1.0 for k in range(30)}
    assert climatology(prints, date(2030, 1, 1), 0.5) == 0.98  # always up -> clamped, never certain
    assert climatology(dict(list(prints.items())[:10]), date(2030, 1, 1), 0.5) is None


def test_direction_nowcast_is_walk_forward_and_follows_the_features():
    table, prints, month = _table()
    table[month] = LaborFeatures(month, {f: 0.0 for f in CORE_FEATURES} | {"icsa_ref_chg": 3.0}, ())
    nc = direction_nowcast(table, prints, month, threshold=UNRATE_UP, min_sigma=0.05)
    assert nc.prob_up > 0.8  # claims surged -> unemployment likely up
    assert nc.model.n_train == 96  # only months strictly before `month`
    table[month] = LaborFeatures(month, {f: 0.0 for f in CORE_FEATURES} | {"icsa_ref_chg": -3.0}, ())
    assert direction_nowcast(table, prints, month, threshold=UNRATE_UP, min_sigma=0.05).prob_up < 0.2
    assert direction_nowcast(table, prints, add_months(month, 1), threshold=UNRATE_UP, min_sigma=0.05) is None


def test_quits_feature_is_the_latest_change_in_the_same_vintage():
    feats = LaborFeatures(date(2026, 9, 1), {"pay_last": 1.0}, ())
    vintage = {date(2026, 6, 1): 3200.0, date(2026, 7, 1): 3150.0}
    assert with_quits_feature(feats, vintage).values["quits_last"] == pytest.approx(-50.0)
    assert with_quits_feature(feats, {}) is None


def test_first_print_change_reads_the_first_vintage_that_contains_the_month():
    calls = []

    def fetch(series, days, **_):
        calls.append((series, days[0], days[-1]))
        before = {date(2026, 8, 1): 4.3}
        released = {date(2026, 8, 1): 4.3, date(2026, 9, 1): 4.5}
        revised = {date(2026, 8, 1): 4.3, date(2026, 9, 1): 4.4, date(2026, 10, 1): 4.4}
        return {d: (before if d < date(2026, 10, 2) else released if d < date(2026, 11, 6) else revised)
                for d in days}

    data = LaborData(load=None, fetch=fetch)
    assert data.first_print_change("UNRATE", date(2026, 9, 1), datetime(2026, 10, 2, 11, tzinfo=UTC)) is None
    later = datetime(2026, 11, 20, 12, tzinfo=UTC)  # after a revision: still the FIRST print
    assert data.first_print_change("UNRATE", date(2026, 9, 1), later) == pytest.approx(0.2)
    assert calls[-1][1] == date(2026, 9, 30)


def _nc(prob, clim=0.3):
    model = SimpleNamespace(n_train=100, features=("icsa_ref_chg",), coef=(0.1,))
    return DirectionNowcast(date(2026, 9, 1), 0.02, 0.1, prob, clim, model)


def test_payrolls_publish_the_existing_nowcast_on_every_strike():
    live = FakeLive([_pay(50000), _pay(100000)])
    nowcast = SimpleNamespace(mu=120.0, sigma=60.0, model=SimpleNamespace(n_train=150))
    fc = PayrollsForecaster(live, lambda t: {}, LaborData(load=None, fetch=None),
                            nowcasts_fn=lambda months, now: {date(2026, 9, 1): nowcast})
    entries = fc.targets(NOW)
    assert {e.target for e in entries} == {"kalshi:KXPAYROLLS-26SEP-T50000", "kalshi:KXPAYROLLS-26SEP-T100000"}
    probs = {e.target: fc.forecast(e, NOW).probability for e in entries}
    assert probs["kalshi:KXPAYROLLS-26SEP-T50000"] > probs["kalshi:KXPAYROLLS-26SEP-T100000"] > 0.5
    assert (fc.name, fc.version) == ("labor_nowcast", "labor-v1")


def test_payrolls_wait_for_the_reference_month_to_end():
    early = datetime(2026, 9, 30, 13, 0, tzinfo=UTC)
    fc = PayrollsForecaster(FakeLive([_pay(50000, close="2026-10-01T12:25:00Z")]), lambda t: {},
                            LaborData(load=None, fetch=None), nowcasts_fn=lambda months, now: {})
    assert fc.targets(early) == []


def test_unrate_direction_freezes_before_the_release_and_settles_on_the_first_print():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    fc = UnrateDirection(FakeLive([_pay(50000), _pay(100000)]), LaborData(load=None, fetch=None),
                         nowcast_fn=lambda month, now: _nc(0.7),
                         settle_fn=lambda month, now: 0.1 if now > datetime(2026, 10, 2, 13, tzinfo=UTC) else None)
    run_journal(db, [fc], clock[0])
    [cal] = db.tables["journal_calendars"]
    assert cal["target"] == "labor:unrate:2026-09:up" and cal["cutoff_at"] == "2026-10-02T12:25:00+00:00"
    assert cal["climatology_prob"] == 0.3 and cal["market_linked"] is False
    clock[0] = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["unrate_direction@unrate-dir-v1"]["settled"] == 1
    [settlement] = db.tables["journal_settlements"]
    assert settlement["outcome"] == 1 and settlement["realized_value"] == 0.1
    card = db.tables["journal_scores"][0]
    assert card["baseline"] == "climatology" and card["brier"] == pytest.approx(0.09)


def test_quits_direction_has_a_conservative_cutoff_and_no_market():
    fc = QuitsDirection(LaborData(load=None, fetch=None), nowcast_fn=lambda month, now: _nc(0.55),
                        settle_fn=lambda month, now: None)
    [entry] = fc.targets(NOW)
    assert entry.target == "labor:quits:2026-09:up" and not entry.market_linked
    assert entry.cutoff_at == datetime(2026, 10, 25, 0, 0, tzinfo=entry.cutoff_at.tzinfo)
    assert fc.forecast(entry, NOW).market_prob is None
    assert fc.targets(datetime(2026, 10, 26, tzinfo=UTC)) == []  # past the cutoff: nothing new
    assert last_completed_month(NOW) == date(2026, 9, 1)
    assert last_completed_month(NOW - timedelta(hours=10)) == date(2026, 8, 1)  # 23:00 ET on Sep 30


def test_the_registry_runs_the_labor_forecasters():
    from tradehub.journal.registry import FORECASTERS

    keys = {(f.name, f.version) for f in FORECASTERS}
    assert {("labor_nowcast", "labor-v1"), ("kalshi_implied_labor", "v1"), ("unrate_direction", "unrate-dir-v1"),
            ("quits_direction", "quits-dir-v1")} <= keys
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_labor.py -v`
Expected: FAIL — `No module named 'tradehub.engines.labor_direction'`.

- [ ] **Step 3: Implement**

`tradehub/engines/labor.py` (apply this change):

```diff
diff --git a/tradehub/engines/labor.py b/tradehub/engines/labor.py
index 0360324..8cec1c4 100644
--- a/tradehub/engines/labor.py
+++ b/tradehub/engines/labor.py
@@ -360,8 +360,13 @@ def fit_payroll_model(
     rows: Sequence[tuple[LaborFeatures, float]],
     features: Sequence[str] = CORE_FEATURES,
     lam: float = RIDGE_LAMBDA,
+    min_sigma: float = MIN_PAYROLL_SIGMA,
 ) -> PayrollModel:
-    """Ridge on standardized features; sigma = RMS of the last SIGMA_WINDOW in-sample residuals."""
+    """Ridge on standardized features; sigma = RMS of the last SIGMA_WINDOW in-sample residuals.
+
+    `min_sigma` is in the target's units (thousands of jobs by default); the labor direction fits
+    reuse this ridge for other targets (percentage points, thousands of quits) with their own floor.
+    """
     usable = sorted((r for r in rows if is_trainable(r[0].month)), key=lambda r: r[0].month)
     if len(usable) < MIN_TRAIN_ROWS:
         raise ValueError(f"need >= {MIN_TRAIN_ROWS} training months, got {len(usable)}")
@@ -375,7 +380,7 @@ def fit_payroll_model(
     coef = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - intercept))
     residuals = y - (intercept + z @ coef)
     recent = residuals[-SIGMA_WINDOW:]
-    sigma = max(MIN_PAYROLL_SIGMA, float(np.sqrt(np.mean(recent ** 2))))
+    sigma = max(min_sigma, float(np.sqrt(np.mean(recent ** 2))))
     return PayrollModel(tuple(features), tuple(center.tolist()), tuple(scale.tolist()), intercept,
                         tuple(coef.tolist()), sigma, len(usable))
 
```

`tradehub/engines/labor_direction.py`:

```python
"""UNRATE and JOLTS-quits direction (v2 spec §5), pure: the payroll ridge pattern on new targets.

Target, exactly: "up" iff the FIRST PRINT of month m, minus month m-1 as printed in that same
release, is at least one printed unit (UNRATE +0.1pp; quits +1k). Self-settling from FRED
vintages; no consensus feed. The fit is `fit_payroll_model` on the same point-in-time
`labor_features`, walk-forward (months strictly before m), with a floor on sigma in the target's
own units. P(up) = P(Normal(mu, sigma) > half a printed unit).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from tradehub.engines.labor import (
    CORE_FEATURES,
    MIN_TRAIN_ROWS,
    LaborFeatures,
    PayrollModel,
    Vintage,
    _change,
    fit_payroll_model,
    is_trainable,
    training_rows,
)
from tradehub.markets import PROBABILITY_EPSILON

UNRATE_UP = 0.05  # UNRATE prints to 0.1pp, so a first-print change of +0.1 or more is "up"
QUITS_UP = 0.5  # JTSQUL prints in whole thousands
MIN_UNRATE_SIGMA = 0.05
MIN_QUITS_SIGMA = 20.0
QUITS_FEATURES = CORE_FEATURES + ("quits_last",)
CLIMATOLOGY_BOUNDS = (0.02, 0.98)


@dataclass(frozen=True)
class DirectionNowcast:
    month: date
    mu: float
    sigma: float
    prob_up: float
    climatology: float
    model: PayrollModel


def up_probability(mu: float, sigma: float, threshold: float) -> float:
    p = 0.5 * math.erfc((threshold - mu) / (sigma * math.sqrt(2.0)))
    return min(1.0 - PROBABILITY_EPSILON, max(PROBABILITY_EPSILON, p))


def climatology(prints: Mapping[date, float], before: date, threshold: float) -> float | None:
    """Share of trainable months before `before` whose first-print change was up; None if too few."""
    past = [v for m, v in prints.items() if m < before and is_trainable(m)]
    if len(past) < MIN_TRAIN_ROWS:
        return None
    lo, hi = CLIMATOLOGY_BOUNDS
    return min(hi, max(lo, sum(v > threshold for v in past) / len(past)))


def with_quits_feature(feats: LaborFeatures, quits_vintage: Vintage | None) -> LaborFeatures | None:
    """Add the latest quits change known at the same month-end vintage (JOLTS lags ~5 weeks)."""
    if not quits_vintage:
        return None
    change = _change(quits_vintage, max(quits_vintage))
    if change is None:
        return None
    return replace(feats, values={**feats.values, "quits_last": change})


def direction_nowcast(
    table: Mapping[date, LaborFeatures],
    prints: Mapping[date, float],
    month: date,
    *,
    threshold: float,
    min_sigma: float,
    features: Sequence[str] = CORE_FEATURES,
) -> DirectionNowcast | None:
    """Walk-forward P(up) for `month`; None when its features or enough history are missing."""
    feats = table.get(month)
    base = climatology(prints, month, threshold)
    if feats is None or base is None:
        return None
    model = fit_payroll_model(training_rows(table, prints, before=month), features, min_sigma=min_sigma)
    mu = model.predict(feats.values)
    return DirectionNowcast(month, mu, model.sigma, up_probability(mu, model.sigma, threshold), base, model)
```

`tradehub/journal/forecasters/labor.py`:

```python
"""Labor through the journal (v2 spec §5): payrolls as-is, plus UNRATE and JOLTS-quits direction.

- `labor_nowcast` / `labor-v1`: the existing ridge payroll nowcast on every KXPAYROLLS strike, same
  math as `tradehub.scripts.scan.scan_labor`; Kalshi-linked, graded against the market.
- `unrate_direction` / `unrate-dir-v1`: P(UNRATE first print is up >= 0.1pp); frozen before the jobs
  release (the KXPAYROLLS close is the calendar); graded against climatology.
- `quits_direction` / `quits-dir-v1`: P(JOLTS quits first print is up); JOLTS has no market, so its
  cutoff is a conservative QUITS_CUTOFF_DAYS after the reference month (JOLTS lands ~35-40 days out).

All three settle against FRED first prints (vintages), never a consensus feed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradehub.data.alfred_vintages import Vintage, fetch_vintages
from tradehub.data.kalshi_live import LiveMarket
from tradehub.data.labor_inputs import (
    LaborInputs,
    cache_dir_from_env,
    feature_table,
    load_labor_inputs,
    payroll_nowcasts,
)
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_SERIES,
    TRAIN_START,
    add_months,
    first_prints,
    month_end,
    payroll_prob,
)
from tradehub.engines.labor_direction import (
    MIN_QUITS_SIGMA,
    MIN_UNRATE_SIGMA,
    QUITS_FEATURES,
    QUITS_UP,
    UNRATE_UP,
    DirectionNowcast,
    direction_nowcast,
    with_quits_feature,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
from tradehub.markets import event_month

ET = ZoneInfo("America/New_York")
QUITS_CUTOFF_DAYS = 25  # earliest JOLTS release is ~30 days after the reference month ends
SETTLE_SEARCH_DAYS = 75  # daily vintages searched for a first print; after that the target stays open


def last_completed_month(now: datetime) -> date:
    today = now.astimezone(ET).date()
    return add_months(date(today.year, today.month, 1), -1)


def _months(first: date, last: date) -> list[date]:
    out, month = [], first
    while month <= last:
        out.append(month)
        month = add_months(month, 1)
    return out


def _target_month(target: str) -> date:
    return date.fromisoformat(target.split(":")[2] + "-01")


class LaborData:
    """The vintages all three labor forecasters read, fetched at most once per ET day and shared."""

    def __init__(self, load: Callable[..., LaborInputs] = load_labor_inputs,
                 fetch: Callable[..., dict[date, Vintage]] = fetch_vintages):
        self._load, self._fetch = load, fetch
        self._memo: dict[tuple[str, date], Any] = {}

    def _once(self, key: str, now: datetime, build: Callable[[], Any]) -> Any:
        slot = (key, now.astimezone(ET).date())
        if slot not in self._memo:
            self._memo = {k: v for k, v in self._memo.items() if k[1] == slot[1]}
            self._memo[slot] = build()
        return self._memo[slot]

    def inputs(self, now: datetime) -> LaborInputs:
        return self._once("inputs", now, lambda: self._load(
            first_month=TRAIN_START, last_month=last_completed_month(now), releases={},
            as_of=now.astimezone(ET).date(), unrate_from=TRAIN_START, with_adp=False))

    def quits(self, now: datetime) -> dict[date, Vintage]:
        today = now.astimezone(ET).date()
        days = [month_end(m) for m in _months(add_months(TRAIN_START, -1), last_completed_month(now))]
        return self._once("quits", now, lambda: self._fetch(
            "JTSQUL", days, cache_dir=cache_dir_from_env(), today=today))

    def first_print_change(self, series: str, month: date, now: datetime) -> float | None:
        """First-print change of `month` (vs m-1 in the same release), or None if not printed yet."""
        today = now.astimezone(ET).date()
        days = [d for k in range(SETTLE_SEARCH_DAYS) if (d := month_end(month) + timedelta(days=k)) < today]
        vintages = self._fetch(series, days, cache_dir=cache_dir_from_env(), today=today)
        return first_prints(vintages, change=True).get(month)


def unrate_nowcast(data: LaborData, month: date, now: datetime) -> DirectionNowcast | None:
    inputs = data.inputs(now)
    table = feature_table(inputs, _months(TRAIN_START, month), {})
    return direction_nowcast(table, first_prints(inputs.unrate, change=True), month,
                             threshold=UNRATE_UP, min_sigma=MIN_UNRATE_SIGMA)


def quits_nowcast(data: LaborData, month: date, now: datetime) -> DirectionNowcast | None:
    quits = data.quits(now)
    table = {}
    for m, feats in feature_table(data.inputs(now), _months(TRAIN_START, month), {}).items():
        augmented = with_quits_feature(feats, quits.get(month_end(m)))
        if augmented is not None:
            table[m] = augmented
    return direction_nowcast(table, first_prints(quits, change=True), month,
                             threshold=QUITS_UP, min_sigma=MIN_QUITS_SIGMA, features=QUITS_FEATURES)


def payroll_markets_by_month(live, now: datetime) -> dict[date, list[LiveMarket]]:
    """Open KXPAYROLLS markets inside the freeze lead whose reference month has ended."""
    out: dict[date, list[LiveMarket]] = {}
    for lm in live.open_markets(PAYROLL_SERIES):
        month = event_month(lm.market.event_ticker)
        if in_freeze_window(lm, now) and month_end(month) < now.astimezone(ET).date():
            out.setdefault(month, []).append(lm)
    return out


class PayrollsForecaster:
    name = "labor_nowcast"
    version = LABOR_ENGINE_VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: LaborData, *,
                 nowcasts_fn: Callable[[list[date], datetime], dict] | None = None):
        self._live, self._fetch_market = live, fetch_market
        self._nowcasts_fn = nowcasts_fn or (lambda months, now: payroll_nowcasts(
            data.inputs(now), months, {}, train_from=TRAIN_START))
        self._open: dict[str, tuple[date, LiveMarket]] = {}
        self._nowcasts: dict | None = None

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): (month, lm)
                      for month, lms in payroll_markets_by_month(self._live, now).items() for lm in lms}
        self._nowcasts = None
        return [entry_for(lm, "labor", self.cadence) for _, lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        month, lm = self._open[entry.target]
        if self._nowcasts is None:
            self._nowcasts = self._nowcasts_fn(sorted({m for m, _ in self._open.values()}), now)
        nc = self._nowcasts.get(month)
        if nc is None:
            return None
        return Forecast(self.name, self.version, entry.target, payroll_prob(lm.market, nc.mu, nc.sigma),
                        market_prob=quote_mid(lm),
                        payload={"month": month.isoformat(), "mu_k": round(nc.mu, 2), "sigma_k": round(nc.sigma, 2),
                                 "n_train": nc.model.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class _DirectionForecaster:
    """Shared shape of the two direction forecasters; subclasses set identity and the calendar."""

    name: str
    version: str
    cadence = "monthly"
    series: str
    threshold: float
    kind: str

    def __init__(self, data: LaborData, *, nowcast_fn: Callable[[date, datetime], DirectionNowcast | None],
                 settle_fn: Callable[[date, datetime], float | None] | None = None):
        self._nowcast_fn = nowcast_fn
        self._settle_fn = settle_fn or (lambda month, now: data.first_print_change(self.series, month, now))
        self._nowcasts: dict[str, DirectionNowcast | None] = {}

    def target_for(self, month: date) -> str:
        return f"labor:{self.kind}:{month:%Y-%m}:up"

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        raise NotImplementedError

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._nowcasts = {}
        entries = []
        for month, cutoff in self._calendar(now).items():
            nc = self._nowcast_fn(month, now)
            self._nowcasts[self.target_for(month)] = nc
            entries.append(CalendarEntry(self.target_for(month), "labor", self.cadence, cutoff,
                                         climatology_prob=nc.climatology if nc else None))
        return entries

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        nc = self._nowcasts.get(entry.target)
        if nc is None:
            return None
        return Forecast(self.name, self.version, entry.target, nc.prob_up,
                        payload={"month": nc.month.isoformat(), "mu": round(nc.mu, 4), "sigma": round(nc.sigma, 4),
                                 "climatology": round(nc.climatology, 4), "n_train": nc.model.n_train,
                                 "coef": dict(zip(nc.model.features, nc.model.coef))})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        change = self._settle_fn(_target_month(target), now)
        if change is None:
            return None
        return Settlement(target, int(change > self.threshold), f"fred:{self.series}:first_print", realized_value=change)


class UnrateDirection(_DirectionForecaster):
    name, version, series, threshold, kind = "unrate_direction", "unrate-dir-v1", "UNRATE", UNRATE_UP, "unrate"

    def __init__(self, live, data: LaborData, **kwargs):
        kwargs.setdefault("nowcast_fn", lambda month, now: unrate_nowcast(data, month, now))
        super().__init__(data, **kwargs)
        self._live = live

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        # The jobs release is the cutoff; the payroll markets carry it (they close 5 minutes before).
        return {m: min(lm.market.close_time for lm in lms) for m, lms in payroll_markets_by_month(self._live, now).items()}


class QuitsDirection(_DirectionForecaster):
    name, version, series, threshold, kind = "quits_direction", "quits-dir-v1", "JTSQUL", QUITS_UP, "quits"

    def __init__(self, data: LaborData, **kwargs):
        kwargs.setdefault("nowcast_fn", lambda month, now: quits_nowcast(data, month, now))
        super().__init__(data, **kwargs)

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        month = last_completed_month(now)
        cutoff = datetime.combine(month_end(month) + timedelta(days=QUITS_CUTOFF_DAYS), time(0), ET)
        return {month: cutoff} if now < cutoff else {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_labor.py -v && SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_labor*.py tests/test_backtest_labor.py`
Expected: all new tests pass except `test_the_registry_runs_the_labor_forecasters` (Task 2); the existing labor tests are unchanged (default `min_sigma` keeps payroll behaviour identical).

- [ ] **Step 5: Commit**

```bash
git add tradehub/engines/labor.py tradehub/engines/labor_direction.py tradehub/journal/forecasters/labor.py tests/test_journal_labor.py
git commit -m "feat(journal): payrolls, UNRATE and JOLTS-quits forecasters"
```

---
### Task 2: Register the labor forecasters

**Files:**
- Modify: `tradehub/journal/registry.py` (replace the whole file)

**Interfaces:**
- Produces: adds `labor_nowcast@labor-v1`, `kalshi_implied_labor@v1`, `unrate_direction@unrate-dir-v1`, `quits_direction@quits-dir-v1`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_labor.py`)

```python
# `test_the_registry_runs_the_labor_forecasters` was written in Task 1.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_labor.py -k registry -v`
Expected: FAIL — labor keys missing.

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
from tradehub.journal.kalshi_linked import KalshiImplied

_LIVE = KalshiLive()
_LABOR = LaborData()

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
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_*.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/registry.py
git commit -m "feat(journal): run the labor forecasters"
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
- [ ] **Operational note for the PR body:** the first run after a month ends loads ALFRED vintages (disk-cached under `TRADEHUB_ALFRED_CACHE`) and, once per series, up to 75 daily vintages to find a first print; with `FRED_API_KEY` set these are paced at `FRED_MIN_INTERVAL_SECONDS`. Subsequent hourly runs hit the cache.

## Self-Review

- **Spec §5 Labor:** payrolls as-is (Task 1, same version); UNRATE and JOLTS-quits direction as new ridge fits (Task 1); settlement on FRED first-print vintages with no consensus feed (`LaborData.first_print_change`).
- **Leakage:** features are `labor_features` at the month-end vintage (existing PIT rule); UNRATE freezes before the release via the KXPAYROLLS close; quits freezes by day 25 after the month, before any JOLTS release (~30–40 days).
- **Type consistency:** `DirectionNowcast` fields used by `_DirectionForecaster.forecast` match Task 1; `LaborData` methods match the tests' fakes.

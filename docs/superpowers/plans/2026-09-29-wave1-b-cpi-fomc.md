# CPI + FOMC Forecasters (Wave 1, Plan b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing CPI nowcast and an experimental CPI-mapped FOMC hold probability through the journal, each beside the Kalshi-implied pseudo-forecaster for the same markets.

**Architecture:** A shared `tradehub/journal/kalshi_linked.py` turns Kalshi markets into journal targets (`kalshi:<ticker>`), freezes them inside a 24h lead of the market close, and settles on Kalshi's final result. `CpiForecaster` reuses `tradehub.engines.cpi` unchanged (same math and versions as `scan_cpi`); `FomcMapped` is a small fixed mapping from the core-CPI nowcast; `KalshiImplied` freezes the market mid as the baseline forecaster.

**Tech Stack:** Python 3.12, existing `KalshiLive` / `fetch_market` / Cleveland Fed nowcast clients, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§5 CPI + FOMC, ruling Q5). **Depends on:** plan (a) merged (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`).

> **Provenance:** every code block below was implemented and run by the reviewer on top of plan (a) in a scratch worktree before this plan was written (full backend suite 1383 passed with `time.monotonic` forced to 5.0 and to 1e7; frontend vitest 462 passed, tsc, eslint and build clean; new Python files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- A forecaster is a class implementing `tradehub.journal.contract.Forecaster`; its `(name, version)` is its journal key and must be unique in `tradehub/journal/registry.py`.
- Constructing a forecaster must not touch the network; network happens only inside `targets` / `forecast` / `settle`.
- `forecast()` returns `None` when an input is missing (a recorded gap), never a guess or a default.
- CPI publishes with **no model changes** and the **same `engine_version`s** (`cpi-v1`, `cpi-core-v1`) under forecaster name `cpi_nowcast`, so the gate for those pairs moves to the journal once they have a scorecard (plan (a) Task 4).
- FOMC is labelled **experimental** (`payload.experimental = true`) and ships with its pseudo-forecaster from its first row (ruling Q5). Its constants are fixed a priori and never tuned on journal outcomes.
- Freeze lead for Kalshi-linked targets: 24h before market close, so model and market mid are frozen at the same horizon.
- A voided (canceled) Kalshi market never settles; it stays out of scoring.

---
### Task 1: Kalshi-linked plumbing, CPI, FOMC and the market pseudo-forecaster

**Files:**
- Create: `tradehub/journal/forecasters/__init__.py`, `tradehub/journal/kalshi_linked.py`, `tradehub/journal/forecasters/cpi.py`, `tradehub/journal/forecasters/fomc.py`
- Test: `tests/test_journal_cpi_fomc.py`

**Interfaces:**
- Consumes: plan (a) `CalendarEntry`, `Forecast`, `Settlement`, `run_journal`, `tests/journal_fakes.FakeJournalDB`; existing `tradehub.engines.cpi`, `tradehub.data.cleveland_fed.fetch_nowcast_history`, `tradehub.settlement.parse_market_result`, fixture `tests/fixtures/cleveland_nowcast_month_trimmed.json`.
- Produces: `kalshi_target(ticker) -> str`, `ticker_of(target) -> str`, `quote_mid(lm) -> float | None`, `in_freeze_window(lm, now, lead=FREEZE_LEAD) -> bool`, `entry_for(lm, family, cadence) -> CalendarEntry`, `settle_on_kalshi(target, fetch_market) -> Settlement | None`, `KalshiImplied(family, series, cadence, live, fetch_market, *, keep=...)` (name `kalshi_implied_<family>`, version `v1`), `CpiForecaster(series, live, fetch_market, *, nowcast_fn=..., params=None)`; `FOMC_SERIES = "KXFEDDECISION"`, `is_hold_market(lm)` (ticker ends `-H0`), `hold_probability(core_mom_pct)`, `FomcMapped(live, fetch_market, *, nowcast_fn=...)` (name `fomc_mapped`, version `fomc-mapped-v1`, cadence `meeting`).

- [ ] **Step 1: Write the failing test** (`tests/test_journal_cpi_fomc.py`)

```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.fomc import FomcMapped, hold_probability, is_hold_market
from tradehub.journal.kalshi_linked import KalshiImplied, settle_on_kalshi
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_cpi_market, parse_market

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text("utf-8"))
NOW = datetime(2026, 9, 11, 12, 5, tzinfo=UTC)  # 08:05 EDT on the Aug-2026 release morning
PARAMS = {"train_months": 24.0, "use_bias": 0.0}


def _cpi(series, strike, close="2026-09-11T12:25:00Z", bid=0.30, ask=0.34):
    event = f"{series}-26AUG"
    market = parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                               "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                               "title": f"{series} {strike}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=50.0, yes_ask_size=50.0))


def _fed(suffix, close="2026-09-11T18:59:00Z", bid=0.90, ask=0.94):
    event = "KXFEDDECISION-26SEP"
    market = parse_market({"ticker": f"{event}-{suffix}", "event_ticker": event, "strike_type": "custom",
                           "open_time": "2026-06-01T00:00:00Z", "close_time": close, "title": suffix})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=10.0, yes_ask_size=10.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _nowcast(kind):
    return parse_nowcast_month(PAYLOAD, kind)


def _result(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_cpi_forecaster_reproduces_the_scan_probability_and_freezes_the_market_mid():
    live = FakeLive([_cpi("KXCPI", 0.3), _cpi("KXCPICORE", 0.2)])
    fc = CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS)
    [entry] = fc.targets(NOW)
    assert entry.target == "kalshi:KXCPI-26AUG-T0.3" and entry.market_linked and entry.cadence == "monthly"
    forecast = fc.forecast(entry, NOW)
    assert (fc.name, fc.version) == ("cpi_nowcast", "cpi-v1")
    assert forecast.probability == pytest.approx(0.5244, abs=1e-4)  # same number test_scan_cpi pins
    assert forecast.market_prob == pytest.approx(0.32)
    assert forecast.payload["nowcast_obs"] == "CPI:2026-08@2026-09-10"


def test_only_markets_inside_the_freeze_lead_are_targets():
    live = FakeLive([_cpi("KXCPI", 0.3, close="2026-10-11T12:25:00Z"),  # a month out: not yet
                     _cpi("KXCPI", 0.4, close="2026-09-11T12:00:00Z")])  # already closed
    assert CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS).targets(NOW) == []


def test_kalshi_settlement_only_on_a_final_yes_or_no():
    assert settle_on_kalshi("kalshi:X", _result("yes")).outcome == 1
    assert settle_on_kalshi("kalshi:X", _result("no")).outcome == 0
    assert settle_on_kalshi("kalshi:X", _result(None)) is None  # voided: never settles
    assert settle_on_kalshi("kalshi:X", lambda t: {"market": {"status": "open"}}) is None


def test_hold_probability_is_the_prior_at_target_and_falls_away_from_it():
    assert hold_probability(2.0 / 12) == pytest.approx(0.70)
    assert hold_probability(2.4 / 12) == pytest.approx(0.70)  # inside the band
    assert hold_probability(4.5 / 12) < hold_probability(3.5 / 12) < 0.70
    assert hold_probability(-1.0 / 12) < 0.70


def test_fomc_targets_only_the_hold_market():
    live = FakeLive([_fed("H0"), _fed("C25"), _fed("H25")])
    fc = FomcMapped(live, _result("yes"), nowcast_fn=_nowcast)
    [entry] = fc.targets(NOW)
    assert entry.target == "kalshi:KXFEDDECISION-26SEP-H0" and entry.cadence == "meeting"
    forecast = fc.forecast(entry, NOW)
    assert 0.0 < forecast.probability < 1.0 and forecast.payload["experimental"] is True
    assert forecast.market_prob == pytest.approx(0.92)
    assert is_hold_market(_fed("H0")) and not is_hold_market(_fed("C25"))


def test_cpi_and_its_pseudo_forecaster_run_end_to_end_and_settle_on_kalshi():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_cpi("KXCPI", 0.3), _cpi("KXCPI", 0.4)])
    fcs = [CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS),
           KalshiImplied("cpi", ("KXCPI",), "monthly", live, _result("yes"))]
    out = run_journal(db, fcs, clock[0])
    assert out["forecasters"]["cpi_nowcast@cpi-v1"]["frozen"] == 2
    assert out["forecasters"]["kalshi_implied_cpi@v1"]["frozen"] == 2
    clock[0] = NOW + timedelta(hours=2)
    live.markets = []  # closed markets are no longer listed; settlement must not depend on them
    out = run_journal(db, fcs, clock[0])
    assert out["forecasters"]["cpi_nowcast@cpi-v1"]["settled"] == 2
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["kalshi_implied_cpi"]["bss"] == pytest.approx(0.0)  # the market vs itself
    assert cards["cpi_nowcast"]["baseline"] == "market" and cards["cpi_nowcast"]["gate_status"] == "SHADOW"


def test_the_registry_builds_without_network():
    from tradehub.journal.registry import FORECASTERS

    keys = {(f.name, f.version) for f in FORECASTERS}
    assert {("cpi_nowcast", "cpi-v1"), ("cpi_nowcast", "cpi-core-v1"), ("fomc_mapped", "fomc-mapped-v1"),
            ("kalshi_implied_cpi", "v1"), ("kalshi_implied_fomc", "v1")} <= keys
    assert len(keys) == len(FORECASTERS), "(name, version) must be unique: it is the journal key"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_cpi_fomc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradehub.journal.forecasters'`.

- [ ] **Step 3: Implement**

`tradehub/journal/forecasters/__init__.py`:

```python
"""Journal forecasters (v2 spec §5-§7). Each module implements `tradehub.journal.contract.Forecaster`."""
```

`tradehub/journal/kalshi_linked.py`:

```python
"""Shared plumbing for forecasters whose targets are Kalshi markets (v2 spec §5, §10 baselines).

A Kalshi-linked target is one market ticker, prefixed `kalshi:`. It is registered and frozen only
inside `FREEZE_LEAD` of the market close, so every forecaster (and the market mid it is compared
with) is frozen at the same horizon instead of whenever the market happened to be listed. It
settles on Kalshi's own result, exactly like `tradehub.settlement` settles `predictions`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.data.kalshi_live import LiveMarket
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.settlement import SETTLED, parse_market_result

FREEZE_LEAD = timedelta(hours=24)
TARGET_PREFIX = "kalshi:"
SETTLEMENT_SOURCE = "kalshi:market_result"


def kalshi_target(ticker: str) -> str:
    return f"{TARGET_PREFIX}{ticker}"


def ticker_of(target: str) -> str:
    if not target.startswith(TARGET_PREFIX):
        raise ValueError(f"not a Kalshi target: {target!r}")
    return target[len(TARGET_PREFIX):]


def quote_mid(lm: LiveMarket) -> float | None:
    """Mid of the top of book; None when either side is empty (same rule as the scan's `_mid`)."""
    if lm.quote.yes_bid is None or lm.quote.yes_ask is None:
        return None
    return (lm.quote.yes_bid + lm.quote.yes_ask) / 2.0


def in_freeze_window(lm: LiveMarket, now: datetime, lead: timedelta = FREEZE_LEAD) -> bool:
    return now < lm.market.close_time <= now + lead


def entry_for(lm: LiveMarket, family: str, cadence: str) -> CalendarEntry:
    return CalendarEntry(kalshi_target(lm.market.ticker), family, cadence, lm.market.close_time, market_linked=True)


def settle_on_kalshi(target: str, fetch_market: Callable[[str], Any]) -> Settlement | None:
    """Kalshi's final yes/no, or None while it is open. A voided market never settles (None forever)."""
    disposition, outcome = parse_market_result(fetch_market(ticker_of(target)))
    if disposition != SETTLED or outcome is None:
        return None
    return Settlement(target, outcome, SETTLEMENT_SOURCE)


class KalshiImplied:
    """The market pseudo-forecaster: freezes the Kalshi mid as its probability.

    It is the baseline the model forecasters are graded against, shown beside them on the journal.
    Its BSS against the market is 0 by construction, so it can never be promoted; that is intended.
    """

    version = "v1"

    def __init__(self, family: str, series: tuple[str, ...], cadence: str, live, fetch_market: Callable[[str], Any],
                 *, keep: Callable[[LiveMarket], bool] = lambda lm: True):
        self.name = f"kalshi_implied_{family}"
        self.family, self.series, self.cadence = family, series, cadence
        self._live, self._fetch_market, self._keep = live, fetch_market, keep
        self._open: dict[str, LiveMarket] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for s in self.series for lm in self._live.open_markets(s)
                      if in_freeze_window(lm, now) and self._keep(lm)}
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        mid = quote_mid(lm) if lm else None
        if mid is None:
            return None
        return Forecast(self.name, self.version, entry.target, mid, market_prob=mid,
                        payload={"yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
```

`tradehub/journal/forecasters/cpi.py`:

```python
"""CPI m/m through the journal (v2 spec §5): the existing nowcast engine, no model changes.

Same math as `tradehub.scripts.scan.scan_cpi` (Cleveland Fed nowcast, `Normal(nowcast + bias, sigma)`
fit at the decision horizon, KXCPI/KXCPICORE bucket mapping) and the same `engine_version`s, so the
journal grades the engine the site already shows. Headline and core are separate forecasters because
they are separate track records.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.data.cleveland_fed import fetch_nowcast_history
from tradehub.data.kalshi_live import LiveMarket
from tradehub.engine_config import load_engine_config
from tradehub.engines.cpi import CPI_TARGETS, CPI_TRAIN_MONTHS, cpi_prob, fit_cpi_error, latest_nowcast, training_pairs
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
from tradehub.markets import event_month

CPI_ENGINE = "cpi_nowcast"


class CpiForecaster:
    name = CPI_ENGINE
    cadence = "monthly"

    def __init__(self, series: str, live, fetch_market: Callable[[str], Any], *,
                 nowcast_fn: Callable[[str], dict] = fetch_nowcast_history, params: dict[str, float] | None = None):
        self.kind, self.version = CPI_TARGETS[series]
        self.series = series
        self._live, self._fetch_market, self._nowcast_fn = live, fetch_market, nowcast_fn
        params = params if params is not None else load_engine_config(CPI_ENGINE).params
        self._window = int(params.get("train_months", CPI_TRAIN_MONTHS))
        self._use_bias = bool(params.get("use_bias", 0.0))
        self._open: dict[str, LiveMarket] = {}
        self._history: dict | None = None

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(self.series)
                      if in_freeze_window(lm, now)}
        self._history = None  # refetched lazily, once per run, only if something needs forecasting
        return [entry_for(lm, "cpi", self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        if self._history is None:
            self._history = self._nowcast_fn(self.kind)
        nowcast = latest_nowcast(self._history.get(event_month(lm.market.event_ticker)), now)
        horizon = lm.market.close_time - now
        if nowcast is None:
            return None
        pairs = training_pairs(self._history, now, horizon)[-self._window:]
        model = fit_cpi_error(pairs, window=self._window, use_bias=self._use_bias)
        return Forecast(self.name, self.version, entry.target, cpi_prob(lm.market, nowcast.value, model),
                        market_prob=quote_mid(lm),
                        payload={"nowcast": nowcast.value, "nowcast_obs": nowcast.name, "bias": model.bias,
                                 "sigma": model.sigma, "n_train": len(pairs),
                                 "hours_to_close": round(horizon.total_seconds() / 3600.0, 2)})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
```

`tradehub/journal/forecasters/fomc.py`:

```python
"""FOMC decision, experimental (v2 spec §5, ruling Q5): P(the Fed holds) mapped from the CPI nowcast.

There is no FOMC model. This is a small fixed mapping, published so the journal can show whether it
beats the Kalshi pseudo-forecaster it ships beside (it is expected not to; it is the first candidate
for `retired`). Target: the "Fed maintains rate" market (`KXFEDDECISION-<meeting>-H0`) of each meeting.

Mapping (constants fixed a priori, never tuned on journal outcomes):
    annualized core CPI  a = latest core nowcast (m/m %) x 12
    logit P(hold) = logit(HOLD_PRIOR) - SLOPE x max(0, |a - TARGET| - BAND)
Inflation near target -> the base-rate hold probability; far from target in either direction ->
more likely to move. Labor is not an input in v1: the payroll nowcast only exists in the few days
between a reference month's end and its release, which rarely brackets a meeting.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.data.cleveland_fed import fetch_nowcast_history
from tradehub.data.kalshi_live import LiveMarket
from tradehub.engines.cpi import latest_nowcast
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi

FOMC_SERIES = "KXFEDDECISION"
HOLD_SUFFIX = "-H0"
HOLD_PRIOR = 0.70  # share of scheduled FOMC meetings with no change, order of magnitude since 1994
INFLATION_TARGET = 2.0
BAND = 0.5  # pp of annualized core inflation treated as "at target"
SLOPE = 1.0  # logit units per pp outside the band


def is_hold_market(lm: LiveMarket) -> bool:
    return lm.market.series_ticker == FOMC_SERIES and lm.market.ticker.endswith(HOLD_SUFFIX)


def hold_probability(core_mom_pct: float) -> float:
    annualized = core_mom_pct * 12.0
    gap = max(0.0, abs(annualized - INFLATION_TARGET) - BAND)
    logit = math.log(HOLD_PRIOR / (1.0 - HOLD_PRIOR)) - SLOPE * gap
    return 1.0 / (1.0 + math.exp(-logit))


def latest_core_nowcast(history: dict, now: datetime):
    """The newest core-CPI nowcast known at `now`, across all months."""
    known = [obs for month in history.values() if (obs := latest_nowcast(month, now)) is not None]
    return max(known, key=lambda o: o.published_at) if known else None


class FomcMapped:
    name = "fomc_mapped"
    version = "fomc-mapped-v1"
    cadence = "meeting"

    def __init__(self, live, fetch_market: Callable[[str], Any], *,
                 nowcast_fn: Callable[[str], dict] = fetch_nowcast_history):
        self._live, self._fetch_market, self._nowcast_fn = live, fetch_market, nowcast_fn
        self._open: dict[str, LiveMarket] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(FOMC_SERIES)
                      if is_hold_market(lm) and in_freeze_window(lm, now)}
        return [entry_for(lm, "fomc", self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        core = latest_core_nowcast(self._nowcast_fn("core"), now) if lm else None
        if core is None:
            return None
        return Forecast(self.name, self.version, entry.target, hold_probability(core.value),
                        market_prob=quote_mid(lm),
                        payload={"core_nowcast": core.value, "core_obs": core.name, "experimental": True,
                                 "hold_prior": HOLD_PRIOR, "slope": SLOPE, "band": BAND})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_cpi_fomc.py -v`
Expected: 6 passed, 1 failed (`test_the_registry_builds_without_network`, Task 2). 0.5244 is the probability `tests/test_scan_cpi.py` pins: proof of no model change. FOMC reference points: core m/m 0.20 → P(hold) 0.70, 0.25 → 0.586, 0.30 → 0.437, 0.35 → 0.299.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/forecasters/__init__.py tradehub/journal/kalshi_linked.py tradehub/journal/forecasters/cpi.py tradehub/journal/forecasters/fomc.py tests/test_journal_cpi_fomc.py
git commit -m "feat(journal): CPI, experimental FOMC, and Kalshi pseudo-forecasters"
```

---
### Task 2: Register the forecasters

**Files:**
- Modify: `tradehub/journal/registry.py` (replace the whole file)

**Interfaces:**
- Produces: `FORECASTERS` containing `cpi_nowcast@cpi-v1`, `cpi_nowcast@cpi-core-v1`, `kalshi_implied_cpi@v1`, `fomc_mapped@fomc-mapped-v1`, `kalshi_implied_fomc@v1`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_cpi_fomc.py`)

```python
# `test_the_registry_builds_without_network` was written in Task 1 and is the one still failing.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_cpi_fomc.py -k registry -v`
Expected: FAIL — the registry is empty.

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
from tradehub.journal.kalshi_linked import KalshiImplied

_LIVE = KalshiLive()

FORECASTERS: list[Forecaster] = [
    # plan (b): CPI + FOMC, each beside its Kalshi pseudo-forecaster (spec §5, ruling Q5)
    CpiForecaster("KXCPI", _LIVE, fetch_market),
    CpiForecaster("KXCPICORE", _LIVE, fetch_market),
    KalshiImplied("cpi", ("KXCPI", "KXCPICORE"), "monthly", _LIVE, fetch_market),
    FomcMapped(_LIVE, fetch_market),
    KalshiImplied("fomc", (FOMC_SERIES,), "meeting", _LIVE, fetch_market, keep=is_hold_market),
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_cpi_fomc.py tests/test_journal_runner.py tests/test_scan_cpi.py -v`
Expected: all pass (7 in the new file).

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/registry.py
git commit -m "feat(journal): run CPI, FOMC and their Kalshi baselines"
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

- **Spec §5 CPI + FOMC:** CPI unchanged and journaled (Task 1); FOMC mapped from CPI nowcast inputs, experimental, beside its pseudo-forecaster from row one (Tasks 1–2, ruling Q5). Labor as an FOMC input is deliberately not in v1: the payroll nowcast exists only between a month's end and its release, which rarely brackets a meeting (documented in `fomc.py`).
- **Baseline:** every target here is market-linked, so BSS is vs the frozen Kalshi mid; `KalshiImplied` has BSS 0 by construction and can never be promoted.
- **Type consistency:** target ids `kalshi:<ticker>` everywhere; forecaster keys match the registry test.

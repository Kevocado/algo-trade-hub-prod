# Data Layer + Weather & Gas Engines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P&L core: a `weather` engine for Kalshi daily-high markets in NYC, Chicago and Miami, and a `gas` engine for the national AAA daily market. A one-shot scan writes every prediction to the `predictions` ledger and writes trade-worthy edges, with deep links, to `kalshi_edges`. It runs suggest-only (nothing is ever executed), and each engine can be backtested point-in-time on the step 3 harness.

**Architecture:**
- **Pure engines:** `tradehub/engines/weather.py` and `gas.py` map a snapshot plus a market to `our_prob` using an explainable normal-error model with walk-forward-fitted parameters.
- **Pure market geometry:** `tradehub/markets.py` turns Kalshi strike types into outcome intervals.
- **Pure edge layer:** `tradehub/edges.py` handles the after-fee edge vs. the executable bid/ask, maker-first, with no taker buys under 10¢. The step 3 fill model is refactored to share its side-selection code.
- **Data fetchers:** `tradehub/data/` handles Kalshi live markets and settled values, Open-Meteo forecasts, and RBOB futures. They return `Observation`s stamped with a publish time.
- **Entrypoints:** `tradehub/scripts/scan.py` (live) and `tradehub/scripts/backtest_engines.py` (point-in-time decision builders plus a CLI) wire everything together.

**Tech Stack:** Python 3.12, `requests`, `yfinance`, `pyyaml`, stdlib `math`/`statistics`/`zoneinfo`, `pytest` + `monkeypatch`.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md), §3.1 (weather + gas rows), §4 (architecture: data layer, pure engines, edge layer, predictions ledger, `EXECUTION_MODE=suggest`), §5a (backtest before shipping), §6 (gate). Rollout step 4 in [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md).

## Global Constraints

- **Prerequisites:** step 2 (predictions ledger: `tradehub/predictions.py`, `tradehub/track_record.py`, `tradehub/settlement.py`) and step 3 (backtesting suite: `tradehub/backtest/*`) are merged to `main`. This plan imports from both. Never copy their code.
- **Suggest-only (spec §4.6):** nothing here places an order, and no Kalshi auth is used. All Kalshi calls go to the public production base `https://api.elections.kalshi.com/trade-api/v2`.
- **Edge rules (spec §4.3):**
  - the edge is after fees (`shared/kalshi_fees.py`) and computed against the executable bid/ask, never the mid;
  - never suggest a taker buy below 10¢;
  - prefer maker (limit) entries.
- **Engine names written to `predictions.engine` are exactly `"weather"` and `"gas"`.** Step 2's settlement cron lists these names in `ENGINES`.
- **Weather settlement facts** (from Kalshi market rules, verified 2026-09-24): NYC settles on `CLINYC` (Central Park), Chicago on `CLIMDW` (**Midway, not O'Hare**), Miami on `CLIMIA`.
  - The daily high is the NWS climate-day maximum in whole °F.
  - The climate day runs in local **standard** time: `Etc/GMT+5` for NYC and Miami, `Etc/GMT+6` for Chicago. Markets close at 05:00 / 06:00 UTC year-round to match.
  - Strikes: `greater k` means YES if the high is at least k+1; `less k` means YES if it is at most k−1; `between floor–cap` means YES if the high is in [floor, cap].
- **Gas settlement facts** (verified 2026-09-24): series `KXAAAGASD`. A market is YES if the AAA US regular average is **strictly greater** than its strike on the event date.
  - The market closes at 23:59 ET the night *before* the event date.
  - The settled market's `expiration_value` is that day's AAA average, and `settlement_ts` is when it became public. Kalshi's settled markets are therefore the AAA history, so no scraping is needed.
- **Don't import `shared.config` from new modules.** It hard-requires env vars at import time.
- **Never edit an existing migration.** New schema goes in a new timestamped file.
- **Test runs:** `.venv/bin/python` from the repo root, each pytest run prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Follow the handoff contract in the rollout tracker: branch `plan/2026-09-24-data-layer-weather-gas-engines`, one commit per task, evidence report at `docs/superpowers/reports/2026-09-24-data-layer-weather-gas-engines.md`.

## Review Focus

- Strike-to-interval mapping uses half-unit continuity exactly as in the Global Constraints (weather resolution 1.0 °F, gas resolution $0.0001). (Task 2)
- Weather aggregates forecast hours over the LST climate day (`Etc/GMT+…`), never over the local clock day. (Task 4)
- Gas decisions only use AAA values whose `settlement_ts` is at or before the decision time, and RBOB closes at or before it. (Tasks 6, 10)
- Weather backtest decisions happen at 23:30 LST the day before the target date and use lead-1 forecasts, which were published by 23:00 LST that day. They must pass the step 3 leakage guard. (Task 10)
- The error and gas models are fit only on data knowable at the decision time (walk-forward). (Task 10)
- `tradehub/backtest/fills.py` keeps passing its step 3 tests after its side-selection code moves to `tradehub/edges.py`. (Task 7)

---

## File Structure

- **Create** `market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql`: adds `market_url`/`source_url` columns to `kalshi_edges`, allows `edge_type = 'ENERGY'`, and adds a unique index on `market_id`.
- **Create** `tradehub/markets.py`: `KalshiMarket`, `parse_market`, `event_date`, `yes_interval`, `prob_in_interval`, `market_url`.
- **Create** `tradehub/edges.py`: `MIN_TAKER_PRICE`, `Quote`, `best_side`, `EdgeSuggestion`, `evaluate_edge`.
- **Modify** `tradehub/backtest/fills.py`: import `MIN_TAKER_PRICE`/`best_side` from `tradehub.edges` and delete its private copies.
- **Create** `tradehub/data/__init__.py`, `tradehub/data/kalshi_live.py` (`LiveMarket`, `quote_from_market_raw`, `settlement_observations`, `KalshiLive`), `tradehub/data/weather.py` (`City`, `WEATHER_CITIES`, `WEATHER_MODELS`, `live_forecast_highs`, `historical_forecast_highs`), `tradehub/data/rbob.py` (`rbob_closes`).
- **Create** `tradehub/engines/weather.py` (`ErrorModel`, `DEFAULT_ERROR`, `fit_error_model`, `weather_prob`) and `tradehub/engines/gas.py` (`GasModel`, `DEFAULT_GAS`, `RBOB_WINDOW`, `rbob_change`, `gas_training_pairs`, `fit_gas_model`, `gas_prob`).
- **Create** `tradehub/config/engines.yaml`, `tradehub/engine_config.py`: `EngineConfig`, `load_engine_config`.
- **Modify** `tradehub/core/supabase_client.py` `upsert_opportunities`: write `market_url`/`source_url` and allow `ENERGY`.
- **Create** `tradehub/scripts/scan.py`: `edge_row`, `scan_weather`, `scan_gas`, `main`.
- **Create** `tradehub/scripts/backtest_engines.py`: `weather_decision_time`, `build_weather_decisions`, `build_gas_decisions`, `main`.
- **Modify** `research/weather_notes/Markets/Kalshi_Weather_Market_Mapping.md`: correct Chicago to Midway and add Miami.
- **Tests:** `tests/test_markets.py`, `tests/test_edges.py`, `tests/test_kalshi_live.py`, `tests/test_weather_data.py`, `tests/test_weather_engine.py`, `tests/test_gas_engine.py`, `tests/test_engine_config.py`, `tests/test_scan.py`, `tests/test_backtest_engines.py`, plus one assertion in `tests/test_repo_layout.py`.

---

## Task 1: `kalshi_edges` migration (URLs, ENERGY, unique market_id)

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Produces: `kalshi_edges.market_url text` and `kalshi_edges.source_url text`; `edge_type` may be `WEATHER|MACRO|SPORTS|CRYPTO|ENERGY`; a unique index on `market_id` (required by `upsert(..., on_conflict="market_id")`).

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_kalshi_edges_urls_energy_migration():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql"
    assert path.is_file(), "kalshi_edges urls/energy migration is missing"
    sql = path.read_text(encoding="utf-8")
    for needle in ("market_url", "source_url", "'ENERGY'", "kalshi_edges_market_id_key"):
        assert needle in sql, f"migration missing {needle}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_kalshi_edges_urls_energy_migration -q`
Expected: FAIL, "kalshi_edges urls/energy migration is missing".

- [ ] **Step 3: Write the migration**

```sql
-- kalshi_edges: deep links + ENERGY edge type + unique market_id (rollout step 4).
-- Idempotent. The original CHECK was declared inline on edge_type, so
-- Postgres named it kalshi_edges_edge_type_check.

ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS market_url text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS source_url text;

ALTER TABLE kalshi_edges DROP CONSTRAINT IF EXISTS kalshi_edges_edge_type_check;
ALTER TABLE kalshi_edges ADD CONSTRAINT kalshi_edges_edge_type_check
  CHECK (edge_type IN ('WEATHER', 'MACRO', 'SPORTS', 'CRYPTO', 'ENERGY'));

-- upsert(on_conflict="market_id") requires a unique index on market_id.
CREATE UNIQUE INDEX IF NOT EXISTS kalshi_edges_market_id_key ON kalshi_edges (market_id);
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql tests/test_repo_layout.py
git commit -m "feat: add kalshi_edges deep-link columns and ENERGY edge type

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Note: before applying in production, check that no duplicate `market_id` rows exist, otherwise the unique index fails: `SELECT market_id, count(*) FROM kalshi_edges GROUP BY 1 HAVING count(*) > 1;`. Applying the migration is a manual deploy step for Kevin.

---

## Task 2: Market geometry (`tradehub/markets.py`)

**Files:**
- Create: `tradehub/markets.py`
- Test: `tests/test_markets.py`

**Interfaces:**
- Consumes: `tradehub.backtest.kalshi_history.parse_ts` (step 3).
- Produces:
  - `KalshiMarket(ticker, event_ticker, series_ticker, strike_type, floor_strike: float | None, cap_strike: float | None, open_time: datetime, close_time: datetime, title: str)` (frozen dataclass).
  - `parse_market(raw: dict) -> KalshiMarket`.
  - `event_date(event_ticker: str) -> date`, e.g. `"KXHIGHNY-26SEP25"` gives `date(2026, 9, 25)`.
  - `yes_interval(market, resolution: float) -> tuple[float, float]`.
  - `prob_in_interval(mu: float, sigma: float, interval: tuple[float, float]) -> float`.
  - `market_url(market) -> str`, i.e. `https://kalshi.com/markets/{series_ticker lowercased}`.

- [ ] **Step 1: Write the failing tests** — `tests/test_markets.py`:

```python
import math
from datetime import date, datetime, timezone

import pytest

from tradehub.markets import event_date, market_url, parse_market, prob_in_interval, yes_interval

RAW = {
    "ticker": "KXHIGHNY-26SEP25-T74", "event_ticker": "KXHIGHNY-26SEP25", "strike_type": "greater",
    "floor_strike": 74, "cap_strike": None, "open_time": "2026-09-23T14:00:00Z",
    "close_time": "2026-09-26T05:00:00Z", "title": "Highest temperature in NYC",
}


def test_parse_market():
    m = parse_market(RAW)
    assert m.series_ticker == "KXHIGHNY"
    assert m.floor_strike == 74.0 and m.cap_strike is None
    assert m.close_time == datetime(2026, 9, 26, 5, tzinfo=timezone.utc)
    assert m.open_time == datetime(2026, 9, 23, 14, tzinfo=timezone.utc)


def test_event_date():
    assert event_date("KXHIGHNY-26SEP25") == date(2026, 9, 25)
    assert event_date("KXAAAGASD-26JUL01") == date(2026, 7, 1)


def test_yes_interval_weather_integer_strikes():
    greater = parse_market(RAW)
    less = parse_market(dict(RAW, strike_type="less", floor_strike=None, cap_strike=67))
    between = parse_market(dict(RAW, strike_type="between", floor_strike=87, cap_strike=88))
    assert yes_interval(greater, 1.0) == (74.5, math.inf)     # YES iff high >= 75
    assert yes_interval(less, 1.0) == (-math.inf, 66.5)       # YES iff high <= 66
    assert yes_interval(between, 1.0) == (86.5, 88.5)         # YES iff high in {87, 88}


def test_yes_interval_gas_strictly_greater():
    gas = parse_market(dict(RAW, ticker="KXAAAGASD-26SEP25-4.5200", event_ticker="KXAAAGASD-26SEP25", floor_strike=4.52))
    lo, hi = yes_interval(gas, 0.0001)
    assert lo == pytest.approx(4.52005) and hi == math.inf


def test_yes_interval_rejects_unknown_strike_type():
    with pytest.raises(ValueError):
        yes_interval(parse_market(dict(RAW, strike_type="custom")), 1.0)


def test_prob_in_interval():
    assert prob_in_interval(70.0, 2.0, (70.0, math.inf)) == pytest.approx(0.5)
    assert prob_in_interval(70.0, 2.0, (-math.inf, math.inf)) == pytest.approx(1.0)
    assert prob_in_interval(70.0, 2.0, (72.0, math.inf)) == pytest.approx(0.158655, abs=1e-5)
    with pytest.raises(ValueError):
        prob_in_interval(70.0, 0.0, (70.0, math.inf))


def test_market_url():
    assert market_url(parse_market(RAW)) == "https://kalshi.com/markets/kxhighny"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_markets.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tradehub.markets'`.

- [ ] **Step 3: Implement** — `tradehub/markets.py`:

```python
"""Kalshi market model and strike geometry (pure)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from tradehub.backtest.kalshi_history import parse_ts


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    event_ticker: str
    series_ticker: str
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None
    open_time: datetime
    close_time: datetime
    title: str


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_market(raw: dict[str, Any]) -> KalshiMarket:
    event = raw["event_ticker"]
    return KalshiMarket(
        ticker=raw["ticker"],
        event_ticker=event,
        series_ticker=event.split("-")[0],
        strike_type=raw["strike_type"],
        floor_strike=_opt_float(raw.get("floor_strike")),
        cap_strike=_opt_float(raw.get("cap_strike")),
        open_time=parse_ts(raw["open_time"]),
        close_time=parse_ts(raw["close_time"]),
        title=raw.get("title", ""),
    )


def event_date(event_ticker: str) -> date:
    """'KXHIGHNY-26SEP25' -> date(2026, 9, 25)."""
    return datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()


def yes_interval(market: KalshiMarket, resolution: float) -> tuple[float, float]:
    """Continuous interval of the settled value for which the market resolves YES.

    `resolution` is the reporting unit (1.0 °F for highs, $0.0001 for AAA gas),
    so a 'greater than k' market on an integer-reported value is YES above k + 0.5.
    """
    half = resolution / 2.0
    if market.strike_type == "greater":
        return (market.floor_strike + half, math.inf)
    if market.strike_type == "less":
        return (-math.inf, market.cap_strike - half)
    if market.strike_type == "between":
        return (market.floor_strike - half, market.cap_strike + half)
    raise ValueError(f"unsupported strike_type {market.strike_type!r} for {market.ticker}")


def _normal_cdf(x: float, mu: float, sigma: float) -> float:
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))


def prob_in_interval(mu: float, sigma: float, interval: tuple[float, float]) -> float:
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    lo, hi = interval
    return min(1.0, max(0.0, _normal_cdf(hi, mu, sigma) - _normal_cdf(lo, mu, sigma)))


def market_url(market: KalshiMarket) -> str:
    return f"https://kalshi.com/markets/{market.series_ticker.lower()}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_markets.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/markets.py tests/test_markets.py
git commit -m "feat: add Kalshi market strike geometry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Kalshi live markets and settled values (`tradehub/data/kalshi_live.py`)

**Files:**
- Create: `tradehub/data/__init__.py` (empty), `tradehub/data/kalshi_live.py`
- Create: `tradehub/edges.py` with only the `Quote` dataclass for now (Task 7 adds the rest)
- Test: `tests/test_kalshi_live.py`

**Interfaces:**
- Consumes: `KalshiHistoryClient` (step 3; `KalshiLive` subclasses it to reuse `_get`/`_paginate`/`settled_markets`), `Observation` (step 3), `parse_market`/`event_date` (Task 2).
- Produces in `tradehub/edges.py`: `Quote(yes_bid: float | None, yes_ask: float | None, yes_bid_size: float, yes_ask_size: float)`.
- Produces in `tradehub/data/kalshi_live.py`:
  - `LiveMarket(market: KalshiMarket, quote: Quote)`.
  - `quote_from_market_raw(raw: dict) -> Quote`. A bid of `<= 0` becomes `None`; an ask of `>= 1` becomes `None`.
  - `settlement_observations(raws: list[dict]) -> list[Observation]`. There is one observation per `event_ticker`: `value = float(expiration_value)`, `published_at` = the earliest `settlement_ts`, `name` = the event ticker. Blank values are skipped, and the result is sorted by event date.
  - `KalshiLive(get_json=default_get_json)`, subclassing `KalshiHistoryClient`, with `.open_markets(series_ticker) -> list[LiveMarket]` and `.settled_values(series_ticker) -> list[Observation]` (historical tier plus live-tier `status=settled`).

- [ ] **Step 1: Write the failing tests** — `tests/test_kalshi_live.py`:

```python
from datetime import date, datetime, timezone

import pytest

from tradehub.backtest.kalshi_history import KALSHI_PUBLIC_BASE
from tradehub.data.kalshi_live import KalshiLive, quote_from_market_raw, settlement_observations
from tradehub.markets import event_date

OPEN = {
    "ticker": "KXAAAGASD-26SEP25-4.5200", "event_ticker": "KXAAAGASD-26SEP25", "strike_type": "greater",
    "floor_strike": 4.52, "cap_strike": None, "open_time": "2026-09-24T14:00:00Z",
    "close_time": "2026-09-25T03:59:00Z", "title": "US gas price",
    "yes_bid_dollars": "0.4100", "yes_ask_dollars": "0.4400", "yes_bid_size_fp": "120.00", "yes_ask_size_fp": "35.00",
}


class FakeGet:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None):
        path = url.replace(KALSHI_PUBLIC_BASE, "")
        self.calls.append((path, dict(params or {})))
        pages = self.routes[path]
        return pages.pop(0) if isinstance(pages, list) else pages


def test_quote_from_market_raw():
    q = quote_from_market_raw(OPEN)
    assert q.yes_bid == pytest.approx(0.41) and q.yes_ask == pytest.approx(0.44)
    assert q.yes_bid_size == pytest.approx(120.0) and q.yes_ask_size == pytest.approx(35.0)


def test_quote_empty_sides_are_none():
    q = quote_from_market_raw(dict(OPEN, yes_bid_dollars="0.0000", yes_ask_dollars="1.0000"))
    assert q.yes_bid is None and q.yes_ask is None


def test_open_markets_paginates_and_pairs_quotes():
    get = FakeGet({"/markets": [{"markets": [OPEN], "cursor": "c"}, {"markets": [OPEN], "cursor": ""}]})
    live = KalshiLive(get_json=get).open_markets("KXAAAGASD")
    assert len(live) == 2 and live[0].market.ticker == "KXAAAGASD-26SEP25-4.5200"
    assert get.calls[0][1] == {"series_ticker": "KXAAAGASD", "status": "open", "limit": 1000}


def test_settlement_observations_one_per_event_sorted_skipping_blanks():
    raws = [
        {"event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.4825", "settlement_ts": "2026-09-24T11:52:00Z"},
        {"event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.4825", "settlement_ts": "2026-09-24T11:50:26Z"},
        {"event_ticker": "KXAAAGASD-26SEP23", "expiration_value": "4.4610", "settlement_ts": "2026-09-23T11:49:00Z"},
        {"event_ticker": "KXAAAGASD-26SEP22", "expiration_value": "", "settlement_ts": "2026-09-22T11:49:00Z"},
    ]
    obs = settlement_observations(raws)
    assert [o.name for o in obs] == ["KXAAAGASD-26SEP23", "KXAAAGASD-26SEP24"]
    assert obs[1].value == pytest.approx(4.4825)
    assert obs[1].published_at == datetime(2026, 9, 24, 11, 50, 26, tzinfo=timezone.utc)
    assert event_date(obs[0].name) == date(2026, 9, 23)


def test_settled_values_merges_historical_and_live_tiers():
    get = FakeGet({
        "/historical/markets": {"markets": [{"event_ticker": "KXAAAGASD-26JUL01", "expiration_value": "4.1", "settlement_ts": "2026-07-01T11:50:00Z"}], "cursor": ""},
        "/markets": {"markets": [{"event_ticker": "KXAAAGASD-26SEP24", "expiration_value": "4.48", "settlement_ts": "2026-09-24T11:50:00Z"}], "cursor": ""},
    })
    obs = KalshiLive(get_json=get).settled_values("KXAAAGASD")
    assert [o.name for o in obs] == ["KXAAAGASD-26JUL01", "KXAAAGASD-26SEP24"]
    assert ("/markets", {"series_ticker": "KXAAAGASD", "status": "settled", "limit": 1000}) in get.calls
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_live.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.data`.

- [ ] **Step 3: Implement** — `tradehub/edges.py` (only this for now):

```python
"""Edge layer: after-fee edge vs executable quotes, maker-first, no taker longshots (spec §4.3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quote:
    yes_bid: float | None
    yes_ask: float | None
    yes_bid_size: float
    yes_ask_size: float
```

Create an empty `tradehub/data/__init__.py`, then `tradehub/data/kalshi_live.py`:

```python
"""Kalshi live markets (with top-of-book quotes) and settled values as point-in-time observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradehub.backtest.kalshi_history import PAGE_LIMIT, KalshiHistoryClient, parse_ts
from tradehub.backtest.pit import Observation
from tradehub.edges import Quote
from tradehub.markets import KalshiMarket, event_date, parse_market


@dataclass(frozen=True)
class LiveMarket:
    market: KalshiMarket
    quote: Quote


def quote_from_market_raw(raw: dict[str, Any]) -> Quote:
    bid = float(raw.get("yes_bid_dollars") or 0.0)
    ask = float(raw.get("yes_ask_dollars") or 1.0)
    return Quote(
        yes_bid=bid if bid > 0.0 else None,
        yes_ask=ask if ask < 1.0 else None,
        yes_bid_size=float(raw.get("yes_bid_size_fp") or 0.0),
        yes_ask_size=float(raw.get("yes_ask_size_fp") or 0.0),
    )


def settlement_observations(raws: list[dict[str, Any]]) -> list[Observation]:
    """One Observation per event: the settled underlying value and when Kalshi published it."""
    best: dict[str, Observation] = {}
    for raw in raws:
        value = raw.get("expiration_value")
        stamp = raw.get("settlement_ts")
        if value in (None, "") or not stamp:
            continue
        obs = Observation(name=raw["event_ticker"], value=float(value), published_at=parse_ts(stamp))
        current = best.get(obs.name)
        if current is None or obs.published_at < current.published_at:
            best[obs.name] = obs
    return sorted(best.values(), key=lambda o: event_date(o.name))


class KalshiLive(KalshiHistoryClient):
    def open_markets(self, series_ticker: str) -> list[LiveMarket]:
        raws = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "open", "limit": PAGE_LIMIT})
        return [LiveMarket(parse_market(r), quote_from_market_raw(r)) for r in raws]

    def settled_values(self, series_ticker: str) -> list[Observation]:
        historical = self.settled_markets(series_ticker)
        live = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "settled", "limit": PAGE_LIMIT})
        return settlement_observations(historical + live)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_live.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/edges.py tradehub/data/__init__.py tradehub/data/kalshi_live.py tests/test_kalshi_live.py
git commit -m "feat: add Kalshi live markets and settled-value observations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Weather data (`tradehub/data/weather.py`) + station-note fix

**Files:**
- Create: `tradehub/data/weather.py`
- Modify: `research/weather_notes/Markets/Kalshi_Weather_Market_Mapping.md`
- Test: `tests/test_weather_data.py`

**Interfaces:**
- Consumes: `Observation`, `default_get_json`, `forecast_daily_high` (step 3).
- Produces:
  - `City(name: str, cli_station: str, latitude: float, longitude: float, lst_timezone: str)`.
  - `WEATHER_CITIES: dict[str, City]`, keyed by series ticker (`KXHIGHNY`, `KXHIGHCHI`, `KXHIGHMIA`).
  - `WEATHER_MODELS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")`.
  - `FORECAST_URL = "https://api.open-meteo.com/v1/forecast"`.
  - `live_forecast_highs(city, target_date, now, get_json=default_get_json) -> list[Observation]`: one per model with data, `published_at = now`, name `"openmeteo:{model}:high:{date}:live"`.
  - `historical_forecast_highs(city, target_date, lead_days, get_json=default_get_json) -> list[Observation]`: step 3's `forecast_daily_high` per model, skipping models that return no data.

The multi-model response keys are `temperature_2m_{model}` (verified live 2026-09-24), and `timezone=Etc/GMT+5` is accepted.

- [ ] **Step 1: Write the failing tests** — `tests/test_weather_data.py`:

```python
from datetime import date, datetime, timezone

import pytest

from tradehub.data.weather import (
    FORECAST_URL,
    WEATHER_CITIES,
    WEATHER_MODELS,
    historical_forecast_highs,
    live_forecast_highs,
)

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)


class Recorder:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.payload(params) if callable(self.payload) else self.payload


def test_cities_use_settlement_stations_and_standard_time_days():
    assert WEATHER_CITIES["KXHIGHNY"].cli_station == "CLINYC"
    assert WEATHER_CITIES["KXHIGHCHI"].cli_station == "CLIMDW"   # Midway, not O'Hare
    assert WEATHER_CITIES["KXHIGHMIA"].cli_station == "CLIMIA"
    assert WEATHER_CITIES["KXHIGHNY"].lst_timezone == "Etc/GMT+5"
    assert WEATHER_CITIES["KXHIGHCHI"].lst_timezone == "Etc/GMT+6"


def test_live_forecast_highs_one_per_model_max_over_lst_day():
    hourly = {"time": [f"2026-09-25T{h:02d}:00" for h in range(24)],
              "temperature_2m_gfs_seamless": [60.0] * 23 + [71.0],
              "temperature_2m_ecmwf_ifs025": [None] * 12 + [70.0] * 12,
              "temperature_2m_icon_seamless": [None] * 24}
    rec = Recorder({"hourly": hourly})
    obs = live_forecast_highs(WEATHER_CITIES["KXHIGHNY"], date(2026, 9, 25), NOW, get_json=rec)
    url, params = rec.calls[0]
    assert url == FORECAST_URL
    assert params["models"] == ",".join(WEATHER_MODELS)
    assert params["timezone"] == "Etc/GMT+5" and params["temperature_unit"] == "fahrenheit"
    assert params["start_date"] == params["end_date"] == "2026-09-25"
    assert [(o.name, o.value) for o in obs] == [
        ("openmeteo:gfs_seamless:high:2026-09-25:live", 71.0),
        ("openmeteo:ecmwf_ifs025:high:2026-09-25:live", 70.0),
    ]
    assert all(o.published_at == NOW for o in obs)


def test_historical_forecast_highs_skips_models_without_data():
    def payload(params):
        var = params["hourly"]
        values = [None] * 24 if params["models"] == "icon_seamless" else [80.0] * 24
        return {"hourly": {"time": [], var: values}}

    obs = historical_forecast_highs(WEATHER_CITIES["KXHIGHCHI"], date(2026, 7, 24), 1, get_json=Recorder(payload))
    assert [o.name.split(":")[1] for o in obs] == ["gfs_seamless", "ecmwf_ifs025"]
    assert all(o.value == pytest.approx(80.0) for o in obs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_data.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.data.weather`.

- [ ] **Step 3: Implement** — `tradehub/data/weather.py`:

```python
"""Weather inputs for Kalshi daily-high markets, aggregated over the NWS climate day (LST)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation
from tradehub.backtest.sources.open_meteo import forecast_daily_high

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_MODELS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")


@dataclass(frozen=True)
class City:
    name: str
    cli_station: str
    latitude: float
    longitude: float
    lst_timezone: str


# Settlement stations come from each market's rules text; climate days run in
# local STANDARD time all year, hence fixed-offset Etc/GMT+N zones.
WEATHER_CITIES: dict[str, City] = {
    "KXHIGHNY": City("New York City (Central Park)", "CLINYC", 40.7789, -73.9692, "Etc/GMT+5"),
    "KXHIGHCHI": City("Chicago (Midway)", "CLIMDW", 41.7868, -87.7522, "Etc/GMT+6"),
    "KXHIGHMIA": City("Miami (International)", "CLIMIA", 25.7906, -80.3164, "Etc/GMT+5"),
}


def live_forecast_highs(
    city: City, target_date: date, now: datetime, get_json: Callable[..., Any] = default_get_json
) -> list[Observation]:
    day = target_date.isoformat()
    data = get_json(FORECAST_URL, {
        "latitude": city.latitude,
        "longitude": city.longitude,
        "hourly": "temperature_2m",
        "models": ",".join(WEATHER_MODELS),
        "temperature_unit": "fahrenheit",
        "timezone": city.lst_timezone,
        "start_date": day,
        "end_date": day,
    })
    hourly = data.get("hourly") or {}
    out = []
    for model in WEATHER_MODELS:
        values = [v for v in hourly.get(f"temperature_2m_{model}") or [] if v is not None]
        if values:
            out.append(Observation(f"openmeteo:{model}:high:{day}:live", max(values), now))
    return out


def historical_forecast_highs(
    city: City, target_date: date, lead_days: int, get_json: Callable[..., Any] = default_get_json
) -> list[Observation]:
    out = []
    for model in WEATHER_MODELS:
        try:
            out.append(forecast_daily_high(latitude=city.latitude, longitude=city.longitude, target_date=target_date,
                                           lead_days=lead_days, model=model, timezone_name=city.lst_timezone,
                                           get_json=get_json))
        except ValueError:
            continue
    return out
```

Then in `research/weather_notes/Markets/Kalshi_Weather_Market_Mapping.md`, replace the `## Initial Mapping Table` block's rows with:

```markdown
| City | Settlement station (Kalshi rules) | Local TZ (climate day = LST) | Settlement Source | Notes |
| --- | --- | --- | --- | --- |
| Chicago | CLIMDW (Midway, KMDW) | Etc/GMT+6 | CLI via The Weather Company | Kalshi KXHIGHCHI rules name Midway, not O'Hare (verified 2026-09-24) |
| New York City | CLINYC (Central Park, KNYC) | Etc/GMT+5 | CLI via The Weather Company | KXHIGHNY |
| Miami | CLIMIA (Miami Intl, KMIA) | Etc/GMT+5 | CLI via The Weather Company | KXHIGHMIA |
| Washington, DC | KDCA | Etc/GMT+5 | CLI/CF6 | Not yet in the engine |
```

Also change the front-matter line `cities: [Chicago, New York City, Washington DC]` to `cities: [Chicago, New York City, Miami, Washington DC]`.

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_data.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/data/weather.py tests/test_weather_data.py research/weather_notes/Markets/Kalshi_Weather_Market_Mapping.md
git commit -m "feat: add LST-day weather forecast inputs; fix Chicago station to Midway

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Weather engine (`tradehub/engines/weather.py`)

**Files:**
- Create: `tradehub/engines/weather.py`
- Test: `tests/test_weather_engine.py`

**Interfaces:**
- Consumes: `KalshiMarket`, `yes_interval`, `prob_in_interval` (Task 2).
- Produces:
  - `ErrorModel(bias: float, sigma: float)`, with `DEFAULT_ERROR = ErrorModel(0.0, 2.5)`, `MIN_SIGMA = 1.0`, `TEMP_RESOLUTION = 1.0`, `WEATHER_ENGINE_VERSION = "weather-v1"`.
  - `fit_error_model(pairs: list[tuple[float, float]], min_pairs: int = 20) -> ErrorModel`. Each pair is `(forecast_mean, actual_high)`; `bias` is the mean of `actual - forecast`; `sigma` is its sample std, floored at `MIN_SIGMA`. It returns `DEFAULT_ERROR` below `min_pairs`.
  - `weather_prob(market, highs: list[float], error: ErrorModel) -> float`: `mu = mean(highs) + bias` and `sigma = sqrt(error.sigma**2 + pvariance(highs))`, so disagreement between models widens the distribution. It raises `ValueError` on empty `highs`.

- [ ] **Step 1: Write the failing tests** — `tests/test_weather_engine.py`:

```python
import math

import pytest

from tradehub.engines.weather import DEFAULT_ERROR, MIN_SIGMA, ErrorModel, fit_error_model, weather_prob
from tradehub.markets import prob_in_interval, parse_market

BASE = {"ticker": "KXHIGHNY-26SEP25-T74", "event_ticker": "KXHIGHNY-26SEP25", "strike_type": "greater",
        "floor_strike": 74, "cap_strike": None, "open_time": "2026-09-23T14:00:00Z",
        "close_time": "2026-09-26T05:00:00Z", "title": "NYC high"}


def test_fit_error_model_defaults_below_min_pairs():
    assert fit_error_model([(70.0, 71.0)] * 5) == DEFAULT_ERROR


def test_fit_error_model_bias_and_sigma():
    pairs = [(70.0, 71.0), (70.0, 73.0)] * 10  # errors +1/+3 -> bias 2, sample std ~1.026
    model = fit_error_model(pairs)
    assert model.bias == pytest.approx(2.0)
    assert model.sigma == pytest.approx(math.sqrt(sum((e - 2.0) ** 2 for e in [1.0, 3.0] * 10) / 19))


def test_fit_error_model_sigma_floor():
    assert fit_error_model([(70.0, 70.0)] * 30).sigma == pytest.approx(MIN_SIGMA)


def test_weather_prob_matches_normal_model():
    m = parse_market(BASE)
    p = weather_prob(m, [75.0, 75.0, 75.0], ErrorModel(bias=0.0, sigma=2.0))
    assert p == pytest.approx(prob_in_interval(75.0, 2.0, (74.5, math.inf)))


def test_weather_prob_bias_shifts_and_disagreement_widens():
    m = parse_market(BASE)
    base = weather_prob(m, [75.0, 75.0], ErrorModel(0.0, 2.0))
    assert weather_prob(m, [75.0, 75.0], ErrorModel(2.0, 2.0)) > base
    # Same mean, models disagree -> wider -> closer to 0.5 from above.
    wide = weather_prob(m, [70.0, 80.0], ErrorModel(0.0, 2.0))
    assert 0.5 < wide < base


def test_weather_prob_requires_highs():
    with pytest.raises(ValueError):
        weather_prob(parse_market(BASE), [], DEFAULT_ERROR)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.engines.weather`.

- [ ] **Step 3: Implement** — `tradehub/engines/weather.py`:

```python
"""Weather engine (pure): P(Kalshi daily-high market resolves YES) from a model-blend forecast.

The settled high ~ Normal(mean(model highs) + bias, sqrt(sigma^2 + model disagreement)),
with bias/sigma fit walk-forward on past (forecast, actual) pairs.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

WEATHER_ENGINE_VERSION = "weather-v1"
TEMP_RESOLUTION = 1.0
MIN_SIGMA = 1.0


@dataclass(frozen=True)
class ErrorModel:
    bias: float
    sigma: float


DEFAULT_ERROR = ErrorModel(bias=0.0, sigma=2.5)


def fit_error_model(pairs: list[tuple[float, float]], min_pairs: int = 20) -> ErrorModel:
    if len(pairs) < min_pairs:
        return DEFAULT_ERROR
    errors = [actual - forecast for forecast, actual in pairs]
    bias = statistics.fmean(errors)
    sigma = statistics.stdev(errors)
    return ErrorModel(bias=bias, sigma=max(MIN_SIGMA, sigma))


def weather_prob(market: KalshiMarket, highs: list[float], error: ErrorModel) -> float:
    if not highs:
        raise ValueError(f"no forecast highs for {market.ticker}")
    mu = statistics.fmean(highs) + error.bias
    spread = statistics.pvariance(highs) if len(highs) > 1 else 0.0
    sigma = math.sqrt(error.sigma ** 2 + spread)
    return prob_in_interval(mu, sigma, yes_interval(market, TEMP_RESOLUTION))
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/engines/weather.py tests/test_weather_engine.py
git commit -m "feat: add pure weather engine with walk-forward error model

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: RBOB input + gas engine (`tradehub/data/rbob.py`, `tradehub/engines/gas.py`)

**Files:**
- Create: `tradehub/data/rbob.py`, `tradehub/engines/gas.py`
- Test: `tests/test_gas_engine.py`

**Interfaces:**
- Consumes: `Observation` (step 3), `event_date`/`yes_interval`/`prob_in_interval` (Task 2).
- Produces in `rbob.py`:
  - `RBOB_SYMBOL = "RB=F"`.
  - `rbob_closes(history_fn=_default_history) -> list[Observation]`. `history_fn()` returns a pandas DataFrame with a `Close` column and a date index, like yfinance's. Each close is published at 18:00 America/New_York on its trading date, converted to UTC. The observation name is `"RBOB:{date}"`, and the list is sorted by `published_at`.
- Produces in `gas.py`:
  - `GasModel(alpha, beta, sigma)`, with `DEFAULT_GAS = GasModel(0.0, 0.0, 0.01)`, `MIN_GAS_SIGMA = 0.002`, `GAS_RESOLUTION = 0.0001`, `RBOB_WINDOW = 5`, `GAS_ENGINE_VERSION = "gas-v1"`, `GAS_SERIES = "KXAAAGASD"`.
  - `rbob_change(closes, as_of, window=RBOB_WINDOW) -> float | None`: the change between the latest known close and the close `window` closes earlier, using only closes with `published_at <= as_of`.
  - `gas_training_pairs(aaa, rbob, window=RBOB_WINDOW) -> list[tuple[float, float, datetime]]`: `(x, y, published_at)` for each pair of consecutive calendar days. `x` is the RBOB change known when the previous day's AAA value was published; `y` is the day-over-day AAA change; `published_at` is when the later AAA value became public.
  - `fit_gas_model(pairs: list[tuple[float, float]], min_points=30) -> GasModel`: OLS of `y` on `x`, with sigma the residual std (`n-2` dof) floored at `MIN_GAS_SIGMA`. It returns `DEFAULT_GAS` below `min_points`.
  - `gas_prob(market, last_value, horizon_days, rbob_x, model) -> float`: `mu = last + h*(alpha + beta*x)` (with `x=0` if `None`) and `sigma = model.sigma*sqrt(h)`. It raises `ValueError` if `h < 1`.

- [ ] **Step 1: Write the failing tests** — `tests/test_gas_engine.py`:

```python
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.rbob import rbob_closes
from tradehub.engines.gas import (
    DEFAULT_GAS,
    MIN_GAS_SIGMA,
    GasModel,
    fit_gas_model,
    gas_prob,
    gas_training_pairs,
    rbob_change,
)
from tradehub.markets import parse_market, prob_in_interval

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
GAS = {"ticker": "KXAAAGASD-26SEP25-4.5200", "event_ticker": "KXAAAGASD-26SEP25", "strike_type": "greater",
       "floor_strike": 4.52, "cap_strike": None, "open_time": "2026-09-24T14:00:00Z",
       "close_time": "2026-09-25T03:59:00Z", "title": "US gas price"}


def test_rbob_closes_publishes_at_1800_new_york():
    frame = pd.DataFrame({"Close": [3.30, 3.40]},
                         index=pd.DatetimeIndex(["2026-09-22", "2026-09-23"]).tz_localize("America/New_York"))
    obs = rbob_closes(history_fn=lambda: frame)
    assert [o.name for o in obs] == ["RBOB:2026-09-22", "RBOB:2026-09-23"]
    assert obs[0].published_at == datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)  # 18:00 EDT
    assert obs[1].value == pytest.approx(3.40)


def _rbob(values):
    return [Observation(f"RBOB:{i}", v, T0 + timedelta(days=i)) for i, v in enumerate(values)]


def test_rbob_change_uses_only_known_closes():
    closes = _rbob([3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 9.9])
    assert rbob_change(closes, T0 + timedelta(days=5), window=5) == pytest.approx(0.5)
    assert rbob_change(closes, T0 + timedelta(days=4), window=5) is None


def test_gas_training_pairs_consecutive_days_only():
    rbob = _rbob([3.0] * 6 + [3.5] * 10)
    aaa = [Observation("KXAAAGASD-26SEP10", 4.40, T0 + timedelta(days=9, hours=12)),
           Observation("KXAAAGASD-26SEP11", 4.42, T0 + timedelta(days=10, hours=12)),
           Observation("KXAAAGASD-26SEP13", 4.50, T0 + timedelta(days=12, hours=12))]  # gap: no pair
    pairs = gas_training_pairs(aaa, rbob)
    assert len(pairs) == 1
    x, y, published = pairs[0]
    assert y == pytest.approx(0.02) and published == aaa[1].published_at
    assert x == pytest.approx(rbob_change(rbob, aaa[0].published_at))


def test_fit_gas_model_recovers_linear_relation_and_defaults():
    assert fit_gas_model([(0.1, 0.01)] * 5) == DEFAULT_GAS
    pairs = [(x / 100, 0.001 + 0.05 * (x / 100) + (0.003 if x % 2 else -0.003)) for x in range(-20, 21)]
    model = fit_gas_model(pairs)
    assert model.beta == pytest.approx(0.05, abs=0.01)
    assert model.alpha == pytest.approx(0.001, abs=0.001)
    assert model.sigma >= MIN_GAS_SIGMA


def test_gas_prob_normal_model_and_horizon_scaling():
    m = parse_market(GAS)
    model = GasModel(alpha=0.0, beta=0.1, sigma=0.01)
    p1 = gas_prob(m, 4.51, 1, 0.1, model)  # mu = 4.52
    assert p1 == pytest.approx(prob_in_interval(4.52, 0.01, (4.52005, math.inf)))
    assert gas_prob(m, 4.51, 1, None, model) < p1
    with pytest.raises(ValueError):
        gas_prob(m, 4.51, 0, 0.1, model)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.data.rbob`.

- [ ] **Step 3: Implement** — `tradehub/data/rbob.py`:

```python
"""RBOB gasoline futures (front month) daily closes as point-in-time observations."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation

RBOB_SYMBOL = "RB=F"
_SETTLE_TZ = ZoneInfo("America/New_York")


def _default_history() -> Any:
    import yfinance as yf

    return yf.Ticker(RBOB_SYMBOL).history(period="2y", interval="1d")


def rbob_closes(history_fn: Callable[[], Any] = _default_history) -> list[Observation]:
    frame = history_fn()
    out = []
    for stamp, close in frame["Close"].items():
        day = stamp.date()
        published = datetime.combine(day, time(18, 0), _SETTLE_TZ).astimezone(timezone.utc)
        out.append(Observation(f"RBOB:{day.isoformat()}", float(close), published))
    return sorted(out, key=lambda o: o.published_at)
```

and `tradehub/engines/gas.py`:

```python
"""Gas engine (pure): P(AAA US average > strike) from last AAA value + lagged RBOB pass-through.

Retail follows wholesale RBOB with a 1-3 week lag, so the day-over-day AAA change
is modeled as alpha + beta * (RBOB change over the last RBOB_WINDOW closes).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

GAS_ENGINE_VERSION = "gas-v1"
GAS_SERIES = "KXAAAGASD"
GAS_RESOLUTION = 0.0001
MIN_GAS_SIGMA = 0.002
RBOB_WINDOW = 5


@dataclass(frozen=True)
class GasModel:
    alpha: float
    beta: float
    sigma: float


DEFAULT_GAS = GasModel(alpha=0.0, beta=0.0, sigma=0.01)


def rbob_change(closes: list[Observation], as_of: datetime, window: int = RBOB_WINDOW) -> float | None:
    known = sorted((o for o in closes if o.published_at <= as_of), key=lambda o: o.published_at)
    if len(known) < window + 1:
        return None
    return known[-1].value - known[-1 - window].value


def gas_training_pairs(
    aaa: list[Observation], rbob: list[Observation], window: int = RBOB_WINDOW
) -> list[tuple[float, float, datetime]]:
    ordered = sorted(aaa, key=lambda o: event_date(o.name))
    pairs = []
    for prev, cur in zip(ordered, ordered[1:]):
        if (event_date(cur.name) - event_date(prev.name)).days != 1:
            continue
        x = rbob_change(rbob, prev.published_at, window)
        if x is None:
            continue
        pairs.append((x, cur.value - prev.value, cur.published_at))
    return pairs


def fit_gas_model(pairs: list[tuple[float, float]], min_points: int = 30) -> GasModel:
    if len(pairs) < min_points:
        return DEFAULT_GAS
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in pairs) / sxx if sxx > 0 else 0.0
    alpha = my - beta * mx
    residuals = [y - (alpha + beta * x) for x, y in pairs]
    sigma = math.sqrt(sum(r * r for r in residuals) / (len(pairs) - 2))
    return GasModel(alpha=alpha, beta=beta, sigma=max(MIN_GAS_SIGMA, sigma))


def gas_prob(market: KalshiMarket, last_value: float, horizon_days: int, rbob_x: float | None, model: GasModel) -> float:
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be >= 1, got {horizon_days}")
    x = 0.0 if rbob_x is None else rbob_x
    mu = last_value + horizon_days * (model.alpha + model.beta * x)
    sigma = model.sigma * math.sqrt(horizon_days)
    return prob_in_interval(mu, sigma, yes_interval(market, GAS_RESOLUTION))
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/data/rbob.py tradehub/engines/gas.py tests/test_gas_engine.py
git commit -m "feat: add RBOB input and pure gas engine

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Edge layer (`tradehub/edges.py`) + share side selection with the fill model

**Files:**
- Modify: `tradehub/edges.py` (add to the `Quote` from Task 3)
- Modify: `tradehub/backtest/fills.py` (delete `MIN_TAKER_PRICE` and `_best_side`; import them from `tradehub.edges`)
- Test: `tests/test_edges.py` (new); `tests/test_backtest_fills.py` must keep passing unchanged

**Interfaces:**
- Consumes: `shared.kalshi_fees.net_edge_pct`.
- Produces:
  - `MIN_TAKER_PRICE = 0.10`.
  - `best_side(our_prob, yes_price, no_price, *, maker) -> tuple[str, float, float]`, returning `(side, price, net_edge_pct)` for the better side.
  - `EdgeSuggestion(market_ticker, side, entry_price, maker: bool, net_edge_pct, our_prob, market_prob: float | None)`.
  - `evaluate_edge(market_ticker, our_prob, quote, *, min_edge_pct, prefer_maker=True) -> EdgeSuggestion | None`:
    - with `prefer_maker`, first try a maker entry at the bid (YES at `yes_bid`, NO at `1 - yes_ask`); it needs `0 < limit < 1`, an edge `> 0`, and `>= min_edge_pct`;
    - otherwise fall back to a taker entry at the ask (YES at `yes_ask`, NO at `1 - yes_bid`) with the same edge rules and `price >= MIN_TAKER_PRICE`;
    - return `None` if either quote side is missing.

    `market_prob` is the mid.

- [ ] **Step 1: Write the failing tests** — `tests/test_edges.py`:

```python
import pytest

from shared.kalshi_fees import net_edge_pct
from tradehub.edges import MIN_TAKER_PRICE, Quote, best_side, evaluate_edge

Q = Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=100.0, yes_ask_size=100.0)


def test_best_side_picks_larger_net_edge():
    side, price, edge = best_side(0.70, 0.44, 0.60, maker=False)
    assert (side, price) == ("yes", 0.44)
    assert edge == pytest.approx(net_edge_pct(70.0, 44.0))
    assert best_side(0.20, 0.44, 0.60, maker=False)[0] == "no"


def test_evaluate_edge_prefers_maker_at_bid():
    s = evaluate_edge("T", 0.70, Q, min_edge_pct=5.0)
    assert s.maker is True and s.side == "yes"
    assert s.entry_price == pytest.approx(0.40)
    assert s.net_edge_pct == pytest.approx(net_edge_pct(70.0, 40.0, maker=True))
    assert s.market_prob == pytest.approx(0.42)


def test_evaluate_edge_taker_when_maker_disabled():
    s = evaluate_edge("T", 0.70, Q, min_edge_pct=5.0, prefer_maker=False)
    assert s.maker is False and s.entry_price == pytest.approx(0.44)


def test_evaluate_edge_no_taker_longshot():
    thin = Quote(yes_bid=0.02, yes_ask=0.05, yes_bid_size=1.0, yes_ask_size=1.0)
    assert MIN_TAKER_PRICE == pytest.approx(0.10)
    assert evaluate_edge("T", 0.30, thin, min_edge_pct=1.0, prefer_maker=False) is None
    maker = evaluate_edge("T", 0.30, thin, min_edge_pct=1.0)  # maker bid at 0.02 is allowed
    assert maker is not None and maker.maker is True


def test_evaluate_edge_min_edge_and_missing_quotes():
    assert evaluate_edge("T", 0.43, Q, min_edge_pct=5.0) is None
    assert evaluate_edge("T", 0.90, Quote(None, 0.44, 0.0, 1.0), min_edge_pct=1.0) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py -q`
Expected: `ImportError: cannot import name 'MIN_TAKER_PRICE' from 'tradehub.edges'`.

- [ ] **Step 3: Implement.** Replace the whole of `tradehub/edges.py` with:

```python
"""Edge layer: after-fee edge vs executable quotes, maker-first, no taker longshots (spec §4.3)."""

from __future__ import annotations

from dataclasses import dataclass

from shared.kalshi_fees import net_edge_pct

MIN_TAKER_PRICE = 0.10


@dataclass(frozen=True)
class Quote:
    yes_bid: float | None
    yes_ask: float | None
    yes_bid_size: float
    yes_ask_size: float


@dataclass(frozen=True)
class EdgeSuggestion:
    market_ticker: str
    side: str
    entry_price: float
    maker: bool
    net_edge_pct: float
    our_prob: float
    market_prob: float | None


def best_side(our_prob: float, yes_price: float, no_price: float, *, maker: bool) -> tuple[str, float, float]:
    """(side, price, net edge in pct points) for whichever of YES/NO has the larger after-fee edge."""
    yes_edge = net_edge_pct(our_prob * 100.0, yes_price * 100.0, maker=maker)
    no_edge = net_edge_pct((1.0 - our_prob) * 100.0, no_price * 100.0, maker=maker)
    if yes_edge >= no_edge:
        return "yes", yes_price, yes_edge
    return "no", no_price, no_edge


def evaluate_edge(
    market_ticker: str, our_prob: float, quote: Quote, *, min_edge_pct: float, prefer_maker: bool = True
) -> EdgeSuggestion | None:
    if quote.yes_bid is None or quote.yes_ask is None:
        return None
    mid = (quote.yes_bid + quote.yes_ask) / 2.0
    if prefer_maker:
        side, limit, edge = best_side(our_prob, quote.yes_bid, round(1.0 - quote.yes_ask, 4), maker=True)
        if edge > 0 and edge >= min_edge_pct and 0.0 < limit < 1.0:
            return EdgeSuggestion(market_ticker, side, limit, True, edge, our_prob, mid)
    side, price, edge = best_side(our_prob, quote.yes_ask, round(1.0 - quote.yes_bid, 4), maker=False)
    if edge > 0 and edge >= min_edge_pct and price >= MIN_TAKER_PRICE:
        return EdgeSuggestion(market_ticker, side, price, False, edge, our_prob, mid)
    return None
```

In `tradehub/backtest/fills.py`:
1. Replace the import `from shared.kalshi_fees import kalshi_fee_cents, net_edge_pct` with `from shared.kalshi_fees import kalshi_fee_cents`.
2. Add `from tradehub.edges import MIN_TAKER_PRICE, best_side`.
3. Delete the line `MIN_TAKER_PRICE = 0.10` and the whole `def _best_side(...)` function.
4. Replace both call sites `_best_side(` with `best_side(`.

`from tradehub.backtest.fills import MIN_TAKER_PRICE` in the step 3 tests keeps working because the name is re-exported by the import.

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py tests/test_backtest_fills.py tests/test_backtest_runner.py -q`
Expected: `28 passed` (5 + 12 + 11).

- [ ] **Step 5: Commit**

```bash
git add tradehub/edges.py tradehub/backtest/fills.py tests/test_edges.py
git commit -m "feat: add maker-first edge layer; share side selection with backtest fills

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Per-engine config (`tradehub/config/engines.yaml`, `tradehub/engine_config.py`)

**Files:**
- Create: `tradehub/config/engines.yaml`, `tradehub/engine_config.py`
- Test: `tests/test_engine_config.py`

**Interfaces:**
- Produces:
  - `EngineConfig(min_edge_pct: float, prefer_maker: bool = True, params: Mapping[str, float] = {})`.
  - `CONFIG_PATH`, which is `tradehub/config/engines.yaml`.
  - `load_engine_config(engine: str, path: Path = CONFIG_PATH) -> EngineConfig`. It raises `KeyError` for an unknown engine; keys other than `min_edge_pct`/`prefer_maker` go into `params`.

This replaces per-engine literals with one config (old roadmap Phase 3). The starting values below are starting points, not tuned numbers. Step 3 backtests tune them.

- [ ] **Step 1: Write the failing tests** — `tests/test_engine_config.py`:

```python
import pytest

from tradehub.engine_config import CONFIG_PATH, EngineConfig, load_engine_config


def test_repo_config_has_weather_and_gas():
    weather = load_engine_config("weather")
    gas = load_engine_config("gas")
    assert weather.min_edge_pct > 0 and gas.min_edge_pct > 0
    assert weather.prefer_maker is True
    assert weather.params["error_sigma"] > 0
    assert CONFIG_PATH.name == "engines.yaml"


def test_unknown_engine_raises(tmp_path):
    path = tmp_path / "engines.yaml"
    path.write_text("weather:\n  min_edge_pct: 5\n")
    with pytest.raises(KeyError):
        load_engine_config("gas", path)


def test_extra_keys_go_to_params(tmp_path):
    path = tmp_path / "engines.yaml"
    path.write_text("gas:\n  min_edge_pct: 3\n  prefer_maker: false\n  foo: 1.5\n")
    assert load_engine_config("gas", path) == EngineConfig(min_edge_pct=3.0, prefer_maker=False, params={"foo": 1.5})
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_engine_config.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.engine_config`.

- [ ] **Step 3: Implement** — `tradehub/config/engines.yaml`:

```yaml
# Per-engine edge settings (spec §4.2/§4.3). Tune from step 3 backtests, not by hand.
weather:
  min_edge_pct: 5.0      # net edge after fees, percentage points
  prefer_maker: true
  error_bias: 0.0        # °F added to the model-blend high (fit via backtest_engines)
  error_sigma: 2.5       # °F base forecast error (fit via backtest_engines)
gas:
  min_edge_pct: 3.0
  prefer_maker: true
```

and `tradehub/engine_config.py`:

```python
"""Per-engine edge configuration loaded from tradehub/config/engines.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "engines.yaml"


@dataclass(frozen=True)
class EngineConfig:
    min_edge_pct: float
    prefer_maker: bool = True
    params: Mapping[str, float] = field(default_factory=dict)


def load_engine_config(engine: str, path: Path = CONFIG_PATH) -> EngineConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = dict(data[engine])
    min_edge = float(raw.pop("min_edge_pct"))
    prefer_maker = bool(raw.pop("prefer_maker", True))
    return EngineConfig(min_edge_pct=min_edge, prefer_maker=prefer_maker, params={k: float(v) for k, v in raw.items()})
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_engine_config.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/config/engines.yaml tradehub/engine_config.py tests/test_engine_config.py
git commit -m "feat: centralize per-engine edge config

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: One-shot scan (`tradehub/scripts/scan.py`) + `upsert_opportunities` deep links

**Files:**
- Create: `tradehub/scripts/scan.py`
- Modify: `tradehub/core/supabase_client.py` (`upsert_opportunities`)
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes:
  - step 2: `tradehub.predictions.build_prediction_row(*, market_ticker, our_prob, market_prob, engine, as_of, engine_version, raw_payload)` and `record_predictions(supa, rows)`;
  - Tasks 2–8 of this plan;
  - `tradehub.core.supabase_client.get_client`/`upsert_opportunities`.
- Produces:
  - `edge_row(market: KalshiMarket, s: EdgeSuggestion, edge_type: str) -> dict`, with keys `market_ticker, market_title, market_price, model_probability, edge, edge_type, market_url, side, entry_price, maker`. `edge` is a fraction (net pct / 100).
  - `scan_weather(live, now, cfg, *, forecast_fn=live_forecast_highs, cities=WEATHER_CITIES) -> tuple[list[dict], list[dict]]` returns `(prediction rows, edge rows)`. It uses `ErrorModel(cfg.params["error_bias"], cfg.params["error_sigma"])` and only scans events whose date is on or after today in the city's LST.
  - `scan_gas(live, now, cfg, *, rbob_fn=rbob_closes) -> tuple[list[dict], list[dict]]`. It uses AAA values published at or before `now`, fits the gas model on training pairs published at or before `now`, and skips horizons `< 1`.
  - `main() -> int`: one-shot. It writes predictions for every scanned market and upserts edges, then prints a JSON summary. It exits 0 and never places orders.
- `upsert_opportunities` now also writes `"market_url": op.get("market_url")` and `"source_url": op.get("source_url")`, and accepts `ENERGY`.

- [ ] **Step 1: Write the failing tests** — `tests/test_scan.py`:

```python
from datetime import date, datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import EdgeSuggestion, Quote
from tradehub.engine_config import EngineConfig
from tradehub.markets import parse_market
from tradehub.scripts import scan

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)  # 13:00 LST NYC -> "today" = Sep 24


def _m(ticker, event, strike_type="greater", floor=74, cap=None, close="2026-09-26T05:00:00Z"):
    return parse_market({"ticker": ticker, "event_ticker": event, "strike_type": strike_type, "floor_strike": floor,
                         "cap_strike": cap, "open_time": "2026-09-23T14:00:00Z", "close_time": close,
                         "title": ticker})


class FakeLive:
    def __init__(self, markets, settled=()):
        self.markets = markets
        self.settled = list(settled)

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values(self, series):
        return self.settled


CFG = EngineConfig(min_edge_pct=5.0, prefer_maker=True, params={"error_bias": 0.0, "error_sigma": 2.0})
GOOD_QUOTE = Quote(yes_bid=0.30, yes_ask=0.34, yes_bid_size=50.0, yes_ask_size=50.0)


def test_edge_row_shape():
    m = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    row = scan.edge_row(m, EdgeSuggestion(m.ticker, "yes", 0.30, True, 12.5, 0.45, 0.32), "WEATHER")
    assert row["market_url"] == "https://kalshi.com/markets/kxhighny"
    assert row["edge"] == pytest.approx(0.125)
    assert row["model_probability"] == pytest.approx(0.45) and row["market_price"] == pytest.approx(0.32)
    assert row["edge_type"] == "WEATHER" and row["maker"] is True


def test_scan_weather_predicts_every_market_and_flags_edges():
    today = _m("KXHIGHNY-26SEP24-T74", "KXHIGHNY-26SEP24", close="2026-09-25T05:00:00Z")
    tomorrow = _m("KXHIGHNY-26SEP25-T74", "KXHIGHNY-26SEP25")
    past = _m("KXHIGHNY-26SEP23-T74", "KXHIGHNY-26SEP23", close="2026-09-24T05:00:00Z")
    live = FakeLive([LiveMarket(today, GOOD_QUOTE), LiveMarket(tomorrow, GOOD_QUOTE), LiveMarket(past, GOOD_QUOTE)])
    calls = []

    def forecast_fn(city, target, now):
        calls.append(target)
        return [Observation(f"f:{target}", 77.0, now)]

    preds, edges = scan.scan_weather(live, NOW, CFG, forecast_fn=forecast_fn,
                                     cities={"KXHIGHNY": scan.WEATHER_CITIES["KXHIGHNY"]})
    assert sorted(calls) == [date(2026, 9, 24), date(2026, 9, 25)]
    assert {p["market_ticker"] for p in preds} == {today.ticker, tomorrow.ticker}
    assert all(p["engine"] == "weather" for p in preds)
    assert {e["market_ticker"] for e in edges} == {today.ticker, tomorrow.ticker}  # P(>=75 | mu 77) >> 0.34 ask
    assert all(e["edge_type"] == "WEATHER" for e in edges)


def test_scan_gas_uses_only_published_aaa_and_positive_horizons():
    m = _m("KXAAAGASD-26SEP25-4.5200", "KXAAAGASD-26SEP25", floor=4.52, close="2026-09-25T03:59:00Z")
    stale = _m("KXAAAGASD-26SEP24-4.5200", "KXAAAGASD-26SEP24", floor=4.52, close="2026-09-24T03:59:00Z")
    settled = [Observation("KXAAAGASD-26SEP23", 4.60, NOW - timedelta(days=1, hours=6)),
               Observation("KXAAAGASD-26SEP24", 4.61, NOW - timedelta(hours=6)),
               Observation("KXAAAGASD-26SEP25", 9.99, NOW + timedelta(hours=18))]  # not yet public
    live = FakeLive([LiveMarket(m, GOOD_QUOTE), LiveMarket(stale, GOOD_QUOTE)], settled)
    rbob = [Observation(f"RBOB:{i}", 3.0, NOW - timedelta(days=10 - i)) for i in range(8)]
    preds, edges = scan.scan_gas(live, NOW, EngineConfig(min_edge_pct=3.0), rbob_fn=lambda: rbob)
    assert [p["market_ticker"] for p in preds] == [m.ticker]  # stale market: horizon 0 -> skipped
    assert preds[0]["engine"] == "gas"
    assert preds[0]["our_prob"] > 0.99  # last known 4.61, default model -> far above 4.52
    assert edges and edges[0]["edge_type"] == "ENERGY"


def test_upsert_opportunities_writes_urls_and_energy(monkeypatch):
    from tradehub.core import supabase_client

    captured = {}

    class Table:
        def upsert(self, rows, on_conflict):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    monkeypatch.setattr(supabase_client, "get_client", lambda: type("C", (), {"table": lambda self, n: Table()})())
    supabase_client.upsert_opportunities([{"market_ticker": "KXAAAGASD-26SEP25-4.5200", "market_title": "gas",
                                           "market_price": 0.32, "model_probability": 0.45, "edge": 0.125,
                                           "edge_type": "ENERGY", "market_url": "https://kalshi.com/markets/kxaaagasd"}])
    row = captured["rows"][0]
    assert row["edge_type"] == "ENERGY"
    assert row["market_url"] == "https://kalshi.com/markets/kxaaagasd"
    assert row["source_url"] is None
    assert captured["on_conflict"] == "market_id"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q`
Expected: collection error, `ImportError` / `ModuleNotFoundError` for `tradehub.scripts.scan`.

- [ ] **Step 3: Implement.** In `tradehub/core/supabase_client.py` `upsert_opportunities`:
1. Change `if edge_type not in ["WEATHER", "MACRO", "SPORTS", "CRYPTO"]:` to `if edge_type not in ["WEATHER", "MACRO", "SPORTS", "CRYPTO", "ENERGY"]:`.
2. In the `unique_rows[market_id] = {...}` dict, add these two entries after `"edge_pct": ...`:

```python
            "market_url": op.get("market_url"),
            "source_url": op.get("source_url"),
```

Then create `tradehub/scripts/scan.py`:

```python
"""One-shot scan (suggest-only): predict every open weather/gas market, flag trade-worthy edges.

Writes every prediction to the predictions ledger and upserts edges (with Kalshi deep links)
into kalshi_edges. Never places orders. Cron-ready: runs once and exits.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.data.kalshi_live import KalshiLive
from tradehub.data.rbob import rbob_closes
from tradehub.data.weather import WEATHER_CITIES, City, live_forecast_highs
from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, ErrorModel, weather_prob
from tradehub.markets import KalshiMarket, event_date, market_url
from tradehub.predictions import build_prediction_row


def edge_row(market: KalshiMarket, s: EdgeSuggestion, edge_type: str) -> dict[str, Any]:
    return {
        "market_ticker": market.ticker,
        "market_title": market.title,
        "market_price": s.market_prob,
        "model_probability": s.our_prob,
        "edge": s.net_edge_pct / 100.0,
        "edge_type": edge_type,
        "market_url": market_url(market),
        "side": s.side,
        "entry_price": s.entry_price,
        "maker": s.maker,
    }


def _mid(quote) -> float | None:
    if quote.yes_bid is None or quote.yes_ask is None:
        return None
    return (quote.yes_bid + quote.yes_ask) / 2.0


def scan_weather(
    live, now: datetime, cfg: EngineConfig, *,
    forecast_fn: Callable[..., list] = live_forecast_highs,
    cities: dict[str, City] = WEATHER_CITIES,
) -> tuple[list[dict], list[dict]]:
    error = ErrorModel(bias=cfg.params.get("error_bias", 0.0), sigma=cfg.params.get("error_sigma", 2.5))
    predictions: list[dict] = []
    edges: list[dict] = []
    for series, city in cities.items():
        today = now.astimezone(ZoneInfo(city.lst_timezone)).date()
        by_date = defaultdict(list)
        for lm in live.open_markets(series):
            target = event_date(lm.market.event_ticker)
            if target >= today:
                by_date[target].append(lm)
        for target, markets in sorted(by_date.items()):
            highs = forecast_fn(city, target, now)
            if not highs:
                continue
            values = [o.value for o in highs]
            for lm in markets:
                prob = weather_prob(lm.market, values, error)
                predictions.append(build_prediction_row(
                    market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="weather",
                    as_of=now, engine_version=WEATHER_ENGINE_VERSION,
                    raw_payload={"highs": {o.name: o.value for o in highs}, "bias": error.bias, "sigma": error.sigma},
                ))
                suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                           prefer_maker=cfg.prefer_maker)
                if suggestion:
                    edges.append(edge_row(lm.market, suggestion, "WEATHER"))
    return predictions, edges


def scan_gas(live, now: datetime, cfg: EngineConfig, *, rbob_fn: Callable[[], list] = rbob_closes) -> tuple[list[dict], list[dict]]:
    known = [o for o in live.settled_values(GAS_SERIES) if o.published_at <= now]
    if not known:
        return [], []
    rbob = rbob_fn()
    last = max(known, key=lambda o: event_date(o.name))
    model = fit_gas_model([(x, y) for x, y, published in gas_training_pairs(known, rbob) if published <= now])
    x_now = rbob_change(rbob, now)
    predictions: list[dict] = []
    edges: list[dict] = []
    for lm in live.open_markets(GAS_SERIES):
        horizon = (event_date(lm.market.event_ticker) - event_date(last.name)).days
        if horizon < 1:
            continue
        prob = gas_prob(lm.market, last.value, horizon, x_now, model)
        predictions.append(build_prediction_row(
            market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="gas", as_of=now,
            engine_version=GAS_ENGINE_VERSION,
            raw_payload={"last_aaa": last.value, "last_aaa_event": last.name, "horizon_days": horizon,
                         "rbob_change": x_now, "alpha": model.alpha, "beta": model.beta, "sigma": model.sigma},
        ))
        suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                   prefer_maker=cfg.prefer_maker)
        if suggestion:
            edges.append(edge_row(lm.market, suggestion, "ENERGY"))
    return predictions, edges


def main() -> int:
    from tradehub.core.supabase_client import get_client, upsert_opportunities
    from tradehub.predictions import record_predictions

    now = datetime.now(timezone.utc)
    live = KalshiLive()
    weather_preds, weather_edges = scan_weather(live, now, load_engine_config("weather"))
    gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
    record_predictions(get_client(), weather_preds + gas_preds)
    upsert_opportunities(weather_edges + gas_edges)
    print(json.dumps({
        "as_of": now.isoformat(),
        "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/scan.py tradehub/core/supabase_client.py tests/test_scan.py
git commit -m "feat: add suggest-only weather/gas scan writing predictions and edges

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: Point-in-time backtests for both engines (`tradehub/scripts/backtest_engines.py`)

**Files:**
- Create: `tradehub/scripts/backtest_engines.py`
- Test: `tests/test_backtest_engines.py`

**Interfaces:**
- Consumes:
  - step 3: `Decision`, `Observation`, `KalshiHistoryClient`, `MarketHistory`, `run_backtest`, `data_snapshot_hash`, `build_backtest_run_row`, `record_backtest_run`, `stable_hash`;
  - Tasks 2–6 of this plan;
  - `settlement_observations` (Task 3).
- Produces:
  - `WEATHER_DECISION_TIME = time(23, 30)` and `GAS_DECISION_LEAD = timedelta(hours=2)`.
  - `weather_decision_time(target: date, lead_days: int, city: City) -> datetime`: 23:30 in the city's LST zone, `lead_days` before the target.
  - `build_weather_decisions(markets, forecasts: Mapping[date, list[Observation]], actuals: list[Observation], city, lead_days=1) -> list[Decision]`. The error model for each decision is fit only on dates whose actual was published at or before the decision time. The decision's features are that date's forecast observations.
  - `build_gas_decisions(markets, aaa: list[Observation], rbob: list[Observation]) -> list[Decision]`. The decision time is `close_time - GAS_DECISION_LEAD`. It uses the latest AAA value published by then and the RBOB change as of then, with the model fit on pairs published by then. Features are the last AAA observation plus the RBOB closes used.
  - `main(argv=None) -> int`: CLI `--engine weather|gas --start YYYY-MM-DD --end YYYY-MM-DD [--mode taker|maker] [--series KXHIGHNY] [--train-days 90] [--record]`. For weather, only actuals from `start - train_days` through `end` are used (and forecast), which keeps the Open-Meteo calls bounded. It pulls history via `KalshiHistoryClient`, runs `run_backtest`, and prints the result JSON. With `--record` it also writes a `backtest_runs` row.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_engines.py`:

```python
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import Observation, check_no_lookahead
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.weather import WEATHER_CITIES
from tradehub.markets import parse_market
from tradehub.scripts.backtest_engines import (
    GAS_DECISION_LEAD,
    build_gas_decisions,
    build_weather_decisions,
    weather_decision_time,
)

NYC = WEATHER_CITIES["KXHIGHNY"]
EST = ZoneInfo("Etc/GMT+5")


def _wm(day: date):
    tag = day.strftime("%y%b%d").upper()
    close = datetime.combine(day + timedelta(days=1), datetime.min.time(), EST).astimezone(timezone.utc)
    return parse_market({"ticker": f"KXHIGHNY-{tag}-T74", "event_ticker": f"KXHIGHNY-{tag}", "strike_type": "greater",
                         "floor_strike": 74, "cap_strike": None, "open_time": "2026-06-01T00:00:00Z",
                         "close_time": close.isoformat().replace("+00:00", "Z"), "title": "NYC high"})


def _fc(day: date, value: float):
    published = datetime.combine(day, datetime.min.time().replace(hour=23), EST) - timedelta(days=1)
    return [Observation(f"openmeteo:gfs_seamless:high:{day}:lead1", value, published.astimezone(timezone.utc))]


def _actual(day: date, value: float):
    tag = day.strftime("%y%b%d").upper()
    published = datetime.combine(day + timedelta(days=1), datetime.min.time().replace(hour=12), timezone.utc)
    return Observation(f"KXHIGHNY-{tag}", value, published)


def test_weather_decision_time_is_2330_lst_the_day_before():
    t = weather_decision_time(date(2026, 7, 24), 1, NYC)
    assert t == datetime(2026, 7, 23, 23, 30, tzinfo=EST)


def test_weather_decisions_are_leakage_safe_and_fit_walk_forward():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(30)]
    forecasts = {d: _fc(d, 75.0) for d in days}
    actuals = [_actual(d, 77.0) for d in days]  # model is always 2°F too cold
    decisions = build_weather_decisions([_wm(d) for d in days], forecasts, actuals, NYC)
    assert len(decisions) == 30
    for d in decisions:
        check_no_lookahead(d)  # raises on leakage
    # Early decisions have < 20 known pairs -> default model; the last has 28 known pairs -> bias +2 learned.
    assert decisions[-1].our_prob > decisions[0].our_prob


def test_weather_decisions_skip_dates_without_forecasts():
    d = date(2026, 7, 5)
    assert build_weather_decisions([_wm(d)], {}, [], NYC) == []


def _gm(day: date, strike: float):
    tag = day.strftime("%y%b%d").upper()
    close = datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=3, minutes=59)
    return parse_market({"ticker": f"KXAAAGASD-{tag}-{strike:.4f}", "event_ticker": f"KXAAAGASD-{tag}",
                         "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
                         "open_time": "2026-06-01T00:00:00Z", "close_time": close.isoformat().replace("+00:00", "Z"),
                         "title": "US gas"})


def test_gas_decisions_use_only_published_inputs():
    start = date(2026, 7, 1)
    aaa = [Observation(f"KXAAAGASD-{(start + timedelta(days=i)).strftime('%y%b%d').upper()}", 4.00 + 0.001 * i,
                       datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc) + timedelta(hours=12))
           for i in range(40)]
    rbob = [Observation(f"RBOB:{i}", 3.0 + 0.01 * i,
                        datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc) - timedelta(hours=2))
            for i in range(40)]
    target = start + timedelta(days=35)
    decisions = build_gas_decisions([_gm(target, 4.03)], aaa, rbob)
    assert len(decisions) == 1
    d = decisions[0]
    check_no_lookahead(d)
    assert d.decided_at == _gm(target, 4.03).close_time - GAS_DECISION_LEAD
    last = [o for o in d.features if o.name.startswith("KXAAAGASD")][0]
    assert last.published_at <= d.decided_at
    assert last.name.endswith(target.replace(day=target.day - 1).strftime("%y%b%d").upper())


def test_built_decisions_run_through_the_backtester():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(3)]
    markets = [_wm(d) for d in days]
    decisions = build_weather_decisions(markets, {d: _fc(d, 80.0) for d in days}, [], NYC)
    histories = {m.ticker: MarketHistory(m.ticker, "yes", m.close_time,
                                         [Candle(dec.decided_at - timedelta(hours=1), 0.40, 0.44, 1.0)], [])
                 for m, dec in zip(markets, decisions)}
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    assert result.n_decisions == 3 and result.n_fills == 3 and result.pnl_after_fees > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.scripts.backtest_engines`.

- [ ] **Step 3: Implement** — `tradehub/scripts/backtest_engines.py`:

```python
"""Point-in-time decision builders for the weather and gas engines, plus a backtest CLI.

Each decision carries only observations published at or before its decision time
(checked by tradehub.backtest.pit.check_no_lookahead inside run_backtest); model
parameters are fit walk-forward on data knowable at that time.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, time, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.pit import Decision, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
from tradehub.data.kalshi_live import settlement_observations
from tradehub.data.rbob import rbob_closes
from tradehub.data.weather import WEATHER_CITIES, City, historical_forecast_highs
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change, RBOB_WINDOW
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, fit_error_model, weather_prob
from tradehub.markets import KalshiMarket, event_date, parse_market

WEATHER_DECISION_TIME = time(23, 30)
GAS_DECISION_LEAD = timedelta(hours=2)


def weather_decision_time(target: date, lead_days: int, city: City) -> datetime:
    return datetime.combine(target - timedelta(days=lead_days), WEATHER_DECISION_TIME, ZoneInfo(city.lst_timezone))


def build_weather_decisions(
    markets: list[KalshiMarket],
    forecasts: Mapping[date, list[Observation]],
    actuals: list[Observation],
    city: City,
    lead_days: int = 1,
) -> list[Decision]:
    decisions = []
    for market in markets:
        target = event_date(market.event_ticker)
        highs = forecasts.get(target) or []
        if not highs:
            continue
        decided_at = weather_decision_time(target, lead_days, city)
        pairs = []
        for actual in actuals:
            day = event_date(actual.name)
            if actual.published_at <= decided_at and forecasts.get(day):
                pairs.append((statistics.fmean(o.value for o in forecasts[day]), actual.value))
        prob = weather_prob(market, [o.value for o in highs], fit_error_model(pairs))
        decisions.append(Decision(market.ticker, decided_at, prob, tuple(highs)))
    return decisions


def build_gas_decisions(markets: list[KalshiMarket], aaa: list[Observation], rbob: list[Observation]) -> list[Decision]:
    rbob_sorted = sorted(rbob, key=lambda o: o.published_at)
    decisions = []
    for market in markets:
        decided_at = market.close_time - GAS_DECISION_LEAD
        known = [o for o in aaa if o.published_at <= decided_at]
        if not known:
            continue
        last = max(known, key=lambda o: event_date(o.name))
        horizon = (event_date(market.event_ticker) - event_date(last.name)).days
        if horizon < 1:
            continue
        model = fit_gas_model([(x, y) for x, y, published in gas_training_pairs(known, rbob_sorted) if published <= decided_at])
        prob = gas_prob(market, last.value, horizon, rbob_change(rbob_sorted, decided_at), model)
        used_rbob = tuple(o for o in rbob_sorted if o.published_at <= decided_at)[-(RBOB_WINDOW + 1):]
        decisions.append(Decision(market.ticker, decided_at, prob, (last,) + used_rbob))
    return decisions


def _histories(client: KalshiHistoryClient, markets: list[KalshiMarket], results: Mapping[str, str | None]) -> dict[str, MarketHistory]:
    out = {}
    for m in markets:
        out[m.ticker] = MarketHistory(
            ticker=m.ticker, result=results.get(m.ticker), close_time=m.close_time,
            candles=client.candles(m.ticker, m.open_time, m.close_time),
            trades=client.trades(m.ticker),
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time backtest for the weather or gas engine.")
    parser.add_argument("--engine", choices=["weather", "gas"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
    parser.add_argument("--series", default=None, help="weather series ticker (default KXHIGHNY)")
    parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
    parser.add_argument("--train-days", type=int, default=90,
                        help="days of history before --start used to fit the weather error model")
    args = parser.parse_args(argv)

    client = KalshiHistoryClient()
    series = args.series or ("KXHIGHNY" if args.engine == "weather" else GAS_SERIES)
    raws = [r for r in client.settled_markets(series) if args.start <= event_date(r["event_ticker"]) <= args.end]
    markets = [parse_market(r) for r in raws]
    results = {r["ticker"]: r.get("result") for r in raws}
    if args.engine == "weather":
        city = WEATHER_CITIES[series]
        actuals = settlement_observations(client.settled_markets(series))
        train_from = args.start - timedelta(days=args.train_days)
        actuals = [o for o in actuals if train_from <= event_date(o.name) <= args.end]
        days = sorted({event_date(m.event_ticker) for m in markets} | {event_date(o.name) for o in actuals})
        forecasts = {d: historical_forecast_highs(city, d, 1) for d in days}
        decisions = build_weather_decisions(markets, forecasts, actuals, city)
        version = WEATHER_ENGINE_VERSION
    else:
        aaa = settlement_observations(client.settled_markets(series))
        decisions = build_gas_decisions(markets, aaa, rbob_closes())
        version = GAS_ENGINE_VERSION
    histories = _histories(client, [m for m in markets if m.ticker in {d.market_ticker for d in decisions}], results)
    result = run_backtest(engine=args.engine, cadence="daily", decisions=decisions, histories=histories, mode=args.mode)
    config = {"engine": args.engine, "series": series, "mode": args.mode, "start": str(args.start), "end": str(args.end)}
    row = build_backtest_run_row(result, engine_version=version, config=config,
                                 data_hash=data_snapshot_hash(decisions, histories),
                                 date_from=datetime.combine(args.start, time(0)).astimezone(),
                                 date_to=datetime.combine(args.end, time(23, 59)).astimezone())
    print(json.dumps({k: row[k] for k in ("engine", "mode", "n_decisions", "n_fills", "pnl_after_fees",
                                          "max_drawdown", "brier_ours", "brier_market", "gate_status", "gate_reasons")},
                     default=str, indent=2))
    if args.record:
        from tradehub.core.supabase_client import get_client

        record_backtest_run(get_client(), row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/backtest_engines.py tests/test_backtest_engines.py
git commit -m "feat: add point-in-time backtests for the weather and gas engines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification

- [ ] **Full suite:** `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q`. Expected: all pass, including the 43 new tests (7 + 5 + 3 + 6 + 5 + 5 + 3 + 4 + 5), the unchanged step 3 fill/runner tests, and the new layout assertion.
- [ ] **Lint:** `.venv/bin/ruff check --select F401,F811,F821 tradehub tests`. Expected: `All checks passed!`
- [ ] **Import boundary:** `grep -rn "shared.config" tradehub/markets.py tradehub/edges.py tradehub/data tradehub/engines/weather.py tradehub/engines/gas.py tradehub/engine_config.py tradehub/scripts/scan.py tradehub/scripts/backtest_engines.py` prints nothing.
- [ ] **Live dry run** (manual; reads public data, writes nothing):

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -c "
from datetime import datetime, timezone
from tradehub.data.kalshi_live import KalshiLive
from tradehub.engine_config import load_engine_config
from tradehub.scripts.scan import scan_weather, scan_gas
now = datetime.now(timezone.utc); live = KalshiLive()
wp, we = scan_weather(live, now, load_engine_config('weather'))
gp, ge = scan_gas(live, now, load_engine_config('gas'))
print('weather', len(wp), 'preds', len(we), 'edges'); print('gas', len(gp), 'preds', len(ge), 'edges')
for e in (we + ge)[:5]: print(e['market_ticker'], e['side'], round(e['edge']*100,1), 'pp', 'maker' if e['maker'] else 'taker')"
```

Expected: a non-zero prediction count for both engines, plus a handful of edges or none. Every scanned market must get a prediction row, whether or not it has an edge.
- [ ] **Backtests before shipping (spec §5a):**
  - weather: `.venv/bin/python -m tradehub.scripts.backtest_engines --engine weather --series KXHIGHNY --start 2026-06-01 --end 2026-07-24`
  - gas: `.venv/bin/python -m tradehub.scripts.backtest_engines --engine gas --start 2026-06-01 --end 2026-07-24`
  - Put both JSON outputs in the evidence report.
  - Once Kevin's `.env` has working Supabase credentials, re-run each with `--record` to store the `backtest_runs` rows.
  - If a backtest reports a better `error_bias`/`error_sigma` than the defaults, tuning `tradehub/config/engines.yaml` is a separate reviewed change, not part of this plan.

## Out of Scope

- **Scheduling the scan** is step 5 (Azure Container Apps Jobs).
- **Retiring or refactoring** the legacy `tradehub/engines/weather_engine.py`/`weather_maker.py` and their calls from `tradehub/scripts/background_scanner.py`. They keep running until step 5 replaces the VPS scanner with `tradehub.scripts.scan`, and are retired then.
- **More cities or state gas series** (e.g. `KXHIGHTDC`, `KXAAAGASDCA`): these are config and dictionary entries once v1 is backtested.
- **The Track Record / Sports UI** (later steps).

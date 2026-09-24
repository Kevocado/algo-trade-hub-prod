# Backtesting Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A point-in-time backtest harness that replays engine decisions against real Kalshi history with conservative fills and after-fee P&L. It scores those decisions with the *same* metric and gate code the live track record uses, so a backtest and the promotion gate can never disagree.

**Architecture:** A new `tradehub/backtest/` package made of small units:
- `pit.py`: point-in-time `Observation`/`Decision` types plus the leakage guard.
- `kalshi_history.py`: a Kalshi public-history client with pure parsers.
- `fills.py`: the taker/maker fill model.
- `metrics.py` + `runner.py`: P&L, drawdown, and turnover, plus reuse of `tradehub.track_record`; also a walk-forward helper.
- `store.py`: reproducible `backtest_runs` rows.
- `sources/`: the first two point-in-time data sources (ALFRED vintages, Open-Meteo previous runs).

Every I/O function takes an injected `get_json` callable, so tests use recorded fixtures and never hit the network.

**Tech Stack:** Python 3.12, `requests`, `pytest` + `monkeypatch` (plain test functions; small fake helper classes are fine, `Test*` classes are not), stdlib `dataclasses`/`zoneinfo`/`hashlib`.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md), §5a "Backtesting suite", plus §4.3 (edge rules) and §6 (promotion gate). Rollout index and the agent handoff contract: [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md), step 3.

## Global Constraints

- **Prerequisite:** the step 2 plan ([2026-09-24-predictions-ledger-settlement-track-record.md](2026-09-24-predictions-ledger-settlement-track-record.md)) is merged to `main`. This plan imports `tradehub.track_record.compute_calibration`, `compute_engine_summary`, and `check_promotion_gate`, and `tradehub.settlement.brier_score`. Don't copy them.
- **Fees:** use `shared/kalshi_fees.py` (`kalshi_fee_cents`, `net_edge_pct`). Never re-derive fee math.
- **Edge rules (spec §4.3):**
  - never simulate a **taker** buy below 10¢ (`MIN_TAKER_PRICE = 0.10`);
  - edge is computed against executable bid/ask after fees, never against the midpoint;
  - nothing ever fills at the midpoint.
- **Fill model (spec §5a):**
  - a taker pays the ask plus the Kalshi taker fee;
  - a maker order counts as filled only if a later trade printed at or through its limit before the market closed; it pays the maker fee.
- **Leakage guard (spec §5a):** any feature whose `published_at` is later than its decision time raises `LeakageError`, and the runner calls the guard on every decision.
- **Kalshi market data** comes from the public production base `https://api.elections.kalshi.com/trade-api/v2` (no auth). Prices are dollar strings (for example `"0.0100"`). Timestamps are ISO-8601 with `Z`, or epoch seconds (`end_period_ts`).
- **Never edit** an existing migration file; new schema goes in a new timestamped migration.
- **New tables** follow the owner RLS pattern (`*_owner` policy on `auth.uid() = user_id`).
- **Don't import `shared.config` from new modules.** It hard-requires env vars at import time. Pass API keys in as arguments.
- **Test runs:** run from the repo root with `.venv/bin/python`, prefixing every pytest run with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` (process env only).
- Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Follow the handoff contract in the rollout tracker: branch `plan/2026-09-24-backtesting-suite`, one commit per task, evidence report at `docs/superpowers/reports/2026-09-24-backtesting-suite.md`.

## Review Focus

- A decision whose features include anything published after `decided_at` must raise `LeakageError`, never be scored. (Task 2, Task 5)
- Taker fills use the **close of the last candle that ended at or before** `decided_at` (the quote actually visible then), never a later candle. (Task 4)
- No taker fill below 10¢; no fill when the net edge after fees is below `min_edge_pct`. (Task 4)
- A maker fill needs a later trade on the opposite taker side at or through the limit, strictly after `decided_at` and no later than close. (Task 4)
- Canceled or unsettled markets (`result` not `yes`/`no`) are excluded from scoring and never fabricated. (Task 5)
- ALFRED values are treated as available only from the **day after** their vintage date, because ALFRED has day granularity and releases land intraday. (Task 6)

---

## File Structure

- **Create** `market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql`: the `backtest_runs` table.
- **Create** `tradehub/backtest/__init__.py`: empty package marker.
- **Create** `tradehub/backtest/http.py`: `default_get_json(url, params)`, the only place `requests` is called.
- **Create** `tradehub/backtest/pit.py`: `Observation`, `Decision`, `LeakageError`, `check_no_lookahead`.
- **Create** `tradehub/backtest/kalshi_history.py`: `Candle`, `Trade`, parsers, and `KalshiHistoryClient`.
- **Create** `tradehub/backtest/fills.py`: `Fill`, `quote_at`, `taker_fill`, `maker_fill`.
- **Create** `tradehub/backtest/metrics.py`: `fill_pnl`, `max_drawdown`, `market_mid`, `prediction_row`.
- **Create** `tradehub/backtest/runner.py`: `MarketHistory`, `BacktestResult`, `run_backtest`, `walk_forward`.
- **Create** `tradehub/backtest/store.py`: `stable_hash`, `data_snapshot_hash`, `build_backtest_run_row`, `record_backtest_run`.
- **Create** `tradehub/backtest/sources/__init__.py`, `tradehub/backtest/sources/alfred.py`, `tradehub/backtest/sources/open_meteo.py`.
- **Tests:** `tests/test_backtest_pit.py`, `tests/test_backtest_kalshi_history.py`, `tests/test_backtest_fills.py`, `tests/test_backtest_runner.py`, `tests/test_backtest_sources.py`, `tests/test_backtest_store.py`, plus one assertion appended to `tests/test_repo_layout.py`.

---

## Task 1: `backtest_runs` migration

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql`
- Modify: `tests/test_repo_layout.py` (append one test)

**Interfaces:**
- Produces: table `backtest_runs` with columns `id, engine, engine_version, mode, config, config_hash, data_hash, date_from, date_to, n_decisions, n_fills, n_settled, pnl_after_fees, max_drawdown, turnover, brier_ours, brier_market, cal_buckets, max_cal_dev, gate_status, gate_reasons, created_at, user_id`. `store.build_backtest_run_row` (Task 7) produces exactly these keys minus `id`, `created_at`, and `user_id`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_backtest_runs_migration_defines_table():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql"
    assert path.is_file(), "backtest_runs migration is missing"
    sql = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backtest_runs" in sql
    assert '"backtest_runs_owner"' in sql
    for column in ("config_hash", "data_hash", "pnl_after_fees", "max_drawdown", "gate_status", "cal_buckets"):
        assert column in sql, f"backtest_runs missing column {column}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_backtest_runs_migration_defines_table -q`
Expected: FAIL with "backtest_runs migration is missing".

- [ ] **Step 3: Write the migration**

```sql
-- Backtest runs (rollout step 3, spec section 5a).
-- One row per reproducible backtest: engine version + config hash +
-- data-snapshot hash + date range pin down exactly what was replayed.
-- Idempotent, following 20260416000003_predictions_ledger.sql.

CREATE TABLE IF NOT EXISTS backtest_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  engine          text NOT NULL,
  engine_version  text NOT NULL,
  mode            text NOT NULL CHECK (mode IN ('taker', 'maker')),
  config          jsonb NOT NULL DEFAULT '{}'::jsonb,
  config_hash     text NOT NULL,
  data_hash       text NOT NULL,
  date_from       timestamptz NOT NULL,
  date_to         timestamptz NOT NULL,
  n_decisions     integer NOT NULL,
  n_fills         integer NOT NULL,
  n_settled       integer NOT NULL,
  pnl_after_fees  numeric(12,4) NOT NULL,
  max_drawdown    numeric(12,4) NOT NULL,
  turnover        numeric(12,4) NOT NULL,
  brier_ours      numeric(6,5),
  brier_market    numeric(6,5),
  cal_buckets     jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_cal_dev     numeric(5,4),
  gate_status     text NOT NULL CHECK (gate_status IN ('SHADOW', 'PROMOTED')),
  gate_reasons    jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at      timestamptz DEFAULT now(),
  user_id         uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS backtest_runs_engine_idx ON backtest_runs (engine, created_at DESC);
ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "backtest_runs_owner" ON backtest_runs;
CREATE POLICY "backtest_runs_owner" ON backtest_runs FOR ALL
  USING (auth.uid() = user_id);
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql tests/test_repo_layout.py
git commit -m "feat: add backtest_runs migration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Note: applying the migration to Supabase is a manual deploy step for Kevin.

---

## Task 2: Point-in-time types and leakage guard (`pit.py`)

**Files:**
- Create: `tradehub/backtest/__init__.py` (empty), `tradehub/backtest/pit.py`
- Test: `tests/test_backtest_pit.py`

**Interfaces:**
- Produces: `Observation(name: str, value: float, published_at: datetime)` (frozen dataclass; `published_at` must be timezone-aware).
- Produces: `Decision(market_ticker: str, decided_at: datetime, our_prob: float, features: tuple[Observation, ...] = ())` (frozen; `our_prob` is P(YES)).
- Produces: `class LeakageError(RuntimeError)`, and `check_no_lookahead(decision: Decision) -> None`. It raises `LeakageError` naming every late feature, and raises `ValueError` on naive datetimes.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_pit.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Decision, LeakageError, Observation, check_no_lookahead

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def test_features_published_before_decision_pass():
    d = Decision("KXHIGHNY-26JUL24-T88", T0, 0.3, (Observation("f", 1.0, T0 - timedelta(hours=1)),))
    check_no_lookahead(d)


def test_feature_published_exactly_at_decision_passes():
    check_no_lookahead(Decision("T", T0, 0.5, (Observation("f", 1.0, T0),)))


def test_feature_published_after_decision_raises_and_names_it():
    late = Observation("late_feature", 1.0, T0 + timedelta(seconds=1))
    ok = Observation("ok_feature", 1.0, T0 - timedelta(days=1))
    with pytest.raises(LeakageError, match="late_feature"):
        check_no_lookahead(Decision("T", T0, 0.5, (ok, late)))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        check_no_lookahead(Decision("T", datetime(2026, 7, 24, 12), 0.5))
    with pytest.raises(ValueError):
        check_no_lookahead(Decision("T", T0, 0.5, (Observation("f", 1.0, datetime(2026, 7, 24)),)))
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tradehub.backtest'`.

- [ ] **Step 3: Implement** — create an empty `tradehub/backtest/__init__.py`, then `tradehub/backtest/pit.py`:

```python
"""Point-in-time primitives: every feature carries the moment it became knowable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class LeakageError(RuntimeError):
    """A decision used information published after the decision time."""


@dataclass(frozen=True)
class Observation:
    name: str
    value: float
    published_at: datetime


@dataclass(frozen=True)
class Decision:
    market_ticker: str
    decided_at: datetime
    our_prob: float
    features: tuple[Observation, ...] = ()


def _require_aware(ts: datetime, what: str) -> None:
    if ts.tzinfo is None:
        raise ValueError(f"{what} must be timezone-aware, got naive {ts!r}")


def check_no_lookahead(decision: Decision) -> None:
    """Raise LeakageError if any feature was published after the decision time."""
    _require_aware(decision.decided_at, "decided_at")
    late = []
    for obs in decision.features:
        _require_aware(obs.published_at, f"published_at of {obs.name}")
        if obs.published_at > decision.decided_at:
            late.append(obs.name)
    if late:
        raise LeakageError(
            f"{decision.market_ticker} at {decision.decided_at.isoformat()}: "
            f"features published after the decision: {late}"
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/__init__.py tradehub/backtest/pit.py tests/test_backtest_pit.py
git commit -m "feat: add point-in-time observations and leakage guard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Kalshi public-history client (`http.py`, `kalshi_history.py`)

**Files:**
- Create: `tradehub/backtest/http.py`, `tradehub/backtest/kalshi_history.py`
- Test: `tests/test_backtest_kalshi_history.py`

**Interfaces:**
- Produces: `default_get_json(url: str, params: dict | None = None) -> dict` in `http.py`. It calls `requests.get` with a 30 s timeout and `raise_for_status()`.
- Produces: `KALSHI_PUBLIC_BASE = "https://api.elections.kalshi.com/trade-api/v2"`.
- Produces: `Candle(end_ts: datetime, yes_bid: float | None, yes_ask: float | None, volume: float)`. Bid and ask are the period **close**, in dollars.
- Produces: `Trade(created_at: datetime, yes_price: float, no_price: float, count: float, taker_side: str)`.
- Produces: `parse_candle(raw: dict) -> Candle`, `parse_trade(raw: dict) -> Trade`, `parse_ts(value: str) -> datetime`.
- Produces: `KalshiHistoryClient(get_json=default_get_json, base_url=KALSHI_PUBLIC_BASE)` with these methods:
  - `.cutoff() -> datetime` (the `market_settled_ts` field);
  - `.settled_markets(series_ticker: str) -> list[dict]`;
  - `.candles(ticker, start, end, *, period_minutes=60, historical=True, series_ticker=None) -> list[Candle]`, sorted by `end_ts`;
  - `.trades(ticker, *, historical=True) -> list[Trade]`, sorted by `created_at`.

  Pagination follows `cursor` until it is empty. On the live tier, candles use `/series/{series_ticker}/markets/{ticker}/candlesticks`, which requires `series_ticker`, and trades use `/markets/trades`.

These fixture shapes are copied from real responses captured on 2026-09-24 (`KXHIGHNY-26JUL24-T88`).

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_kalshi_history.py`:

```python
from datetime import datetime, timezone

import pytest

from tradehub.backtest import kalshi_history as kh

CANDLE = {
    "end_period_ts": 1784894400,
    "open_interest": "1335.68",
    "price": {"close": None, "high": None, "low": None, "mean": None, "open": None, "previous": "0.0100"},
    "volume": "12.00",
    "yes_ask": {"close": "0.0300", "high": "0.0400", "low": "0.0100", "open": "0.0100"},
    "yes_bid": {"close": "0.0200", "high": "0.0200", "low": "0.0000", "open": "0.0000"},
}
TRADE = {
    "count_fp": "83.00",
    "created_time": "2026-07-24T22:19:22.675922Z",
    "is_block_trade": False,
    "no_price_dollars": "0.9900",
    "taker_book_side": "bid",
    "taker_outcome_side": "yes",
    "taker_side": "yes",
    "ticker": "KXHIGHNY-26JUL24-T88",
    "trade_id": "a90acdda-3192-7344-f6e6-161b9667972e",
    "yes_price_dollars": "0.0100",
}


class FakeGet:
    """Serves canned JSON per path; records every (path, params) call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None):
        path = url.replace(kh.KALSHI_PUBLIC_BASE, "")
        self.calls.append((path, dict(params or {})))
        pages = self.routes[path]
        return pages.pop(0) if isinstance(pages, list) else pages


def test_parse_candle_uses_close_of_bid_and_ask_in_dollars():
    c = kh.parse_candle(CANDLE)
    assert c.end_ts == datetime.fromtimestamp(1784894400, tz=timezone.utc)
    assert c.yes_bid == pytest.approx(0.02)
    assert c.yes_ask == pytest.approx(0.03)
    assert c.volume == pytest.approx(12.0)


def test_parse_candle_missing_quote_is_none():
    c = kh.parse_candle({"end_period_ts": 1784894400, "volume": "0.00", "yes_ask": {"close": None}})
    assert c.yes_ask is None and c.yes_bid is None


def test_parse_trade():
    t = kh.parse_trade(TRADE)
    assert t.created_at == datetime(2026, 7, 24, 22, 19, 22, 675922, tzinfo=timezone.utc)
    assert t.yes_price == pytest.approx(0.01)
    assert t.no_price == pytest.approx(0.99)
    assert t.count == pytest.approx(83.0)
    assert t.taker_side == "yes"


def test_cutoff_reads_market_settled_ts():
    get = FakeGet({"/historical/cutoff": {"market_settled_ts": "2026-07-25T00:00:00Z", "trades_created_ts": "2026-07-25T00:00:00Z"}})
    assert kh.KalshiHistoryClient(get_json=get).cutoff() == datetime(2026, 7, 25, tzinfo=timezone.utc)


def test_settled_markets_follows_cursor_pagination():
    get = FakeGet({"/historical/markets": [
        {"markets": [{"ticker": "A"}], "cursor": "c1"},
        {"markets": [{"ticker": "B"}], "cursor": ""},
    ]})
    markets = kh.KalshiHistoryClient(get_json=get).settled_markets("KXHIGHNY")
    assert [m["ticker"] for m in markets] == ["A", "B"]
    assert get.calls[0][1]["series_ticker"] == "KXHIGHNY"
    assert get.calls[1][1]["cursor"] == "c1"


def test_candles_historical_path_params_and_sorting():
    later = dict(CANDLE, end_period_ts=1784898000)
    get = FakeGet({"/historical/markets/T/candlesticks": {"candlesticks": [later, CANDLE], "ticker": "T"}})
    start = datetime(2026, 7, 23, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 25, 5, tzinfo=timezone.utc)
    candles = kh.KalshiHistoryClient(get_json=get).candles("T", start, end)
    assert [c.end_ts.timestamp() for c in candles] == [1784894400, 1784898000]
    assert get.calls[0][1] == {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 60}


def test_candles_live_tier_requires_series_ticker():
    client = kh.KalshiHistoryClient(get_json=FakeGet({}))
    with pytest.raises(ValueError):
        client.candles("T", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 2, tzinfo=timezone.utc), historical=False)


def test_candles_live_tier_path():
    get = FakeGet({"/series/KXHIGHNY/markets/T/candlesticks": {"candlesticks": [CANDLE]}})
    kh.KalshiHistoryClient(get_json=get).candles(
        "T", datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 2, tzinfo=timezone.utc),
        historical=False, series_ticker="KXHIGHNY",
    )
    assert get.calls[0][0] == "/series/KXHIGHNY/markets/T/candlesticks"


def test_trades_paginates_and_sorts_oldest_first():
    newer = dict(TRADE, created_time="2026-07-24T23:00:00Z")
    get = FakeGet({"/historical/trades": [{"trades": [newer], "cursor": "x"}, {"trades": [TRADE], "cursor": None}]})
    trades = kh.KalshiHistoryClient(get_json=get).trades("KXHIGHNY-26JUL24-T88")
    assert [t.created_at.hour for t in trades] == [22, 23]
    assert get.calls[0][1]["ticker"] == "KXHIGHNY-26JUL24-T88"


def test_live_trades_path():
    get = FakeGet({"/markets/trades": {"trades": [TRADE], "cursor": ""}})
    kh.KalshiHistoryClient(get_json=get).trades("T", historical=False)
    assert get.calls[0][0] == "/markets/trades"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.backtest.kalshi_history`.

- [ ] **Step 3: Implement** — `tradehub/backtest/http.py`:

```python
"""The single place backtest code touches the network."""

from __future__ import annotations

from typing import Any

import requests


def default_get_json(url: str, params: dict | None = None) -> Any:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

and `tradehub/backtest/kalshi_history.py`:

```python
"""Kalshi public market history (candlesticks, trades) for backtests.

Kalshi splits data into a live tier and a historical tier; anything that
settled before GET /historical/cutoff's `market_settled_ts` must be read
from /historical/*. No auth is needed for market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from tradehub.backtest.http import default_get_json

KALSHI_PUBLIC_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PAGE_LIMIT = 1000


@dataclass(frozen=True)
class Candle:
    end_ts: datetime
    yes_bid: float | None
    yes_ask: float | None
    volume: float


@dataclass(frozen=True)
class Trade:
    created_at: datetime
    yes_price: float
    no_price: float
    count: float
    taker_side: str


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dollars(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_candle(raw: dict[str, Any]) -> Candle:
    return Candle(
        end_ts=datetime.fromtimestamp(int(raw["end_period_ts"]), tz=timezone.utc),
        yes_bid=_dollars((raw.get("yes_bid") or {}).get("close")),
        yes_ask=_dollars((raw.get("yes_ask") or {}).get("close")),
        volume=float(raw.get("volume") or 0.0),
    )


def parse_trade(raw: dict[str, Any]) -> Trade:
    return Trade(
        created_at=parse_ts(raw["created_time"]),
        yes_price=float(raw["yes_price_dollars"]),
        no_price=float(raw["no_price_dollars"]),
        count=float(raw["count_fp"]),
        taker_side=raw["taker_side"],
    )


class KalshiHistoryClient:
    def __init__(self, get_json: Callable[..., Any] = default_get_json, base_url: str = KALSHI_PUBLIC_BASE):
        self._get_json = get_json
        self._base = base_url.rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._get_json(f"{self._base}{path}", params)

    def _paginate(self, path: str, key: str, params: dict) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            data = self._get(path, page_params)
            out.extend(data.get(key) or [])
            cursor = data.get("cursor")
            if not cursor:
                return out

    def cutoff(self) -> datetime:
        return parse_ts(self._get("/historical/cutoff")["market_settled_ts"])

    def settled_markets(self, series_ticker: str) -> list[dict]:
        return self._paginate("/historical/markets", "markets", {"series_ticker": series_ticker, "limit": PAGE_LIMIT})

    def candles(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        period_minutes: int = 60,
        historical: bool = True,
        series_ticker: str | None = None,
    ) -> list[Candle]:
        if historical:
            path = f"/historical/markets/{ticker}/candlesticks"
        else:
            if not series_ticker:
                raise ValueError("live-tier candlesticks require series_ticker")
            path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        params = {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": period_minutes}
        raw = self._get(path, params).get("candlesticks") or []
        return sorted((parse_candle(c) for c in raw), key=lambda c: c.end_ts)

    def trades(self, ticker: str, *, historical: bool = True) -> list[Trade]:
        path = "/historical/trades" if historical else "/markets/trades"
        raw = self._paginate(path, "trades", {"ticker": ticker, "limit": PAGE_LIMIT})
        return sorted((parse_trade(t) for t in raw), key=lambda t: t.created_at)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/http.py tradehub/backtest/kalshi_history.py tests/test_backtest_kalshi_history.py
git commit -m "feat: add Kalshi public-history client for backtests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Fill model (`fills.py`)

**Files:**
- Create: `tradehub/backtest/fills.py`
- Test: `tests/test_backtest_fills.py`

**Interfaces:**
- Consumes: `Decision` (Task 2), `Candle`/`Trade` (Task 3), `shared.kalshi_fees.kalshi_fee_cents`/`net_edge_pct`.
- Produces: `MIN_TAKER_PRICE = 0.10`.
- Produces: `Fill(market_ticker: str, side: str, price: float, contracts: int, fee: float, filled_at: datetime, maker: bool)`. `side` is `"yes"`/`"no"`; `price` is dollars per contract; `fee` is total dollars.
- Produces: `quote_at(candles: list[Candle], at: datetime) -> Candle | None`, the last candle with `end_ts <= at` and both quotes present.
- Produces: `taker_fill(decision, candles, *, contracts=1, min_edge_pct=0.0) -> Fill | None`.
- Produces: `maker_fill(decision, candles, trades, close_time, *, contracts=1, min_edge_pct=0.0) -> Fill | None`.

**Side selection (both functions):**
- Buying YES costs `yes_ask` as a taker, or the limit is `yes_bid` as a maker.
- Buying NO costs `1 - yes_bid` as a taker, or the limit is `1 - yes_ask` as a maker.
- Net edge per side is `net_edge_pct(our_side_prob*100, price*100, maker=...)`, where `our_side_prob` is `our_prob` for YES and `1 - our_prob` for NO. Pick the side with the larger net edge, and return `None` unless it is `>= min_edge_pct` and `> 0`.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_fills.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.backtest.fills import MIN_TAKER_PRICE, maker_fill, quote_at, taker_fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.pit import Decision

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)


def candle(hours_before, bid, ask):
    return Candle(end_ts=T0 - timedelta(hours=hours_before), yes_bid=bid, yes_ask=ask, volume=1.0)


def test_quote_at_uses_last_candle_at_or_before_decision_not_future():
    candles = [candle(2, 0.30, 0.34), candle(1, 0.40, 0.44), candle(-1, 0.90, 0.95)]
    assert quote_at(candles, T0).yes_ask == pytest.approx(0.44)


def test_quote_at_skips_candles_without_both_quotes():
    candles = [candle(2, 0.30, 0.34), Candle(T0 - timedelta(hours=1), None, 0.5, 0.0)]
    assert quote_at(candles, T0).yes_ask == pytest.approx(0.34)


def test_quote_at_none_when_no_prior_candle():
    assert quote_at([candle(-1, 0.4, 0.44)], T0) is None


def test_taker_buys_yes_at_ask_with_taker_fee():
    fill = taker_fill(Decision("T", T0, 0.70), [candle(1, 0.40, 0.44)], contracts=10)
    assert fill.side == "yes" and fill.maker is False
    assert fill.price == pytest.approx(0.44)
    assert fill.fee == pytest.approx(kalshi_fee_cents(44.0, contracts=10) / 100)
    assert fill.filled_at == T0


def test_taker_buys_no_at_one_minus_bid():
    fill = taker_fill(Decision("T", T0, 0.20), [candle(1, 0.40, 0.44)])
    assert fill.side == "no"
    assert fill.price == pytest.approx(0.60)


def test_taker_never_buys_below_10_cents():
    # our_prob 0.30 vs ask 0.05 is a big YES edge, but 5c < 10c -> no taker fill.
    assert MIN_TAKER_PRICE == pytest.approx(0.10)
    assert taker_fill(Decision("T", T0, 0.30), [candle(1, 0.03, 0.05)]) is None


def test_taker_respects_min_edge_after_fees():
    # 0.47 vs ask 0.44: gross 3pp, fee ~1.73pp -> net ~1.27pp.
    d = Decision("T", T0, 0.47)
    assert taker_fill(d, [candle(1, 0.40, 0.44)], min_edge_pct=1.0) is not None
    assert taker_fill(d, [candle(1, 0.40, 0.44)], min_edge_pct=2.0) is None


def test_taker_no_fill_without_edge():
    assert taker_fill(Decision("T", T0, 0.42), [candle(1, 0.40, 0.44)]) is None


def test_maker_yes_bid_fills_on_later_no_taker_trade_at_or_through_limit():
    trades = [
        Trade(T0 - timedelta(minutes=5), 0.39, 0.61, 3.0, "no"),   # before decision: ignored
        Trade(T0 + timedelta(minutes=10), 0.41, 0.59, 2.0, "no"),  # above limit 0.40: no fill
        Trade(T0 + timedelta(minutes=20), 0.40, 0.60, 5.0, "no"),  # at limit: fill
    ]
    fill = maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE, contracts=2)
    assert fill.side == "yes" and fill.maker is True
    assert fill.price == pytest.approx(0.40)
    assert fill.filled_at == T0 + timedelta(minutes=20)
    assert fill.fee == pytest.approx(kalshi_fee_cents(40.0, contracts=2, maker=True) / 100)


def test_maker_ignores_same_side_takers_and_trades_after_close():
    trades = [
        Trade(T0 + timedelta(minutes=5), 0.30, 0.70, 1.0, "yes"),  # taker bought YES: doesn't hit our bid
        Trade(CLOSE + timedelta(minutes=1), 0.30, 0.70, 1.0, "no"),  # after close
    ]
    assert maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE) is None


def test_maker_no_side_fills_on_yes_taker_at_or_through_no_limit():
    # our_prob 0.20 -> buy NO; limit = 1 - ask = 0.56; a YES taker printing no_price <= 0.56 fills it.
    trades = [Trade(T0 + timedelta(minutes=3), 0.45, 0.55, 1.0, "yes")]
    fill = maker_fill(Decision("T", T0, 0.20), [candle(1, 0.40, 0.44)], trades, CLOSE)
    assert fill.side == "no"
    assert fill.price == pytest.approx(0.56)


def test_maker_needs_positive_limit():
    assert maker_fill(Decision("T", T0, 0.90), [candle(1, 0.0, 0.02)], [], CLOSE) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.backtest.fills`.

- [ ] **Step 3: Implement** — `tradehub/backtest/fills.py`:

```python
"""Conservative Kalshi fill model: taker at the visible ask, maker only on a printed trade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shared.kalshi_fees import kalshi_fee_cents, net_edge_pct
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.pit import Decision

MIN_TAKER_PRICE = 0.10


@dataclass(frozen=True)
class Fill:
    market_ticker: str
    side: str
    price: float
    contracts: int
    fee: float
    filled_at: datetime
    maker: bool


def quote_at(candles: list[Candle], at: datetime) -> Candle | None:
    """Last candle that ended at or before `at` with both quotes present."""
    visible = [c for c in candles if c.end_ts <= at and c.yes_bid is not None and c.yes_ask is not None]
    return visible[-1] if visible else None


def _best_side(our_prob: float, yes_price: float, no_price: float, *, maker: bool) -> tuple[str, float, float]:
    yes_edge = net_edge_pct(our_prob * 100.0, yes_price * 100.0, maker=maker)
    no_edge = net_edge_pct((1.0 - our_prob) * 100.0, no_price * 100.0, maker=maker)
    if yes_edge >= no_edge:
        return "yes", yes_price, yes_edge
    return "no", no_price, no_edge


def _fee_dollars(price: float, contracts: int, maker: bool) -> float:
    return kalshi_fee_cents(price * 100.0, contracts=contracts, maker=maker) / 100.0


def taker_fill(decision: Decision, candles: list[Candle], *, contracts: int = 1, min_edge_pct: float = 0.0) -> Fill | None:
    quote = quote_at(candles, decision.decided_at)
    if quote is None:
        return None
    side, price, edge = _best_side(decision.our_prob, quote.yes_ask, 1.0 - quote.yes_bid, maker=False)
    if edge <= 0 or edge < min_edge_pct or price < MIN_TAKER_PRICE:
        return None
    return Fill(decision.market_ticker, side, price, contracts, _fee_dollars(price, contracts, False),
                decision.decided_at, maker=False)


def maker_fill(
    decision: Decision,
    candles: list[Candle],
    trades: list[Trade],
    close_time: datetime,
    *,
    contracts: int = 1,
    min_edge_pct: float = 0.0,
) -> Fill | None:
    quote = quote_at(candles, decision.decided_at)
    if quote is None:
        return None
    side, limit, edge = _best_side(decision.our_prob, quote.yes_bid, 1.0 - quote.yes_ask, maker=True)
    if edge <= 0 or edge < min_edge_pct or not 0.0 < limit < 1.0:
        return None
    for trade in trades:
        if not decision.decided_at < trade.created_at <= close_time:
            continue
        if side == "yes" and trade.taker_side == "no" and trade.yes_price <= limit:
            break
        if side == "no" and trade.taker_side == "yes" and trade.no_price <= limit:
            break
    else:
        return None
    return Fill(decision.market_ticker, side, limit, contracts, _fee_dollars(limit, contracts, True),
                trade.created_at, maker=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/fills.py tests/test_backtest_fills.py
git commit -m "feat: add conservative taker/maker fill model for backtests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Metrics and runner (`metrics.py`, `runner.py`)

**Files:**
- Create: `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py`
- Test: `tests/test_backtest_runner.py`

**Interfaces:**
- Consumes: `Decision`/`check_no_lookahead`/`LeakageError` (Task 2), `Candle`/`Trade` (Task 3), `Fill`/`quote_at`/`taker_fill`/`maker_fill` (Task 4). From step 2: `tradehub.settlement.brier_score(prob, outcome)` and `tradehub.track_record.compute_engine_summary(rows)`, `compute_calibration(rows)`, `check_promotion_gate(*, engine, cadence, summary, cal_buckets, simulated_pnl_after_fees)`.
- Produces in `metrics.py`:
  - `fill_pnl(fill: Fill, result: str) -> float`: dollars; payout is $1 per contract if `fill.side == result`, minus price times contracts, minus fee.
  - `max_drawdown(pnls: list[float]) -> float`: largest peak-to-trough drop of cumulative P&L, `>= 0`.
  - `market_mid(candle: Candle | None) -> float | None`.
  - `prediction_row(our_prob: float, market_prob: float | None, result: str) -> dict`: the settled-row shape `track_record` consumes (`our_prob, market_prob, result, brier, market_brier, status`).
- Produces in `runner.py`:
  - `MarketHistory(ticker: str, result: str | None, close_time: datetime, candles: list[Candle], trades: list[Trade])`.
  - `BacktestResult(engine, cadence, mode, n_decisions, n_fills, pnl_after_fees, max_drawdown, turnover, summary, cal_buckets, gate, fills)`.
  - `run_backtest(*, engine: str, cadence: str, decisions: Iterable[Decision], histories: Mapping[str, MarketHistory], mode: str = "taker", contracts: int = 1, min_edge_pct: float = 0.0) -> BacktestResult`.
  - `walk_forward(events, time_of, fit, predict, *, min_history=1) -> list[tuple[event, prediction]]`.

**Runner rules:**
- Decisions are processed in `decided_at` order, and `check_no_lookahead` runs on each one before anything else.
- A decision at or after its market's `close_time` raises `LeakageError`.
- Markets whose `result` isn't `"yes"`/`"no"` are skipped (not counted in `n_decisions`).
- `turnover` is the sum of `price * contracts` over fills.
- `simulated_pnl_after_fees` passed to the gate is the total P&L, or `None` when there were no fills.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_runner.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from tradehub.backtest.fills import Fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
from tradehub.backtest.pit import Decision, LeakageError, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest, walk_forward

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)


def hist(ticker, result, bid=0.40, ask=0.44, trades=()):
    return MarketHistory(ticker, result, CLOSE, [Candle(T0 - timedelta(hours=1), bid, ask, 1.0)], list(trades))


def test_fill_pnl_win_and_loss():
    f = Fill("T", "yes", 0.44, 10, 0.18, T0, False)
    assert fill_pnl(f, "yes") == pytest.approx((1.0 - 0.44) * 10 - 0.18)
    assert fill_pnl(f, "no") == pytest.approx(-0.44 * 10 - 0.18)


def test_max_drawdown():
    assert max_drawdown([]) == 0.0
    assert max_drawdown([1.0, -2.0, 0.5, -1.0, 3.0]) == pytest.approx(2.5)
    assert max_drawdown([1.0, 1.0]) == 0.0


def test_market_mid():
    assert market_mid(Candle(T0, 0.40, 0.44, 0.0)) == pytest.approx(0.42)
    assert market_mid(None) is None


def test_prediction_row_scores_both_briers():
    row = prediction_row(0.7, 0.5, "yes")
    assert row["brier"] == pytest.approx(0.09)
    assert row["market_brier"] == pytest.approx(0.25)
    assert row["status"] == "SETTLED" and row["result"] == "yes"
    assert prediction_row(0.7, None, "no")["market_brier"] is None


def test_run_backtest_taker_scores_fills_and_feeds_gate():
    decisions = [Decision("A", T0, 0.70), Decision("B", T0 + timedelta(minutes=1), 0.20)]
    histories = {"A": hist("A", "yes"), "B": hist("B", "no")}
    res = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    assert res.n_decisions == 2 and res.n_fills == 2
    expected = sum(fill_pnl(f, {"A": "yes", "B": "no"}[f.market_ticker]) for f in res.fills)
    assert res.pnl_after_fees == pytest.approx(expected)
    assert res.pnl_after_fees > 0
    assert res.turnover == pytest.approx(0.44 + 0.60)
    assert res.summary["n_settled"] == 2
    assert res.gate["status"] == "SHADOW"  # 2 contracts << 200 daily minimum
    assert any("200" in r for r in res.gate["reasons"])


def test_run_backtest_skips_canceled_markets():
    res = run_backtest(engine="weather", cadence="daily",
                       decisions=[Decision("C", T0, 0.7)], histories={"C": hist("C", None)})
    assert res.n_decisions == 0 and res.n_fills == 0
    assert res.pnl_after_fees == 0.0


def test_run_backtest_rejects_lookahead_features():
    late = Observation("forecast", 80.0, T0 + timedelta(hours=1))
    with pytest.raises(LeakageError):
        run_backtest(engine="weather", cadence="daily",
                     decisions=[Decision("A", T0, 0.7, (late,))], histories={"A": hist("A", "yes")})


def test_run_backtest_rejects_decision_after_close():
    with pytest.raises(LeakageError):
        run_backtest(engine="weather", cadence="daily",
                     decisions=[Decision("A", CLOSE, 0.7)], histories={"A": hist("A", "yes")})


def test_run_backtest_maker_mode_uses_trades():
    trades = [Trade(T0 + timedelta(minutes=5), 0.40, 0.60, 1.0, "no")]
    res = run_backtest(engine="weather", cadence="daily", mode="maker",
                       decisions=[Decision("A", T0, 0.70)], histories={"A": hist("A", "yes", trades=trades)})
    assert res.n_fills == 1 and res.fills[0].maker is True


def test_run_backtest_no_fills_passes_none_pnl_to_gate():
    res = run_backtest(engine="weather", cadence="daily",
                       decisions=[Decision("A", T0, 0.42)], histories={"A": hist("A", "yes")})
    assert res.n_fills == 0
    assert any("P&L" in r for r in res.gate["reasons"])


def test_walk_forward_only_fits_on_strictly_earlier_events():
    times = [T0 + timedelta(hours=h) for h in (0, 1, 1, 2)]
    seen = []

    def fit(history):
        seen.append(len(history))
        return len(history)

    out = walk_forward(times, time_of=lambda t: t, fit=fit, predict=lambda model, t: model)
    # The two events at hour 1 must not see each other.
    assert [p for _, p in out] == [1, 1, 3]
    assert seen == [1, 1, 3]
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.backtest.metrics`.

- [ ] **Step 3: Implement** — `tradehub/backtest/metrics.py`:

```python
"""Per-fill P&L and prediction rows shaped for tradehub.track_record."""

from __future__ import annotations

from typing import Any

from tradehub.backtest.fills import Fill
from tradehub.backtest.kalshi_history import Candle
from tradehub.settlement import brier_score


def fill_pnl(fill: Fill, result: str) -> float:
    payout = 1.0 if fill.side == result else 0.0
    return (payout - fill.price) * fill.contracts - fill.fee


def max_drawdown(pnls: list[float]) -> float:
    peak = cum = 0.0
    worst = 0.0
    for pnl in pnls:
        cum += pnl
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def market_mid(candle: Candle | None) -> float | None:
    if candle is None or candle.yes_bid is None or candle.yes_ask is None:
        return None
    return (candle.yes_bid + candle.yes_ask) / 2.0


def prediction_row(our_prob: float, market_prob: float | None, result: str) -> dict[str, Any]:
    outcome = 1 if result == "yes" else 0
    return {
        "our_prob": our_prob,
        "market_prob": market_prob,
        "result": result,
        "brier": brier_score(our_prob, outcome),
        "market_brier": None if market_prob is None else brier_score(market_prob, outcome),
        "status": "SETTLED",
    }
```

and `tradehub/backtest/runner.py`:

```python
"""Replay point-in-time decisions against Kalshi history and score them with the live gate code."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from tradehub.backtest.fills import Fill, maker_fill, quote_at, taker_fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
from tradehub.backtest.pit import Decision, LeakageError, check_no_lookahead
from tradehub.track_record import check_promotion_gate, compute_calibration, compute_engine_summary

E = TypeVar("E")
M = TypeVar("M")
R = TypeVar("R")


@dataclass
class MarketHistory:
    ticker: str
    result: str | None
    close_time: datetime
    candles: list[Candle]
    trades: list[Trade]


@dataclass
class BacktestResult:
    engine: str
    cadence: str
    mode: str
    n_decisions: int
    n_fills: int
    pnl_after_fees: float
    max_drawdown: float
    turnover: float
    summary: dict[str, Any]
    cal_buckets: list[dict[str, Any]]
    gate: dict[str, Any]
    fills: list[Fill] = field(default_factory=list)


def run_backtest(
    *,
    engine: str,
    cadence: str,
    decisions: Iterable[Decision],
    histories: Mapping[str, MarketHistory],
    mode: str = "taker",
    contracts: int = 1,
    min_edge_pct: float = 0.0,
) -> BacktestResult:
    if mode not in ("taker", "maker"):
        raise ValueError(f"mode must be 'taker' or 'maker', got {mode!r}")
    rows: list[dict[str, Any]] = []
    fills: list[Fill] = []
    pnls: list[float] = []
    for decision in sorted(decisions, key=lambda d: d.decided_at):
        check_no_lookahead(decision)
        history = histories[decision.market_ticker]
        if decision.decided_at >= history.close_time:
            raise LeakageError(f"{decision.market_ticker}: decision at/after market close {history.close_time.isoformat()}")
        if history.result not in ("yes", "no"):
            continue
        rows.append(prediction_row(decision.our_prob, market_mid(quote_at(history.candles, decision.decided_at)), history.result))
        if mode == "taker":
            fill = taker_fill(decision, history.candles, contracts=contracts, min_edge_pct=min_edge_pct)
        else:
            fill = maker_fill(decision, history.candles, history.trades, history.close_time,
                              contracts=contracts, min_edge_pct=min_edge_pct)
        if fill is not None:
            fills.append(fill)
            pnls.append(fill_pnl(fill, history.result))
    summary = compute_engine_summary(rows)
    cal_buckets = compute_calibration(rows)
    total = sum(pnls)
    gate = check_promotion_gate(engine=engine, cadence=cadence, summary=summary, cal_buckets=cal_buckets,
                                simulated_pnl_after_fees=total if fills else None)
    return BacktestResult(
        engine=engine, cadence=cadence, mode=mode, n_decisions=len(rows), n_fills=len(fills),
        pnl_after_fees=total, max_drawdown=max_drawdown(pnls),
        turnover=sum(f.price * f.contracts for f in fills),
        summary=summary, cal_buckets=cal_buckets, gate=gate, fills=fills,
    )


def walk_forward(
    events: Sequence[E],
    time_of: Callable[[E], datetime],
    fit: Callable[[list[E]], M],
    predict: Callable[[M, E], R],
    *,
    min_history: int = 1,
) -> list[tuple[E, R]]:
    """Predict each event from a model fit only on events strictly earlier in time."""
    ordered = sorted(events, key=time_of)
    out: list[tuple[E, R]] = []
    for event in ordered:
        history = [e for e in ordered if time_of(e) < time_of(event)]
        if len(history) < min_history:
            continue
        out.append((event, predict(fit(history), event)))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/metrics.py tradehub/backtest/runner.py tests/test_backtest_runner.py
git commit -m "feat: add backtest runner sharing the live promotion-gate metrics

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: First point-in-time sources (ALFRED vintages, Open-Meteo previous runs)

**Files:**
- Create: `tradehub/backtest/sources/__init__.py` (empty), `tradehub/backtest/sources/alfred.py`, `tradehub/backtest/sources/open_meteo.py`
- Test: `tests/test_backtest_sources.py`

**Interfaces:**
- Consumes: `Observation` (Task 2), `default_get_json` (Task 3).
- Produces in `alfred.py`:
  - `FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"`;
  - `AlfredSource(series_id: str, api_key: str, get_json=default_get_json)` with `.latest_as_of(as_of: datetime) -> Observation | None`.

  It queries the vintage for the **previous UTC day** (`realtime_start = realtime_end = as_of.date() - 1 day`, `sort_order=desc`) and returns the newest non-missing value. `published_at` is that vintage's `realtime_start` date plus one day, at 00:00 UTC. ALFRED is day-granular and releases land intraday, so this lag is what keeps it lookahead-safe. The observation name is `"{series_id}:{observation date}"`.
- Produces in `open_meteo.py`:
  - `PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"`;
  - `forecast_daily_high(*, latitude, longitude, target_date: date, lead_days: int, model: str, timezone_name: str, get_json=default_get_json) -> Observation`.

  It requests hourly `temperature_2m_previous_day{lead_days}` in °F for the target local date and returns the max. `published_at` is 23:00 local on the target date minus `lead_days` days, converted to UTC; that is the latest issue time behind any value used. `lead_days` must be 1–7. It raises `ValueError` if no values come back. The observation name is `"openmeteo:{model}:high:{target_date}:lead{lead_days}"`.

The Open-Meteo fixture below mirrors a real response captured 2026-09-24 for Central Park, `ncep_gfs_seamless`, 2026-07-24.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_sources.py`:

```python
from datetime import date, datetime, timezone

import pytest

from tradehub.backtest.sources.alfred import FRED_OBSERVATIONS_URL, AlfredSource
from tradehub.backtest.sources.open_meteo import PREVIOUS_RUNS_URL, forecast_daily_high


class Recorder:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.payload


def test_alfred_queries_previous_day_vintage_and_lags_publication():
    rec = Recorder({"observations": [
        {"realtime_start": "2026-09-04", "realtime_end": "2026-09-04", "date": "2026-08-01", "value": "159123"},
        {"realtime_start": "2026-08-07", "realtime_end": "2026-09-04", "date": "2026-07-01", "value": "158900"},
    ]})
    obs = AlfredSource("PAYEMS", "k", get_json=rec).latest_as_of(datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc))
    url, params = rec.calls[0]
    assert url == FRED_OBSERVATIONS_URL
    assert params["realtime_start"] == params["realtime_end"] == "2026-09-04"
    assert params["sort_order"] == "desc" and params["file_type"] == "json" and params["series_id"] == "PAYEMS"
    assert obs.value == pytest.approx(159123.0)
    assert obs.name == "PAYEMS:2026-08-01"
    assert obs.published_at == datetime(2026, 9, 5, tzinfo=timezone.utc)
    assert obs.published_at <= datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)


def test_alfred_skips_missing_values_and_handles_empty():
    rec = Recorder({"observations": [
        {"realtime_start": "2026-09-04", "realtime_end": "2026-09-04", "date": "2026-08-01", "value": "."},
        {"realtime_start": "2026-08-07", "realtime_end": "2026-09-04", "date": "2026-07-01", "value": "158900"},
    ]})
    obs = AlfredSource("PAYEMS", "k", get_json=rec).latest_as_of(datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert obs.value == pytest.approx(158900.0)
    assert obs.published_at == datetime(2026, 8, 8, tzinfo=timezone.utc)
    assert AlfredSource("X", "k", get_json=Recorder({"observations": []})).latest_as_of(
        datetime(2026, 9, 5, tzinfo=timezone.utc)) is None


def test_forecast_daily_high_max_of_previous_day_series_and_issue_time():
    hourly = [65.6, 65.3, 64.5] + [70.0] * 18 + [84.4, 80.0, 75.0]
    rec = Recorder({"hourly": {"time": [f"2026-07-24T{h:02d}:00" for h in range(24)],
                               "temperature_2m_previous_day1": hourly}})
    obs = forecast_daily_high(latitude=40.7794, longitude=-73.9692, target_date=date(2026, 7, 24), lead_days=1,
                              model="ncep_gfs_seamless", timezone_name="America/New_York", get_json=rec)
    url, params = rec.calls[0]
    assert url == PREVIOUS_RUNS_URL
    assert params["hourly"] == "temperature_2m_previous_day1"
    assert params["start_date"] == params["end_date"] == "2026-07-24"
    assert params["temperature_unit"] == "fahrenheit" and params["models"] == "ncep_gfs_seamless"
    assert obs.value == pytest.approx(84.4)
    # 23:00 EDT on Jul 24 minus 1 day = Jul 23 23:00 EDT = Jul 24 03:00 UTC.
    assert obs.published_at == datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)
    assert obs.name == "openmeteo:ncep_gfs_seamless:high:2026-07-24:lead1"


def test_forecast_daily_high_validates_lead_and_empty_payload():
    kwargs = dict(latitude=40.7, longitude=-73.9, target_date=date(2026, 7, 24),
                  model="ncep_gfs_seamless", timezone_name="America/New_York")
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=0, get_json=Recorder({}), **kwargs)
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=8, get_json=Recorder({}), **kwargs)
    empty = Recorder({"hourly": {"time": [], "temperature_2m_previous_day2": [None, None]}})
    with pytest.raises(ValueError):
        forecast_daily_high(lead_days=2, get_json=empty, **kwargs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.backtest.sources`.

- [ ] **Step 3: Implement** — create an empty `tradehub/backtest/sources/__init__.py`, then `tradehub/backtest/sources/alfred.py`:

```python
"""ALFRED (FRED archival) vintages: macro values exactly as they were known at a past date."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class AlfredSource:
    def __init__(self, series_id: str, api_key: str, get_json: Callable[..., Any] = default_get_json):
        self.series_id = series_id
        self._api_key = api_key
        self._get_json = get_json

    def latest_as_of(self, as_of: datetime) -> Observation | None:
        """Newest value knowable at `as_of`.

        ALFRED vintages are day-granular but releases land intraday (e.g. 8:30 ET),
        so we read the previous day's vintage and treat each vintage as available
        only from the start of the day after it began.
        """
        vintage_day = (as_of.astimezone(timezone.utc).date() - timedelta(days=1)).isoformat()
        data = self._get_json(FRED_OBSERVATIONS_URL, {
            "series_id": self.series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "realtime_start": vintage_day,
            "realtime_end": vintage_day,
            "sort_order": "desc",
            "limit": 50,
        })
        for obs in data.get("observations") or []:
            if obs.get("value") in (None, "", "."):
                continue
            began = datetime.combine(datetime.fromisoformat(obs["realtime_start"]).date(), time(0), timezone.utc)
            return Observation(
                name=f"{self.series_id}:{obs['date']}",
                value=float(obs["value"]),
                published_at=began + timedelta(days=1),
            )
        return None
```

and `tradehub/backtest/sources/open_meteo.py`:

```python
"""Open-Meteo Previous Runs: weather forecasts exactly as issued N days ahead."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


def forecast_daily_high(
    *,
    latitude: float,
    longitude: float,
    target_date: date,
    lead_days: int,
    model: str,
    timezone_name: str,
    get_json: Callable[..., Any] = default_get_json,
) -> Observation:
    """Max hourly 2 m temperature (°F) for target_date as forecast `lead_days` earlier."""
    if not 1 <= lead_days <= 7:
        raise ValueError(f"lead_days must be 1..7, got {lead_days}")
    variable = f"temperature_2m_previous_day{lead_days}"
    day = target_date.isoformat()
    data = get_json(PREVIOUS_RUNS_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": variable,
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": timezone_name,
        "start_date": day,
        "end_date": day,
    })
    values = [v for v in (data.get("hourly") or {}).get(variable) or [] if v is not None]
    if not values:
        raise ValueError(f"no {variable} values for {day} ({model})")
    last_hour_local = datetime.combine(target_date, time(23, 0), ZoneInfo(timezone_name))
    issued = (last_hour_local - timedelta(days=lead_days)).astimezone(timezone.utc)
    return Observation(name=f"openmeteo:{model}:high:{day}:lead{lead_days}", value=max(values), published_at=issued)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/sources tests/test_backtest_sources.py
git commit -m "feat: add ALFRED and Open-Meteo previous-runs point-in-time sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Reproducible run storage (`store.py`)

**Files:**
- Create: `tradehub/backtest/store.py`
- Test: `tests/test_backtest_store.py`

**Interfaces:**
- Consumes: `BacktestResult`/`MarketHistory` (Task 5), `Decision` (Task 2), and the `backtest_runs` table (Task 1).
- Produces:
  - `stable_hash(obj: Any) -> str`: sha256 hex of `json.dumps(obj, sort_keys=True, default=str)`.
  - `data_snapshot_hash(decisions: Iterable[Decision], histories: Mapping[str, MarketHistory]) -> str`: order-independent; covers every decision, feature, candle, trade, result, and close time.
  - `build_backtest_run_row(result: BacktestResult, *, engine_version: str, config: dict, data_hash: str, date_from: datetime, date_to: datetime) -> dict`: exactly the Task 1 columns minus `id`, `created_at`, and `user_id`.
  - `record_backtest_run(supa, row: dict) -> dict`: inserts into `backtest_runs` and returns the inserted row.

- [ ] **Step 1: Write the failing tests** — `tests/test_backtest_store.py`:

```python
from datetime import datetime, timedelta, timezone

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import Decision, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import (
    build_backtest_run_row,
    data_snapshot_hash,
    record_backtest_run,
    stable_hash,
)

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)
MIGRATION_COLUMNS = {
    "engine", "engine_version", "mode", "config", "config_hash", "data_hash", "date_from", "date_to",
    "n_decisions", "n_fills", "n_settled", "pnl_after_fees", "max_drawdown", "turnover", "brier_ours",
    "brier_market", "cal_buckets", "max_cal_dev", "gate_status", "gate_reasons",
}


def _inputs():
    decisions = [Decision("A", T0, 0.7, (Observation("f", 1.0, T0 - timedelta(hours=2)),))]
    histories = {"A": MarketHistory("A", "yes", CLOSE, [Candle(T0 - timedelta(hours=1), 0.40, 0.44, 1.0)], [])}
    return decisions, histories


def test_stable_hash_is_key_order_independent():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_data_snapshot_hash_changes_with_inputs_but_not_order():
    decisions, histories = _inputs()
    h1 = data_snapshot_hash(decisions, histories)
    assert h1 == data_snapshot_hash(list(reversed(decisions)), dict(histories))
    changed = {"A": MarketHistory("A", "no", CLOSE, histories["A"].candles, [])}
    assert h1 != data_snapshot_hash(decisions, changed)


def test_build_row_matches_migration_columns():
    decisions, histories = _inputs()
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    row = build_backtest_run_row(result, engine_version="v1", config={"min_edge_pct": 0.0},
                                 data_hash=data_snapshot_hash(decisions, histories),
                                 date_from=T0, date_to=CLOSE)
    assert set(row) == MIGRATION_COLUMNS
    assert row["config_hash"] == stable_hash({"min_edge_pct": 0.0})
    assert row["gate_status"] == "SHADOW"
    assert row["n_fills"] == 1 and row["mode"] == "taker"
    assert row["date_from"] == T0.isoformat()


def test_record_backtest_run_inserts():
    inserted = []

    class Table:
        def insert(self, row):
            inserted.append(row)
            return self

        def execute(self):
            return type("R", (), {"data": list(inserted)})()

    class Supa:
        def table(self, name):
            assert name == "backtest_runs"
            return Table()

    assert record_backtest_run(Supa(), {"engine": "weather"}) == {"engine": "weather"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_store.py -q`
Expected: collection error, `ModuleNotFoundError` for `tradehub.backtest.store`.

- [ ] **Step 3: Implement** — `tradehub/backtest/store.py`:

```python
"""Reproducible backtest_runs rows: config hash + data-snapshot hash pin a run down exactly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from tradehub.backtest.pit import Decision
from tradehub.backtest.runner import BacktestResult, MarketHistory

BACKTEST_RUNS_TABLE = "backtest_runs"


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def data_snapshot_hash(decisions: Iterable[Decision], histories: Mapping[str, MarketHistory]) -> str:
    decision_blobs = sorted(stable_hash(asdict(d)) for d in decisions)
    history_blobs = sorted(stable_hash(asdict(h)) for h in histories.values())
    return stable_hash({"decisions": decision_blobs, "histories": history_blobs})


def build_backtest_run_row(
    result: BacktestResult,
    *,
    engine_version: str,
    config: dict[str, Any],
    data_hash: str,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, Any]:
    return {
        "engine": result.engine,
        "engine_version": engine_version,
        "mode": result.mode,
        "config": config,
        "config_hash": stable_hash(config),
        "data_hash": data_hash,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "n_decisions": result.n_decisions,
        "n_fills": result.n_fills,
        "n_settled": result.summary["n_settled"],
        "pnl_after_fees": round(result.pnl_after_fees, 4),
        "max_drawdown": round(result.max_drawdown, 4),
        "turnover": round(result.turnover, 4),
        "brier_ours": result.summary["brier_ours"],
        "brier_market": result.summary["brier_market"],
        "cal_buckets": result.cal_buckets,
        "max_cal_dev": result.gate["max_cal_dev"],
        "gate_status": result.gate["status"],
        "gate_reasons": result.gate["reasons"],
    }


def record_backtest_run(supa, row: dict[str, Any]) -> dict[str, Any]:
    res = supa.table(BACKTEST_RUNS_TABLE).insert(row).execute()
    data = res.data or []
    return data[0] if data else {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_store.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/backtest/store.py tests/test_backtest_store.py
git commit -m "feat: add reproducible backtest_runs rows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification

- [ ] **Full suite:** `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q`. Expected: all pass, including the 45 new tests (4 + 10 + 12 + 11 + 4 + 4) and the new layout assertion.
- [ ] **Lint:** `.venv/bin/ruff check --select F401,F811,F821 tradehub/backtest tests`. Expected: `All checks passed!`
- [ ] **Import boundary:** `grep -rn "shared.config" tradehub/backtest` prints nothing.
- [ ] **Live smoke (manual, optional, not in CI):**

```bash
.venv/bin/python -c "
from datetime import datetime, timezone
from tradehub.backtest.kalshi_history import KalshiHistoryClient
c = KalshiHistoryClient()
print('cutoff', c.cutoff())
print('candles', len(c.candles('KXHIGHNY-26JUL24-T88', datetime(2026,7,23,14,tzinfo=timezone.utc), datetime(2026,7,25,5,tzinfo=timezone.utc))))
print('trades', len(c.trades('KXHIGHNY-26JUL24-T88')))"
```

Expected: a cutoff datetime, about 36 candles, and a non-zero trade count.

## Out of Scope

- **Engine-specific backtests** (weather, gas): they need the step 4 engines. Step 4 runs `run_backtest` + `record_backtest_run` for each engine it ships.
- **Kelly sizing:** `research/legacy/backtester.py` has Kelly math. This harness scores fixed-size fills, which is all the §6 gate needs. Port Kelly sizing with the live-execution work.
- **A Cleveland Fed nowcast source:** whether an archive exists is still open (rollout tracker, step 6); add it as a `sources/` module then.

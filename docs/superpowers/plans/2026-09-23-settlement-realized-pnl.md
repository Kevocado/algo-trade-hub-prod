# Settlement + Realized P&L Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give trades a real path from `OPEN` to `SETTLED`, with a Kalshi settlement payout turned into `realized_pnl` on the matching `trades` row, so downstream track-record/calibration work (Phase 2 of the roadmap) has real settled data to aggregate.

**Architecture:** A new pure-math module (`market_sentiment_tool/backend/settlement.py`) holds the P&L formula and the settlement-to-trade matching logic so both can be unit tested without a database or network call. Thin I/O wrapper functions in the same module call Supabase and the existing read-only `KalshiPortfolio.get_settlements()` client. An async polling loop is started alongside the existing Telegram operator-plane task in `run_crypto_services()` — the crypto worker loop itself is event-driven off Kalshi WS ticks with no natural periodic slot, so settlement runs on its own timer instead of piggybacking on tick arrival.

**Tech Stack:** Python 3, `pytest` + `monkeypatch` (matching the existing house style in `SP500 Predictor/tests/`), `supabase-py`, the existing `KalshiPortfolio` client at `SP500 Predictor/src/kalshi_portfolio.py`.

**Spec:** [docs/superpowers/plans/2026-09-23-algo-trade-hub-roadmap.md](2026-09-23-algo-trade-hub-roadmap.md) (Phase 1 of the roadmap; see that doc's Context section for why this is sequenced right after schema consolidation)

## Global Constraints

- `trades.status` is constrained to `PENDING | OPEN | FILLED | SETTLED | CLOSED | CANCELLED` (added in `market_sentiment_tool/supabase/migrations/20260416000000_schema_consolidation.sql`) — never write a status outside this set.
- `trades.pnl` no longer exists; it was split into `realized_pnl` and `unrealized_pnl` in the same migration. Every write must target the correct one.
- Match the repo's existing pytest style: plain functions, `monkeypatch.setattr` on module-level names, no mocking framework, no test classes (see `SP500 Predictor/tests/test_crypto_shadow_and_scripts.py` for the reference pattern).
- Cross-project imports of `SP500 Predictor/` (a directory with a space in its name) go through a lazy `sys.path.insert` loader function, mirroring `orchestrator.py:_load_async_telegram_notifier` (`orchestrator.py:2115-2122`) — never a top-level `import` of anything under that path.

---

## File Structure

- **Create** `market_sentiment_tool/backend/settlement.py` — pure P&L math + matching (no I/O), plus thin Supabase/Kalshi I/O wrappers and the async poll loop. One file because the I/O wrappers are each 3-5 lines that directly call the pure functions next to them; splitting further would just add import indirection for no testability gain.
- **Create** `market_sentiment_tool/backend/tests/__init__.py` — empty, makes the directory a package (already created; no test directory existed for this backend before).
- **Create** `market_sentiment_tool/backend/tests/test_settlement.py` — unit tests for everything in `settlement.py`.
- **Modify** `market_sentiment_tool/backend/orchestrator.py` — start the settlement poll loop from `run_crypto_services()`, and replace the duplicated P&L diff math in the M2M block (`orchestrator.py:3036-3038`) with a call to `settlement.compute_realized_pnl`, and fold settled trades' `realized_pnl` into the equity calc (`orchestrator.py:3052`).

---

## Task 1: Pure settlement math

**Files:**
- Create: `market_sentiment_tool/backend/settlement.py`
- Test: `market_sentiment_tool/backend/tests/test_settlement.py`

**Interfaces:**
- Produces: `compute_realized_pnl(entry_price: float, exit_price: float, qty: float, side: str) -> float`
- Produces: `match_kalshi_settlement_to_trade(settlement: dict, open_trades: list[dict]) -> dict | None`
- Produces: `settlement_realized_pnl(settlement: dict) -> float`

- [ ] **Step 1: Write the failing tests**

```python
# market_sentiment_tool/backend/tests/test_settlement.py
import pytest

from market_sentiment_tool.backend import settlement


def test_compute_realized_pnl_buy_side_profit():
    # Bought at 10, exit at 12, 5 contracts -> +10
    assert settlement.compute_realized_pnl(10.0, 12.0, 5, "BUY") == pytest.approx(10.0)


def test_compute_realized_pnl_sell_side_profit():
    # Sold at 10 (short), exit at 8, 5 contracts -> +10
    assert settlement.compute_realized_pnl(10.0, 8.0, 5, "SELL") == pytest.approx(10.0)


def test_compute_realized_pnl_is_case_insensitive_on_side():
    assert settlement.compute_realized_pnl(10.0, 12.0, 5, "buy") == pytest.approx(10.0)


def test_match_kalshi_settlement_to_trade_matches_on_ticker_and_open_status():
    open_trades = [
        {"id": "t1", "market_ticker": "BTC-24APR-100000", "status": "OPEN"},
        {"id": "t2", "market_ticker": "ETH-24APR-5000", "status": "OPEN"},
    ]
    settlement_row = {"ticker": "ETH-24APR-5000", "revenue": 250}
    matched = settlement.match_kalshi_settlement_to_trade(settlement_row, open_trades)
    assert matched["id"] == "t2"


def test_match_kalshi_settlement_to_trade_ignores_non_open_trades():
    open_trades = [{"id": "t1", "market_ticker": "BTC-24APR-100000", "status": "SETTLED"}]
    settlement_row = {"ticker": "BTC-24APR-100000", "revenue": 100}
    assert settlement.match_kalshi_settlement_to_trade(settlement_row, open_trades) is None


def test_match_kalshi_settlement_to_trade_returns_none_when_no_ticker():
    open_trades = [{"id": "t1", "market_ticker": "BTC-24APR-100000", "status": "OPEN"}]
    assert settlement.match_kalshi_settlement_to_trade({"revenue": 100}, open_trades) is None


def test_settlement_realized_pnl_converts_cents_to_dollars():
    assert settlement.settlement_realized_pnl({"ticker": "X", "revenue": 1250}) == pytest.approx(12.50)


def test_settlement_realized_pnl_handles_a_loss():
    assert settlement.settlement_realized_pnl({"ticker": "X", "revenue": -300}) == pytest.approx(-3.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: `ModuleNotFoundError: No module named 'market_sentiment_tool.backend.settlement'` (or collection error) — the module doesn't exist yet.

- [ ] **Step 3: Write the minimal implementation**

```python
# market_sentiment_tool/backend/settlement.py
"""
Settlement — turns Kalshi settlement payouts into realized P&L on `trades`
rows.

Pure math and matching logic live here with no I/O so they can be unit
tested without touching Supabase or the Kalshi API. The thin I/O wrapper
functions further down in this module call into these.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

TRADES_TABLE = "trades"


def compute_realized_pnl(entry_price: float, exit_price: float, qty: float, side: str) -> float:
    """Realized P&L for a closed position, sign-adjusted for side."""
    diff = exit_price - entry_price
    if side.upper() == "BUY":
        return diff * qty
    return -diff * qty


def match_kalshi_settlement_to_trade(
    settlement: dict[str, Any], open_trades: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """
    Find the open `trades` row a Kalshi settlement payload resolves.
    Matches on market_ticker against trades still in OPEN status; a
    settlement with no matching open trade (e.g. a position opened outside
    this system, or one already settled) returns None.
    """
    ticker = settlement.get("ticker")
    if not ticker:
        return None
    for trade in open_trades:
        if trade.get("market_ticker") == ticker and trade.get("status") == "OPEN":
            return trade
    return None


def settlement_realized_pnl(settlement: dict[str, Any]) -> float:
    """
    Realized P&L for a Kalshi settlement, in dollars. Kalshi's
    `/portfolio/settlements` reports `revenue` in cents (see
    KalshiPortfolio.get_portfolio_summary in SP500 Predictor/src/kalshi_portfolio.py,
    which does the same cents-to-dollars conversion).
    """
    return float(settlement.get("revenue", 0)) / 100.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/backend/settlement.py market_sentiment_tool/backend/tests/__init__.py market_sentiment_tool/backend/tests/test_settlement.py
git commit -m "feat: add pure settlement math and Kalshi settlement matching"
```

---

## Task 2: Supabase I/O wrappers for a settlement pass

**Files:**
- Modify: `market_sentiment_tool/backend/settlement.py`
- Test: `market_sentiment_tool/backend/tests/test_settlement.py`

**Interfaces:**
- Consumes: `match_kalshi_settlement_to_trade`, `settlement_realized_pnl` from Task 1
- Produces: `fetch_settleable_trades(supa) -> list[dict]`
- Produces: `apply_settlement(supa, trade: dict, realized_pnl: float) -> None`
- Produces: `run_settlement_pass(supa, kalshi) -> int` (returns count of trades settled)

- [ ] **Step 1: Write the failing tests**

Append to `market_sentiment_tool/backend/tests/test_settlement.py`:

```python
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def not_(self):
        return self

    def is_(self, *_a, **_kw):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSupabase:
    """Records every .table(name).update(...).eq("id", x).execute() call."""

    def __init__(self, open_trades):
        self._open_trades = open_trades
        self.updates: list[tuple[str, dict]] = []

    def table(self, name):
        assert name == settlement.TRADES_TABLE
        return _RecordingQuery(self)


class _RecordingQuery:
    def __init__(self, parent: "_FakeSupabase"):
        self._parent = parent
        self._pending_id = None

    def select(self, *_a, **_kw):
        return self

    def eq(self, field, value):
        if field == "id":
            self._pending_id = value
        return self

    def not_(self):
        return self

    def is_(self, *_a, **_kw):
        return self

    def update(self, payload):
        self._pending_payload = payload
        return self

    def execute(self):
        if hasattr(self, "_pending_payload"):
            self._parent.updates.append((self._pending_id, self._pending_payload))
            return _FakeResult(None)
        return _FakeResult(self._parent._open_trades)


class _FakeKalshi:
    def __init__(self, settlements):
        self._settlements = settlements

    def get_settlements(self, limit=100):
        return self._settlements


def test_fetch_settleable_trades_returns_open_trades_with_a_ticker():
    supa = _FakeSupabase(open_trades=[{"id": "t1", "market_ticker": "BTC-X", "status": "OPEN"}])
    result = settlement.fetch_settleable_trades(supa)
    assert result == [{"id": "t1", "market_ticker": "BTC-X", "status": "OPEN"}]


def test_apply_settlement_writes_settled_status_and_realized_pnl():
    supa = _FakeSupabase(open_trades=[])
    settlement.apply_settlement(supa, {"id": "t1"}, 12.5)
    assert supa.updates == [("t1", {"status": "SETTLED", "realized_pnl": 12.5, "unrealized_pnl": 0.0})]


def test_run_settlement_pass_matches_and_settles_one_trade():
    open_trades = [{"id": "t1", "market_ticker": "BTC-X", "status": "OPEN"}]
    supa = _FakeSupabase(open_trades=open_trades)
    kalshi = _FakeKalshi(settlements=[{"ticker": "BTC-X", "revenue": 500}])

    settled_count = settlement.run_settlement_pass(supa, kalshi)

    assert settled_count == 1
    assert supa.updates == [("t1", {"status": "SETTLED", "realized_pnl": 5.0, "unrealized_pnl": 0.0})]


def test_run_settlement_pass_skips_unmatched_settlements():
    open_trades = [{"id": "t1", "market_ticker": "BTC-X", "status": "OPEN"}]
    supa = _FakeSupabase(open_trades=open_trades)
    kalshi = _FakeKalshi(settlements=[{"ticker": "ETH-Y", "revenue": 500}])

    settled_count = settlement.run_settlement_pass(supa, kalshi)

    assert settled_count == 0
    assert supa.updates == []


def test_run_settlement_pass_returns_zero_with_no_open_trades():
    supa = _FakeSupabase(open_trades=[])
    kalshi = _FakeKalshi(settlements=[{"ticker": "BTC-X", "revenue": 500}])
    assert settlement.run_settlement_pass(supa, kalshi) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: `AttributeError: module 'market_sentiment_tool.backend.settlement' has no attribute 'fetch_settleable_trades'` (and the other two new functions)

- [ ] **Step 3: Write the minimal implementation**

Append to `market_sentiment_tool/backend/settlement.py`:

```python
def fetch_settleable_trades(supa) -> list[dict[str, Any]]:
    """Open trades that came from a Kalshi order (i.e. have a market_ticker)."""
    res = (
        supa.table(TRADES_TABLE)
        .select("*")
        .eq("status", "OPEN")
        .not_()
        .is_("market_ticker", "null")
        .execute()
    )
    return res.data or []


def apply_settlement(supa, trade: dict[str, Any], realized_pnl: float) -> None:
    supa.table(TRADES_TABLE).update(
        {
            "status": "SETTLED",
            "realized_pnl": realized_pnl,
            "unrealized_pnl": 0.0,
        }
    ).eq("id", trade["id"]).execute()


def run_settlement_pass(supa, kalshi) -> int:
    """
    One settlement pass: fetch open Kalshi-sourced trades, fetch recent
    Kalshi settlements, match them, and write realized P&L. Returns the
    number of trades settled.
    """
    open_trades = fetch_settleable_trades(supa)
    if not open_trades:
        return 0

    settled_count = 0
    for settlement_row in kalshi.get_settlements(limit=100):
        trade = match_kalshi_settlement_to_trade(settlement_row, open_trades)
        if trade is None:
            continue
        realized = settlement_realized_pnl(settlement_row)
        apply_settlement(supa, trade, realized)
        settled_count += 1
    return settled_count
```

Note: the real `supabase-py` query builder's `.not_()` takes no arguments and
returns a negated-filter builder whose next call (`.is_`) is negated — this
matches the library's actual chained-filter API (`supa.table(...).select("*").eq(...).not_.is_(...)`
in some client versions uses `.not_` as a property, not a method; verify
against the installed `supabase-py` version in
`market_sentiment_tool/backend/requirements.txt` before running this against
a real database, and adjust to `.not_.is_(...)` if the installed version
exposes it as a property rather than a callable). The fakes in the test
above implement `.not_()` as a method returning `self`, which is sufficient
for these unit tests either way since they don't exercise the real client.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/backend/settlement.py market_sentiment_tool/backend/tests/test_settlement.py
git commit -m "feat: add Supabase I/O wrappers for running a settlement pass"
```

---

## Task 3: Async settlement poll loop with a lazy KalshiPortfolio loader

**Files:**
- Modify: `market_sentiment_tool/backend/settlement.py`
- Test: `market_sentiment_tool/backend/tests/test_settlement.py`

**Interfaces:**
- Consumes: `run_settlement_pass` from Task 2
- Produces: `load_kalshi_portfolio_client() -> type` (returns the `KalshiPortfolio` class, imported lazily)
- Produces: `async def settlement_poll_loop(supa, interval_seconds: int = 300) -> None` (loops forever; test only the single-iteration body via a helper)
- Produces: `async def run_settlement_pass_once(supa) -> int` (one iteration: load client, run one pass, log the result) — this is what `settlement_poll_loop` calls in its `while True`, and what the test exercises directly instead of running an infinite loop

- [ ] **Step 1: Write the failing tests**

Append to `market_sentiment_tool/backend/tests/test_settlement.py`:

```python
import asyncio


def test_load_kalshi_portfolio_client_returns_the_class(monkeypatch):
    # Avoid requiring real Kalshi credentials in .env during this test:
    # patch the module-level loader's target instead of constructing a client.
    client_cls = settlement.load_kalshi_portfolio_client()
    assert client_cls.__name__ == "KalshiPortfolio"


def test_run_settlement_pass_once_uses_injected_client_and_supa(monkeypatch):
    open_trades = [{"id": "t1", "market_ticker": "BTC-X", "status": "OPEN"}]
    supa = _FakeSupabase(open_trades=open_trades)
    fake_kalshi_instance = _FakeKalshi(settlements=[{"ticker": "BTC-X", "revenue": 500}])

    monkeypatch.setattr(settlement, "load_kalshi_portfolio_client", lambda: lambda: fake_kalshi_instance)

    settled_count = asyncio.run(settlement.run_settlement_pass_once(supa))

    assert settled_count == 1
    assert supa.updates == [("t1", {"status": "SETTLED", "realized_pnl": 5.0, "unrealized_pnl": 0.0})]


def test_run_settlement_pass_once_swallows_client_construction_errors(monkeypatch):
    def _raise():
        raise ValueError("KALSHI_API_KEY_ID not found")

    monkeypatch.setattr(settlement, "load_kalshi_portfolio_client", lambda: _raise)
    supa = _FakeSupabase(open_trades=[])

    settled_count = asyncio.run(settlement.run_settlement_pass_once(supa))

    assert settled_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: `AttributeError: module 'market_sentiment_tool.backend.settlement' has no attribute 'load_kalshi_portfolio_client'`

- [ ] **Step 3: Write the minimal implementation**

Append to `market_sentiment_tool/backend/settlement.py`:

```python
def load_kalshi_portfolio_client():
    """
    Lazily import KalshiPortfolio from the sibling "SP500 Predictor" project.
    Mirrors orchestrator.py:_load_async_telegram_notifier, which does the
    same sys.path trick because that directory name has a space in it and
    can't be imported as a normal package.
    """
    import sys
    from pathlib import Path

    predictor_root = Path(__file__).resolve().parents[2] / "SP500 Predictor"
    predictor_root_text = str(predictor_root)
    if predictor_root_text not in sys.path:
        sys.path.insert(0, predictor_root_text)
    from src.kalshi_portfolio import KalshiPortfolio

    return KalshiPortfolio


async def run_settlement_pass_once(supa) -> int:
    """
    One settlement iteration: construct a KalshiPortfolio client and run a
    settlement pass. Client construction can fail if Kalshi credentials
    aren't configured (ValueError from KalshiPortfolio.__init__) -- that's
    logged and treated as "nothing settled this cycle" rather than crashing
    the poll loop.
    """
    try:
        kalshi_cls = load_kalshi_portfolio_client()
        kalshi = kalshi_cls()
    except Exception as exc:
        log.error("Settlement pass skipped: could not build Kalshi client: %s", exc)
        return 0

    try:
        return run_settlement_pass(supa, kalshi)
    except Exception as exc:
        log.error("Settlement pass failed: %s", exc)
        return 0


async def settlement_poll_loop(supa, interval_seconds: int = 300) -> None:
    """Background task: run a settlement pass every `interval_seconds`."""
    import asyncio

    log.info("Settlement poll loop starting (interval=%ds)…", interval_seconds)
    while True:
        settled_count = await run_settlement_pass_once(supa)
        if settled_count:
            log.info("Settlement pass: %d trade(s) settled.", settled_count)
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/backend/settlement.py market_sentiment_tool/backend/tests/test_settlement.py
git commit -m "feat: add async settlement poll loop with lazy KalshiPortfolio loader"
```

---

## Task 4: Wire the settlement loop into the live crypto worker

**Files:**
- Modify: `market_sentiment_tool/backend/orchestrator.py:2846-2860` (`run_crypto_services`)

**Interfaces:**
- Consumes: `settlement.settlement_poll_loop(supa, interval_seconds)` from Task 3, and the module-level `supa` client already initialized elsewhere in `orchestrator.py` (set by `initialize_runtime_clients`, called inside `crypto_worker_loop`)

This task has no new unit test of its own — `settlement_poll_loop`'s behavior is already covered by Task 3's tests via `run_settlement_pass_once`. This step is pure wiring, verified by the manual smoke check in Step 3.

- [ ] **Step 1: Add the import**

At the top of `market_sentiment_tool/backend/orchestrator.py`, alongside the existing `market_sentiment_tool.backend.*` imports (near line 45-57):

```python
from market_sentiment_tool.backend import settlement
```

- [ ] **Step 2: Start the poll loop from `run_crypto_services`**

In `market_sentiment_tool/backend/orchestrator.py`, `run_crypto_services()` currently reads (lines 2846-2860):

```python
async def run_crypto_services() -> None:
    notifier = None
    telegram_task = None
    try:
        TelegramNotifier = _load_async_telegram_notifier()
        notifier = TelegramNotifier()
        if notifier.is_enabled():
            await notifier.start()
            telegram_task = asyncio.create_task(notifier.run_polling(), name="telegram-operator-plane")
            log_to_supabase("orchestrator.crypto_runtime", "Telegram operator plane started.", level="INFO")
    except Exception as exc:
        notifier = None
        telegram_task = None
        log.error("Failed to start Telegram operator plane: %s", exc)
        log_to_supabase("orchestrator.crypto_runtime", f"Telegram operator plane failed to start: {exc}", level="ERROR")
```

Change it to also start the settlement loop as a background task, using the same `asyncio.create_task` pattern already used for the Telegram task:

```python
async def run_crypto_services() -> None:
    notifier = None
    telegram_task = None
    try:
        TelegramNotifier = _load_async_telegram_notifier()
        notifier = TelegramNotifier()
        if notifier.is_enabled():
            await notifier.start()
            telegram_task = asyncio.create_task(notifier.run_polling(), name="telegram-operator-plane")
            log_to_supabase("orchestrator.crypto_runtime", "Telegram operator plane started.", level="INFO")
    except Exception as exc:
        notifier = None
        telegram_task = None
        log.error("Failed to start Telegram operator plane: %s", exc)
        log_to_supabase("orchestrator.crypto_runtime", f"Telegram operator plane failed to start: {exc}", level="ERROR")

    settlement_task = None
    if supa is not None:
        settlement_task = asyncio.create_task(
            settlement.settlement_poll_loop(supa, interval_seconds=300),
            name="settlement-poll-loop",
        )
        log_to_supabase("orchestrator.crypto_runtime", "Settlement poll loop started.", level="INFO")
    else:
        log.error("Settlement poll loop not started: Supabase client is not initialized.")
```

`supa` is the module-level `SupabaseClient | None` declared at `orchestrator.py:149` and populated by `initialize_runtime_clients(require_supabase=True, ...)`, which `crypto_worker_loop` already calls before `run_crypto_services` reaches this point in the real startup sequence (see `orchestrator.py:3083`) — so by the time this code runs, `supa` is set.

- [ ] **Step 3: Manual smoke check (no live trading required)**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -c "from market_sentiment_tool.backend import orchestrator; print('import OK')"`
Expected: `import OK` — confirms the new import and the edited function don't have a syntax or circular-import error. (A full run of `run_crypto_services()` needs live Kalshi WS + Supabase credentials and is out of scope for this smoke check; Task 5's tests plus this import check are the verification for this task.)

- [ ] **Step 4: Commit**

```bash
git add market_sentiment_tool/backend/orchestrator.py
git commit -m "feat: start the settlement poll loop alongside the crypto worker"
```

---

## Task 5: Reuse the settlement math in the M2M loop and fold realized P&L into equity

**Files:**
- Modify: `market_sentiment_tool/backend/orchestrator.py:2996-3052` (the M2M block inside `heartbeat_loop`)
- Test: `market_sentiment_tool/backend/tests/test_orchestrator_equity.py` (new file — the first test for `heartbeat_loop`'s equity math)

**Interfaces:**
- Consumes: `settlement.compute_realized_pnl` from Task 1

This closes the loop the roadmap's Context section calls out: today `total_equity = base_equity + unrealized_pnl` only ever sums *unrealized* P&L from OPEN trades, so a trade that settles (Task 1-4) never moves the needle on displayed equity even though real money changed hands.

- [ ] **Step 1: Write the failing test**

```python
# market_sentiment_tool/backend/tests/test_orchestrator_equity.py
import pytest

from market_sentiment_tool.backend import orchestrator


def test_compute_total_equity_sums_base_unrealized_and_realized():
    # base 100000, one OPEN trade up $10 unrealized, one SETTLED trade that
    # locked in $25 realized -> 100000 + 10 + 25
    total = orchestrator.compute_total_equity(
        base_equity=100000.0,
        unrealized_pnl=10.0,
        settled_trades=[{"realized_pnl": 25.0}, {"realized_pnl": None}],
    )
    assert total == pytest.approx(100035.0)


def test_compute_total_equity_with_no_settled_trades():
    assert orchestrator.compute_total_equity(100000.0, 0.0, []) == pytest.approx(100000.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_orchestrator_equity.py -v`
Expected: `AttributeError: module 'market_sentiment_tool.backend.orchestrator' has no attribute 'compute_total_equity'`

- [ ] **Step 3: Extract `compute_total_equity` and use it, reusing `settlement.compute_realized_pnl` for the M2M diff**

Add this small function near the top of `market_sentiment_tool/backend/orchestrator.py`, close to the other small helpers (e.g. right after `_load_async_telegram_notifier`, or any existing helper cluster — exact placement doesn't matter since it's a standalone pure function):

```python
def compute_total_equity(base_equity: float, unrealized_pnl: float, settled_trades: list[dict]) -> float:
    """
    Total displayed equity = base + unrealized P&L on OPEN trades + realized
    P&L already locked in by SETTLED trades. `settled_trades` rows with a
    null realized_pnl (shouldn't happen once Task 1-4 land, but guards
    against a partially-migrated row) contribute 0.
    """
    realized_total = sum(t.get("realized_pnl") or 0.0 for t in settled_trades)
    return base_equity + unrealized_pnl + realized_total
```

Then change the M2M block (`orchestrator.py:3017-3052`) from:

```python
            unrealized_pnl = 0.0
            base_equity = 100000.0  # Would fetch from Alpaca in prod

            if supa:
                try:
                    open_trades_res = supa.table("trades").select("*").eq("status", "OPEN").execute()
                    open_trades = open_trades_res.data or []
                    
                    for row in open_trades:
                        pos_sym = row["symbol"]
                        pos_qty = float(row["qty"])
                        pos_side = row["side"].upper()
                        entry = float(row.get("entry_price") or row.get("execution_price") or 0.0)
                        
                        # Get latest price
                        live_price = entry
                        if pos_sym in snapshot:
                            live_price = float(snapshot[pos_sym]["price"])
                            
                        # Compute PnL
                        diff = live_price - entry
                        u_pnl = (diff * pos_qty) if pos_side == "BUY" else (-diff * pos_qty)
                        unrealized_pnl += u_pnl
                        
                        # Update the specific trade row so UI ActivePositions table updates
                        supa.table("trades").update({
                            "unrealized_pnl": round(u_pnl, 2),
                            # Optional: could update current_price but frontend might not need it
                        }).eq("id", row["id"]).execute()
                        
                        log.debug(f"M2M: {pos_sym} {pos_side} {pos_qty}x | Entry: ${entry:.2f} Live: ${live_price:.2f} | PnL: ${u_pnl:.2f}")

                except Exception as e:
                    log.error("Live M2M PnL update failed: %s", e)

            total_equity = base_equity + unrealized_pnl
```

to:

```python
            unrealized_pnl = 0.0
            base_equity = 100000.0  # Would fetch from Alpaca in prod
            settled_trades: list[dict] = []

            if supa:
                try:
                    open_trades_res = supa.table("trades").select("*").eq("status", "OPEN").execute()
                    open_trades = open_trades_res.data or []
                    
                    for row in open_trades:
                        pos_sym = row["symbol"]
                        pos_qty = float(row["qty"])
                        pos_side = row["side"].upper()
                        entry = float(row.get("entry_price") or row.get("execution_price") or 0.0)
                        
                        # Get latest price
                        live_price = entry
                        if pos_sym in snapshot:
                            live_price = float(snapshot[pos_sym]["price"])
                            
                        # Compute PnL
                        u_pnl = settlement.compute_realized_pnl(entry, live_price, pos_qty, pos_side)
                        unrealized_pnl += u_pnl
                        
                        # Update the specific trade row so UI ActivePositions table updates
                        supa.table("trades").update({
                            "unrealized_pnl": round(u_pnl, 2),
                            # Optional: could update current_price but frontend might not need it
                        }).eq("id", row["id"]).execute()
                        
                        log.debug(f"M2M: {pos_sym} {pos_side} {pos_qty}x | Entry: ${entry:.2f} Live: ${live_price:.2f} | PnL: ${u_pnl:.2f}")

                    settled_res = supa.table("trades").select("realized_pnl").eq("status", "SETTLED").execute()
                    settled_trades = settled_res.data or []

                except Exception as e:
                    log.error("Live M2M PnL update failed: %s", e)

            total_equity = compute_total_equity(base_equity, unrealized_pnl, settled_trades)
```

(This also fixes a naming/formula duplication the roadmap flagged: the M2M loop had its own inline copy of the same `diff * qty` sign logic as `settlement.compute_realized_pnl` and `mcp_server.close_position` — now there's one implementation.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest market_sentiment_tool/backend/tests/test_orchestrator_equity.py market_sentiment_tool/backend/tests/test_settlement.py -v`
Expected: 19 passed

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && python3 -m pytest "SP500 Predictor/tests/" market_sentiment_tool/backend/tests/ -v`
Expected: all pass (same pass count as before this plan, plus the 19 new tests)

- [ ] **Step 6: Commit**

```bash
git add market_sentiment_tool/backend/orchestrator.py market_sentiment_tool/backend/tests/test_orchestrator_equity.py
git commit -m "feat: fold settled trades' realized P&L into total equity, reuse settlement math in M2M loop"
```

---

## Self-Review

**1. Spec coverage against roadmap Phase 1** ([2026-09-23-algo-trade-hub-roadmap.md](2026-09-23-algo-trade-hub-roadmap.md), "Phase 1 — Settlement + realized-P&L writer"):
- "Move `close_position()` out from after the blocking `mcp.run()` call" — already done directly in the prior session (not part of this plan's tasks; see git history on `market_sentiment_tool/backend/mcp_server.py`).
- "Add a settlement job... that polls open Kalshi positions... and writes `realized_pnl` + `status='SETTLED'`" — Tasks 1-4.
- "Update the equities orchestrator's portfolio equity calc... to also account for settled trades' realized P&L" — Task 5.
- Gap: the roadmap doesn't specify whether `close_position` (manual MCP tool) and the new automatic `settlement_poll_loop` (Task 3-4) could race on the same trade. They can't corrupt data (both are idempotent updates keyed by trade id, and `run_settlement_pass` only touches trades still in `OPEN` status), but this is worth a one-line note rather than a new task: if `close_position` is called manually on a trade in the same window the poll loop also settles it, whichever runs second will simply find the trade no longer `OPEN` (via `fetch_settleable_trades`'s status filter, or `close_position`'s own `if trade.get("status") != "OPEN"` guard) and no-op. No code change needed.

**2. Placeholder scan:** No TBD/TODO, no "add error handling" hand-waves, no "similar to Task N" — Task 5's diff is written out in full precisely so it doesn't need to reference Task 1-4's code from memory.

**3. Type consistency:** `compute_realized_pnl(entry_price, exit_price, qty, side)` is defined once in Task 1 and called with the same positional order in Task 5's M2M rewrite. `run_settlement_pass(supa, kalshi)` (Task 2) is called from `run_settlement_pass_once(supa)` (Task 3) with the same two arguments. `settlement_poll_loop(supa, interval_seconds)` (Task 3) is called from `run_crypto_services()` (Task 4) with `interval_seconds=300` as a keyword, matching the signature's default-having parameter name.

**Known open question flagged for whoever executes Task 2:** the exact chained-filter method name for a `NOT NULL` filter differs across `supabase-py` versions (`.not_.is_(...)` as a property vs `.not_().is_(...)` as a method). The plan calls this out inline in Task 2 rather than guessing — check the installed version (`pip show supabase` inside the backend's venv) before running `fetch_settleable_trades` against a real database; the unit tests pass regardless since the fakes implement whichever shape is called.

---

## What's Deliberately Out of Scope Here

Per the writing-plans skill's scope check, this plan covers exactly one independently-shippable subsystem (Phase 1 of the roadmap). The other 9 phases in [2026-09-23-algo-trade-hub-roadmap.md](2026-09-23-algo-trade-hub-roadmap.md) — track-record ledger, config centralization, backtester rewiring, broader TDD coverage, batched inference, model registry, risk controls, multi-market config, frontend cleanup — each need their own plan doc in this same `docs/superpowers/plans/` folder, written the same way, when work reaches them. Phase 2 (track-record ledger) depends on this plan's settled rows existing, so it's the natural next one to write.

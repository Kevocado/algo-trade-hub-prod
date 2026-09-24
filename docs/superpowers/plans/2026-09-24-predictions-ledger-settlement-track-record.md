# Predictions Ledger + Settlement by Market Result + Track Record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every engine output as a prediction row, settle those rows against Kalshi's public market results on an hourly cron, and maintain a per-engine track record (calibration buckets, Brier vs market, promotion-gate status) — rollout step 2 of the prediction-scope redesign.

**Architecture:** Three small modules with a strict pure/IO split. `tradehub/predictions.py` validates and writes prediction rows. `tradehub/settlement.py` holds pure settlement math (Brier, market-result parsing, settle payload) plus thin Supabase wrappers and a `run_settlement_pass` driven by an injected `fetch_market` callable. `tradehub/track_record.py` holds pure calibration/gate math plus a `refresh_track_record` upsert. `tradehub/scripts/settle_predictions.py` is the cron entrypoint that wires the real clients. There is no always-on loop.

**Tech Stack:** Python 3.11+, `pytest` + `monkeypatch` (house style: plain functions, no mocking framework, no test classes), `supabase-py`, `requests` (Kalshi public market endpoint).

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) (rollout step 2; sections 4.4, 4.5, 6). This plan revises [2026-09-23-settlement-realized-pnl.md](2026-09-23-settlement-realized-pnl.md): it keeps that plan's pure-math tasks (`compute_realized_pnl`, matching discipline, fake-based TDD style), replaces the always-on poll loop and crypto-worker wiring (old Tasks 3-4) with a cron entrypoint plus settlement by market result, drops the M2M/orchestrator edit (old Task 5 — the spec removes the equities swarm and the always-on worker), and adds the predictions ledger and track record the old plan never had.

## Global Constraints

- `EXECUTION_MODE` stays `suggest`: this plan builds no order-placement path and no live-execution wiring.
- Predictions settle against the Kalshi market result (`GET /markets/{ticker}` → `status: finalized`, `result: yes|no`), independent of position ownership — never against `get_settlements()` (spec section 4.5).
- Each prediction settles independently; no netting across predictions.
- Never edit an existing migration file; schema changes go in a new timestamped migration only.
- New tables follow the existing RLS pattern (`*_owner` policy on `auth.uid() = user_id`).
- House test style: plain functions, `monkeypatch.setattr` on module-level names, no mocking framework, no test classes.
- Every commit carries the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run everything from the repo root with the project venv: `.venv/bin/python` (Python 3.12, installed from `pyproject.toml` with `--extra dev --extra scanner`). Plain `pytest` picks up `pyproject.toml` (`testpaths = ["tests"]`, `pythonpath = ["."]`).
- Prefix every test run with the process-only env var `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` — the local `.env` has no usable value for it and a module-level Supabase client otherwise aborts collection. Never write it into a file.
- Prerequisite (done): the repo-cleanup plan is merged — code lives in the `tradehub/` package, tests in root `tests/`.

## Review Focus

- A Kalshi market canceled before settlement must not sit `OPEN` forever and must never settle with a fabricated result — expect `CANCELED`. (Test in Task 4.)
- `fetch_market` reuses `kalshi_feed.py`'s existing `KALSHI_API_URL` (hardcoded prod elections base), deliberately *not* `kalshi_portfolio.py`'s `KALSHI_API_BASE` (which defaults to demo) — so the fetch base always agrees with the base the market tickers were listed from. If a ticker is unknown or the environments ever disagree, every fetch 404s — expect the pass to skip those tickers and the `checked`/`settled`/`skipped` counts to make that visible. (Test in Task 4.)
- The hourly cron must never settle the same prediction twice — expect a second pass over an already-settled row to be a no-op. (Test in Task 4.)
- A prediction recorded without `market_prob` must still settle; its `market_brier` stays null and the gate reports missing market Brier instead of crashing on `None`. (Tests in Tasks 3 and 5.)
- Bucket boundaries must be deterministic at exactly 0.5 and 1.0 — expect `bucketize(0.5) == "50-60"` and `bucketize(1.0) == "90-100"`. (Test in Task 5.)

---

## File Structure

- **Create** `market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql` — `predictions` + `track_record` tables, idempotent, RLS like the existing migrations.
- **Create** `tradehub/predictions.py` — pure `build_prediction_row` validation plus thin `record_prediction` / `record_predictions` Supabase wrappers.
- **Create** `tradehub/settlement.py` — pure math (`compute_realized_pnl`, `brier_score`, `parse_market_result`, `is_market_canceled`, `settle_prediction_row`) plus thin I/O (`fetch_open_predictions`, `apply_prediction_settlement`, `run_settlement_pass`).
- **Modify** `tradehub/core/kalshi_feed.py` — add `fetch_market(ticker)` reusing the module's existing `KALSHI_API_URL` constant, so the fetch base always agrees with the base the market tickers were listed from.
- **Create** `tradehub/track_record.py` — pure `bucketize`, `compute_calibration`, `compute_engine_summary`, `check_promotion_gate` plus `refresh_track_record` upsert.
- **Create** `tradehub/scripts/settle_predictions.py` — cron entrypoint wiring the real clients.
- **Tests:** `tests/test_predictions.py`, `tests/test_settlement.py`, `tests/test_track_record.py`, `tests/test_settle_predictions.py`; one structural assertion appended to `tests/test_repo_layout.py`.

## Task 1: Predictions ledger + track_record migrations

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql`
- Modify: `tests/test_repo_layout.py` (append one structural assertion)
- Test: the appended assertion in `tests/test_repo_layout.py`

**Interfaces:**
- Produces: `predictions` table — `id, market_ticker, our_prob, market_prob, engine, engine_version, as_of, status, result, brier, market_brier, raw_payload, created_at, user_id`
- Produces: `track_record` table — `engine` (PK), `engine_version, n_settled, brier_ours, brier_market, cal_buckets, max_cal_dev, gate_status, updated_at, user_id`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repo_layout.py`:

```python
def test_predictions_ledger_migration_defines_both_tables():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql"
    assert path.is_file(), "predictions ledger migration is missing"
    sql = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS predictions" in sql
    assert "CREATE TABLE IF NOT EXISTS track_record" in sql
    assert '"predictions_owner"' in sql
    assert '"track_record_owner"' in sql
    for column in ("market_ticker", "our_prob", "as_of", "status", "brier"):
        assert column in sql, f"predictions table missing column {column}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_predictions_ledger_migration_defines_both_tables -v`
Expected: FAIL — the migration file does not exist yet.

- [ ] **Step 3: Write the migration**

```sql
-- Predictions ledger + per-engine track record (rollout step 2 of the
-- prediction-scope redesign).
--
-- Idempotent: safe to re-run via `supabase db push` or the SQL editor,
-- following the pattern of 20260416000001_kalshi_edges_and_macro.sql.

-- Every engine output, whether or not anyone trades on it (spec section 4.4).
-- Rows start OPEN; the settlement job flips them to SETTLED (or CANCELED)
-- against the Kalshi market result.
CREATE TABLE IF NOT EXISTS predictions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  market_ticker  text NOT NULL,
  our_prob       numeric(5,4) NOT NULL CHECK (our_prob >= 0 AND our_prob <= 1),
  market_prob    numeric(5,4) CHECK (market_prob IS NULL OR (market_prob >= 0 AND market_prob <= 1)),
  engine         text NOT NULL,
  engine_version text NOT NULL DEFAULT 'v0',
  as_of          timestamptz NOT NULL,
  status         text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'SETTLED', 'CANCELED')),
  result         text CHECK (result IN ('yes', 'no')),
  brier          numeric(6,5),
  market_brier   numeric(6,5),
  raw_payload    jsonb,
  created_at     timestamptz DEFAULT now(),
  user_id        uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS predictions_engine_status_idx ON predictions (engine, status);
CREATE INDEX IF NOT EXISTS predictions_ticker_idx ON predictions (market_ticker);
ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "predictions_owner" ON predictions;
CREATE POLICY "predictions_owner" ON predictions FOR ALL
  USING (auth.uid() = user_id);

-- Per-engine rollup the Track Record UI reads (spec sections 4.5 and 6).
-- Recomputed by the settlement cron job after every pass.
CREATE TABLE IF NOT EXISTS track_record (
  engine         text PRIMARY KEY,
  engine_version text NOT NULL DEFAULT 'v0',
  n_settled      integer NOT NULL DEFAULT 0,
  brier_ours     numeric(6,5),
  brier_market   numeric(6,5),
  cal_buckets    jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_cal_dev    numeric(5,4),
  gate_status    text NOT NULL DEFAULT 'SHADOW' CHECK (gate_status IN ('SHADOW', 'PROMOTED', 'DEMOTED')),
  updated_at     timestamptz DEFAULT now(),
  user_id        uuid REFERENCES auth.users(id)
);
ALTER TABLE track_record ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "track_record_owner" ON track_record;
CREATE POLICY "track_record_owner" ON track_record FOR ALL
  USING (auth.uid() = user_id);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -v`
Expected: all pass, including the new assertion.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql tests/test_repo_layout.py
git commit -m "feat: add predictions ledger and track_record migrations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Note: applying the migration to Supabase (`supabase db push` or the SQL editor) is a manual deploy step for Kevin — it is not run by this plan's tests.

---

## Task 2: Prediction writer (`tradehub/predictions.py`)

**Files:**
- Create: `tradehub/predictions.py`
- Test: `tests/test_predictions.py`

**Interfaces:**
- Produces: `build_prediction_row(*, market_ticker: str, our_prob: float, market_prob: float | None, engine: str, as_of: datetime, engine_version: str = "v0", raw_payload: dict | None = None) -> dict`
- Produces: `record_prediction(supa, row: dict) -> dict` (inserts one row, returns the inserted row)
- Produces: `record_predictions(supa, rows: list[dict]) -> list[dict]` (batch insert; empty list is a no-op returning `[]`)
- Consumes: `predictions` table from Task 1.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_predictions.py
from datetime import datetime, timezone

import pytest

from tradehub import predictions


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, parent):
        self._parent = parent

    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        self._parent.inserts.extend(rows)
        return self

    def execute(self):
        return _FakeResult(list(self._parent.inserts))


class _FakeSupa:
    def __init__(self):
        self.inserts: list = []
        self.tables: list = []

    def table(self, name):
        self.tables.append(name)
        assert name == predictions.PREDICTIONS_TABLE
        return _FakeTable(self)


def _row(**overrides):
    base = dict(
        market_ticker="KXHIGHNY-25SEP26-T70",
        our_prob=0.62,
        market_prob=0.55,
        engine="weather",
        as_of=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return predictions.build_prediction_row(**base)


def test_build_prediction_row_happy_path():
    row = _row()
    assert row["market_ticker"] == "KXHIGHNY-25SEP26-T70"
    assert row["our_prob"] == pytest.approx(0.62)
    assert row["market_prob"] == pytest.approx(0.55)
    assert row["engine"] == "weather"
    assert row["engine_version"] == "v0"
    assert row["status"] == "OPEN"
    assert row["as_of"] == "2026-09-24T12:00:00+00:00"


def test_build_prediction_row_rejects_out_of_range_prob():
    with pytest.raises(ValueError):
        _row(our_prob=1.5)
    with pytest.raises(ValueError):
        _row(our_prob=-0.1)
    with pytest.raises(ValueError):
        _row(market_prob=2.0)


def test_build_prediction_row_allows_missing_market_prob():
    assert _row(market_prob=None)["market_prob"] is None


def test_build_prediction_row_rejects_empty_ticker_and_engine():
    with pytest.raises(ValueError):
        _row(market_ticker="  ")
    with pytest.raises(ValueError):
        _row(engine="")


def test_build_prediction_row_rounds_probs_to_4dp():
    assert _row(our_prob=0.123456)["our_prob"] == pytest.approx(0.1235)


def test_record_prediction_inserts_one_row():
    supa = _FakeSupa()
    row = _row()
    inserted = predictions.record_prediction(supa, row)
    assert supa.tables == ["predictions"]
    assert supa.inserts == [row]
    assert inserted == row


def test_record_predictions_empty_list_is_noop():
    supa = _FakeSupa()
    assert predictions.record_predictions(supa, []) == []
    assert supa.inserts == []
    assert supa.tables == []


def test_record_predictions_batch_inserts():
    supa = _FakeSupa()
    rows = [_row(), _row(market_ticker="KXAAAGAS-26SEP26-B3.50")]
    out = predictions.record_predictions(supa, rows)
    assert len(out) == 2
    assert supa.tables == ["predictions"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_predictions.py -v`
Expected: `ModuleNotFoundError: No module named 'tradehub.predictions'` (or collection error).

- [ ] **Step 3: Write the minimal implementation**

```python
# tradehub/predictions.py
"""Predictions ledger writer.

Every engine output becomes a row in the `predictions` Supabase table,
whether or not anyone trades on it (spec section 4.4). The settlement job
(tradehub/settlement.py) later flips rows to SETTLED against the Kalshi
market result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

PREDICTIONS_TABLE = "predictions"


def build_prediction_row(
    *,
    market_ticker: str,
    our_prob: float,
    market_prob: float | None,
    engine: str,
    as_of: datetime,
    engine_version: str = "v0",
    raw_payload: dict | None = None,
) -> dict[str, Any]:
    """Validate engine output and build the `predictions` insert payload."""
    if not market_ticker or not market_ticker.strip():
        raise ValueError("market_ticker must be a non-empty string")
    if not engine or not engine.strip():
        raise ValueError("engine must be a non-empty string")
    our_prob = float(our_prob)
    if not 0.0 <= our_prob <= 1.0:
        raise ValueError(f"our_prob must be in [0, 1], got {our_prob}")
    if market_prob is not None:
        market_prob = float(market_prob)
        if not 0.0 <= market_prob <= 1.0:
            raise ValueError(f"market_prob must be in [0, 1] or None, got {market_prob}")
    if not isinstance(as_of, datetime):
        raise ValueError("as_of must be a datetime")
    return {
        "market_ticker": market_ticker.strip(),
        "our_prob": round(our_prob, 4),
        "market_prob": round(market_prob, 4) if market_prob is not None else None,
        "engine": engine.strip(),
        "engine_version": engine_version,
        "as_of": as_of.isoformat(),
        "status": "OPEN",
        "raw_payload": raw_payload or {},
    }


def record_prediction(supa, row: dict[str, Any]) -> dict[str, Any]:
    """Insert one prediction row; returns the inserted row."""
    res = supa.table(PREDICTIONS_TABLE).insert(row).execute()
    data = res.data or []
    return data[0] if data else {}


def record_predictions(supa, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch-insert prediction rows; an empty list is a no-op."""
    if not rows:
        return []
    res = supa.table(PREDICTIONS_TABLE).insert(rows).execute()
    return res.data or []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_predictions.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tradehub/predictions.py tests/test_predictions.py
git commit -m "feat: add predictions ledger writer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Settlement math (`tradehub/settlement.py`, pure functions)

**Files:**
- Create: `tradehub/settlement.py` (pure half; I/O wrapper `apply_prediction_settlement` and `run_settlement_pass` land in Task 4)
- Test: `tests/test_settlement.py` (pure tests land here; pass tests in Task 4)

**Interfaces (all pure):**
- Produces: `compute_realized_pnl(qty: int, buy_price: float, settle_price: float, fees_cents: int = 0) -> float` — realized dollar P&L for one settled position: `(settle_price - buy_price) * qty - fees_cents / 100`.
- Produces: `brier_score(prob: float, outcome: int) -> float` — `(prob - outcome) ** 2`.
- Produces: `parse_market_result(market: dict) -> tuple[str, int | None]` — maps `{"market": {"status", "result"}}` to `(disposition, outcome)` where disposition is `"OPEN"` / `"SETTLED"` / `"CANCELED"` and outcome is `1`/`0`/`None`:
  - status `"finalized"` + result `"yes"` → `("SETTLED", 1)`; `"no"` → `("SETTLED", 0)`
  - status `"finalized"` + result `null`/`""`/`"canceled"` (key present, non-binary) → `("CANCELED", None)` — voided market, never fabricate a yes/no
  - status `"finalized"` + result key missing → `("OPEN", None)` (malformed payload; retried next pass)
  - status `"active"`, `"determined"`, or any other value → `("OPEN", None)`
  - malformed market payloads (non-dict, missing `market`/`status`) → `("OPEN", None)` — never settle on what we cannot parse.
- Produces: `is_market_canceled(market: dict) -> bool` — `True` iff `parse_market_result(market)[0] == "CANCELED"`.
- Produces: `settle_prediction_row(row: dict, market: dict) -> dict | None` — builds the DB update payload for one prediction row against a fetched market dict; returns `None` when the market is still open. On settle: `{"id", "status": "SETTLED", "result": "yes"|"no", "brier", "market_brier" (null when `market_prob` is None), "raw_payload"}`. On cancel: `{"id", "status": "CANCELED"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settlement.py
import pytest

from tradehub import settlement


def test_compute_realized_pnl_long_winner():
    # 10 contracts bought at 55c, settled at $1.00, 10c total fees.
    assert settlement.compute_realized_pnl(10, 0.55, 1.0, fees_cents=10) == pytest.approx(4.40)


def test_compute_realized_pnl_short_loser():
    # Short 5 contracts at 40c, settles YES at $1.00: loss.
    assert settlement.compute_realized_pnl(-5, 0.40, 1.0) == pytest.approx(-3.00)


def test_compute_realized_pnl_zero_qty():
    assert settlement.compute_realized_pnl(0, 0.50, 1.0, fees_cents=7) == pytest.approx(-0.07)


def test_brier_score_perfect_and_worst():
    assert settlement.brier_score(1.0, 1) == pytest.approx(0.0)
    assert settlement.brier_score(0.0, 1) == pytest.approx(1.0)
    assert settlement.brier_score(0.7, 1) == pytest.approx(0.09)


def test_parse_market_result_finalized_yes():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "yes"}}) == ("SETTLED", 1)


def test_parse_market_result_finalized_no():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "no"}}) == ("SETTLED", 0)


def test_parse_market_result_active_and_determined_are_open():
    for status in ("active", "determined", "paused", "unknown"):
        assert settlement.parse_market_result({"market": {"status": status, "result": None}}) == ("OPEN", None)


def test_parse_market_result_canceled_outcomes():
    for result in (None, "", "canceled"):
        payload = {"market": {"status": "finalized", "result": result}}
        assert settlement.parse_market_result(payload) == ("CANCELED", None)
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": None}}) is True
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": "yes"}}) is False


def test_parse_market_result_malformed_is_open_not_settled():
    for payload in ({}, {"market": None}, {"market": {"status": "finalized"}}, "nope", None):
        assert settlement.parse_market_result(payload) == ("OPEN", None)


def test_settle_prediction_row_settles_and_scores_both_briers():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": "yes"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["id"] == "abc"
    assert update["status"] == "SETTLED"
    assert update["result"] == "yes"
    assert update["brier"] == pytest.approx(0.09)
    assert update["market_brier"] == pytest.approx(0.25)


def test_settle_prediction_row_missing_market_prob_gives_null_market_brier():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": None}
    market = {"market": {"status": "finalized", "result": "no"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["status"] == "SETTLED"
    assert update["result"] == "no"
    assert update["brier"] == pytest.approx(0.49)
    assert update["market_brier"] is None


def test_settle_prediction_row_open_market_returns_none():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    assert settlement.settle_prediction_row(row, {"market": {"status": "active", "result": None}}) is None


def test_settle_prediction_row_canceled_marks_canceled_without_fabricating_result():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": None}}
    update = settlement.settle_prediction_row(row, market)
    assert update == {"id": "abc", "status": "CANCELED"}
    assert "result" not in update and "brier" not in update
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v`
Expected: `ModuleNotFoundError: No module named 'tradehub.settlement'` (or collection error).

- [ ] **Step 3: Write the minimal implementation**

```python
# tradehub/settlement.py
"""Settle `predictions` rows against Kalshi public market results.

Pure math here; Supabase/Kalshi I/O is injected or isolated in thin
wrappers so the settlement rules are unit-testable. Predictions settle
against the Kalshi market result (spec section 4.5) — never against the
portfolio settlement history, which covers only owned positions.
"""

from __future__ import annotations

from typing import Any

PREDICTIONS_TABLE = "predictions"
TRACK_RECORD_TABLE = "track_record"

OPEN = "OPEN"
SETTLED = "SETTLED"
CANCELED = "CANCELED"


def compute_realized_pnl(qty: int, buy_price: float, settle_price: float, fees_cents: int = 0) -> float:
    """Realized dollar P&L for one settled position: (settle - buy) * qty minus fees."""
    return (settle_price - buy_price) * qty - fees_cents / 100.0


def brier_score(prob: float, outcome: int) -> float:
    """Brier score for a binary prediction: (prob - outcome) ** 2."""
    return (prob - outcome) ** 2


def parse_market_result(market: Any) -> tuple[str, int | None]:
    """Map a Kalshi `GET /markets/{ticker}` payload to (disposition, outcome).

    Disposition is OPEN, SETTLED, or CANCELED; outcome is 1/0/None.
    Anything malformed or ambiguous returns ("OPEN", None) — never settle
    on what we cannot parse. A finalized market whose result key is missing
    is malformed (stays OPEN, retried next pass); a finalized market with a
    present-but-non-binary result (null, "", "canceled", ...) was voided and
    is CANCELED — we never fabricate a yes/no.
    """
    try:
        inner = market["market"]
        status = inner["status"]
        result = inner.get("result")
    except (TypeError, KeyError, AttributeError):
        return (OPEN, None)
    if status == "finalized":
        if result == "yes":
            return (SETTLED, 1)
        if result == "no":
            return (SETTLED, 0)
        if "result" in inner:
            return (CANCELED, None)
        return (OPEN, None)
    return (OPEN, None)


def is_market_canceled(market: Any) -> bool:
    """True iff the market was finalized without a yes/no result."""
    return parse_market_result(market)[0] == CANCELED


def settle_prediction_row(row: dict[str, Any], market: Any) -> dict[str, Any] | None:
    """Build the `predictions` update payload for one row against a fetched market.

    Returns None when the market is still open (caller skips the row).
    A canceled market yields a CANCELED payload with no fabricated result.
    """
    disposition, outcome = parse_market_result(market)
    if disposition == OPEN:
        return None
    if disposition == CANCELED:
        return {"id": row["id"], "status": CANCELED}
    outcome_str = "yes" if outcome == 1 else "no"
    update: dict[str, Any] = {
        "id": row["id"],
        "status": SETTLED,
        "result": outcome_str,
        "brier": round(brier_score(float(row["our_prob"]), outcome), 5),
        "raw_payload": market,
    }
    market_prob = row.get("market_prob")
    update["market_brier"] = (
        round(brier_score(float(market_prob), outcome), 5) if market_prob is not None else None
    )
    return update
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add tradehub/settlement.py tests/test_settlement.py
git commit -m "feat: add pure prediction settlement math

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Settlement I/O (`fetch_market` + `run_settlement_pass`)

**Files:**
- Modify: `tradehub/core/kalshi_feed.py` — add `fetch_market(ticker: str) -> dict`; reuses the module's existing `KALSHI_API_URL` constant (no new env var, no auth — `GET /markets/{ticker}` is public); returns the parsed JSON `{"market": {...}}` payload. Raises on HTTP errors (e.g. 404 unknown ticker) — the pass catches and skips.
- Modify: `tradehub/settlement.py` — add thin I/O: `fetch_open_predictions(supa) -> list[dict]`, `apply_prediction_settlement(supa, update: dict) -> None` (update by `id`), and `run_settlement_pass(supa, fetch_market) -> dict`.
- Tests: append to `tests/test_settlement.py`.

**Interfaces (I/O):**
- Produces: `fetch_open_predictions(supa) -> list[dict]` — all `predictions` rows with `status = 'OPEN'`.
- Produces: `apply_prediction_settlement(supa, update: dict) -> None` — writes the settle payload from `settle_prediction_row` to the row by `id`.
- Produces: `run_settlement_pass(supa, fetch_market) -> dict` — one idempotent pass: for each open row, `fetch_market(ticker)`; skip on fetch failure (404s, connection errors) so a bad base URL or unknown ticker never blocks or fabricates; `settle_prediction_row` for the rest; applies non-None updates; returns `{"checked": int, "settled": int, "canceled": int, "skipped": int}`. A second pass over settled rows is a no-op because `fetch_open_predictions` only returns `OPEN` rows.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settlement.py`:

```python
# --- I/O (Task 4) ---


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, parent):
        self._parent = parent
        self._payload = None
        self._eq_id = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        # apply_prediction_settlement calls .update() before .eq("id", ...),
        # so the id is captured here and committed at execute() time.
        if col == "id":
            self._eq_id = val
        else:
            self._parent.filters.append((col, val))
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def execute(self):
        if self._payload is not None:
            self._parent.updates.append({"id": self._eq_id, **self._payload})
            return _FakeResult(list(self._parent.updates))
        return _FakeResult([r for r in self._parent.rows if r["status"] == "OPEN"])


class _FakeSupaIO:
    def __init__(self, rows):
        self.rows = rows
        self.tables: list = []
        self.filters: list = []
        self.updates: list = []

    def table(self, name):
        self.tables.append(name)
        return _FakeQuery(self)


def _open_row(id_, ticker, our, market):
    return {"id": id_, "market_ticker": ticker, "our_prob": our, "market_prob": market, "status": "OPEN"}


def test_fetch_open_predictions_returns_only_open():
    supa = _FakeSupaIO([_open_row("a", "T1", 0.6, 0.5), {"id": "b", "status": "SETTLED"}])
    rows = settlement.fetch_open_predictions(supa)
    assert [r["id"] for r in rows] == ["a"]
    assert supa.filters == [("status", "OPEN")]


def test_run_settlement_pass_settles_finalized_and_skips_others():
    rows = [
        _open_row("a", "KXFINAL-YES", 0.7, 0.5),
        _open_row("b", "KXACTIVE", 0.6, 0.4),
        _open_row("c", "KXFINAL-CANCEL", 0.6, 0.4),
        _open_row("d", "KXUNKNOWN", 0.6, 0.4),
    ]
    markets = {
        "KXFINAL-YES": {"market": {"status": "finalized", "result": "yes"}},
        "KXACTIVE": {"market": {"status": "active", "result": None}},
        "KXFINAL-CANCEL": {"market": {"status": "finalized", "result": None}},
    }

    def fake_fetch(ticker):
        if ticker == "KXUNKNOWN":
            raise ValueError("404 Not Found")  # unknown ticker (or environment mismatch)
        return markets[ticker]

    supa = _FakeSupaIO(rows)
    summary = settlement.run_settlement_pass(supa, fake_fetch)
    assert summary == {"checked": 4, "settled": 1, "canceled": 1, "skipped": 2}
    statuses = {u["id"]: u["status"] for u in supa.updates}
    assert statuses == {"a": "SETTLED", "c": "CANCELED"}


def test_run_settlement_pass_is_idempotent():
    row = _open_row("a", "KXFINAL-YES", 0.7, 0.5)
    market = {"market": {"status": "finalized", "result": "yes"}}
    supa = _FakeSupaIO([row])
    first = settlement.run_settlement_pass(supa, lambda _t: market)
    assert first["settled"] == 1
    # Simulate the row flipping to SETTLED in the DB, as the real pass would.
    supa.rows = [{**row, "status": "SETTLED"}]
    supa.updates.clear()
    second = settlement.run_settlement_pass(supa, lambda _t: market)
    assert second == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
    assert supa.updates == []


def test_run_settlement_pass_no_open_predictions():
    supa = _FakeSupaIO([])
    summary = settlement.run_settlement_pass(supa, lambda _t: (_ for _ in ()).throw(AssertionError("must not fetch")))
    assert summary == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v`
Expected: FAIL — `fetch_open_predictions` / `run_settlement_pass` do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

In `tradehub/core/kalshi_feed.py`, add:

```python
def fetch_market(ticker: str) -> dict:
    """Fetch the public market snapshot for a ticker (`GET /markets/{ticker}`).

    Reuses this module's KALSHI_API_URL so the fetch base always agrees with
    the base the market tickers were listed from. The endpoint is public;
    no auth header needed.
    """
    resp = requests.get(f"{KALSHI_API_URL}/{ticker}", timeout=30)
    resp.raise_for_status()
    return resp.json()
```

Append to `tradehub/settlement.py`:

```python
def fetch_open_predictions(supa) -> list[dict[str, Any]]:
    """Return all `predictions` rows still awaiting settlement."""
    res = supa.table(PREDICTIONS_TABLE).select("*").eq("status", OPEN).execute()
    return res.data or []


def apply_prediction_settlement(supa, update: dict[str, Any]) -> None:
    """Write one settle payload (from `settle_prediction_row`) to its row by id."""
    payload = {k: v for k, v in update.items() if k != "id"}
    supa.table(PREDICTIONS_TABLE).update(payload).eq("id", update["id"]).execute()


def run_settlement_pass(supa, fetch_market) -> dict[str, int]:
    """One idempotent settlement pass over all OPEN predictions.

    `fetch_market(ticker)` is injected so tests can fake it; the cron
    entrypoint passes the real Kalshi client. Fetch failures (404 unknown
    ticker, wrong demo/prod base URL, connection errors) skip the row —
    they never fabricate a result and never block the rest of the pass.
    """
    summary = {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
    for row in fetch_open_predictions(supa):
        summary["checked"] += 1
        try:
            market = fetch_market(row["market_ticker"])
        except Exception:
            summary["skipped"] += 1
            continue
        update = settle_prediction_row(row, market)
        if update is None:
            summary["skipped"] += 1
            continue
        apply_prediction_settlement(supa, update)
        if update["status"] == SETTLED:
            summary["settled"] += 1
        else:
            summary["canceled"] += 1
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v`
Expected: 17 passed (13 pure + 4 I/O).

- [ ] **Step 5: Commit**

```bash
git add tradehub/settlement.py tradehub/core/kalshi_feed.py tests/test_settlement.py
git commit -m "feat: add prediction settlement pass against Kalshi market results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Track record + promotion gate (`tradehub/track_record.py`)

**Files:**
- Create: `tradehub/track_record.py`
- Test: `tests/test_track_record.py`

**Interfaces (pure unless noted):**
- Produces: `BUCKETS = ["50-60", "60-70", "70-80", "80-90", "90-100"]`; `bucketize(prob: float) -> str` — deterministic: exactly 0.5 → `"50-60"`, exactly 1.0 → `"90-100"`; predictions below 0.5 are mirrored (the model's confidence is `max(prob, 1 - prob)`), matching the spec's per-band observed rates.
- Produces: `compute_calibration(rows: list[dict]) -> list[dict]` — per bucket `{"bucket", "n", "predicted", "observed"}` over settled rows only (`result` in `("yes", "no")`). Everything is measured in **confidence space** so mirrored rows are comparable: a row's confidence is `max(our_prob, 1 - our_prob)` and its favored side is YES when `our_prob >= 0.5`, else NO. `predicted` is the bucket's mean confidence; `observed` is the fraction of the bucket's rows whose favored side won (`result == "yes"` for YES-favored rows, `result == "no"` for NO-favored rows). A 0.30 forecast that resolves NO therefore counts as a 70%-confidence hit in `"70-80"`, not as a miss.
- Produces: `compute_engine_summary(rows: list[dict]) -> dict` — `{"n_settled", "brier_ours" (mean `brier`), "brier_market" (mean of non-null `market_brier`, else None)}`.
- Produces: `check_promotion_gate(*, engine: str, cadence: str, summary: dict, cal_buckets: list[dict], simulated_pnl_after_fees: float | None) -> dict` — spec section 6 thresholds. `cadence` is `"daily"` (min 200 settled contracts) or `"monthly"` (min 50). Returns `{"status": "PROMOTED"|"SHADOW", "reasons": [str], "max_cal_dev": float}` where `reasons` lists every unmet criterion:
  - `n_settled` below the cadence minimum → not enough contracts
  - `brier_market` is None → missing market Brier, gate cannot be evaluated
  - `brier_ours >= brier_market` → model Brier not below market's
  - `simulated_pnl_after_fees` is None or `<= 0` → P&L not positive after fees/spread
  - any calibration bucket with `|observed - predicted| > 0.10` → calibration miss
- Produces: `fetch_settled_rows(supa, engine: str) -> list[dict]` (I/O) — every `SETTLED` row for the engine, fetched in `PAGE_SIZE` (1000) pages via `.range()` so PostgREST's default row cap never silently truncates the track record.
- Produces: `refresh_track_record(supa, engine: str, engine_version: str = "v0", cadence: str = "daily", simulated_pnl_after_fees: float | None = None) -> dict` (I/O) — reads the engine's settled rows via `fetch_settled_rows`, computes summary + calibration + gate, upserts the `track_record` row, returns the written payload.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_track_record.py
import pytest

from tradehub import track_record


def _settled(id_, prob, market_prob, result):
    return {
        "id": id_,
        "our_prob": prob,
        "market_prob": market_prob,
        "result": result,
        "brier": (prob - (1 if result == "yes" else 0)) ** 2,
        "market_brier": None if market_prob is None else (market_prob - (1 if result == "yes" else 0)) ** 2,
        "status": "SETTLED",
    }


def test_bucketize_boundaries():
    assert track_record.bucketize(0.5) == "50-60"
    assert track_record.bucketize(0.599) == "50-60"
    assert track_record.bucketize(0.6) == "60-70"
    assert track_record.bucketize(1.0) == "90-100"


def test_compute_calibration_buckets():
    rows = [
        _settled("a", 0.55, 0.5, "yes"),
        _settled("b", 0.65, 0.6, "no"),
        _settled("c", 0.75, 0.7, "yes"),
        _settled("d", 0.75, 0.7, "no"),
    ]
    buckets = {b["bucket"]: b for b in track_record.compute_calibration(rows)}
    assert buckets["50-60"]["n"] == 1
    assert buckets["50-60"]["observed"] == pytest.approx(1.0)
    assert buckets["60-70"]["observed"] == pytest.approx(0.0)
    assert buckets["70-80"]["n"] == 2
    assert buckets["70-80"]["observed"] == pytest.approx(0.5)
    assert buckets["70-80"]["predicted"] == pytest.approx(0.75)


def test_compute_calibration_mirrors_no_favored_rows_into_confidence_space():
    # 0.30 means 70% confidence in NO. It resolves NO, so it is a hit in "70-80",
    # and it pools correctly with a YES-favored 0.75 row that resolved YES.
    rows = [_settled("a", 0.30, 0.5, "no"), _settled("b", 0.75, 0.5, "yes")]
    buckets = {b["bucket"]: b for b in track_record.compute_calibration(rows)}
    assert buckets["70-80"]["n"] == 2
    assert buckets["70-80"]["predicted"] == pytest.approx(0.725)
    assert buckets["70-80"]["observed"] == pytest.approx(1.0)


def test_compute_calibration_no_favored_miss():
    # 0.20 (80% confident NO) that resolves YES is a miss in "80-90".
    buckets = {b["bucket"]: b for b in track_record.compute_calibration([_settled("a", 0.20, 0.5, "yes")])}
    assert buckets["80-90"]["observed"] == pytest.approx(0.0)
    assert buckets["80-90"]["predicted"] == pytest.approx(0.80)


def test_compute_engine_summary_briers():
    rows = [_settled("a", 0.7, 0.5, "yes"), _settled("b", 0.8, 0.9, "no")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 2
    assert summary["brier_ours"] == pytest.approx((0.09 + 0.64) / 2)
    assert summary["brier_market"] == pytest.approx((0.25 + 0.81) / 2)


def test_compute_engine_summary_missing_market_brier_is_none():
    rows = [_settled("a", 0.7, None, "yes")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["brier_market"] is None


def _gate_kwargs(**overrides):
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    base = dict(engine="weather", cadence="daily", summary=summary, cal_buckets=cal, simulated_pnl_after_fees=50.0)
    base.update(overrides)
    return base


def test_gate_promotes_when_all_criteria_met():
    gate = track_record.check_promotion_gate(**_gate_kwargs())
    assert gate["status"] == "PROMOTED"
    assert gate["reasons"] == []


def test_gate_blocks_on_insufficient_contracts():
    rows = [_settled("a", 0.95, 0.6, "yes")]
    summary = track_record.compute_engine_summary(rows)
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate["status"] == "SHADOW"
    assert any("200" in r for r in gate["reasons"])


def test_gate_blocks_when_model_brier_not_below_market():
    gate = track_record.check_promotion_gate(**_gate_kwargs(simulated_pnl_after_fees=50.0))
    assert gate["status"] == "PROMOTED"  # sanity: base case promotes
    rows = [_settled(f"r{i}", 0.4, 0.9, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    gate2 = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate2["status"] == "SHADOW"
    assert any("Brier" in r for r in gate2["reasons"])


def test_gate_blocks_on_nonpositive_pnl_and_missing_market_brier():
    gate = track_record.check_promotion_gate(**_gate_kwargs(simulated_pnl_after_fees=0.0))
    assert gate["status"] == "SHADOW"
    rows = [_settled(f"r{i}", 0.95, None, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    gate2 = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate2["status"] == "SHADOW"
    assert any("market" in r.lower() for r in gate2["reasons"])


def test_gate_blocks_on_calibration_miss_over_10pp():
    # 200 settled rows all predicted 0.95 but only half resolve yes -> 45pp miss.
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes" if i % 2 == 0 else "no") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=cal, simulated_pnl_after_fees=50.0,
    )
    assert gate["status"] == "SHADOW"
    assert any("calibration" in r.lower() for r in gate["reasons"])


class _PagedResult:
    def __init__(self, data):
        self.data = data


class _PagedQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}
        self._range = (0, len(rows) - 1)

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        start, end = self._range
        return _PagedResult(matched[start:end + 1])


class _PagedSupa:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "predictions"
        return _PagedQuery(self.rows)


def test_fetch_settled_rows_pages_past_the_1000_row_cap(monkeypatch):
    monkeypatch.setattr(track_record, "PAGE_SIZE", 3)
    rows = [{"id": f"r{i}", "engine": "weather", "status": "SETTLED"} for i in range(7)]
    rows += [{"id": "x", "engine": "weather", "status": "OPEN"}, {"id": "y", "engine": "gas", "status": "SETTLED"}]
    got = track_record.fetch_settled_rows(_PagedSupa(rows), "weather")
    assert [r["id"] for r in got] == [f"r{i}" for i in range(7)]


def test_gate_reports_worst_calibration_miss_across_all_buckets():
    cal = [
        {"bucket": "50-60", "n": 50, "predicted": 0.55, "observed": 0.70},  # 15pp miss
        {"bucket": "90-100", "n": 50, "predicted": 0.95, "observed": 0.60},  # 35pp miss
    ]
    summary = {"n_settled": 300, "brier_ours": 0.10, "brier_market": 0.20}
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary, cal_buckets=cal, simulated_pnl_after_fees=5.0,
    )
    assert gate["status"] == "SHADOW"
    assert gate["max_cal_dev"] == pytest.approx(0.35)
    assert sum("calibration" in r.lower() for r in gate["reasons"]) == 2


def test_gate_monthly_cadence_needs_only_50_contracts():
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes") for i in range(50)]
    summary = track_record.compute_engine_summary(rows)
    gate = track_record.check_promotion_gate(
        engine="macro", cadence="monthly", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=10.0,
    )
    assert gate["status"] == "PROMOTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: `ModuleNotFoundError: No module named 'tradehub.track_record'` (or collection error).

- [ ] **Step 3: Write the minimal implementation**

```python
# tradehub/track_record.py
"""Per-engine track record: calibration, Brier vs market, promotion gate.

Consumes the settled `predictions` rows (spec sections 4.5 and 6) — the
same rows the settlement job writes. Pure math except for
`refresh_track_record`, which upserts the `track_record` rollup table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BUCKETS = ["50-60", "60-70", "70-80", "80-90", "90-100"]
MIN_CONTRACTS = {"daily": 200, "monthly": 50}
MAX_CALIBRATION_MISS = 0.10
TRACK_RECORD_TABLE = "track_record"


def bucketize(prob: float) -> str:
    """Map a probability to its 10pp calibration bucket.

    Confidence is mirrored at 0.5 (a 0.3 forecast is 70% confidence it
    resolves NO). Boundaries are deterministic: 0.5 -> "50-60",
    1.0 -> "90-100".
    """
    confidence = max(prob, 1.0 - prob)
    confidence = min(max(confidence, 0.5), 1.0)
    # 1e-9 absorbs float dust (e.g. 0.7 * 10 == 6.999999999999999 in float);
    # empirically verified: 0.5 -> "50-60", 0.6 -> "60-70", 1.0 -> "90-100".
    idx = min(int(confidence * 10 + 1e-9) - 5, 4)
    return BUCKETS[idx]


def _settled_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("result") in ("yes", "no")]


def _confidence_and_hit(row: dict[str, Any]) -> tuple[float, bool]:
    """Confidence in the favored side, and whether that side won."""
    prob = float(row["our_prob"])
    favored_yes = prob >= 0.5
    confidence = prob if favored_yes else 1.0 - prob
    hit = (row["result"] == "yes") if favored_yes else (row["result"] == "no")
    return confidence, hit


def compute_calibration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-bucket n, mean confidence, and favored-side hit rate over settled rows."""
    groups: dict[str, list[tuple[float, bool]]] = {b: [] for b in BUCKETS}
    for row in _settled_only(rows):
        confidence, hit = _confidence_and_hit(row)
        groups[bucketize(confidence)].append((confidence, hit))
    out = []
    for bucket in BUCKETS:
        members = groups[bucket]
        if not members:
            continue
        predicted = sum(c for c, _ in members) / len(members)
        observed = sum(1 for _, hit in members if hit) / len(members)
        out.append({"bucket": bucket, "n": len(members),
                    "predicted": round(predicted, 4), "observed": round(observed, 4)})
    return out


def compute_engine_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """n_settled, mean model Brier, mean market Brier (None if never recorded)."""
    settled = _settled_only(rows)
    briers = [float(r["brier"]) for r in settled if r.get("brier") is not None]
    market_briers = [float(r["market_brier"]) for r in settled if r.get("market_brier") is not None]
    return {
        "n_settled": len(settled),
        "brier_ours": round(sum(briers) / len(briers), 5) if briers else None,
        "brier_market": round(sum(market_briers) / len(market_briers), 5) if market_briers else None,
    }


def check_promotion_gate(
    *,
    engine: str,
    cadence: str,
    summary: dict[str, Any],
    cal_buckets: list[dict[str, Any]],
    simulated_pnl_after_fees: float | None,
) -> dict[str, Any]:
    """Evaluate the spec section 6 promotion gate for one engine.

    Returns {"status": "PROMOTED"|"SHADOW", "reasons": [...]} where
    reasons lists every unmet criterion. Re-evaluated after every
    settlement pass: an engine that slips below any threshold is
    demoted back to SHADOW (promotion is dynamic, per the spec).
    """
    reasons: list[str] = []
    min_contracts = MIN_CONTRACTS.get(cadence, MIN_CONTRACTS["daily"])
    if summary["n_settled"] < min_contracts:
        reasons.append(f"only {summary['n_settled']} settled contracts, need {min_contracts} ({cadence})")
    ours = summary.get("brier_ours")
    market = summary.get("brier_market")
    if market is None:
        reasons.append("no market Brier recorded; gate cannot be evaluated")
    elif ours is None or ours >= market:
        reasons.append(f"model Brier {ours} is not below market Brier {market}")
    if simulated_pnl_after_fees is None or simulated_pnl_after_fees <= 0:
        reasons.append("simulated P&L after fees/spread is not positive")
    worst_miss = 0.0
    for bucket in cal_buckets:
        miss = abs(bucket["observed"] - bucket["predicted"])
        worst_miss = max(worst_miss, miss)
        if miss > MAX_CALIBRATION_MISS:
            reasons.append(f"calibration miss {miss:.1%} in bucket {bucket['bucket']} (limit 10pp)")
    status = "PROMOTED" if not reasons else "SHADOW"
    return {"status": status, "reasons": reasons, "max_cal_dev": round(worst_miss, 4)}


PAGE_SIZE = 1000  # PostgREST's default max rows per response


def fetch_settled_rows(supa, engine: str) -> list[dict[str, Any]]:
    """All SETTLED prediction rows for one engine, paged past PostgREST's 1000-row cap."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        res = (
            supa.table("predictions").select("*")
            .eq("engine", engine).eq("status", "SETTLED")
            .order("id").range(start, start + PAGE_SIZE - 1).execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def refresh_track_record(supa, engine: str, engine_version: str = "v0",
                         cadence: str = "daily",
                         simulated_pnl_after_fees: float | None = None) -> dict[str, Any]:
    """Recompute one engine's rollup from its settled rows and upsert it."""
    rows = fetch_settled_rows(supa, engine)
    summary = compute_engine_summary(rows)
    cal_buckets = compute_calibration(rows)
    gate = check_promotion_gate(engine=engine, cadence=cadence, summary=summary,
                                cal_buckets=cal_buckets,
                                simulated_pnl_after_fees=simulated_pnl_after_fees)
    payload = {
        "engine": engine,
        "engine_version": engine_version,
        "n_settled": summary["n_settled"],
        "brier_ours": summary["brier_ours"],
        "brier_market": summary["brier_market"],
        "cal_buckets": cal_buckets,
        "max_cal_dev": gate["max_cal_dev"],
        "gate_status": gate["status"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supa.table(TRACK_RECORD_TABLE).upsert(payload, on_conflict="engine").execute()
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add tradehub/track_record.py tests/test_track_record.py
git commit -m "feat: add track record calibration and promotion gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Cron entrypoint (`tradehub/scripts/settle_predictions.py`)

**Files:**
- Create: `tradehub/scripts/settle_predictions.py` — one-shot `main()` wiring the real Supabase client (`get_client` from `tradehub/core/supabase_client.py`), the real `fetch_market` from `tradehub/core/kalshi_feed.py`, `run_settlement_pass`, and `refresh_track_record` for each `(engine, cadence)` in the module-level `ENGINES` list (the spec's engine set: weather/gas daily, cpi_nowcast/labor_nowcast monthly, crypto daily). Prints a JSON summary. Suitable for Azure scale-to-zero: it runs once and exits, no loop.
- Test: `tests/test_settle_predictions.py` — monkeypatches module-level `get_client`, `fetch_market`, `run_settlement_pass`, `refresh_track_record` to assert the wiring: one pass runs, track record refreshes per distinct engine, and the JSON summary prints.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settle_predictions.py
import json

import pytest

from tradehub.scripts import settle_predictions


class _FakeSupa:
    pass


def test_engines_match_spec_engine_set_and_cadences():
    assert dict(settle_predictions.ENGINES) == {
        "weather": "daily",
        "gas": "daily",
        "cpi_nowcast": "monthly",
        "labor_nowcast": "monthly",
        "crypto": "daily",
    }


def test_main_wires_pass_and_refresh(monkeypatch, capsys):
    calls = {}

    def fake_get_client():
        calls["client"] = True
        return _FakeSupa()

    def fake_fetch_market(ticker):
        return {"market": {"status": "active", "result": None}}

    def fake_run_pass(supa, fetch):
        calls["pass"] = True
        assert fetch is fake_fetch_market
        return {"checked": 3, "settled": 0, "canceled": 0, "skipped": 3}

    refreshed = []

    def fake_refresh(supa, engine, **kwargs):
        refreshed.append(engine)
        return {"engine": engine}

    monkeypatch.setattr(settle_predictions, "get_client", fake_get_client)
    monkeypatch.setattr(settle_predictions, "fetch_market", fake_fetch_market)
    monkeypatch.setattr(settle_predictions, "run_settlement_pass", fake_run_pass)
    monkeypatch.setattr(settle_predictions, "refresh_track_record", fake_refresh)
    monkeypatch.setattr(settle_predictions, "ENGINES", [("weather", "daily"), ("macro", "monthly")])

    assert settle_predictions.main() == 0
    assert calls == {"client": True, "pass": True}
    assert refreshed == ["weather", "macro"]
    out = json.loads(capsys.readouterr().out)
    assert out["checked"] == 3
    assert out["track_record_refreshed"] == ["weather", "macro"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settle_predictions.py -v`
Expected: `ModuleNotFoundError` (the script does not exist yet).

- [ ] **Step 3: Write the minimal implementation**

```python
# tradehub/scripts/settle_predictions.py
"""Cron entrypoint: settle open predictions against Kalshi market results.

Runs one settlement pass and refreshes each engine's track record, then
exits. Designed for an hourly cron on Azure scale-to-zero — there is no
polling loop here. Simulated P&L wiring (spec section 4.5's fees+spread
term) lands with the paper-trading work; until then the gate receives
None and promotion stays blocked on that criterion.
"""

from __future__ import annotations

import json
import sys

from tradehub.core.kalshi_feed import fetch_market
from tradehub.core.supabase_client import get_client
from tradehub.settlement import run_settlement_pass
from tradehub.track_record import refresh_track_record

# (engine, cadence) pairs the cron refreshes — the spec's engine set (section
# 3.1). Cadence sets the gate's contract minimum: daily engines need 200
# settled contracts, monthly-release engines 50. `engine` values must match
# what each engine writes into predictions.engine.
ENGINES = [
    ("weather", "daily"),
    ("gas", "daily"),
    ("cpi_nowcast", "monthly"),
    ("labor_nowcast", "monthly"),
    ("crypto", "daily"),
]


def main() -> int:
    supa = get_client()
    summary = run_settlement_pass(supa, fetch_market)
    refreshed = []
    for engine, cadence in ENGINES:
        refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
        refreshed.append(engine)
    summary["track_record_refreshed"] = refreshed
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settle_predictions.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/settle_predictions.py tests/test_settle_predictions.py
git commit -m "feat: add hourly settlement cron entrypoint

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification

- [ ] **Step 1: Full test suite**

Run: `cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/ -v`
Expected: all pass, including the 41 new tests from Tasks 2–6 (8 + 17 + 14 + 2) plus the new migration assertion in Task 1.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check tradehub/predictions.py tradehub/settlement.py tradehub/track_record.py tradehub/scripts/settle_predictions.py tradehub/core/kalshi_feed.py tests/test_predictions.py tests/test_settlement.py tests/test_track_record.py tests/test_settle_predictions.py tests/test_repo_layout.py`
Expected: clean.

- [ ] **Step 3: Self-review** — Before asking Kevin to review: re-read every new function signature against its task's test calls (argument names, return shapes, `None` handling), confirm every Review Focus item has its named test, and confirm no TODO/FIXME/placeholder remains.

---

## Out of Scope (explicitly not in this plan)

- Simulated P&L computation (fees/spread terms from spec section 4.5): until the paper-trading work lands, the gate receives `simulated_pnl_after_fees=None` and promotion stays blocked on that criterion — honest rather than fabricated.
- Track Record UI/API surface: the spec's `shadow`/`trade-worthy` labels and dashboard read from the `track_record` table, which this plan populates; the UI comes later. Note for that step: both new tables use the owner-only RLS pattern, and the War Room reads Supabase with the anon key — the UI step must either add an anon `SELECT` policy on `track_record` (aggregate, non-sensitive) or serve it through `tradehub.api`.
- Engine wiring to call `record_prediction`: engines start writing rows once this lands, in a follow-up.
- The Azure cron schedule itself: `settle_predictions.py` is cron-ready, but creating the schedule is a deploy step for Kevin.
- The old plan's realized position P&L dashboard wiring: `compute_realized_pnl` is kept as pure math (preserved from the old plan), but the position-settlement dashboard is out of scope for rollout step 2.

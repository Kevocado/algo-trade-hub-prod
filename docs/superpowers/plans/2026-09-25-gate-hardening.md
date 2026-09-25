# Step 2b: Promotion-Gate and Settlement Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the step-2 track record trustworthy before the hourly VPS scan starts feeding it: count contracts, not rows; don't let one thin calibration bucket block promotion; give each engine version its own record; keep the engine's inputs when a row settles; fetch each Kalshi market once per pass; and lock client writes out of the ledger.

**Why now:** the PR #2 review (2026-09-25) found these in merged code. None are live bugs yet, because nothing can be promoted until simulated P&L is wired in. But the step-5 scan writes one prediction per open market every hour, so a daily weather market lands in the ledger about 24–36 times, and the gate as written would count each of those rows as a contract. **The VPS timers must not be enabled until this plan is merged** (see [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md) Task 5).

**Architecture:** One new migration (`20260416000007`) plus changes to four modules. No new tables, no new dependencies.
- `tradehub/track_record.py`: every settled row gets weight `1/k`, where `k` is the number of rows for its `market_ticker`. Briers and calibration are contract-weighted, and `n_settled` counts distinct contracts. A calibration bucket only blocks the gate once it holds at least `MIN_BUCKET_CONTRACTS = 20` effective contracts. `refresh_track_record` upserts one row per `(engine, engine_version)`.
- `tradehub/settlement.py`: the Kalshi payload goes to `settlement_payload` plus a `settled_at` stamp. `raw_payload` (the engine's inputs) is never overwritten. Markets are cached per ticker within a pass. Fetch errors and write errors are counted separately and never abort the pass.
- `tradehub/backtest/metrics.py` and `runner.py`: backtest rows carry `market_ticker`, so the backtest gate counts contracts the same way.
- `tradehub/scripts/settle_predictions.py`: reports `engine@version` per refreshed record.

**Tech Stack:** Python 3.12, Supabase Postgres (PostgREST via `supabase-py`), pytest.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) §6 (promotion gate). The "contract" and minimum-bucket rules were added to §6 on 2026-09-25 together with this plan.

## Global Constraints

- **Prerequisites:** PR #3 (backtesting suite) and PR #4 (data layer, weather/gas) are merged to `main`. The patches below were produced against PR #4's head (`31b66b1`). If a later fix changed the same lines and `git apply` fails, make the change by hand. Each task's **Intent** says exactly what must hold.
- **Don't edit** migration `20260416000003` or any other applied migration. Only add `20260416000007`.
- **Test runs:** `.venv/bin/python` from the repo root, each pytest run prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- **Applying patches:** save the diff block to a file in `/tmp` and run `git apply --3way /tmp/<file>.patch` from the repo root.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Handoff contract** (rollout tracker): branch `plan/2026-09-25-gate-hardening`, one commit per task, evidence report at `docs/superpowers/reports/2026-09-25-gate-hardening.md`.

## Validation already done (2026-09-25)

- The whole plan was applied on top of `31b66b1`: **292 passed**, plus `ruff check --select F401,F811,F821 tradehub tests`, which passes.
- The migration was applied twice (idempotent) to a throwaway `postgres:16` with a stubbed `auth` schema, after `20260416000003`. Results:
  - `track_record_pkey` became `(engine, engine_version)`, and two versions of one engine insert side by side;
  - a `SETTLED` row without a result is rejected by `predictions_settled_has_result`;
  - only the `*_owner_read` SELECT policies remain.

## Review Focus

- `n_settled` equals the number of distinct `market_ticker`s. A row without a ticker counts as its own contract, so older tests and callers still work.
- A bucket with fewer than 20 effective contracts is still listed in `cal_buckets`, but it never adds a gate reason and never raises `max_cal_dev`.
- `settle_prediction_row` output never contains `raw_payload`.
- Within a pass, `fetch_market` is called at most once per ticker, including when that ticker's fetch fails.
- The migration leaves no `FOR ALL` policy on `predictions` or `track_record`.

---

## File Structure

- **Create** `market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql` (Task 1)
- **Create** `tests/test_predictions_hardening_migration.py` (Task 1)
- **Modify** `tradehub/track_record.py`, `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py` (Task 2)
- **Create** `tests/test_track_record_contracts.py` (Task 2)
- **Modify** `tradehub/settlement.py`, `tests/test_settlement.py` (Task 3)
- **Modify** `tradehub/scripts/settle_predictions.py`, `tradehub/core/supabase_client.py`, `tests/test_settle_predictions.py` (Task 4)
- **Modify** `docs/superpowers/plans/2026-09-24-rollout-tracker.md` (Task 4)

---

## Task 1: Hardening migration

**Intent:**
- `predictions` gains `settlement_payload jsonb` and `settled_at timestamptz`.
- A `SETTLED` row must have a `result`.
- `track_record`'s primary key becomes `(engine, engine_version)`.
- Clients (anon or authenticated) can at most SELECT their own rows. The service-role jobs bypass RLS, and the War Room reads through `GET /api/track-record`.

- [ ] **Step 1: Write the failing test** — `tests/test_predictions_hardening_migration.py`:

```python
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql"
)


def test_hardening_migration_covers_step_2b():
    sql = MIGRATION.read_text(encoding="utf-8")
    for needle in (
        "ADD COLUMN IF NOT EXISTS settlement_payload jsonb",
        "ADD COLUMN IF NOT EXISTS settled_at timestamptz",
        "CHECK (status <> 'SETTLED' OR result IS NOT NULL)",
        "PRIMARY KEY (engine, engine_version)",
        'CREATE POLICY "predictions_owner_read" ON predictions FOR SELECT',
        'CREATE POLICY "track_record_owner_read" ON track_record FOR SELECT',
    ):
        assert needle in sql, needle
    assert "FOR ALL" not in sql, "clients must not get write policies"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_predictions_hardening_migration.py -q`
Expected: FAIL, `FileNotFoundError` for the migration.

- [ ] **Step 3: Create the migration** — `market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql`:

```sql
-- Rollout step 2b: harden the predictions ledger and track record.
--
-- * settlement_payload / settled_at: settlement no longer overwrites the
--   engine's raw_payload (its inputs), and the settle time is auditable.
-- * A SETTLED row must carry its result.
-- * track_record is keyed per (engine, engine_version): a new model version
--   earns its own record instead of inheriting its predecessor's promotion.
-- * Clients get read-only access. All writes come from the service-role
--   jobs (which bypass RLS); the War Room reads through the API.
--
-- Idempotent, like the earlier migrations.

ALTER TABLE predictions ADD COLUMN IF NOT EXISTS settlement_payload jsonb;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS settled_at timestamptz;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'predictions_settled_has_result') THEN
    ALTER TABLE predictions
      ADD CONSTRAINT predictions_settled_has_result CHECK (status <> 'SETTLED' OR result IS NOT NULL);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS predictions_engine_version_status_idx
  ON predictions (engine, engine_version, status);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.conname = 'track_record_pkey'
    GROUP BY c.conname HAVING count(*) = 1
  ) THEN
    ALTER TABLE track_record DROP CONSTRAINT track_record_pkey;
    ALTER TABLE track_record ADD CONSTRAINT track_record_pkey PRIMARY KEY (engine, engine_version);
  END IF;
END $$;

DROP POLICY IF EXISTS "predictions_owner" ON predictions;
DROP POLICY IF EXISTS "predictions_owner_read" ON predictions;
CREATE POLICY "predictions_owner_read" ON predictions FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "track_record_owner" ON track_record;
DROP POLICY IF EXISTS "track_record_owner_read" ON track_record;
CREATE POLICY "track_record_owner_read" ON track_record FOR SELECT
  USING (auth.uid() = user_id);
```

- [ ] **Step 4: Run to verify it passes**

Run the same pytest command. Expected: `1 passed`.

Optional, if Docker is available: repeat the throwaway-Postgres check from "Validation already done":

```bash
docker run -d --name pg2b -e POSTGRES_PASSWORD=x postgres:16-alpine && sleep 6
docker exec -i pg2b psql -q -v ON_ERROR_STOP=1 -U postgres -c "CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid primary key); CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';"
for f in 20260416000003_predictions_ledger 20260416000007_predictions_hardening 20260416000007_predictions_hardening; do docker exec -i pg2b psql -q -v ON_ERROR_STOP=1 -U postgres < market_sentiment_tool/supabase/migrations/$f.sql && echo "applied $f"; done
docker exec pg2b psql -U postgres -tAc "select pg_get_constraintdef(oid) from pg_constraint where conname='track_record_pkey'"
docker rm -f pg2b
```
Expected: three `applied` lines, then `PRIMARY KEY (engine, engine_version)`.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql tests/test_predictions_hardening_migration.py
git commit -m "feat: harden predictions ledger schema and make client access read-only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Contract-weighted gate, minimum bucket size, per-version records

**Intent:**
- **Contract weights.** `_contract_weights` gives each settled row weight `1/k`, where `k` is the number of settled rows sharing its `market_ticker`. A row with no ticker is its own contract.
- **Summary.** `compute_engine_summary` returns:
  - `n_settled` = distinct contracts, and `n_rows` = raw rows;
  - contract-weighted `brier_ours` and `brier_market`. The market Brier still fails closed if any settled row lacks one.
- **Calibration.** `compute_calibration` weights the same way. Its `n` is the effective contract count, rounded to 2 decimal places, and it adds `n_rows`.
- **Gate.** `check_promotion_gate` skips buckets with `n < MIN_BUCKET_CONTRACTS` (20).
- **Per-version records.** `refresh_track_record(supa, engine, cadence=..., simulated_pnl_after_fees=...)` groups by `engine_version` and returns a list with one payload per version. It upserts with `on_conflict="engine,engine_version"`, and it no longer takes an `engine_version` argument.
- **Backtest rows.** Backtest prediction rows carry `market_ticker`.

- [ ] **Step 1: Write the failing tests** — `tests/test_track_record_contracts.py`:

```python
import pytest

from tradehub import track_record


def _row(ticker, prob, market_prob, result, version="v1", id_=None):
    outcome = 1 if result == "yes" else 0
    return {
        "id": id_ or f"{ticker}-{prob}-{market_prob}",
        "market_ticker": ticker,
        "engine_version": version,
        "our_prob": prob,
        "market_prob": market_prob,
        "result": result,
        "brier": (prob - outcome) ** 2,
        "market_brier": (market_prob - outcome) ** 2,
        "status": "SETTLED",
    }


def test_hourly_repeats_of_one_market_count_as_one_contract():
    rows = [_row("KXHIGHNY-26SEP25-B72.5", 0.9, 0.6, "yes", id_=f"h{i}") for i in range(24)]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 1
    assert summary["n_rows"] == 24


def test_briers_weight_each_contract_equally():
    # Market A predicted 3 times (Brier 0.01 each), market B once (Brier 0.81).
    rows = [_row("A", 0.9, 0.5, "yes", id_=f"a{i}") for i in range(3)] + [_row("B", 0.9, 0.5, "no")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 2
    assert summary["brier_ours"] == pytest.approx((0.01 + 0.81) / 2)
    assert summary["brier_market"] == pytest.approx(0.25)


def test_calibration_n_is_effective_contracts():
    rows = [_row("A", 0.95, 0.5, "yes", id_=f"a{i}") for i in range(4)] + [_row("B", 0.95, 0.5, "no")]
    (bucket,) = track_record.compute_calibration(rows)
    assert bucket["bucket"] == "90-100"
    assert bucket["n"] == pytest.approx(2.0)
    assert bucket["n_rows"] == 5
    assert bucket["observed"] == pytest.approx(0.5)  # A hit, B missed: one contract each


def test_thin_bucket_does_not_block_the_gate():
    # 199 contracts right at 0.95, one stray 0.55 miss (the case that blocked the step-2 gate).
    rows = [_row(f"M{i}", 0.95, 0.9, "yes") for i in range(199)] + [_row("STRAY", 0.55, 0.5, "no")]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    gate = track_record.check_promotion_gate(engine="weather", cadence="daily", summary=summary,
                                             cal_buckets=cal, simulated_pnl_after_fees=5.0)
    assert gate["status"] == "PROMOTED", gate["reasons"]
    assert any(b["bucket"] == "50-60" and b["n"] == 1 for b in cal)  # still reported


def test_full_bucket_miss_still_blocks_the_gate():
    rows = [_row(f"M{i}", 0.95, 0.9, "yes" if i % 2 else "no") for i in range(200)]
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=track_record.compute_engine_summary(rows),
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=5.0)
    assert gate["status"] == "SHADOW"
    assert any("calibration" in r for r in gate["reasons"])


class _Upserts:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def table(self, name):
        self.name = name
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._slice = (start, end)
        return self

    def upsert(self, payload, on_conflict):
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self):
        if self.name == "predictions":
            start, end = self._slice
            return type("R", (), {"data": self.rows[start:end + 1]})()
        return type("R", (), {"data": []})()


def test_refresh_writes_one_record_per_engine_version():
    rows = [_row("A", 0.9, 0.5, "yes", version="v1"), _row("B", 0.8, 0.5, "yes", version="v2"),
            _row("C", 0.7, 0.5, "no", version="v2")]
    supa = _Upserts(rows)
    out = track_record.refresh_track_record(supa, "weather", cadence="daily")
    assert [(p["engine_version"], p["n_settled"]) for p in out] == [("v1", 1), ("v2", 2)]
    assert {c for _, c in supa.upserts} == {"engine,engine_version"}


def test_backtest_rows_carry_their_market_ticker():
    from tradehub.backtest.metrics import prediction_row

    rows = [prediction_row(0.8, 0.5, "yes", market_ticker="A") for _ in range(5)]
    assert rows[0]["market_ticker"] == "A"
    assert track_record.compute_engine_summary(rows)["n_settled"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record_contracts.py -q`
Expected: most tests FAIL. `n_settled` is 24 instead of 1, `refresh_track_record` returns a dict rather than a list, and `prediction_row` has no `market_ticker` keyword. `test_full_bucket_miss_still_blocks_the_gate` already passes.

- [ ] **Step 3: Implement** by applying this patch:

```diff
diff --git a/tradehub/backtest/metrics.py b/tradehub/backtest/metrics.py
index d2c13de..3f14b1d 100644
--- a/tradehub/backtest/metrics.py
+++ b/tradehub/backtest/metrics.py
@@ -49,9 +49,11 @@ def market_mid(candle: Candle | None) -> float | None:
     return (candle.yes_bid + candle.yes_ask) / 2.0


-def prediction_row(our_prob: float, market_prob: float | None, result: str) -> dict[str, Any]:
+def prediction_row(our_prob: float, market_prob: float | None, result: str,
+                   market_ticker: str | None = None) -> dict[str, Any]:
     outcome = _binary_outcome(result)
     return {
+        "market_ticker": market_ticker,
         "our_prob": our_prob,
         "market_prob": market_prob,
         "result": result,
diff --git a/tradehub/backtest/runner.py b/tradehub/backtest/runner.py
index 04e8cf4..d360786 100644
--- a/tradehub/backtest/runner.py
+++ b/tradehub/backtest/runner.py
@@ -84,7 +84,8 @@ def run_backtest(
             raise LeakageError(f"{decision.market_ticker}: decision at/after market close {history.close_time.isoformat()}")
         if history.result not in ("yes", "no"):
             continue
-        rows.append(prediction_row(decision.our_prob, market_mid(quote_at(history.candles, decision.decided_at)), history.result))
+        rows.append(prediction_row(decision.our_prob, market_mid(quote_at(history.candles, decision.decided_at)),
+                                  history.result, market_ticker=decision.market_ticker))
         if mode == "taker":
             fill = taker_fill(decision, history.candles, contracts=contracts, min_edge_pct=min_edge_pct)
         else:
diff --git a/tradehub/track_record.py b/tradehub/track_record.py
index 3e05bc0..ff7354e 100644
--- a/tradehub/track_record.py
+++ b/tradehub/track_record.py
@@ -13,6 +13,10 @@ from typing import Any
 BUCKETS = ["50-60", "60-70", "70-80", "80-90", "90-100"]
 MIN_CONTRACTS = {"daily": 200, "monthly": 50}
 MAX_CALIBRATION_MISS = 0.10
+# A calibration bucket needs this many contracts (effective, see
+# _contract_weights) before its miss can block promotion; thinner buckets
+# are still reported. Spec section 6.
+MIN_BUCKET_CONTRACTS = 20
 TRACK_RECORD_TABLE = "track_record"


@@ -35,6 +39,25 @@ def _settled_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
     return [r for r in rows if r.get("result") in ("yes", "no")]


+def _contract_key(row: dict[str, Any]) -> str:
+    """Rows about the same Kalshi contract share a key; rows without a ticker stand alone."""
+    ticker = row.get("market_ticker")
+    return f"ticker:{ticker}" if ticker else f"row:{row.get('id', id(row))}"
+
+
+def _contract_weights(rows: list[dict[str, Any]]) -> list[float]:
+    """Weight each row 1/k, k = rows for its contract, so every contract counts once.
+
+    The hourly scan predicts each open market many times; without this a
+    single daily market would count ~24 times toward the gate.
+    """
+    counts: dict[str, int] = {}
+    for row in rows:
+        key = _contract_key(row)
+        counts[key] = counts.get(key, 0) + 1
+    return [1.0 / counts[_contract_key(row)] for row in rows]
+
+
 def _confidence_and_hit(row: dict[str, Any]) -> tuple[float, bool]:
     """Confidence in the favored side, and whether that side won."""
     prob = float(row["our_prob"])
@@ -45,37 +68,51 @@ def _confidence_and_hit(row: dict[str, Any]) -> tuple[float, bool]:


 def compute_calibration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
-    """Per-bucket n, mean confidence, and favored-side hit rate over settled rows."""
-    groups: dict[str, list[tuple[float, bool]]] = {b: [] for b in BUCKETS}
-    for row in _settled_only(rows):
+    """Per-bucket contract-weighted n, mean confidence, and favored-side hit rate.
+
+    `n` is the effective number of contracts in the bucket (sum of row
+    weights); `n_rows` is the raw row count.
+    """
+    settled = _settled_only(rows)
+    groups: dict[str, list[tuple[float, bool, float]]] = {b: [] for b in BUCKETS}
+    for row, weight in zip(settled, _contract_weights(settled)):
         confidence, hit = _confidence_and_hit(row)
-        groups[bucketize(confidence)].append((confidence, hit))
+        groups[bucketize(confidence)].append((confidence, hit, weight))
     out = []
     for bucket in BUCKETS:
         members = groups[bucket]
         if not members:
             continue
-        predicted = sum(c for c, _ in members) / len(members)
-        observed = sum(1 for _, hit in members if hit) / len(members)
-        out.append({"bucket": bucket, "n": len(members),
+        total = sum(w for _, _, w in members)
+        predicted = sum(c * w for c, _, w in members) / total
+        observed = sum(w for _, hit, w in members if hit) / total
+        out.append({"bucket": bucket, "n": round(total, 2), "n_rows": len(members),
                     "predicted": round(predicted, 4), "observed": round(observed, 4)})
     return out


+def _weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
+    total = sum(w for _, w in pairs)
+    return sum(v * w for v, w in pairs) / total if total else None
+
+
 def compute_engine_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
-    """n_settled and mean Briers; market Brier requires full settled coverage."""
+    """Distinct settled contracts and contract-weighted mean Briers.
+
+    `n_settled` counts contracts, not rows (spec section 6 says "settled
+    contracts"). Market Brier still fails closed: every settled row must
+    carry one.
+    """
     settled = _settled_only(rows)
-    briers = [float(r["brier"]) for r in settled if r.get("brier") is not None]
-    complete_market_briers = [
-        float(r["market_brier"]) for r in settled if r.get("market_brier") is not None
-    ]
-    market_brier = None
-    if settled and len(complete_market_briers) == len(settled):
-        market_brier = round(sum(complete_market_briers) / len(complete_market_briers), 5)
+    weights = _contract_weights(settled)
+    ours = _weighted_mean([(float(r["brier"]), w) for r, w in zip(settled, weights) if r.get("brier") is not None])
+    market_pairs = [(float(r["market_brier"]), w) for r, w in zip(settled, weights) if r.get("market_brier") is not None]
+    market = _weighted_mean(market_pairs) if settled and len(market_pairs) == len(settled) else None
     return {
-        "n_settled": len(settled),
-        "brier_ours": round(sum(briers) / len(briers), 5) if briers else None,
-        "brier_market": market_brier,
+        "n_settled": len({_contract_key(r) for r in settled}),
+        "n_rows": len(settled),
+        "brier_ours": round(ours, 5) if ours is not None else None,
+        "brier_market": round(market, 5) if market is not None else None,
     }


@@ -108,6 +145,8 @@ def check_promotion_gate(
         reasons.append("simulated P&L after fees/spread is not positive")
     worst_miss = 0.0
     for bucket in cal_buckets:
+        if bucket["n"] < MIN_BUCKET_CONTRACTS:
+            continue  # too thin to judge; still shown in cal_buckets
         miss = abs(bucket["observed"] - bucket["predicted"])
         worst_miss = max(worst_miss, miss)
         if miss > MAX_CALIBRATION_MISS:
@@ -136,11 +175,24 @@ def fetch_settled_rows(supa, engine: str) -> list[dict[str, Any]]:
         start += PAGE_SIZE


-def refresh_track_record(supa, engine: str, engine_version: str = "v0",
-                         cadence: str = "daily",
-                         simulated_pnl_after_fees: float | None = None) -> dict[str, Any]:
-    """Recompute one engine's rollup from its settled rows and upsert it."""
-    rows = fetch_settled_rows(supa, engine)
+def refresh_track_record(supa, engine: str, cadence: str = "daily",
+                         simulated_pnl_after_fees: float | None = None) -> list[dict[str, Any]]:
+    """Recompute one rollup per engine_version from the engine's settled rows and upsert them.
+
+    Each version earns its own record: a new model version never inherits
+    its predecessor's promotion.
+    """
+    by_version: dict[str, list[dict[str, Any]]] = {}
+    for row in fetch_settled_rows(supa, engine):
+        by_version.setdefault(row.get("engine_version") or "v0", []).append(row)
+    return [
+        _upsert_version(supa, engine, version, rows, cadence, simulated_pnl_after_fees)
+        for version, rows in sorted(by_version.items())
+    ]
+
+
+def _upsert_version(supa, engine: str, engine_version: str, rows: list[dict[str, Any]], cadence: str,
+                    simulated_pnl_after_fees: float | None) -> dict[str, Any]:
     summary = compute_engine_summary(rows)
     cal_buckets = compute_calibration(rows)
     gate = check_promotion_gate(engine=engine, cadence=cadence, summary=summary,
@@ -157,5 +209,5 @@ def refresh_track_record(supa, engine: str, engine_version: str = "v0",
         "gate_status": gate["status"],
         "updated_at": datetime.now(UTC).isoformat(),
     }
-    supa.table(TRACK_RECORD_TABLE).upsert(payload, on_conflict="engine").execute()
+    supa.table(TRACK_RECORD_TABLE).upsert(payload, on_conflict="engine,engine_version").execute()
     return payload
```

- [ ] **Step 4: Run to verify they pass, with no regressions**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record_contracts.py tests/test_track_record.py tests/test_backtest_runner.py tests/test_backtest_store.py -q`
Expected: all pass. The existing step-2 tests keep passing because their rows have no `market_ticker`, so each row is its own contract.

- [ ] **Step 5: Commit**

```bash
git add tradehub/track_record.py tradehub/backtest/metrics.py tradehub/backtest/runner.py tests/test_track_record_contracts.py
git commit -m "fix: count settled contracts, not rows, in the promotion gate

Contract-weighted Briers and calibration, a 20-contract minimum before a
calibration bucket can block promotion, and one track record per engine
version.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Settlement keeps engine inputs, caches markets, isolates errors

**Intent:**
- **What a settlement writes.** A SETTLED or CANCELED update carries `settlement_payload` (the Kalshi JSON) and `settled_at` (ISO UTC), and never `raw_payload`.
- **One fetch per ticker.** `run_settlement_pass` calls `fetch_market` at most once per ticker. If that fetch fails, every row for the ticker is skipped, and `fetch_errors` goes up once.
- **Write errors.** An exception from `apply_prediction_settlement` counts in `write_errors` and `skipped`, and the pass continues.
- **Summary keys.** The summary always has `checked`, `settled`, `canceled`, `skipped`, `fetch_errors` and `write_errors`.

- [ ] **Step 1: Update and add the tests** by applying this patch to `tests/test_settlement.py`. It updates four existing expectations and adds four tests:

```diff
diff --git a/tests/test_settlement.py b/tests/test_settlement.py
index 6f877bb..dcf198a 100644
--- a/tests/test_settlement.py
+++ b/tests/test_settlement.py
@@ -79,7 +79,8 @@ def test_settle_prediction_row_canceled_marks_canceled_without_fabricating_resul
     row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
     market = {"market": {"status": "finalized", "result": None}}
     update = settlement.settle_prediction_row(row, market)
-    assert update == {"id": "abc", "status": "CANCELED"}
+    assert update["id"] == "abc" and update["status"] == "CANCELED"
+    assert update["settlement_payload"] == market and update["settled_at"]
     assert "result" not in update and "brier" not in update


@@ -204,7 +205,8 @@ def test_run_settlement_pass_settles_finalized_and_skips_others():

     supa = _FakeSupaIO(rows)
     summary = settlement.run_settlement_pass(supa, fake_fetch)
-    assert summary == {"checked": 4, "settled": 1, "canceled": 1, "skipped": 2}
+    assert summary == {"checked": 4, "settled": 1, "canceled": 1, "skipped": 2,
+                       "fetch_errors": 1, "write_errors": 0}
     statuses = {u["id"]: u["status"] for u in supa.updates}
     assert statuses == {"a": "SETTLED", "c": "CANCELED"}

@@ -219,7 +221,7 @@ def test_run_settlement_pass_is_idempotent():
     supa.rows = [{**row, "status": "SETTLED"}]
     supa.updates.clear()
     second = settlement.run_settlement_pass(supa, lambda _t: market)
-    assert second == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
+    assert second == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0, "fetch_errors": 0, "write_errors": 0}
     assert supa.updates == []


@@ -232,7 +234,8 @@ def test_run_settlement_pass_counts_conditional_update_miss_as_skipped(monkeypat

     summary = settlement.run_settlement_pass(supa, lambda _t: market)

-    assert summary == {"checked": 2, "settled": 1, "canceled": 0, "skipped": 1}
+    assert summary == {"checked": 2, "settled": 1, "canceled": 0, "skipped": 1,
+                       "fetch_errors": 0, "write_errors": 0}
     assert [update["id"] for update in supa.updates] == ["a"]
     assert row["status"] == "SETTLED"

@@ -240,4 +243,56 @@ def test_run_settlement_pass_counts_conditional_update_miss_as_skipped(monkeypat
 def test_run_settlement_pass_no_open_predictions():
     supa = _FakeSupaIO([])
     summary = settlement.run_settlement_pass(supa, lambda _t: (_ for _ in ()).throw(AssertionError("must not fetch")))
-    assert summary == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
+    assert summary == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0, "fetch_errors": 0, "write_errors": 0}
+
+
+def test_settled_row_keeps_engine_inputs_and_stamps_settlement():
+    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5, "raw_payload": {"highs": {"gfs": 71.2}}}
+    market = {"market": {"status": "finalized", "result": "yes"}}
+    update = settlement.settle_prediction_row(row, market)
+    assert "raw_payload" not in update  # the engine's inputs are never overwritten
+    assert update["settlement_payload"] == market
+    assert update["settled_at"]
+
+
+def test_run_settlement_pass_fetches_each_ticker_once():
+    rows = [_open_row(f"h{i}", "KXFINAL-YES", 0.7, 0.5) for i in range(24)]
+    market = {"market": {"status": "finalized", "result": "yes"}}
+    calls = []
+
+    def fetch(ticker):
+        calls.append(ticker)
+        return market
+
+    summary = settlement.run_settlement_pass(_FakeSupaIO(rows), fetch)
+    assert calls == ["KXFINAL-YES"]
+    assert summary["settled"] == 24
+
+
+def test_run_settlement_pass_failed_fetch_skips_all_rows_for_that_ticker_once():
+    rows = [_open_row(f"h{i}", "KXDOWN", 0.7, 0.5) for i in range(3)]
+    calls = []
+
+    def fetch(ticker):
+        calls.append(ticker)
+        raise ValueError("429 Too Many Requests")
+
+    summary = settlement.run_settlement_pass(_FakeSupaIO(rows), fetch)
+    assert calls == ["KXDOWN"]
+    assert summary["fetch_errors"] == 1 and summary["skipped"] == 3
+
+
+def test_run_settlement_pass_isolates_write_errors(monkeypatch):
+    rows = [_open_row("a", "KXFINAL-YES", 0.7, 0.5), _open_row("b", "KXFINAL-YES", 0.6, 0.5)]
+    market = {"market": {"status": "finalized", "result": "yes"}}
+    supa = _FakeSupaIO(rows)
+    real_apply = settlement.apply_prediction_settlement
+
+    def flaky_apply(client, update):
+        if update["id"] == "a":
+            raise RuntimeError("PostgREST 500")
+        return real_apply(client, update)
+
+    monkeypatch.setattr(settlement, "apply_prediction_settlement", flaky_apply)
+    summary = settlement.run_settlement_pass(supa, lambda _t: market)
+    assert summary["write_errors"] == 1 and summary["settled"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -q`
Expected: FAIL. The summary dicts lack `fetch_errors`/`write_errors`, updates carry `raw_payload`, and the market is fetched 24 times.

- [ ] **Step 3: Implement** by applying:

```diff
diff --git a/tradehub/settlement.py b/tradehub/settlement.py
index 0ea4743..b365cad 100644
--- a/tradehub/settlement.py
+++ b/tradehub/settlement.py
@@ -8,6 +8,7 @@ portfolio settlement history, which covers only owned positions.

 from __future__ import annotations

+from datetime import UTC, datetime
 from typing import Any

 PREDICTIONS_TABLE = "predictions"
@@ -61,24 +62,28 @@ def is_market_canceled(market: Any) -> bool:
     return parse_market_result(market)[0] == CANCELED


-def settle_prediction_row(row: dict[str, Any], market: Any) -> dict[str, Any] | None:
+def settle_prediction_row(row: dict[str, Any], market: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
     """Build the `predictions` update payload for one row against a fetched market.

     Returns None when the market is still open (caller skips the row).
     A canceled market yields a CANCELED payload with no fabricated result.
+    The Kalshi payload goes to `settlement_payload`; the engine's own
+    `raw_payload` (its inputs) is never overwritten.
     """
     disposition, outcome = parse_market_result(market)
     if disposition == OPEN:
         return None
+    settled_at = (now or datetime.now(UTC)).isoformat()
     if disposition == CANCELED:
-        return {"id": row["id"], "status": CANCELED}
+        return {"id": row["id"], "status": CANCELED, "settlement_payload": market, "settled_at": settled_at}
     outcome_str = "yes" if outcome == 1 else "no"
     update: dict[str, Any] = {
         "id": row["id"],
         "status": SETTLED,
         "result": outcome_str,
         "brier": round(brier_score(float(row["our_prob"]), outcome), 5),
-        "raw_payload": market,
+        "settlement_payload": market,
+        "settled_at": settled_at,
     }
     market_prob = row.get("market_prob")
     update["market_brier"] = (
@@ -124,23 +129,42 @@ def run_settlement_pass(supa, fetch_market) -> dict[str, int]:
     """One idempotent settlement pass over all OPEN predictions.

     `fetch_market(ticker)` is injected so tests can fake it; the cron
-    entrypoint passes the real Kalshi client. Fetch failures (404 unknown
-    ticker, wrong demo/prod base URL, connection errors) skip the row —
-    they never fabricate a result and never block the rest of the pass.
+    entrypoint passes the real Kalshi client. Each ticker is fetched at most
+    once per pass (the hourly scan writes many rows per market). Fetch
+    failures (404 unknown ticker, 429, connection errors) skip that ticker's
+    rows and are counted in `fetch_errors`; a failed write skips its row and
+    is counted in `write_errors`. Neither fabricates a result or blocks the
+    rest of the pass.
     """
-    summary = {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
+    summary = {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0, "fetch_errors": 0, "write_errors": 0}
+    markets: dict[str, Any] = {}
+    failed: set[str] = set()
+    now = datetime.now(UTC)
     for row in fetch_open_predictions(supa):
         summary["checked"] += 1
-        try:
-            market = fetch_market(row["market_ticker"])
-        except Exception:  # noqa: BLE001 - injected fetcher failures must skip the row
+        ticker = row["market_ticker"]
+        if ticker in failed:
             summary["skipped"] += 1
             continue
-        update = settle_prediction_row(row, market)
+        if ticker not in markets:
+            try:
+                markets[ticker] = fetch_market(ticker)
+            except Exception:  # noqa: BLE001 - injected fetcher failures must skip the ticker
+                failed.add(ticker)
+                summary["fetch_errors"] += 1
+                summary["skipped"] += 1
+                continue
+        update = settle_prediction_row(row, markets[ticker], now=now)
         if update is None:
             summary["skipped"] += 1
             continue
-        if not apply_prediction_settlement(supa, update):
+        try:
+            written = apply_prediction_settlement(supa, update)
+        except Exception:  # noqa: BLE001 - one bad write must not abort the pass
+            summary["write_errors"] += 1
+            summary["skipped"] += 1
+            continue
+        if not written:
             summary["skipped"] += 1
             continue
         if update["status"] == SETTLED:
```

- [ ] **Step 4: Run to verify they pass**

Run the same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/settlement.py tests/test_settlement.py
git commit -m "fix: keep engine inputs on settlement, fetch each market once per pass

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Cron wiring, error message, tracker

**Intent:**
- `settle_predictions.main()` reports `track_record_refreshed` as `["weather@v1", ...]`, one entry per upserted version.
- The docstring names the VPS timer, not Azure.
- `get_client()`'s error names the real variable, `SUPABASE_SERVICE_ROLE_KEY`.

- [ ] **Step 1: Update the test** by applying:

```diff
diff --git a/tests/test_settle_predictions.py b/tests/test_settle_predictions.py
index f50a15c..943bf8b 100644
--- a/tests/test_settle_predictions.py
+++ b/tests/test_settle_predictions.py
@@ -36,7 +36,7 @@ def test_main_wires_pass_and_refresh(monkeypatch, capsys):

     def fake_refresh(supa, engine, **kwargs):
         refreshed.append(engine)
-        return {"engine": engine}
+        return [{"engine": engine, "engine_version": "v1"}]

     monkeypatch.setattr(settle_predictions, "get_client", fake_get_client)
     monkeypatch.setattr(settle_predictions, "fetch_market", fake_fetch_market)
@@ -49,4 +49,4 @@ def test_main_wires_pass_and_refresh(monkeypatch, capsys):
     assert refreshed == ["weather", "macro"]
     out = json.loads(capsys.readouterr().out)
     assert out["checked"] == 3
-    assert out["track_record_refreshed"] == ["weather", "macro"]
+    assert out["track_record_refreshed"] == ["weather@v1", "macro@v1"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settle_predictions.py -q`
Expected: FAIL. The output has `["weather", "macro"]` instead of the `@v1` entries.

- [ ] **Step 3: Implement** by applying:

```diff
diff --git a/tradehub/core/supabase_client.py b/tradehub/core/supabase_client.py
index 73a098c..f7ac362 100644
--- a/tradehub/core/supabase_client.py
+++ b/tradehub/core/supabase_client.py
@@ -22,7 +22,7 @@ def get_client():
     global _client
     if _client is None:
         if not SUPABASE_URL or not SUPABASE_KEY:
-            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
+            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (environment or .env)")
         from supabase import create_client
         _client = create_client(SUPABASE_URL, SUPABASE_KEY)
     return _client
diff --git a/tradehub/scripts/settle_predictions.py b/tradehub/scripts/settle_predictions.py
index 124ad69..085d7ef 100644
--- a/tradehub/scripts/settle_predictions.py
+++ b/tradehub/scripts/settle_predictions.py
@@ -1,7 +1,7 @@
 """Cron entrypoint: settle open predictions against Kalshi market results.

 Runs one settlement pass and refreshes each engine's track record, then
-exits. Designed for an hourly cron on Azure scale-to-zero — there is no
+exits. Run hourly by the VPS `tradehub-settle.timer` — there is no
 polling loop here. Simulated P&L wiring (spec section 4.5's fees+spread
 term) lands with the paper-trading work; until then the gate receives
 None and promotion stays blocked on that criterion.
@@ -35,8 +35,8 @@ def main() -> int:
     summary = run_settlement_pass(supa, fetch_market)
     refreshed = []
     for engine, cadence in ENGINES:
-        refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
-        refreshed.append(engine)
+        payloads = refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
+        refreshed.extend(f"{engine}@{p['engine_version']}" for p in payloads)
     summary["track_record_refreshed"] = refreshed
     print(json.dumps(summary))
     return 0
```

In `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, set the step 2b row's status to `✅ implemented on branch, review pending`.

- [ ] **Step 4: Full suite and lint**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
```
Expected: everything passes (292 on top of `31b66b1`; the count grows if PR #3/#4 fixes added tests), and `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/settle_predictions.py tradehub/core/supabase_client.py tests/test_settle_predictions.py docs/superpowers/plans/2026-09-24-rollout-tracker.md
git commit -m "fix: report per-version track records from the settle job

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After merge (Kevin)

Apply `20260416000007` to Supabase together with the earlier unapplied migrations (`000003`–`000006`), in filename order, before the first VPS scan/settle run.

## Out of Scope

- **Simulated P&L wiring** (the gate's last criterion). It lands with paper trading; until then no engine can be promoted.
- **A unique key on `predictions`.** Contract weighting makes duplicate hourly rows harmless for the gate. Deduping them would need an hour-bucket column, because `date_trunc` on `timestamptz` isn't immutable and can't be indexed.
- **Keyset pagination and a per-pass time budget.** With the per-ticker cache, one pass makes one request per open market (tens, not thousands).

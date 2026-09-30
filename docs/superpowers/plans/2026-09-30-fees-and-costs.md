# Fees and Costs Spine (Plan h) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin Kalshi's fee schedule with mutation-grade tests, record each market-linked forecast's frozen quote, and make promotion require positive simulated P&L after the taker fee and the spread.

**Architecture:** `tests/test_kalshi_fee_pins.py` states the published schedule three independent ways, then rewrites `shared/kalshi_fees.py` in memory (12 mutants) and requires the pins to fail for every one. `tradehub/journal/costs.py` replays each settled, market-linked forecast as a one-contract taker trade with the same `best_side` and `kalshi_fee_cents` the live edge layer uses. `score()` gains a `costs` block and a promotion-gate reason; the frozen top of book rides in each Kalshi-linked forecast's payload.

**Tech Stack:** Python 3.12, PostgreSQL (one additive column), React + TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§10 promotion gate, §12 fees and testing spine). **Depends on:** plans (a)–(f) merged (they are); plan (g) is independent.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1415 passed at monotonic 5.0 and at 1e7; vitest 463 passed, tsc and eslint clean; all 12 fee mutants caught; trigger/migration tests pass on real Postgres 16). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Deploy order:** the code upserts `journal_scores.costs`, so migration `20260428000015` must be applied **before** the code deploys (PostgREST rejects an unknown column). State this in the PR; the reviewer applies it.
- Costs apply only when the baseline is the market. Climatology-graded forecasters (direction targets) have `costs = {}` and no fee gate, because no Kalshi trade exists to price.
- `frozen_quote` accepts only a sane book (0 <= bid <= ask <= 1). A market-linked forecaster with no recorded quotes can never promote (`no frozen quotes recorded`), which is the conservative direction for rows frozen before this change.
- The simulated trade is deliberately simple and conservative: one contract, taker, at the visible ask, only when the after-fee edge is positive and the price clears the existing 10c no-longshot floor (`edges.MIN_TAKER_PRICE`). It is a gate input, not a claim about real fills.

---
### Task 1: Pin the fee schedule with mutation-grade tests

**Files:**
- Create: `tests/test_kalshi_fee_pins.py`

**Interfaces:**
- Consumes: `shared.kalshi_fees.{kalshi_fee_cents, net_edge_pct}` (existing, unchanged).
- Produces: `pins(module)` (the assertions), `MUTATIONS` (12 named source rewrites), and one parametrised test that fails if any mutant passes the pins.

- [ ] **Step 1: Write the test** (`tests/test_kalshi_fee_pins.py`)

```python
"""Fee-schedule pins with mutation-grade teeth (v2 spec §12).

The fee schedule is published: taker = ceil(0.07 * C * P * (1 - P)) dollars, maker = ceil(0.0175 * ...).
`pins()` states that schedule three independent ways (an exact-fraction reference, a golden table,
and structural properties). The mutation tests then rewrite `shared/kalshi_fees.py` in memory, one
constant or rounding rule at a time, and require `pins()` to FAIL for every mutant. A pin that
survives a mutation would be decoration.
"""

from fractions import Fraction
from math import ceil
from pathlib import Path

import pytest

import shared.kalshi_fees as fees

SOURCE = Path(fees.__file__).read_text(encoding="utf-8")
PRICES = range(101)
COUNTS = (1, 2, 3, 7, 10, 25, 100, 1000, 99999)  # 99999 exposes a one-part-in-10000 denominator error


def reference_cents(price: int, contracts: int, *, maker: bool) -> int:
    rate = Fraction(7, 400) if maker else Fraction(7, 100)  # 0.0175 and 0.07, exactly
    p = Fraction(price, 100)
    return ceil(rate * contracts * p * (1 - p) * 100)  # dollars -> cents, rounded UP once, on the total


GOLDEN = {  # (price cents, contracts, maker) -> total fee cents; hand-checked against the published formula
    (50, 1, False): 2, (50, 1, True): 1, (50, 100, False): 175, (50, 100, True): 44,
    (10, 100, False): 63, (90, 100, False): 63, (5, 1, False): 1, (95, 1, False): 1,
    (0, 100, False): 0, (100, 100, False): 0, (44, 10, False): 18, (20, 25, True): 7,
    (10.5, 100, False): 69,  # half a cent rounds UP to 11c (63 would mean half-even, 10c)
}


def pins(module) -> None:
    for price in PRICES:
        for contracts in COUNTS:
            for maker in (False, True):
                got = module.kalshi_fee_cents(float(price), contracts=contracts, maker=maker)
                assert got == reference_cents(price, contracts, maker=maker), (price, contracts, maker, got)
    for (price, contracts, maker), cents in GOLDEN.items():
        assert module.kalshi_fee_cents(price, contracts=contracts, maker=maker) == cents
    for price in PRICES:  # symmetry: a YES at p and a NO at 100-p cost the same
        assert module.kalshi_fee_cents(float(price)) == module.kalshi_fee_cents(float(100 - price))
    assert module.kalshi_fee_cents(50.0, contracts=0) == 0.0  # nothing traded, nothing owed
    assert module.kalshi_fee_cents(49.5) == module.kalshi_fee_cents(50.0)  # half-cents round half up
    assert module.net_edge_pct(60.0, 50.0) == pytest.approx(10.0 - 2.0)  # the fee always works against you
    assert module.net_edge_pct(40.0, 50.0) == pytest.approx(-10.0 - 2.0)


def test_the_real_schedule_satisfies_every_pin():
    pins(fees)


MUTATIONS = {
    "taker rate 7 -> 6": ("7 * contracts * p * (100 - p)", "6 * contracts * p * (100 - p)"),
    "taker rate 7 -> 8": ("7 * contracts * p * (100 - p)", "8 * contracts * p * (100 - p)"),
    "maker share 40000 -> 30000": ("40000 if maker else 10000", "30000 if maker else 10000"),
    "maker share 40000 -> 20000": ("40000 if maker else 10000", "20000 if maker else 10000"),
    "taker denominator 10000 -> 10001": ("40000 if maker else 10000", "40000 if maker else 10001"),
    "round up -> round down": ("(numerator + denominator - 1) // denominator", "numerator // denominator"),
    "round up -> round nearest": ("(numerator + denominator - 1) // denominator",
                                  "(numerator + denominator // 2) // denominator"),
    "price rounding half-up -> half-even": ("rounding=ROUND_HALF_UP", "rounding=__import__('decimal').ROUND_HALF_EVEN"),
    "price clamp 100 -> 99": ("min(100, int(rounded))", "min(99, int(rounded))"),
    "fee per order not per contract": ("7 * contracts * p", "7 * 1 * p"),
    "maker pays the taker rate": ("40000 if maker else 10000", "10000"),
    "fee subtracted with the wrong sign": ("return gross_edge_pct - fee_pct_per_contract",
                                           "return gross_edge_pct + fee_pct_per_contract"),
}


def _load(source: str):
    namespace: dict = {"__name__": "mutant"}
    exec(compile(source, "mutant_kalshi_fees", "exec"), namespace)  # noqa: S102 - our own source, mutated
    return type("Mutant", (), namespace)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_fee_mutation_is_caught_by_the_pins(name):
    old, new = MUTATIONS[name]
    assert SOURCE.count(old) == 1, f"mutation anchor {old!r} must appear exactly once in kalshi_fees.py"
    with pytest.raises((AssertionError, ZeroDivisionError)):
        pins(_load(SOURCE.replace(old, new)))
```

- [ ] **Step 2: Run it** — it passes at once, because the schedule is already correct; the mutation tests are what give it teeth.

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_kalshi_fee_pins.py -v`
Expected: 13 passed (1 real-schedule pin test + 12 mutants, each proven to be caught).

- [ ] **Step 3: Prove a pin can fail** (do not commit): in `shared/kalshi_fees.py` change `TAKER_RATE`-equivalent `7 * contracts` to `6 * contracts`, run `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_kalshi_fee_pins.py -k real_schedule`, expect FAIL, then `git checkout -- shared/kalshi_fees.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_kalshi_fee_pins.py
git commit -m "test: pin Kalshi's fee schedule; twelve mutants must all fail"
```

---

### Task 2: Costs module, recorded quotes, and the net-of-costs gate

**Files:**
- Create: `tradehub/journal/costs.py`, `market_sentiment_tool/supabase/migrations/20260428000015_journal_costs.sql`, `tests/test_journal_costs.py`
- Modify: `tradehub/journal/scoring.py`, `tradehub/journal/kalshi_linked.py`, `tradehub/journal/forecasters/cpi.py`, `tradehub/journal/forecasters/fomc.py`, `tradehub/journal/forecasters/labor.py`
- Test: `tests/test_journal_costs.py` (create), `tests/test_journal_scoring.py`, `tests/test_journal_cpi_fomc.py`, `tests/test_journal_migration_pg.py` (modify)

**Interfaces:**
- Consumes: `tradehub.edges.{best_side, MIN_TAKER_PRICE}`, `shared.kalshi_fees.kalshi_fee_cents`, plan (b) `kalshi_linked`.
- Produces: `frozen_quote(payload) -> (bid, ask) | None`; `simulated_trade(our_prob, yes_bid, yes_ask, outcome) -> {gross_cents, fee_cents, net_cents} | None`; `cost_summary(pairs) -> {n_quoted, n_traded, gross_pnl_cents, fees_cents, net_pnl_cents}`; `kalshi_linked.quote_payload(lm) -> {yes_bid, yes_ask}`; `score()` returns an extra key `costs` (`{}` unless `baseline == "market"`); `journal_scores.costs jsonb NOT NULL DEFAULT '{}'`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_journal_costs.py`:

```python
import pytest

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.journal.costs import cost_summary, frozen_quote, simulated_trade


def test_a_quote_needs_both_sides_and_a_sane_book():
    assert frozen_quote({"yes_bid": 0.4, "yes_ask": 0.44}) == (0.4, 0.44)
    assert frozen_quote({"yes_bid": None, "yes_ask": 0.44}) is None
    assert frozen_quote({"yes_bid": 0.5, "yes_ask": 0.4}) is None  # crossed
    assert frozen_quote({}) is None and frozen_quote(None) is None


def test_a_yes_trade_pays_the_ask_and_the_fee_and_settles_at_par():
    won = simulated_trade(0.80, 0.58, 0.62, outcome=1)
    assert won["gross_cents"] == pytest.approx(38.0)  # 100 - 62
    assert won["fee_cents"] == kalshi_fee_cents(62.0)
    assert won["net_cents"] == pytest.approx(38.0 - won["fee_cents"])
    lost = simulated_trade(0.80, 0.58, 0.62, outcome=0)
    assert lost["gross_cents"] == pytest.approx(-62.0) and lost["net_cents"] < -62.0


def test_a_no_trade_pays_the_no_ask_which_is_one_minus_the_yes_bid():
    trade = simulated_trade(0.10, 0.58, 0.62, outcome=0)  # we think NO; buy NO at 1 - 0.58 = 42c
    assert trade["gross_cents"] == pytest.approx(100.0 - 42.0)


def test_no_edge_after_fees_means_no_trade_and_longshots_are_not_taken():
    assert simulated_trade(0.61, 0.58, 0.62, outcome=1) is None  # below the ask: nothing to buy
    assert simulated_trade(0.99, 0.02, 0.06, outcome=1) is None  # a 6c ask is under the 10c taker floor


def test_the_summary_counts_quoted_and_traded_separately():
    pairs = [
        {"probability": 0.8, "outcome": 1, "payload": {"yes_bid": 0.58, "yes_ask": 0.62}},   # trades, wins
        {"probability": 0.61, "outcome": 1, "payload": {"yes_bid": 0.58, "yes_ask": 0.62}},  # quoted, no trade
        {"probability": 0.9, "outcome": 1, "payload": {}},                                     # no quote at all
    ]
    summary = cost_summary(pairs)
    assert (summary["n_quoted"], summary["n_traded"]) == (2, 1)
    assert summary["net_pnl_cents"] == pytest.approx(summary["gross_pnl_cents"] - summary["fees_cents"])
```

Apply these test changes (they fail until Step 3):

```diff
diff --git a/tests/test_journal_cpi_fomc.py b/tests/test_journal_cpi_fomc.py
index 44fec84..92aac5b 100644
--- a/tests/test_journal_cpi_fomc.py
+++ b/tests/test_journal_cpi_fomc.py
@@ -60,6 +60,7 @@ def test_cpi_forecaster_reproduces_the_scan_probability_and_freezes_the_market_m
     assert forecast.probability == pytest.approx(0.5244, abs=1e-4)  # same number test_scan_cpi pins
     assert forecast.market_prob == pytest.approx(0.32)
     assert forecast.payload["nowcast_obs"] == "CPI:2026-08@2026-09-10"
+    assert (forecast.payload["yes_bid"], forecast.payload["yes_ask"]) == (0.30, 0.34)  # frozen for cost netting
 
 
 def test_only_markets_inside_the_freeze_lead_are_targets():
diff --git a/tests/test_journal_migration_pg.py b/tests/test_journal_migration_pg.py
index 7ad31f7..85e774d 100644
--- a/tests/test_journal_migration_pg.py
+++ b/tests/test_journal_migration_pg.py
@@ -18,6 +18,7 @@ import pytest
 MIGRATION = Path(__file__).resolve().parents[1] / (
     "market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql"
 )
+COSTS_MIGRATION = MIGRATION.with_name("20260428000015_journal_costs.sql")
 
 
 def _docker_ok() -> bool:
@@ -47,9 +48,10 @@ def pg():
 
         # Supabase has these roles; a plain postgres does not.
         assert run("CREATE ROLE anon; CREATE ROLE authenticated;").returncode == 0
-        for _ in range(2):  # applied twice: the migration must be idempotent
-            applied = run(MIGRATION.read_text(encoding="utf-8"))
-            assert applied.returncode == 0, applied.stderr
+        for _ in range(2):  # applied twice: the migrations must be idempotent
+            for migration in (MIGRATION, COSTS_MIGRATION):
+                applied = run(migration.read_text(encoding="utf-8"))
+                assert applied.returncode == 0, applied.stderr
         yield run
     finally:
         subprocess.run(["docker", "rm", "-f", name], capture_output=True)  # noqa: PLW1510
@@ -130,3 +132,10 @@ def test_clients_have_no_write_privilege(pg):
     out = pg("SELECT count(*) FROM information_schema.role_table_grants WHERE grantee IN ('anon','authenticated') "
              "AND table_name LIKE 'journal_%' AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE');")
     assert out.returncode == 0 and out.stdout.strip() == "0"
+
+
+def test_the_costs_column_exists_and_defaults_to_an_empty_object(pg):
+    out = pg("INSERT INTO journal_scores (forecaster, forecaster_version, cadence, baseline) "
+             "VALUES ('c', 'v1', 'daily', 'none'); SELECT costs::text FROM journal_scores WHERE forecaster = 'c';")
+    assert out.returncode == 0, out.stderr
+    assert out.stdout.strip().splitlines()[-1] == "{}"
diff --git a/tests/test_journal_scoring.py b/tests/test_journal_scoring.py
index 40d4e3b..8354890 100644
--- a/tests/test_journal_scoring.py
+++ b/tests/test_journal_scoring.py
@@ -6,8 +6,11 @@ from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
 from tradehub.journal.scoring import MIN_BUCKET_TARGETS, murphy, reliability, score, settled_pairs
 
 
-def _row(target, prob, market=None, rebuilt=False):
-    return {"target": target, "probability": prob, "market_prob": market, "rebuilt": rebuilt}
+def _row(target, prob, market=None, rebuilt=False, quote=None):
+    row = {"target": target, "probability": prob, "market_prob": market, "rebuilt": rebuilt}
+    if quote is not None:
+        row["payload"] = {"yes_bid": quote[0], "yes_ask": quote[1]}
+    return row
 
 
 def test_contract_rejects_naive_times_and_bad_values():
@@ -63,7 +66,7 @@ def test_gate_counts_monthly_at_50_and_daily_at_200():
 
 
 def test_promotion_needs_positive_skill_and_calibrated_buckets():
-    good = [_row(f"g{i}", 0.95, market=0.6) for i in range(MIN_BUCKET_TARGETS * 3)]
+    good = [_row(f"g{i}", 0.95, market=0.6, quote=(0.58, 0.62)) for i in range(MIN_BUCKET_TARGETS * 3)]
     card = score(good, {r["target"]: 1 for r in good}, {}, "monthly")
     assert card["calibration_ready"] and card["bss"] > 0
     assert card["gate_status"] == "PROMOTED", card["gate_reasons"]
@@ -81,3 +84,29 @@ def test_reliability_is_confidence_space_and_murphy_adds_up():
     brier = sum((p["probability"] - p["outcome"]) ** 2 for p in pairs) / len(pairs)
     # Binned Murphy is exact when every bin holds a single forecast value, as here.
     assert m["reliability"] - m["resolution"] + m["uncertainty"] == pytest.approx(brier, abs=1e-6)
+
+
+def test_a_market_forecaster_with_no_frozen_quotes_cannot_promote():
+    rows = [_row(f"g{i}", 0.95, market=0.6) for i in range(MIN_BUCKET_TARGETS * 3)]
+    card = score(rows, {r["target"]: 1 for r in rows}, {}, "monthly")
+    assert card["bss"] > 0 and card["gate_status"] == "SHADOW"
+    assert any("no frozen quotes" in r for r in card["gate_reasons"])
+    assert card["costs"]["n_quoted"] == 0
+
+
+def test_skill_that_fees_and_spread_eat_does_not_promote():
+    # Forecast 0.75 against a 0.60 mid, with a wide 50/70 book. At a 70% hit rate the Brier skill vs
+    # the market is positive (it beats 0.60 whenever the hit rate is above 0.675), but buying at the
+    # 70c ask plus a 2c fee needs a 72% hit rate to break even: the edge exists only before costs.
+    rows = [_row(f"t{i}", 0.75, market=0.60, quote=(0.50, 0.70)) for i in range(60)]
+    settle = {r["target"]: int(i < 42) for i, r in enumerate(rows)}
+    card = score(rows, settle, {}, "monthly")
+    assert card["bss"] > 0 and card["costs"]["n_traded"] == 60
+    assert card["costs"]["net_pnl_cents"] == pytest.approx(42 * (30 - 2) + 18 * (-70 - 2))  # -100
+    assert card["gate_status"] == "SHADOW" and any("after fees and spread" in r for r in card["gate_reasons"])
+
+
+def test_climatology_baselines_carry_no_cost_block():
+    rows = [_row(f"c{i}", 0.9) for i in range(5)]
+    card = score(rows, {r["target"]: 1 for r in rows}, {r["target"]: {"climatology_prob": 0.5} for r in rows}, "daily")
+    assert card["baseline"] == "climatology" and card["costs"] == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_costs.py tests/test_journal_scoring.py tests/test_journal_cpi_fomc.py -v`
Expected: FAIL — `No module named 'tradehub.journal.costs'`.

- [ ] **Step 3: Implement**

`tradehub/journal/costs.py`:

```python
"""What trading a frozen forecast would have cost (v2 spec §10, §12).

The journal's headline edge is model probability minus the market mid, which is gross of both the
Kalshi taker fee and the half-spread paid to cross the book. Promotion needs the edge *net* of those
costs, so this module replays each settled, market-linked forecast as a one-contract taker trade:
buy the side with the larger after-fee edge at its visible ask, only when that edge is positive and the
price clears the no-longshot floor (`edges.MIN_TAKER_PRICE`), and settle it at 0 or 100 cents. It uses
the same `best_side` and `kalshi_fee_cents` as the live edge layer, so the two cannot disagree.
"""

from __future__ import annotations

from typing import Any

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.edges import MIN_TAKER_PRICE, best_side


def frozen_quote(payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """(yes_bid, yes_ask) in dollars from a forecast payload, or None when either side was not recorded."""
    bid, ask = (payload or {}).get("yes_bid"), (payload or {}).get("yes_ask")
    if bid is None or ask is None or not 0.0 <= float(bid) <= float(ask) <= 1.0:
        return None
    return float(bid), float(ask)


def simulated_trade(our_prob: float, yes_bid: float, yes_ask: float, outcome: int) -> dict[str, float] | None:
    """The one-contract taker trade the forecast would have made, or None when it would not trade."""
    side, price, edge_pct = best_side(our_prob, yes_ask, round(1.0 - yes_bid, 4), maker=False)
    if edge_pct <= 0 or price < MIN_TAKER_PRICE:
        return None
    won = outcome == 1 if side == "yes" else outcome == 0
    fee = kalshi_fee_cents(price * 100.0)
    gross = (100.0 if won else 0.0) - price * 100.0
    return {"gross_cents": gross, "fee_cents": fee, "net_cents": gross - fee}


def cost_summary(pairs: list[dict[str, Any]]) -> dict[str, float | int]:
    """Totals over settled forecasts: how many carried a quote, how many would have traded, and the P&L."""
    quoted = traded = 0
    gross = fees = 0.0
    for row in pairs:
        quote = frozen_quote(row.get("payload"))
        if quote is None:
            continue
        quoted += 1
        trade = simulated_trade(float(row["probability"]), quote[0], quote[1], int(row["outcome"]))
        if trade is None:
            continue
        traded += 1
        gross += trade["gross_cents"]
        fees += trade["fee_cents"]
    return {"n_quoted": quoted, "n_traded": traded, "gross_pnl_cents": round(gross, 2),
            "fees_cents": round(fees, 2), "net_pnl_cents": round(gross - fees, 2)}
```

`market_sentiment_tool/supabase/migrations/20260428000015_journal_costs.sql`:

```sql
-- 20260428000015: net-of-costs summary on the journal scorecard (v2 spec §10, §12).
--
-- journal_scores.costs holds, for market-linked forecasters, {n_quoted, n_traded, gross_pnl_cents,
-- fees_cents, net_pnl_cents}: the simulated one-contract taker P&L of every settled forecast after
-- Kalshi's fee and the half-spread. Empty ({}) for forecasters graded against climatology.
-- Apply BEFORE deploying the code that upserts the column. Idempotent.

ALTER TABLE journal_scores ADD COLUMN IF NOT EXISTS costs jsonb NOT NULL DEFAULT '{}'::jsonb;
NOTIFY pgrst, 'reload schema';
```

Apply these changes:

```diff
diff --git a/tradehub/journal/forecasters/cpi.py b/tradehub/journal/forecasters/cpi.py
index 77f227f..67acbd2 100644
--- a/tradehub/journal/forecasters/cpi.py
+++ b/tradehub/journal/forecasters/cpi.py
@@ -17,7 +17,14 @@ from tradehub.data.kalshi_live import LiveMarket
 from tradehub.engine_config import load_engine_config
 from tradehub.engines.cpi import CPI_TARGETS, CPI_TRAIN_MONTHS, cpi_prob, fit_cpi_error, latest_nowcast, training_pairs
 from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
-from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
+from tradehub.journal.kalshi_linked import (
+    entry_for,
+    in_freeze_window,
+    kalshi_target,
+    quote_mid,
+    quote_payload,
+    settle_on_kalshi,
+)
 from tradehub.markets import event_month
 
 CPI_ENGINE = "cpi_nowcast"
@@ -58,7 +65,8 @@ class CpiForecaster:
         model = fit_cpi_error(pairs, window=self._window, use_bias=self._use_bias)
         return Forecast(self.name, self.version, entry.target, cpi_prob(lm.market, nowcast.value, model),
                         market_prob=quote_mid(lm),
-                        payload={"nowcast": nowcast.value, "nowcast_obs": nowcast.name, "bias": model.bias,
+                        payload={**quote_payload(lm), "nowcast": nowcast.value, "nowcast_obs": nowcast.name,
+                                 "bias": model.bias,
                                  "sigma": model.sigma, "n_train": len(pairs),
                                  "hours_to_close": round(horizon.total_seconds() / 3600.0, 2)})
 
diff --git a/tradehub/journal/forecasters/fomc.py b/tradehub/journal/forecasters/fomc.py
index b9d8ee0..b9cd4fe 100644
--- a/tradehub/journal/forecasters/fomc.py
+++ b/tradehub/journal/forecasters/fomc.py
@@ -23,7 +23,14 @@ from tradehub.data.cleveland_fed import fetch_nowcast_history
 from tradehub.data.kalshi_live import LiveMarket
 from tradehub.engines.cpi import latest_nowcast
 from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
-from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
+from tradehub.journal.kalshi_linked import (
+    entry_for,
+    in_freeze_window,
+    kalshi_target,
+    quote_mid,
+    quote_payload,
+    settle_on_kalshi,
+)
 
 FOMC_SERIES = "KXFEDDECISION"
 HOLD_SUFFIX = "-H0"
@@ -72,7 +79,7 @@ class FomcMapped:
             return None
         return Forecast(self.name, self.version, entry.target, hold_probability(core.value),
                         market_prob=quote_mid(lm),
-                        payload={"core_nowcast": core.value, "core_obs": core.name, "experimental": True,
+                        payload={**quote_payload(lm), "core_nowcast": core.value, "core_obs": core.name, "experimental": True,
                                  "hold_prior": HOLD_PRIOR, "slope": SLOPE, "band": BAND})
 
     def settle(self, target: str, now: datetime) -> Settlement | None:
diff --git a/tradehub/journal/forecasters/labor.py b/tradehub/journal/forecasters/labor.py
index c8542fb..c68e3db 100644
--- a/tradehub/journal/forecasters/labor.py
+++ b/tradehub/journal/forecasters/labor.py
@@ -46,7 +46,14 @@ from tradehub.engines.labor_direction import (
     with_quits_feature,
 )
 from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
-from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
+from tradehub.journal.kalshi_linked import (
+    entry_for,
+    in_freeze_window,
+    kalshi_target,
+    quote_mid,
+    quote_payload,
+    settle_on_kalshi,
+)
 from tradehub.markets import event_month
 
 ET = ZoneInfo("America/New_York")
@@ -163,7 +170,8 @@ class PayrollsForecaster:
             return None
         return Forecast(self.name, self.version, entry.target, payroll_prob(lm.market, nc.mu, nc.sigma),
                         market_prob=quote_mid(lm),
-                        payload={"month": month.isoformat(), "mu_k": round(nc.mu, 2), "sigma_k": round(nc.sigma, 2),
+                        payload={**quote_payload(lm), "month": month.isoformat(), "mu_k": round(nc.mu, 2),
+                                 "sigma_k": round(nc.sigma, 2),
                                  "n_train": nc.model.n_train})
 
     def settle(self, target: str, now: datetime) -> Settlement | None:
diff --git a/tradehub/journal/kalshi_linked.py b/tradehub/journal/kalshi_linked.py
index 4b040b8..b21b9e0 100644
--- a/tradehub/journal/kalshi_linked.py
+++ b/tradehub/journal/kalshi_linked.py
@@ -38,6 +38,11 @@ def quote_mid(lm: LiveMarket) -> float | None:
     return (lm.quote.yes_bid + lm.quote.yes_ask) / 2.0
 
 
+def quote_payload(lm: LiveMarket) -> dict[str, float | None]:
+    """The frozen top of book, recorded in every market-linked forecast so its edge can be netted of costs."""
+    return {"yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask}
+
+
 def in_freeze_window(lm: LiveMarket, now: datetime, lead: timedelta = FREEZE_LEAD) -> bool:
     return now < lm.market.close_time <= now + lead
 
@@ -81,7 +86,7 @@ class KalshiImplied:
         if mid is None:
             return None
         return Forecast(self.name, self.version, entry.target, mid, market_prob=mid,
-                        payload={"yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask})
+                        payload=quote_payload(lm))
 
     def settle(self, target: str, now: datetime) -> Settlement | None:
         return settle_on_kalshi(target, self._fetch_market)
diff --git a/tradehub/journal/scoring.py b/tradehub/journal/scoring.py
index 74d8937..45485fd 100644
--- a/tradehub/journal/scoring.py
+++ b/tradehub/journal/scoring.py
@@ -8,6 +8,7 @@ from __future__ import annotations
 
 from typing import Any
 
+from tradehub.journal.costs import cost_summary
 from tradehub.track_record import BUCKETS, bucketize
 
 MIN_SETTLED = {"daily": 200, "monthly": 50, "meeting": 50}
@@ -119,6 +120,7 @@ def score(forecasts: list[dict[str, Any]], settlements: dict[str, int],
 
     buckets = reliability(pairs)
     calibration_ready = bool(buckets) and all(b["n"] >= MIN_BUCKET_TARGETS for b in buckets)
+    costs = cost_summary(pairs) if baseline == "market" else {}
     reasons = []
     if len(pairs) < MIN_SETTLED[cadence]:
         reasons.append(f"only {len(pairs)} settled targets, need {MIN_SETTLED[cadence]} ({cadence})")
@@ -126,6 +128,12 @@ def score(forecasts: list[dict[str, Any]], settlements: dict[str, int],
         reasons.append("no baseline to compare against")
     elif bss <= 0:
         reasons.append(f"Brier skill {bss:.4f} vs {baseline} is not positive")
+    if baseline == "market":  # spec §10: the edge must survive Kalshi's taker fee and the spread
+        if not costs["n_quoted"]:
+            reasons.append("no frozen quotes recorded, so edge cannot be netted of fees and spread")
+        elif costs["net_pnl_cents"] <= 0:
+            reasons.append(f"simulated P&L after fees and spread is {costs['net_pnl_cents']:.1f}c over "
+                           f"{costs['n_traded']} trades, not positive")
     if not calibration_ready:
         reasons.append(f"a calibration bucket has fewer than {MIN_BUCKET_TARGETS} settled targets")
     return {
@@ -138,6 +146,7 @@ def score(forecasts: list[dict[str, Any]], settlements: dict[str, int],
         "bss": round(bss, 6) if bss is not None else None,
         "reliability": buckets,
         "murphy": murphy(pairs) or {},
+        "costs": costs,
         "calibration_ready": calibration_ready,
         "gate_status": "PROMOTED" if not reasons else "SHADOW",
         "gate_reasons": reasons,
```

- [ ] **Step 4: Run to verify it passes** (Docker must be running for the migration test)

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_*.py tests/test_kalshi_fee_pins.py -v`
Expected: all pass. Reference numbers: a forecaster quoting 0.75 against a 50/70 book with 70% hits has Brier skill > 0 and net P&L −100¢, so it stays SHADOW with reason `simulated P&L after fees and spread is -100.0c over 60 trades, not positive`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal market_sentiment_tool/supabase/migrations/20260428000015_journal_costs.sql tests/test_journal_costs.py tests/test_journal_scoring.py tests/test_journal_cpi_fomc.py tests/test_journal_migration_pg.py
git commit -m "feat(journal): promotion needs positive P&L after fees and spread; record frozen quotes"
```

---

### Task 3: Say it on /journal

**Files:**
- Modify: `market_sentiment_tool/src/lib/journal.ts`, `market_sentiment_tool/src/lib/journal.test.ts`, `market_sentiment_tool/src/pages/Journal.tsx`, `market_sentiment_tool/src/pages/Journal.test.tsx`

**Interfaces:**
- Consumes: Task 2's `costs` object on each `/api/journal` scorecard (no API change: it selects `*`).
- Produces: `costsText(score) -> string | null` and a line on every market-graded tile; the edge shown elsewhere on the page is labelled as before costs.

- [ ] **Step 1–3: Apply the change** (the tests and code are one reviewed unit; run the tests first to watch them fail by applying only the `*.test.*` hunks, then the rest):

```diff
diff --git a/market_sentiment_tool/src/lib/journal.test.ts b/market_sentiment_tool/src/lib/journal.test.ts
index f85440b..530b7c9 100644
--- a/market_sentiment_tool/src/lib/journal.test.ts
+++ b/market_sentiment_tool/src/lib/journal.test.ts
@@ -1,6 +1,6 @@
 import { describe, expect, it } from "vitest";
 
-import { biasReadout, pct, skillText, tiles, type JournalScore } from "@/lib/journal";
+import { biasReadout, costsText, pct, skillText, tiles, type JournalScore } from "@/lib/journal";
 
 function score(over: Partial<JournalScore> = {}): JournalScore {
   return {
@@ -56,3 +56,17 @@ describe("wording", () => {
     expect(biasReadout([])).toBeNull();
   });
 });
+
+describe("costsText", () => {
+  it("says what survives fees and spread, in words when nothing was measured", () => {
+    expect(costsText(score({ baseline: "climatology" }))).toBeNull();
+    expect(costsText(score({ costs: {} }))).toBe("After fees and spread: no quoted prices recorded yet");
+    expect(costsText(score({ costs: { n_quoted: 9, n_traded: 0, net_pnl_cents: 0 } }))).toBe(
+      "After fees and spread: no trade would have cleared costs (9 quoted)",
+    );
+    expect(costsText(score({ costs: { n_quoted: 9, n_traded: 4, net_pnl_cents: -12.5 } }))).toBe(
+      "After fees and spread: -12.5¢ over 4 simulated trades (edge above is before costs)",
+    );
+    expect(costsText(score({ costs: { n_quoted: 9, n_traded: 4, net_pnl_cents: 30 } }))).toContain("+30.0¢");
+  });
+});
diff --git a/market_sentiment_tool/src/lib/journal.ts b/market_sentiment_tool/src/lib/journal.ts
index 4367a0e..64d6138 100644
--- a/market_sentiment_tool/src/lib/journal.ts
+++ b/market_sentiment_tool/src/lib/journal.ts
@@ -27,12 +27,22 @@ export interface JournalScore {
   bss: number | null;
   reliability: ReliabilityBucket[];
   murphy: { reliability?: number; resolution?: number; uncertainty?: number };
+  /** Simulated one-contract taker P&L after Kalshi's fee and the spread; {} unless graded vs a market. */
+  costs?: JournalCosts;
   calibration_ready: boolean;
   gate_status: "SHADOW" | "PROMOTED";
   gate_reasons: string[];
   computed_at: string;
 }
 
+export interface JournalCosts {
+  n_quoted?: number;
+  n_traded?: number;
+  gross_pnl_cents?: number;
+  fees_cents?: number;
+  net_pnl_cents?: number;
+}
+
 export interface JournalHeadline {
   forecasters: number;
   calibrated: number;
@@ -147,3 +157,17 @@ export function biasReadout(buckets: ReliabilityBucket[]): string | null {
   const word = gap < 0 ? "overconfident" : "underconfident";
   return `${word} by ${Math.abs(gap).toFixed(1)}pp in the ${top.bucket} bucket (n=${top.n})`;
 }
+
+/**
+ * The edge on the tile is model minus market mid, which is BEFORE Kalshi's fee and the spread. This is
+ * the line that says what survives them. Said in words when nothing was quoted: never a bare 0.
+ */
+export function costsText(score: Pick<JournalScore, "baseline" | "costs">): string | null {
+  if (score.baseline !== "market") return null;
+  const c = score.costs;
+  if (!c || !c.n_quoted) return "After fees and spread: no quoted prices recorded yet";
+  if (!c.n_traded) return `After fees and spread: no trade would have cleared costs (${c.n_quoted} quoted)`;
+  const net = c.net_pnl_cents ?? 0;
+  const sign = net > 0 ? "+" : "";
+  return `After fees and spread: ${sign}${net.toFixed(1)}¢ over ${c.n_traded} simulated trades (edge above is before costs)`;
+}
diff --git a/market_sentiment_tool/src/pages/Journal.test.tsx b/market_sentiment_tool/src/pages/Journal.test.tsx
index ba36934..128842f 100644
--- a/market_sentiment_tool/src/pages/Journal.test.tsx
+++ b/market_sentiment_tool/src/pages/Journal.test.tsx
@@ -69,6 +69,7 @@ describe("Journal", () => {
     expect(within(tile).getByText("Brier skill -0.043 vs the Kalshi market")).toBeInTheDocument();
     expect(within(tile).getByText("Kalshi-implied (kalshi_implied_cpi@v1)")).toBeInTheDocument();
     expect(within(tile).getByText("provisional")).toBeInTheDocument();
+    expect(within(tile).getAllByText(/^After fees and spread: no quoted prices recorded yet/).length).toBeGreaterThan(0);
     expect(within(tile).getByText("only 10 settled targets, need 50 (monthly)")).toBeInTheDocument();
     expect(within(tile).getByText(/overconfident by 15.0pp/)).toBeInTheDocument();
   });
diff --git a/market_sentiment_tool/src/pages/Journal.tsx b/market_sentiment_tool/src/pages/Journal.tsx
index 480502f..1f09051 100644
--- a/market_sentiment_tool/src/pages/Journal.tsx
+++ b/market_sentiment_tool/src/pages/Journal.tsx
@@ -8,6 +8,7 @@ import {
   EXPERIMENTAL,
   biasReadout,
   brierText,
+  costsText,
   key,
   pct,
   settledText,
@@ -42,6 +43,7 @@ function ScoreLines({ score, label }: { score: JournalScore; label?: string }) {
         {brierText(score.brier)}
       </p>
       <p className="text-slate-300">{skillText(score)}</p>
+      {costsText(score) && <p className="text-xs text-slate-400">{costsText(score)}</p>}
       <p className="text-slate-500">{settledText(score)}</p>
     </div>
   );
```

- [ ] **Step 4: Run**

Run: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/lib/journal.ts src/pages/Journal.tsx`
Expected: vitest all pass (reviewer baseline 463), tsc/eslint silent.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src
git commit -m "feat(ui): show what survives fees and spread on each market-graded tile"
```

---

### Task 4: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] In the PR body write: **migration `20260428000015` must be applied before merge** (reviewer does it).
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §12:** fee schedule pinned with mutation-grade tests (any constant or rounding mutation fails: 12 shown to fail); spread-cost modeling via the executable-price replay; the copy on the tile says the edge shown is before costs until the net figure appears.
- **Spec §10:** promotion now needs positive BSS **and** positive simulated P&L net of the taker fee (and the spread, via the ask) wherever a market exists.
- **Type consistency:** `costs` keys (`n_quoted, n_traded, gross_pnl_cents, fees_cents, net_pnl_cents`) are identical in `cost_summary`, the gate reason, `journal.ts` `JournalCosts`, and the tests.

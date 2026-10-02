# Journal Engines Stop Writing Predictions (Roadmap v2 item 14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the scan writing `predictions` rows for `cpi_nowcast` and `labor_nowcast`, the two engines whose record is now the journal.

**Architecture:** One constant, `JOURNAL_ONLY_ENGINES`, names the engines whose forecasts live in the journal. The scan's two prediction-write sites skip them and report `"journal"` in the run summary. Their edges, cleanup and gate lookups are unchanged. Weather and gas have no journal scorecard and keep writing. Sports keeps writing too, deliberately: its `predictions` rows cover every rung of every ladder and are what the reviewer scorecard settles against, so removing them would starve it.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§4 one record per engine). **Depends on:** plans 12 and 13 merged (nothing reads the CPI or labor `predictions` rows after them).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (scan, labor, CPI and cleanup test files green; full suite at both clocks on the final stack). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Owner approval:** this is roadmap decision D2. Kevin said the readers could be repointed; ask him for the explicit go before opening this PR if the roadmap still lists it as pending.
- **Do not delete history:** existing `predictions` rows stay. `settle_predictions` keeps settling the open ones until they are gone.
- **What stays on purpose:** sports `predictions` writes, the reviewer scorecard's read, `scan.unrecorded`'s dedup, weather and gas.
- No migration.

---
### Task 1: Skip the journal engines in the scan

**Files:**
- Modify: `tradehub/scripts/scan.py`, `tests/test_cpi_no_edges.py` (the full-scan test now asserts CPI writes no prediction)
- Create: `tests/test_scan_journal_only.py`

**Interfaces:**
- Produces: `JOURNAL_ONLY_ENGINES = frozenset({'cpi_nowcast', 'labor_nowcast'})` in `tradehub/scripts/scan.py`; the run summary's `writes.predictions[<engine>]` is `"journal"` for those two.

- [ ] **Step 1: Write the failing test** (`tests/test_scan_journal_only.py`)

`tests/test_scan_journal_only.py`:

```python
"""CPI and labor are journal engines: the scan no longer writes their `predictions` rows (plan 14).

Their edges, cleanup and gate lookups are unchanged. Weather, gas and sports keep writing `predictions`:
weather and gas have no journal scorecard, and sports rows are the edge ledger the reviewer scorecard
settles against (every rung of a ladder, not the one the journal picks).
"""
from datetime import datetime, timezone

from test_scan_labor import _base

from tradehub.scripts import scan
from tradehub.scripts.scan import JOURNAL_ONLY_ENGINES

NOW = datetime(2026, 10, 2, 11, 5, tzinfo=timezone.utc)


def _pred(engine, ticker):
    return {"engine": engine, "market_ticker": ticker, "our_prob": 0.5}


def _run(monkeypatch, recorded):
    import tradehub.predictions as predictions

    _base(monkeypatch)
    monkeypatch.setattr(predictions, "record_predictions", lambda client, rows: recorded.extend(rows))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: True)
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([_pred("weather", "W")], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([_pred("gas", "G")], []))
    monkeypatch.setattr(scan, "scan_cpi", lambda *a, **k: ([_pred("cpi_nowcast", "C")], []))
    monkeypatch.setattr(scan, "scan_labor", lambda *a, **k: ([_pred("labor_nowcast", "L")], [], "ok", []))
    return scan.main(now=NOW, live=object(), client=object())


def test_the_journal_engines_are_named_once():
    assert JOURNAL_ONLY_ENGINES == frozenset({"cpi_nowcast", "labor_nowcast"})


def test_cpi_and_labor_predictions_are_not_written_but_weather_and_gas_still_are(monkeypatch):
    recorded: list = []
    assert _run(monkeypatch, recorded) == 0
    assert sorted(r["engine"] for r in recorded) == ["gas", "weather"]


def test_the_run_summary_says_where_the_cpi_and_labor_rows_went(monkeypatch, capsys):
    _run(monkeypatch, [])
    out = capsys.readouterr().out
    assert '"cpi_nowcast": "journal"' in out and '"labor_nowcast": "journal"' in out, out
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scan_journal_only.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

```diff
diff --git a/tests/test_cpi_no_edges.py b/tests/test_cpi_no_edges.py
index 04e3ce3..9ccecbb 100644
--- a/tests/test_cpi_no_edges.py
+++ b/tests/test_cpi_no_edges.py
@@ -286,23 +286,18 @@ def test_the_cpi_delete_is_run_on_every_scan_which_is_what_bounds_the_retention_
 
 # ── the end-to-end claim: what the scan actually wrote ───────────────────────────────────────────
 
-def test_a_full_scan_writes_the_prediction_and_upserts_no_cpi_edge(monkeypatch, capsys):
+def test_a_full_scan_writes_no_cpi_prediction_row_and_upserts_no_cpi_edge(monkeypatch, capsys):
     """The end-to-end version, and the one that would catch an edge built by any route.
 
     Drives `scan.main()` with the REAL `scan_cpi` (not a stub) and a recording Supabase stub, then
-    asserts on the rows that reached the writer. A second edge route -- a new `edges.append`, a
-    different engine name, a row assembled in `main()` -- lands in the same recording and fails
-    here, which a test of `scan_cpi`'s return value alone would not catch.
+    asserts on the rows that reached the writer. CPI is a journal engine (plan 14): the journal owns its
+    forecasts, so no `predictions` row is written for it, and it still never reaches `kalshi_edges`.
     """
     client, upserted, pruned = _run_main(monkeypatch)
 
-    cpi_predictions = [r for r in client.inserted if r.get("engine") == "cpi_nowcast"]
-    assert cpi_predictions, f"the CPI prediction must still be written; got {client.inserted}"
-    row = cpi_predictions[0]
-    assert 0.0 <= row["our_prob"] <= 1.0
-    assert 0.0 <= row["market_prob"] <= 1.0
-    assert row["raw_payload"]["nowcast"] is not None
-    assert row["raw_payload"]["sigma"] > 0
+    assert not [r for r in client.inserted if r.get("engine") == "cpi_nowcast"], (
+        f"CPI is a journal engine and must not write predictions; got {client.inserted}"
+    )
 
     assert not [r for r in upserted if r.get("engine") == "cpi_nowcast"], (
         f"CPI must not reach kalshi_edges; got {upserted}"
@@ -334,7 +329,7 @@ def test_a_full_scan_does_not_prune_the_cpi_rows_the_absent_writer_leaves_behind
     assert not prune_deletes, (
         f"the absent writer deleted the historical CPI edges through main(): {prune_deletes}"
     )
-    assert client.inserted, "and the measurement was still written"
+    assert not [r for r in client.inserted if r.get("engine") == "cpi_nowcast"], "CPI writes no predictions now"
 
 
 # ── stubs ───────────────────────────────────────────────────────────────────────────────────────
diff --git a/tradehub/scripts/scan.py b/tradehub/scripts/scan.py
index 3c064e6..5751522 100644
--- a/tradehub/scripts/scan.py
+++ b/tradehub/scripts/scan.py
@@ -62,6 +62,11 @@ from tradehub.sports.scan import (
 )
 
 
+# Engines whose forecasts live in the prediction journal. Their `predictions` rows are no longer written:
+# the journal freezes, settles and scores them, and a second per-scan copy is a second record to disagree.
+# Their edges, cleanup and gate lookups are unchanged. Weather, gas and sports still write `predictions`.
+JOURNAL_ONLY_ENGINES = frozenset({"cpi_nowcast", "labor_nowcast"})
+
 log = logging.getLogger(__name__)
 SCAN_DEADLINE_SECONDS = 15 * 60
 CPI_SCAN_HOURS_ET = (8, 12, 16)  # 08:05 ET is the last run before the 08:25 ET release-day close
@@ -707,8 +712,11 @@ def main(
                 edge_writes[name] = "skipped"
                 continue
             try:
-                record_predictions(client, predictions)
-                prediction_writes[name] = "ok"
+                if name in JOURNAL_ONLY_ENGINES:
+                    prediction_writes[name] = "journal"
+                else:
+                    record_predictions(client, predictions)
+                    prediction_writes[name] = "ok"
             except Exception as exc:
                 message = f"{name}.predictions: {type(exc).__name__}: {exc}"
                 failures.append(message)
@@ -791,13 +799,7 @@ def main(
                             log.exception("scan labor gate-status lookup failed")
                             labor_statuses = {}
                         apply_gate_statuses(labor_edges, labor_statuses)
-                        try:
-                            record_predictions(client, labor_predictions)
-                            writes["predictions"]["labor_nowcast"] = "ok"
-                        except Exception as exc:
-                            failures.append(f"labor_nowcast.predictions: {type(exc).__name__}: {exc}")
-                            writes["predictions"]["labor_nowcast"] = "failed"
-                            log.exception("scan labor prediction write failed")
+                        writes["predictions"]["labor_nowcast"] = "journal"   # see JOURNAL_ONLY_ENGINES
                         try:
                             upsert_opportunities(labor_edges)
                             writes["edges"]["labor_nowcast"] = "ok"
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scan_journal_only.py tests/test_scan.py tests/test_scan_labor.py tests/test_scan_cpi.py tests/test_scan_cpi_closed_cleanup.py tests/test_cpi_delisted_cleanup.py tests/test_sports_order_and_deadline.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/scan.py tests/test_scan_journal_only.py
git commit -m "cut: the scan no longer writes predictions for the journal engines"
```

---

### Task 2: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/scripts/scan.py tests/test_scan_journal_only.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Self-Review

- **Exactly two engines skip:** the first test pins the set, the second runs the whole scan with all four engines and checks only weather and gas rows reach `record_predictions`.
- **Visible, not silent:** the summary reports `"journal"` where it used to report `"ok"`.
- **Follow-up (not in this PR):** with no writer, the CPI scan step only feeds edges that CPI no longer produces; the roadmap lists removing that step and the now-unused `_hub_settled_ledger` as cleanup.

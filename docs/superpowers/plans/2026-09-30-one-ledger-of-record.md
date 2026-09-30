# One Ledger of Record: Retire the Second Headline Number (Plan k) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the legacy `track_record` rollup for any engine the journal grades, and serve exactly one record per engine from `/api/track-record`, so there are never two headline numbers for one engine.

**Architecture:** `tradehub/journal/legacy.py` decides an engine is "on the journal" when any journal scorecard carries its name as `forecaster` (legacy versions like `cpi-v1` or `feed:ridge@...` and the journal's own versions are separate keys). The hourly settle job skips `refresh_track_record` for those engines; `/api/track-record` returns the legacy rollup only for engines not on the journal plus one journal-backed row per scorecard, each tagged `source`. `predictions` itself keeps being written and settled: it becomes per-scan telemetry, not a ledger.

**Tech Stack:** Python 3.12, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§4 one ledger of record). **Depends on:** plans (a), (b), (c), (l) merged (the engines it retires the legacy record for).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1399 passed at monotonic 5.0 and at 1e7; new files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Deviation from the spec's wording, for Kevin to confirm:** §4 says an engine on the contract "stops writing `predictions`". This plan does **not** stop the writes, because the CPI display (`/api/cpi-display`) and the sports hub calibration (`_hub_settled_ledger`) read the latest `predictions` rows every hour, and a frozen-once journal row cannot feed a live display. What stops is the second *headline*: the legacy rollup for journal engines is no longer refreshed or served, and the gate already reads the journal first (plan a, Task 4). If Kevin wants the writes stopped as well, that is a separate plan that must first repoint those two readers.
- Engines with no journal scorecard (weather, gas, crypto) keep their legacy rollup exactly as before.
- An engine is on the journal by **forecaster name, any version**; do not match on `(name, version)`: the legacy and journal version strings differ.
- A missing `journal_scores` table reads as no scorecards (code can reach production before the migration); any other database error must raise, never be read as an empty journal.
- `/api/track-record` stays a list and keeps every legacy key; it only adds `source` (and, on journal rows, `baseline`, `bss`, `calibration_ready`).
- Do not touch the `predictions` or `track_record` tables' schema. No migration.

---
### Task 1: The legacy adapter, the settle-job skip and the one-record endpoint

**Files:**
- Create: `tradehub/journal/legacy.py`, `tests/test_journal_legacy.py`
- Modify: `tradehub/gate_status.py` (one shared `table_missing` helper), `tradehub/scripts/settle_predictions.py`, `tradehub/api/main.py`, `tests/test_settle_predictions.py`, `tests/test_api_frontend.py`

**Interfaces:**
- Consumes: plan (a) `journal_scores` table and `tradehub.gate_status`; existing `refresh_track_record`.
- Produces: `gate_status.table_missing(exc, table) -> bool`; `legacy.journal_scores(supa) -> list[dict]` (empty when the table is missing); `legacy.journal_engines(scores) -> set[str]`; `legacy.journal_track_row(score) -> dict`; `legacy.merge_track_record(legacy_rows, scores) -> list[dict]`; settle summary gains `track_record_skipped_on_journal`; `/api/track-record` rows gain `source`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_journal_legacy.py`:

```python
from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app
from tradehub.journal.legacy import journal_engines, journal_scores, journal_track_row, merge_track_record

LEGACY = [
    {"engine": "weather", "engine_version": "w-v1", "n_settled": 40, "gate_status": "SHADOW"},
    {"engine": "cpi_nowcast", "engine_version": "cpi-v1", "n_settled": 12, "gate_status": "SHADOW"},
    {"engine": "cpi_nowcast", "engine_version": "cpi-core-v1", "n_settled": 9, "gate_status": "SHADOW"},
]
SCORE = {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "baseline": "market", "n_settled": 7,
         "brier": 0.07, "brier_baseline": 0.068, "bss": -0.03, "reliability": [{"bucket": "60-70", "n": 7}],
         "gate_status": "SHADOW", "calibration_ready": False, "computed_at": "2026-10-01T13:00:00+00:00"}


def test_a_journal_scorecard_becomes_one_legacy_shaped_row_tagged_with_its_source():
    row = journal_track_row(SCORE)
    assert (row["engine"], row["engine_version"], row["source"]) == ("cpi_nowcast", "cpi-v1", "journal")
    assert row["n_settled"] == 7 and row["brier_ours"] == 0.07 and row["brier_market"] == 0.068
    assert row["cal_buckets"] == [{"bucket": "60-70", "n": 7}] and row["bss"] == -0.03
    clim = journal_track_row({**SCORE, "baseline": "climatology"})
    assert clim["brier_market"] is None  # a climatology baseline is not "the market's Brier"


def test_an_engine_on_the_journal_is_served_once_from_the_journal_whatever_the_legacy_version():
    rows = merge_track_record(LEGACY, [SCORE])
    assert [(r["engine"], r["engine_version"], r["source"]) for r in rows] == [
        ("cpi_nowcast", "cpi-v1", "journal"), ("weather", "w-v1", "legacy")]
    assert journal_engines([SCORE]) == {"cpi_nowcast"}  # both legacy cpi versions are dropped, not just one


def test_with_no_journal_scorecards_the_legacy_record_is_served_unchanged_but_tagged():
    rows = merge_track_record(LEGACY, [])
    assert len(rows) == 3 and all(r["source"] == "legacy" for r in rows)


def test_a_missing_journal_table_reads_as_no_scorecards_and_any_other_fault_raises():
    class NoTable(FakeJournalDB):
        def table(self, name):
            raise RuntimeError("Could not find the table 'public.journal_scores' in the schema cache")

    class Broken(FakeJournalDB):
        def table(self, name):
            raise RuntimeError("connection reset")

    assert journal_scores(NoTable(lambda: None)) == []
    try:
        journal_scores(Broken(lambda: None))
    except RuntimeError as exc:
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("a real fault must not be read as an empty journal")


def test_the_track_record_endpoint_serves_one_record_per_engine():
    db = FakeJournalDB(lambda: None)
    db.tables["track_record"] += [dict(r) for r in LEGACY]
    db.tables["journal_scores"].append(dict(SCORE))
    app.dependency_overrides[get_supabase] = lambda: db
    try:
        body = TestClient(app).get("/api/track-record").json()
    finally:
        app.dependency_overrides.clear()
    assert [(r["engine"], r["source"]) for r in body] == [("cpi_nowcast", "journal"), ("weather", "legacy")]
```

Apply these test changes (the existing fakes must now answer a `journal_scores` read):

```diff
diff --git a/tests/test_api_frontend.py b/tests/test_api_frontend.py
index 1c01d7b..aeea7e6 100644
--- a/tests/test_api_frontend.py
+++ b/tests/test_api_frontend.py
@@ -52,6 +52,8 @@ class _Supa:
         self.query = _Query(rows)
 
     def table(self, name):
+        if name == "journal_scores":
+            return _Query([])  # no forecaster is on the journal in this test
         assert name == "track_record"
         return self.query
 
diff --git a/tests/test_settle_predictions.py b/tests/test_settle_predictions.py
index ea161c3..adfcb7c 100644
--- a/tests/test_settle_predictions.py
+++ b/tests/test_settle_predictions.py
@@ -4,7 +4,20 @@ from tradehub.scripts import settle_predictions
 
 
 class _FakeSupa:
-    pass
+    """No journal scorecards: the journal table is empty (or not deployed yet)."""
+
+    def table(self, name):
+        assert name == "journal_scores"
+        return self
+
+    def select(self, *_a):
+        return self
+
+    def order(self, *_a, **_k):
+        return self
+
+    def execute(self):
+        return type("R", (), {"data": []})()
 
 
 def test_engines_match_spec_engine_set_and_cadences():
@@ -52,3 +65,22 @@ def test_main_wires_pass_and_refresh(monkeypatch, capsys):
     out = json.loads(capsys.readouterr().out)
     assert out["checked"] == 3
     assert out["track_record_refreshed"] == ["weather@v1", "macro@v1"]
+
+
+def test_an_engine_on_the_journal_is_not_refreshed_into_the_legacy_track_record(monkeypatch, capsys):
+    class OnJournal(_FakeSupa):
+        def execute(self):
+            return type("R", (), {"data": [{"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1"}]})()
+
+    refreshed = []
+    monkeypatch.setattr(settle_predictions, "get_client", lambda: OnJournal())
+    monkeypatch.setattr(settle_predictions, "fetch_market", lambda t: {})
+    monkeypatch.setattr(settle_predictions, "run_settlement_pass", lambda supa, fetch: {"checked": 0})
+    monkeypatch.setattr(settle_predictions, "refresh_track_record",
+                        lambda supa, engine, **kw: refreshed.append(engine) or [{"engine": engine, "engine_version": "v1"}])
+    monkeypatch.setattr(settle_predictions, "ENGINES", [("weather", "daily"), ("cpi_nowcast", "monthly")])
+
+    assert settle_predictions.main() == 0
+    assert refreshed == ["weather"]  # cpi_nowcast is graded by the journal now
+    out = json.loads(capsys.readouterr().out)
+    assert out["track_record_skipped_on_journal"] == ["cpi_nowcast"] and out["track_record_refreshed"] == ["weather@v1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_legacy.py tests/test_settle_predictions.py tests/test_api_frontend.py -v`
Expected: FAIL — `No module named 'tradehub.journal.legacy'`.

- [ ] **Step 3: Implement**

`tradehub/journal/legacy.py`:

```python
"""One record per engine (v2 spec §4): the journal's scorecard replaces the legacy track record.

`predictions` is now a per-scan telemetry table (the CPI display and the sports hub calibration still
read its latest rows), not a ledger. For an engine that has a journal scorecard, the legacy
`track_record` rollup is no longer refreshed and no longer served: two live rollups with two headline
numbers for one engine is the failure this module prevents. Engines with no journal scorecard (weather,
gas, crypto) keep their legacy rollup untouched.

An engine is "on the journal" when any journal scorecard carries its name as `forecaster`, whatever the
version: the legacy versions (`cpi-v1`, `feed:ridge@...`) and the journal's are separate keys.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tradehub.gate_status import table_missing


def journal_scores(supa) -> list[dict[str, Any]]:
    """Every journal scorecard, or [] when the journal table has not been deployed yet."""
    try:
        return list(supa.table("journal_scores").select("*").order("forecaster").execute().data or [])
    except Exception as exc:
        if table_missing(exc, "journal_scores"):
            return []
        raise


def journal_engines(scores: Iterable[dict[str, Any]]) -> set[str]:
    return {str(s["forecaster"]) for s in scores}


def journal_track_row(score: dict[str, Any]) -> dict[str, Any]:
    """One scorecard in the legacy `track_record` row shape, tagged so the reader knows where it came from."""
    market = score.get("baseline") == "market"
    return {
        "engine": score["forecaster"],
        "engine_version": score["forecaster_version"],
        "n_settled": score.get("n_settled"),
        "brier_ours": score.get("brier"),
        "brier_market": score.get("brier_baseline") if market else None,
        "cal_buckets": score.get("reliability") or [],
        "max_cal_dev": None,
        "gate_status": score.get("gate_status"),
        "updated_at": score.get("computed_at"),
        "source": "journal",
        "baseline": score.get("baseline"),
        "bss": score.get("bss"),
        "calibration_ready": score.get("calibration_ready"),
    }


def merge_track_record(legacy_rows: Iterable[dict[str, Any]], scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy rows for engines NOT on the journal, plus a row per journal scorecard, ordered by engine."""
    on_journal = journal_engines(scores)
    rows = [{**r, "source": "legacy"} for r in legacy_rows if r.get("engine") not in on_journal]
    rows += [journal_track_row(s) for s in scores]
    return sorted(rows, key=lambda r: (str(r["engine"]), str(r.get("engine_version"))))
```

```diff
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index ae169fe..52b7fbb 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -32,6 +32,7 @@ from tradehub.engines.cpi import CPI_MIN_TRAIN, DEFAULT_CPI_ERROR
 from tradehub.engine_catalogue import engine_catalogue
 from tradehub.engine_health import engine_health
 from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
+from tradehub.journal.legacy import journal_scores, merge_track_record
 from tradehub.journal.scoring import headline as journal_headline
 from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report
 from tradehub.scoreboard import current_runs, market_comparison
@@ -443,7 +444,9 @@ async def get_track_record(supabase=Depends(get_supabase)):
     if supabase is None:
         raise HTTPException(status_code=503, detail="Supabase is not configured")
     result = supabase.table("track_record").select("*").order("engine").execute()
-    return result.data or []
+    # One record per engine (v2 spec §4): an engine graded by the journal is served from its journal
+    # scorecard, tagged `source: "journal"`; the rest keep their legacy rollup, tagged `source: "legacy"`.
+    return merge_track_record(result.data or [], journal_scores(supabase))
 
 
 # ════════════════════════════════════════════════════════════════════════════
diff --git a/tradehub/gate_status.py b/tradehub/gate_status.py
index c6246ce..7ee90c6 100644
--- a/tradehub/gate_status.py
+++ b/tradehub/gate_status.py
@@ -25,6 +25,12 @@ log = logging.getLogger(__name__)
 DEFAULT_GATE_STATUS = "SHADOW"
 
 
+def table_missing(exc: Exception, table: str) -> bool:
+    """True when `exc` says `table` does not exist (PostgREST schema cache, or Postgres), not any other fault."""
+    text = str(exc)
+    return table in text and ("schema cache" in text or "does not exist" in text or "PGRST205" in text)
+
+
 def _journal_rows(supa, engine: str, version: str) -> list[dict]:
     """The journal scorecard row for this pair, or [] when the journal table does not exist yet.
 
@@ -36,9 +42,8 @@ def _journal_rows(supa, engine: str, version: str) -> list[dict]:
     try:
         result = supa.table("journal_scores").select("gate_status") \
             .eq("forecaster", engine).eq("forecaster_version", version).limit(1).execute()
-    except Exception as exc:  # noqa: BLE001 - narrowed just below
-        text = str(exc)
-        if "journal_scores" in text and ("schema cache" in text or "does not exist" in text or "PGRST205" in text):
+    except Exception as exc:
+        if table_missing(exc, "journal_scores"):
             log.info("gate: journal_scores not present yet; using the legacy gate tables")
             return []
         raise
diff --git a/tradehub/scripts/settle_predictions.py b/tradehub/scripts/settle_predictions.py
index fb0cbd2..65b50e4 100644
--- a/tradehub/scripts/settle_predictions.py
+++ b/tradehub/scripts/settle_predictions.py
@@ -15,6 +15,7 @@ import sys
 from tradehub.core.env import load_local_env
 from tradehub.core.kalshi_feed import fetch_market
 from tradehub.core.supabase_client import get_client
+from tradehub.journal.legacy import journal_engines, journal_scores
 from tradehub.settlement import run_settlement_pass
 from tradehub.track_record import refresh_track_record
 
@@ -40,11 +41,20 @@ def main() -> int:
     load_local_env()
     supa = get_client()
     summary = run_settlement_pass(supa, fetch_market)
+    # One ledger of record (v2 spec §4): an engine with a journal scorecard is graded by the journal, so
+    # its legacy rollup is left alone. Its `predictions` rows are still settled above (the CPI display and
+    # the sports hub calibration read them); only the second headline number is retired.
+    on_journal = journal_engines(journal_scores(supa))
     refreshed = []
+    skipped = []
     for engine, cadence in ENGINES:
+        if engine in on_journal:
+            skipped.append(engine)
+            continue
         payloads = refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
         refreshed.extend(f"{engine}@{p['engine_version']}" for p in payloads)
     summary["track_record_refreshed"] = refreshed
+    summary["track_record_skipped_on_journal"] = skipped
     print(json.dumps(summary))
     return 0
 
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_legacy.py tests/test_settle_predictions.py tests/test_api_frontend.py tests/test_scoreboard_api.py tests/test_journal_runner.py tests/test_track_record.py -v`
Expected: all pass (the gate tests in `test_journal_runner.py` still pass because `table_missing` is the same condition the gate used inline).

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/legacy.py tradehub/gate_status.py tradehub/scripts/settle_predictions.py tradehub/api/main.py tests/test_journal_legacy.py tests/test_settle_predictions.py tests/test_api_frontend.py
git commit -m "feat(journal): one ledger of record: legacy track record retired for journal engines"
```

---

### Task 2: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] Check in the PR body that `predictions` writes are unchanged (`git diff --stat` shows no edit under `tradehub/scripts/scan.py` or `tradehub/predictions.py`).
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §4:** one ledger of record: for every engine on the contract the journal scorecard is the only record served and the only one the gate consults; `predictions` remains readable as history and as display telemetry. The one deliberate gap (writes not stopped) is called out for Kevin with the readers that force it.
- **Safety:** a missing journal table degrades to today's behaviour; a real database fault is never read as "no engines on the journal" (that would quietly resurrect the second headline).
- **Type consistency:** the journal row is the legacy `track_record` shape (`engine`, `engine_version`, `n_settled`, `brier_ours`, `brier_market`, `cal_buckets`, `gate_status`, `updated_at`) plus `source`; the reliability buckets already share the legacy `{bucket, n, predicted, observed}` shape.

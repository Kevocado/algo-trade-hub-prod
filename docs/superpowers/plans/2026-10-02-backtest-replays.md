# Replayed Backtests for the Daily Models (Roadmap v2 item 16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay the four daily-direction models (S&P 500, VIX, gold, EUR/USD) over three years of history the way the journal would have run them, store the result apart from the journal, and show it labelled "not counted" on /journal.

**Architecture:** `journal/replay.py` walks forward session by session: the model for a month is fitted once on sessions strictly before that month (exactly the journal's refit rule), predicts each session from closes strictly before it, and is graded against the usual up-rate on that session; results are also split by year so one lucky year cannot carry the headline. `scripts/backtest_daily.py` runs all four and writes one row per forecaster to a new `journal_backtests` table (migration `20260428000016`, which the reviewer applies). `/api/journal/backtests` serves the latest row per forecaster and `/journal`'s closed "Past backtests (not counted)" section shows them. A replay has no path into `journal_forecasts`, `journal_scores` or any gate.

**Tech Stack:** Python 3.12 + numpy (existing), FastAPI, React.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§2 pre-journal context, §7 walk-forward model). **Depends on:** none (independent of plans 11 to 15, but touches the same API file as plan 13, so merge after it).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend suite all-pass at both clocks on the final stack; vitest, tsc, build green). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **History is context, never evidence.** Even with a clean fit, the choice of model and features was made knowing the history. The page says "not counted" and nothing here may feed a gate or promote a forecaster.
- **Measured when this plan was written (2026-10-01, replay over 2023-10-01 to 2026-09-30, skill vs the usual up-rate):** gold 752 sessions, skill +0.0006; EUR/USD 765 sessions, skill +0.0006. That is no skill: a daily direction call is a coin flip with these inputs. S&P and VIX could not be run locally (they need the keyed FRED API); run the script where the key is set (the VPS) and report all four.
- The migration is idempotent; **do not apply it yourself**, name it in the PR and the reviewer applies it before merge.
- The CLI never touches the journal tables; its only write is `journal_backtests`.
- After the migration is applied, run `python -m tradehub.scripts.backtest_daily --years 3` once on the VPS to fill the table; do not add a timer.

---
### Task 1: The replay

**Files:**
- Create: `tradehub/journal/replay.py`, `tests/test_journal_replay.py`

**Interfaces:**
- Consumes: `features_for`, `training_set`, `fit`, `climatology_up`.
- Produces: `replay(closes, *, start, end, fit_fn=fit) -> {n, brier, brier_baseline, bss, up_rate, date_from, date_to, by_year}`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_replay.py`)

`tests/test_journal_replay.py`:

```python
import random
from datetime import date, timedelta

import pytest

from tradehub.journal.replay import replay


def _closes(n=1500, seed=3, drift=0.0004):
    rng, day, price, out = random.Random(seed), date(2019, 1, 1), 100.0, {}
    while len(out) < n:
        if day.weekday() < 5:
            price *= 1 + drift + rng.gauss(0, 0.01)
            out[day] = price
        day += timedelta(days=1)
    return out


class Const:
    def __init__(self, p):
        self.p = p

    def predict(self, row):
        return self.p


def test_the_model_for_a_session_is_fitted_only_on_sessions_before_that_months_first_day():
    closes, seen = _closes(), []

    def spy_fit(x, y, days):
        seen.append(max(days))
        return Const(0.5)

    result = replay(closes, start=date(2022, 3, 1), end=date(2022, 5, 31), fit_fn=spy_fit)
    assert result["n"] > 40
    assert len(seen) == 3                                                    # one refit per month, as live
    assert [d < date(2022, m, 1) for d, m in zip(seen, (3, 4, 5))] == [True] * 3


def test_brier_and_skill_are_computed_on_the_same_sessions_against_climatology():
    closes = _closes()
    r = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30), fit_fn=lambda x, y, d: Const(0.5))
    days = sorted(d for d in closes if date(2022, 3, 1) <= d <= date(2022, 4, 30))
    prev = {d: closes[p] for p, d in zip(sorted(closes), sorted(closes)[1:])}
    outcomes = [closes[d] > prev[d] for d in days]
    assert r["n"] == len(days)
    assert r["brier"] == pytest.approx(0.25)                                 # a constant 0.5
    assert r["up_rate"] == pytest.approx(sum(outcomes) / len(outcomes))
    assert r["brier_baseline"] > 0 and r["bss"] == pytest.approx(1 - r["brier"] / r["brier_baseline"], abs=1e-5)


def test_each_forecast_is_graded_on_its_own_session_using_only_closes_before_it():
    """A momentum rule (up if yesterday was up), computed here independently from the raw closes."""
    closes = _closes()
    ordered = sorted(closes)

    class Momentum:
        def predict(self, row):
            return 0.9 if row["r1"] > 0 else 0.1

    r = replay(closes, start=date(2022, 3, 1), end=date(2022, 4, 30), fit_fn=lambda x, y, d: Momentum())
    losses = []
    for i, day in enumerate(ordered):
        if date(2022, 3, 1) <= day <= date(2022, 4, 30):
            yesterday_up = closes[ordered[i - 1]] > closes[ordered[i - 2]]
            p, y = (0.9 if yesterday_up else 0.1), float(closes[day] > closes[ordered[i - 1]])
            losses.append((p - y) ** 2)
    assert r["n"] == len(losses) and r["brier"] == pytest.approx(sum(losses) / len(losses))


def test_skill_is_reported_per_year_so_one_lucky_year_cannot_carry_the_headline():
    r = replay(_closes(), start=date(2021, 6, 1), end=date(2022, 12, 31), fit_fn=lambda x, y, d: Const(0.5))
    assert set(r["by_year"]) == {"2021", "2022"}
    assert all({"n", "brier", "brier_baseline", "bss"} <= set(v) for v in r["by_year"].values())


def test_a_window_with_too_little_history_is_empty_not_a_guess():
    r = replay(_closes(n=150), start=date(2019, 3, 1), end=date(2019, 5, 31), fit_fn=lambda x, y, d: Const(0.5))
    assert r["n"] == 0 and r["bss"] is None and r["brier"] is None
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_replay.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`tradehub/journal/replay.py`:

```python
"""Walk-forward replay of a daily-direction model over history (plan 16): context, never counted.

The live journal needs 200 settled days before a daily model can pass its gate, which is most of a year
of waiting. This replays the same model over years that already happened, so there is an honest
out-of-sample answer today: for each session, the model is refit the way the journal refits it (once a
month, on sessions strictly before that month), predicts the session from closes strictly before it, and
is graded against the usual climatology rate on that session.

A replay is never a journal row. It is stored apart (`journal_backtests`), shown labelled "backtest, not
counted", and has no path into `journal_forecasts`, `journal_scores` or any gate: history cannot be frozen
before the fact, and the hindsight in choosing the model is real even when the fit is clean.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Protocol

from tradehub.journal.spx import climatology_up
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import fit


class Predictor(Protocol):
    def predict(self, row: dict[str, float]) -> float: ...


def _skill(brier: float | None, base: float | None) -> float | None:
    return None if brier is None or not base else 1.0 - brier / base


def _summary(rows: list[tuple[float, float, int]]) -> dict[str, Any]:
    """rows: (probability, climatology, outcome)."""
    if not rows:
        return {"n": 0, "brier": None, "brier_baseline": None, "bss": None, "up_rate": None}
    n = len(rows)
    brier = sum((p - y) ** 2 for p, _c, y in rows) / n
    base = sum((c - y) ** 2 for _p, c, y in rows) / n
    return {"n": n, "brier": round(brier, 6), "brier_baseline": round(base, 6),
            "bss": round(_skill(brier, base), 6) if base else None, "up_rate": round(sum(y for *_r, y in rows) / n, 6)}


def replay(closes: Mapping[date, float], *, start: date, end: date,
           fit_fn: Callable[..., Predictor] = fit) -> dict[str, Any]:
    ordered = sorted(closes)
    previous = dict(zip(ordered[1:], ordered[:-1], strict=True))
    models: dict[tuple[int, int], Predictor] = {}
    rows: list[tuple[float, float, int]] = []
    by_year: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for day in ordered:
        if not start <= day <= end or day not in previous:
            continue
        found, clim = features_for(closes, day), climatology_up(closes, day)
        if found is None or clim is None:
            continue
        month = (day.year, day.month)
        if month not in models:
            x, y, used = training_set(closes, before=day.replace(day=1))
            models[month] = fit_fn(x, y, used)
        probability = models[month].predict(found[0])
        outcome = int(closes[day] > closes[previous[day]])
        rows.append((probability, clim, outcome))
        by_year[str(day.year)].append((probability, clim, outcome))
    return {**_summary(rows), "date_from": start.isoformat(), "date_to": end.isoformat(),
            "by_year": {year: _summary(group) for year, group in sorted(by_year.items())}}
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_replay.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/replay.py tests/test_journal_replay.py
git commit -m "feat(journal): walk-forward replay of the daily models"
```

---

### Task 2: Store it, serve it, run it

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260428000016_journal_backtests.sql`, `tradehub/scripts/backtest_daily.py`, `tests/test_journal_backtests.py`
- Modify: `tradehub/api/main.py` (the endpoint)

**Interfaces:**
- Produces: table `journal_backtests`; `GET /api/journal/backtests -> {as_of, counted: false, backtests: [...]}` (latest row per forecaster; a missing table is an empty list); `backtest_daily.run(now, years)` and `record(supa, results, now)`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_backtests.py`)

`tests/test_journal_backtests.py`:

```python
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api import main as api_main
from tradehub.scripts import backtest_daily as bd

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
MIGRATION = Path(__file__).resolve().parents[1] / "market_sentiment_tool/supabase/migrations/20260428000016_journal_backtests.sql"


def _closes(n=1500):
    out, day, price = {}, date(2019, 1, 1), 100.0
    while len(out) < n:
        if day.weekday() < 5:
            price *= 1.0004 + 0.01 * (1 if len(out) % 3 else -1)
            out[day] = price
        day += timedelta(days=1)
    return out


def test_the_migration_is_idempotent_and_client_proof():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS journal_backtests" in sql and "CREATE INDEX IF NOT EXISTS" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql and "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in sql
    assert "journal_forecasts" not in sql.replace("journal_forecasts, journal_scores", "")  # no foreign path in


def test_run_replays_each_family_and_one_failure_does_not_hide_the_rest():
    closes = _closes()
    sources = {("a", "a-v1"): lambda start: (closes, "America/New_York"),
               ("b", "b-v1"): lambda start: (_ for _ in ()).throw(RuntimeError("FRED down"))}
    out = bd.run(datetime(2023, 1, 1, tzinfo=UTC), 1, sources=sources)
    ok, bad = out
    assert ok["forecaster"] == "a" and ok["n"] > 100 and ok["by_year"]
    assert bad["error"] == "RuntimeError: FRED down" and "n" not in bad


def test_record_writes_one_row_per_successful_replay_and_never_an_empty_one():
    class Supa:
        def __init__(self):
            self.rows = []

        def table(self, name):
            assert name == "journal_backtests"
            return self

        def insert(self, rows):
            self.rows = rows
            return self

        def execute(self):
            return self

    results = [{"forecaster": "a", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 5, "brier": 0.25,
                "brier_baseline": 0.25, "bss": 0.0, "by_year": {}},
               {"forecaster": "b", "forecaster_version": "v", "error": "boom"},
               {"forecaster": "c", "forecaster_version": "v", "date_from": "x", "date_to": "y", "n": 0, "brier": None,
                "brier_baseline": None, "bss": None, "by_year": {}}]
    supa = Supa()
    assert bd.record(supa, results, NOW) == 1 and [r["forecaster"] for r in supa.rows] == ["a"]


def test_the_endpoint_serves_the_latest_replay_per_forecaster_and_never_the_journal_tables():
    db = FakeJournalDB(lambda: NOW)
    db.tables["journal_backtests"] = [
        {"id": 1, "forecaster": "gold_direction", "forecaster_version": "gold-wf-v1", "n": 700, "bss": 0.001,
         "brier": 0.2469, "brier_baseline": 0.2470, "date_from": "2023-10-01", "date_to": "2026-09-30",
         "by_year": {}, "created_at": "2026-09-30T00:00:00+00:00"},
        {"id": 2, "forecaster": "gold_direction", "forecaster_version": "gold-wf-v1", "n": 752, "bss": 0.0006,
         "brier": 0.2468, "brier_baseline": 0.2470, "date_from": "2023-10-01", "date_to": "2026-09-30",
         "by_year": {"2025": {"n": 250, "bss": 0.01}}, "created_at": "2026-10-01T00:00:00+00:00"},
    ]
    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: db
    try:
        body = TestClient(api_main.app).get("/api/journal/backtests").json()
    finally:
        api_main.app.dependency_overrides.clear()
    assert [r["n"] for r in body["backtests"]] == [752]
    assert body["counted"] is False
    assert body["backtests"][0]["by_year"] == {"2025": {"n": 250, "bss": 0.01}}


def test_a_missing_table_is_an_empty_answer_not_a_500():
    class NoTable:
        def table(self, name):
            raise RuntimeError('relation "journal_backtests" does not exist')

    api_main.app.dependency_overrides[api_main.get_supabase] = lambda: NoTable()
    try:
        r = TestClient(api_main.app).get("/api/journal/backtests")
    finally:
        api_main.app.dependency_overrides.clear()
    assert r.status_code == 200 and r.json()["backtests"] == []
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_backtests.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`market_sentiment_tool/supabase/migrations/20260428000016_journal_backtests.sql`:

```sql
-- Plan 16: walk-forward replays of the daily-direction models, stored apart from the journal.
--
-- A replay is context, never evidence: it has no path into journal_forecasts, journal_scores or any gate.
-- One row per replay run, so the page can show how the answer moves. Written by the service role only
-- (tradehub.scripts.backtest_daily); clients read through /api/journal/backtests.

CREATE TABLE IF NOT EXISTS journal_backtests (
  id                 bigserial PRIMARY KEY,
  forecaster         text        NOT NULL,
  forecaster_version text        NOT NULL,
  date_from          date        NOT NULL,
  date_to            date        NOT NULL,
  n                  integer     NOT NULL CHECK (n > 0),
  brier              numeric     NOT NULL,
  brier_baseline     numeric     NOT NULL,
  bss                numeric,
  by_year            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS journal_backtests_latest ON journal_backtests (forecaster, forecaster_version, created_at DESC);

ALTER TABLE journal_backtests ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON journal_backtests FROM anon, authenticated;
```

`tradehub/scripts/backtest_daily.py`:

```python
"""Replay the daily-direction models over history and store the result as context (plan 16).

    python -m tradehub.scripts.backtest_daily --years 3 --dry-run     # print only
    python -m tradehub.scripts.backtest_daily --years 3               # also write `journal_backtests`

Never touches the journal tables. Each run adds one row per forecaster, so the page can show how the answer
moves over time; nothing here is counted toward a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta

from tradehub.core.env import load_local_env
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.daily import closed_only
from tradehub.journal.forecasters.daily_direction import eurusd_source, gold_source, vix_source
from tradehub.journal.replay import replay
from tradehub.journal.spx import HISTORY_DAYS, SPX_SERIES

BACKTESTS = "journal_backtests"

# (forecaster, version) exactly as the live journal names them, and how to fetch each family's closes.
SOURCES: dict[tuple[str, str], Callable[[date], tuple[Mapping[date, float], str]]] = {
    ("spy_quant", "spy-wf-v1"): lambda start: (fetch_fred_daily(SPX_SERIES, start), "America/New_York"),
    ("vix_direction", "vix-wf-v1"): vix_source().fetch,
    ("gold_direction", "gold-wf-v1"): gold_source().fetch,
    ("eurusd_direction", "eurusd-wf-v1"): eurusd_source().fetch,
}


def run(now: datetime, years: int, *, sources=SOURCES) -> list[dict]:
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=365 * years)
    out = []
    for (forecaster, version), fetch in sources.items():
        try:
            closes, tz = fetch(now.date() - timedelta(days=HISTORY_DAYS))
            result = replay(closed_only(closes, tz, now), start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - one family failing must not hide the others
            out.append({"forecaster": forecaster, "forecaster_version": version, "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({"forecaster": forecaster, "forecaster_version": version, **result})
    return out


def record(supa, results: list[dict], now: datetime) -> int:
    rows = [{"forecaster": r["forecaster"], "forecaster_version": r["forecaster_version"],
             "date_from": r["date_from"], "date_to": r["date_to"], "n": r["n"], "brier": r["brier"],
             "brier_baseline": r["brier_baseline"], "bss": r["bss"], "by_year": r["by_year"],
             "created_at": now.isoformat()} for r in results if "error" not in r and r["n"]]
    if rows:
        supa.table(BACKTESTS).insert(rows).execute()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_local_env()
    now = datetime.now(UTC)
    results = run(now, args.years)
    written = 0
    if not args.dry_run:
        from tradehub.core.supabase_client import get_client

        written = record(get_client(), results, now)
    print(json.dumps({"as_of": now.isoformat(), "written": written, "results": results}, default=str))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
```

`tradehub/api/main.py`:

```diff
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index 34fbf66..e514a89 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -30,7 +30,7 @@ from tradehub.api.dependencies import get_supabase
 from tradehub.api.frontend import mount_frontend
 from tradehub.engine_catalogue import engine_catalogue
 from tradehub.engine_health import engine_health
-from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
+from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses, table_missing
 from tradehub.journal.legacy import journal_scores, merge_track_record
 from tradehub.journal.scoring import headline as journal_headline
 from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report
@@ -457,6 +457,31 @@ def get_journal_feed(forecaster: str, version: str, limit: int = 100, offset: in
     }
 
 
+@app.get("/api/journal/backtests", tags=["Journal"])
+def get_journal_backtests(supabase=Depends(get_supabase)):
+    """The latest walk-forward replay of each daily model: context, never counted toward a gate.
+
+    A missing table (the migration is not applied yet) is an empty answer, the same rule the journal's
+    other reads follow, because "no replay yet" is the true statement.
+    """
+    if supabase is None:
+        raise HTTPException(status_code=503, detail="Supabase is not configured")
+    try:
+        rows = _fetch_all(supabase, "journal_backtests", lambda q: q.select("*"), order=("id",))
+    except Exception as exc:  # noqa: BLE001 - classified below
+        if table_missing(exc, "journal_backtests"):
+            rows = []
+        else:
+            raise _table_fault("journal_backtests", exc) from exc
+    latest: dict[tuple[str, str], dict] = {}
+    for row in rows:  # ascending id, so the last row per pair is the newest
+        latest[(row["forecaster"], row["forecaster_version"])] = row
+    keep = ("forecaster", "forecaster_version", "date_from", "date_to", "n", "brier", "brier_baseline", "bss",
+            "by_year", "created_at")
+    return {"as_of": datetime.now(timezone.utc).isoformat(), "counted": False,
+            "backtests": [{k: r.get(k) for k in keep} for r in latest.values()]}
+
+
 # ════════════════════════════════════════════════════════════════════════════
 # Sports edges (rollout step 7): candidate edges with review verdicts and links
 # ════════════════════════════════════════════════════════════════════════════
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_backtests.py tests/test_api_route_order.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub market_sentiment_tool/supabase tests
git commit -m "feat(journal): store and serve the replays"
```

---

### Task 3: Show it, labelled

**Files:**
- Modify: `market_sentiment_tool/src/components/PreJournalContext.tsx`, `market_sentiment_tool/src/pages/Journal.test.tsx`

**Interfaces:**
- Consumes: `/api/journal/backtests`; a failure there must not hide the existing backtest table.
- Produces: a table `Daily models replayed over history` (model, window, sessions, signed skill) inside the closed "Past backtests (not counted)" section.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/pages/Journal.test.tsx`)

The extended test is in the diff below (it asserts the label, the session count and `+0.001`).

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/pages/Journal.test.tsx` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

```diff
diff --git a/market_sentiment_tool/src/components/PreJournalContext.tsx b/market_sentiment_tool/src/components/PreJournalContext.tsx
index 2bb614c..ea2f5be 100644
--- a/market_sentiment_tool/src/components/PreJournalContext.tsx
+++ b/market_sentiment_tool/src/components/PreJournalContext.tsx
@@ -2,8 +2,18 @@ import { useEffect, useState } from "react";
 
 import { buildApiUrl } from "@/lib/api";
 import { brierPair } from "@/lib/models";
+import { forecasterLabel } from "@/lib/forecasterLabels";
 import type { ScoreboardResponse } from "@/lib/scoreboard";
 
+export interface ReplayRow {
+  forecaster: string;
+  forecaster_version: string;
+  date_from: string;
+  date_to: string;
+  n: number;
+  bss: number | null;
+}
+
 /**
  * Backtests run before the journal existed (v2 spec §2): context only, never counted. The caller labels
  * it ("Past backtests (not counted)") and mounts it only when opened, so it adds no words or requests
@@ -12,6 +22,15 @@ import type { ScoreboardResponse } from "@/lib/scoreboard";
 export function PreJournalContext() {
   const [data, setData] = useState<ScoreboardResponse | null>(null);
   const [error, setError] = useState<string | null>(null);
+  const [replays, setReplays] = useState<ReplayRow[]>([]);
+
+  useEffect(() => {
+    // Optional context: a failure here must not hide the backtest table below.
+    fetch(buildApiUrl("/api/journal/backtests"))
+      .then((response) => response.json())
+      .then((payload) => setReplays(Array.isArray(payload?.backtests) ? payload.backtests : []))
+      .catch(() => setReplays([]));
+  }, []);
 
   useEffect(() => {
     fetch(buildApiUrl("/api/scoreboard"))
@@ -25,6 +44,28 @@ export function PreJournalContext() {
 
   return (
     <section aria-label="Pre-journal backtests">
+      {replays.length > 0 && (
+        <table className="mb-6 w-full text-xs text-slate-300" aria-label="Daily models replayed over history">
+          <thead className="text-slate-500">
+            <tr>
+              <th className="text-left font-normal">Replayed over history</th>
+              <th className="text-left font-normal">Window</th>
+              <th className="text-right font-normal">Sessions</th>
+              <th className="text-right font-normal" title="Positive means better than the usual up-rate">Skill</th>
+            </tr>
+          </thead>
+          <tbody>
+            {replays.map((r) => (
+              <tr key={`${r.forecaster}@${r.forecaster_version}`}>
+                <td>{forecasterLabel(r.forecaster, r.forecaster_version)}</td>
+                <td>{r.date_from} → {r.date_to}</td>
+                <td className="text-right">{r.n}</td>
+                <td className="text-right font-mono">{r.bss === null ? "—" : `${r.bss > 0 ? "+" : ""}${r.bss.toFixed(3)}`}</td>
+              </tr>
+            ))}
+          </tbody>
+        </table>
+      )}
       {error ? (
         <p className="text-sm text-rose-300">Backtest history unavailable: {error}</p>
       ) : !data ? (
diff --git a/market_sentiment_tool/src/pages/Journal.test.tsx b/market_sentiment_tool/src/pages/Journal.test.tsx
index 062c950..28b9343 100644
--- a/market_sentiment_tool/src/pages/Journal.test.tsx
+++ b/market_sentiment_tool/src/pages/Journal.test.tsx
@@ -40,9 +40,13 @@ const feed: JournalFeed = {
 const scoreboard = { as_of: "x", runs_read: 1, engines: 1, rows: [{ engine: "cpi_nowcast", engine_version: "cpi-v1", mode: "taker",
   date_from: "2025-01-01T00:00:00+00:00", date_to: "2026-06-30T00:00:00+00:00", n_decisions: 412, brier_ours: 0.0712, brier_market: 0.0683 }] };
 
+const backtests = { as_of: "x", counted: false, backtests: [{ forecaster: "gold_direction", forecaster_version: "gold-wf-v1",
+  date_from: "2023-10-01", date_to: "2026-09-30", n: 752, bss: 0.0006, brier: 0.2468, brier_baseline: 0.247, by_year: {} }] };
+
 function stubFetch() {
   const fn = vi.fn((url: string) => {
-    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard : journal;
+    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard
+      : url.includes("/api/journal/backtests") ? backtests : journal;
     return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
   });
   vi.stubGlobal("fetch", fn);
@@ -93,6 +97,10 @@ describe("Journal", () => {
     details.open = true;
     fireEvent(details, new Event("toggle"));
     expect(await screen.findByText("cpi_nowcast · cpi-v1 · taker")).toBeInTheDocument();
+    const replay = await screen.findByLabelText("Daily models replayed over history");
+    expect(within(replay).getByText("Gold tomorrow")).toBeInTheDocument();
+    expect(within(replay).getByText("752")).toBeInTheDocument();
+    expect(within(replay).getByText("+0.001")).toBeInTheDocument();
   });
 
   it("stays inside its word budget", async () => {
```

- [ ] **Step 4: Run** — `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src
git commit -m "feat(ui): replayed daily models in the not-counted backtests"
```

---

### Task 4: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/journal/replay.py tradehub/scripts/backtest_daily.py tests/test_journal_replay.py tests/test_journal_backtests.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Frontend: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Self-Review

- **No lookahead:** a test records the last training day of each refit and asserts it precedes that month; another recomputes a momentum rule's Brier independently from raw closes.
- **Never counted:** separate table, `counted: false` in the response, the page label, and a migration test that the file has no path into the journal tables.
- **Truthful when empty:** a window with too little history returns `n: 0` and nulls, and is never written.

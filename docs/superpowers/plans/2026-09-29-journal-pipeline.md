# Prediction Journal Pipeline (Wave 1, Plan a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the forecaster-agnostic journal (freeze → settle → score → render contract) that every wave-1 forecaster (plans b–f) publishes through, and make it the gate's ledger of record.

**Architecture:** Four Supabase tables whose freeze/immutability rules are enforced by **database triggers** (the service role bypasses RLS, so RLS cannot guarantee a freeze). A small Python package `tradehub/journal/` defines the `Forecaster` protocol, a pure scoring module (Brier, BSS vs market-or-climatology, confidence-space reliability, Murphy decomposition, per-target gates), a store for Supabase I/O, and a runner that isolates each forecaster. An hourly CLI (`python -m tradehub.scripts.journal_run`) drives it; two read-only API endpoints render precomputed numbers. `latest_gate_statuses` reads `journal_scores` first and only falls back to the legacy tables for forecasters not on the journal.

**Tech Stack:** Python 3.12, supabase-py (PostgREST), FastAPI, PostgreSQL 16 triggers (plpgsql), pytest, Docker (`postgres:16-alpine`, trigger tests only).

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (APPROVED 2026-09-29, incl. second-pass amendment and rulings Q1–Q5). Read §3 (contract), §4 (ledger + failure rules), §5 (gates), §11 (API) before starting.

> **Provenance:** every code block below was implemented and run by the reviewer in a scratch worktree off `main@2b82d93` before this plan was written: full suite **1353 passed** with `time.monotonic` forced to both `5.0` and `1e7`; new files ruff-clean; the trigger tests passed against real Postgres 16, and a mutation (deleting the cutoff check) made them fail. Copy the code as written; if something disagrees with `main` because `main` moved, fix it and say so in the PR.

## Global Constraints

- Migration number is **`20260428000014`** (latest on main is `…000013`). Idempotent: `IF NOT EXISTS`, `CREATE OR REPLACE`, `DROP TRIGGER IF EXISTS`.
- Freeze and immutability live in **triggers**, never only in Python. `frozen_at` is server time (`now()`), never client-supplied.
- A forecast is accepted only when `now() < cutoff_at` of its calendar row; a missed freeze is a **gap, never backfilled**.
- Forecasts are append-only. The single allowed update is `rebuilt false → true` with every other column unchanged. No DELETE, no TRUNCATE.
- A settlement is accepted only when `now() >= cutoff_at`, and is immutable afterwards.
- Clients (`anon`, `authenticated`) have **no write privilege** on journal tables; RLS on, no policies.
- Gate minimums are counted **per settled target**, not per row: `daily` 200, `monthly` 50, `meeting` 50.
- BSS baseline: the frozen `market_prob` when the target has a Kalshi market, else the calendar's `climatology_prob`; a target with neither is excluded from BSS and PROMOTION is refused if no target has a baseline.
- Calibration buckets are confidence-space `50–60 … 90–100`; `calibration_ready` needs ≥ **20** targets in every populated bucket.
- `rebuilt = true` rows are excluded from scoring.
- Every timestamp is timezone-aware; `run_journal` refuses a naive `now`.
- One forecaster failing must not stop the others; the CLI exits 1 if any failed.
- The fail-closed gate value is `DEFAULT_GATE_STATUS` imported from `tradehub/gate_status.py`; **never** write the `"SHADOW"` literal in `tradehub/api/main.py` or `tradehub/scoreboard.py` (a structural test enforces this).
- Tests must pass with `time.monotonic` forced to `5.0` and to `1e7` (see Task 6).
- Deploy order: apply the migration to Supabase **before** merging code that writes to it, then `NOTIFY pgrst, 'reload schema';`. The gate lookup tolerates a missing table, so reading code is safe either way.
- Weather stays quarantined; earnings and crypto are out of scope (v1.x).

## File Structure

| File | Responsibility |
|---|---|
| `market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql` (create) | Tables, trigger guards, privileges |
| `tests/test_journal_migration_pg.py` (create) | Proves the trigger rules against real Postgres (skips without Docker) |
| `tradehub/journal/__init__.py` (create) | Package marker |
| `tradehub/journal/contract.py` (create) | `CalendarEntry`, `Forecast`, `Settlement`, `Forecaster` protocol, `require_aware` |
| `tradehub/journal/scoring.py` (create) | Pure scoring: Brier, BSS, reliability, Murphy, gate verdict, journal headline |
| `tradehub/journal/store.py` (create) | Supabase reads (paged) and inserts; reports DB refusals as `False` |
| `tradehub/journal/runner.py` (create) | freeze → settle → score per forecaster, isolated |
| `tradehub/journal/registry.py` (create) | `FORECASTERS` list plans b–f append to |
| `tradehub/scripts/journal_run.py` (create) | Hourly CLI entrypoint |
| `tradehub/gate_status.py` (modify) | Journal scorecard is the gate for journal forecasters |
| `tradehub/api/main.py` (modify) | `GET /api/journal`, `GET /api/journal/feed` |
| `tests/journal_fakes.py` (create) | In-memory Supabase that emulates the trigger rules |
| `tests/test_journal_scoring.py`, `tests/test_journal_runner.py`, `tests/test_journal_api.py` (create) | Unit/integration tests |
| `tests/test_scan.py`, `tests/test_migration_exception_conditions.py` (modify) | Keep existing tests correct with the new migration and gate lookup |

**Interfaces other plans rely on** (plans b–f import only these):

```python
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement, Forecaster, CADENCES, require_aware
from tradehub.journal.registry import FORECASTERS          # append your forecaster instance here
from tradehub.journal.scoring import MIN_SETTLED, MIN_BUCKET_TARGETS, score
# HTTP: GET /api/journal -> {as_of, forecasters: [journal_scores row], headline: {forecasters, calibrated,
#         settled_calibrated, promoted}}   (headline counts calibrated forecasters only, spec §10)
#       GET /api/journal/feed?forecaster=&version=&limit=1..500&offset=>=0
#         -> {forecaster, forecaster_version, generated_at, forecasts:[{target, probability, market_prob,
#             frozen_at, rebuilt, source_hash}], calibration, gate_status, provisional}
```

A forecaster's `targets(now)` returns `CalendarEntry` objects whose `cadence` equals the forecaster's `cadence` (others are ignored); `forecast()` returns `None` when inputs are missing (never a guess); `settle()` returns `None` until the outcome is public. Target ids are global strings `<namespace>:<event-key>` shared across forecasters, so a model and the market pseudo-forecaster on the same event line up: `kalshi:<market ticker>` (plans b–c), `labor:<unrate|quits>:<YYYY-MM>:up` (plan c), `spx:<YYYY-MM-DD>:up` (plans d–e).

---

### Task 1: Migration with trigger-enforced freeze

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql`
- Test: `tests/test_journal_migration_pg.py`

**Interfaces:**
- Produces: tables `journal_calendars`, `journal_forecasts`, `journal_settlements`, `journal_scores` with the columns below; the trigger error messages begin with `journal:`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_migration_pg.py`)

```python
"""The journal's freeze and immutability guarantees, run against a real Postgres.

These are the spec's load-bearing claims (v2 §3-§4), and they live in database triggers, so a fake
client cannot prove them. Each test runs SQL through `psql` inside a throwaway `postgres:16-alpine`
container. When Docker is unavailable the module is skipped, loudly; CI and the pre-push checklist
must run it with Docker.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql"
)


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0  # noqa: PLW1510


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="needs Docker for a throwaway postgres:16 (journal triggers)")


@pytest.fixture(scope="module")
def pg():
    name = f"journal-pg-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=x", "postgres:16-alpine"],
                   check=True, capture_output=True)
    try:
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True).returncode == 0:  # noqa: PLW1510
                break
            time.sleep(0.5)
        time.sleep(1.0)

        def run(sql: str) -> subprocess.CompletedProcess:
            return subprocess.run(["docker", "exec", "-i", name, "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres",  # noqa: PLW1510
                                   "-tA"], input=sql, text=True, capture_output=True)

        # Supabase has these roles; a plain postgres does not.
        assert run("CREATE ROLE anon; CREATE ROLE authenticated;").returncode == 0
        for _ in range(2):  # applied twice: the migration must be idempotent
            applied = run(MIGRATION.read_text(encoding="utf-8"))
            assert applied.returncode == 0, applied.stderr
        yield run
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)  # noqa: PLW1510


def _calendar(run, target: str, seconds: float) -> None:
    out = run(f"INSERT INTO journal_calendars (target, family, cadence, cutoff_at) "
              f"VALUES ('{target}', 'test', 'daily', now() + interval '{seconds} seconds');")
    assert out.returncode == 0, out.stderr


def test_a_freeze_before_the_cutoff_is_accepted_and_frozen_at_is_server_time(pg):
    _calendar(pg, "t:ok", 60)
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash, frozen_at) "
             "VALUES ('f', 'v1', 't:ok', 0.6, 'h', '2000-01-01T00:00:00Z') RETURNING frozen_at > now() - interval '1 minute';")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[0] == "t"  # the client's 2000-01-01 was ignored


def test_a_freeze_after_the_cutoff_is_refused(pg):
    _calendar(pg, "t:late", 1)
    time.sleep(2.0)
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
             "VALUES ('f', 'v1', 't:late', 0.6, 'h');")
    assert out.returncode != 0
    assert "cutoff" in out.stderr and "has passed" in out.stderr


def test_a_freeze_for_a_target_without_a_calendar_row_is_refused(pg):
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
             "VALUES ('f', 'v1', 't:unknown', 0.6, 'h');")
    assert out.returncode != 0
    assert "no calendar row" in out.stderr


def test_a_calendar_row_cannot_be_created_in_the_past_or_changed(pg):
    past = pg("INSERT INTO journal_calendars (target, family, cadence, cutoff_at) "
              "VALUES ('t:past', 'test', 'daily', now() - interval '1 second');")
    assert past.returncode != 0 and "not in the future" in past.stderr
    _calendar(pg, "t:cal", 60)
    moved = pg("UPDATE journal_calendars SET cutoff_at = cutoff_at + interval '1 day' WHERE target = 't:cal';")
    assert moved.returncode != 0 and "immutable" in moved.stderr


def test_forecasts_cannot_be_updated_or_deleted_but_rebuilt_can_flip_on(pg):
    _calendar(pg, "t:imm", 60)
    assert pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
              "VALUES ('f', 'v1', 't:imm', 0.6, 'h');").returncode == 0
    changed = pg("UPDATE journal_forecasts SET probability = 0.9 WHERE target = 't:imm';")
    assert changed.returncode != 0 and "immutable" in changed.stderr
    sneaky = pg("UPDATE journal_forecasts SET rebuilt = true, probability = 0.9 WHERE target = 't:imm';")
    assert sneaky.returncode != 0
    deleted = pg("DELETE FROM journal_forecasts WHERE target = 't:imm';")
    assert deleted.returncode != 0 and "immutable" in deleted.stderr
    flipped = pg("UPDATE journal_forecasts SET rebuilt = true WHERE target = 't:imm' RETURNING rebuilt;")
    assert flipped.returncode == 0 and flipped.stdout.strip().splitlines()[0] == "t"
    back = pg("UPDATE journal_forecasts SET rebuilt = false WHERE target = 't:imm';")
    assert back.returncode != 0


def test_a_settlement_is_refused_before_the_cutoff_and_immutable_after(pg):
    _calendar(pg, "t:set", 1)
    early = pg("INSERT INTO journal_settlements (target, outcome, source) VALUES ('t:set', 1, 'test');")
    assert early.returncode != 0 and "before its cutoff" in early.stderr
    time.sleep(2.0)
    assert pg("INSERT INTO journal_settlements (target, outcome, source) VALUES ('t:set', 1, 'test');").returncode == 0
    changed = pg("UPDATE journal_settlements SET outcome = 0 WHERE target = 't:set';")
    assert changed.returncode != 0 and "immutable" in changed.stderr


def test_truncate_is_refused_even_for_the_owner(pg):
    for table in ("journal_forecasts", "journal_settlements", "journal_calendars"):
        out = pg(f"TRUNCATE {table} CASCADE;")
        assert out.returncode != 0 and "TRUNCATE" in out.stderr, table


def test_clients_have_no_write_privilege(pg):
    out = pg("SELECT count(*) FROM information_schema.role_table_grants WHERE grantee IN ('anon','authenticated') "
             "AND table_name LIKE 'journal_%' AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE');")
    assert out.returncode == 0 and out.stdout.strip() == "0"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_migration_pg.py -v`
Expected: FAIL/ERROR — migration file not found (or SKIPPED if Docker is not running; start Docker, these tests are the only proof of the freeze).

- [ ] **Step 3: Write the migration**

```sql
-- 20260428000014: the prediction journal (v2 spec §3-§4).
--
-- Four tables:
--   journal_calendars   one row per target: its family, cadence and freeze cutoff. Immutable.
--   journal_forecasts   one frozen forecast per (forecaster, version, target). Immutable, except
--                       that `rebuilt` may flip false -> true (a row found invalid is kept and shown,
--                       never counted).
--   journal_settlements one realised outcome per target. Immutable. Only after the cutoff.
--   journal_scores      the per-(forecaster, version) scorecard. Derived data: recomputed and
--                       upserted by the score job, so it is the one table that is updatable.
--
-- ENFORCEMENT IS BY TRIGGER, NOT RLS. The scan/settle/journal jobs write as the service role, and the
-- service role bypasses RLS, so an RLS insert policy could never refuse a late write. Row triggers
-- fire for every role, including the service role:
--   * BEFORE INSERT on journal_forecasts: `frozen_at := now()` (a client value is ignored),
--     `rebuilt := false`, and the insert is refused when the target has no calendar row or
--     `now() >= cutoff_at`.
--   * BEFORE UPDATE/DELETE on the three ledger tables: refused (except the rebuilt flip above).
--   * BEFORE TRUNCATE (statement trigger): refused. TRUNCATE skips row triggers, so without this a
--     service-role TRUNCATE would empty the audit trail silently.
-- Clients (anon, authenticated) get no write privilege and no RLS policy: the War Room reads
-- through the API (service role).
--
-- Idempotent: CREATE ... IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS.

CREATE TABLE IF NOT EXISTS journal_calendars (
  target           text PRIMARY KEY,
  family           text NOT NULL,
  cadence          text NOT NULL CHECK (cadence IN ('daily', 'monthly', 'meeting')),
  cutoff_at        timestamptz NOT NULL,
  market_linked    boolean NOT NULL DEFAULT false,
  climatology_prob numeric(6,5) CHECK (climatology_prob IS NULL OR (climatology_prob > 0 AND climatology_prob < 1)),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journal_calendars_family_cutoff_idx ON journal_calendars (family, cutoff_at);

CREATE TABLE IF NOT EXISTS journal_forecasts (
  id                 bigserial PRIMARY KEY,
  forecaster         text NOT NULL,
  forecaster_version text NOT NULL,
  target             text NOT NULL REFERENCES journal_calendars (target),
  probability        numeric(6,5) NOT NULL CHECK (probability >= 0 AND probability <= 1),
  market_prob        numeric(6,5) CHECK (market_prob IS NULL OR (market_prob >= 0 AND market_prob <= 1)),
  source_hash        text NOT NULL,
  payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
  rebuilt            boolean NOT NULL DEFAULT false,
  frozen_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (forecaster, forecaster_version, target)
);
CREATE INDEX IF NOT EXISTS journal_forecasts_forecaster_idx ON journal_forecasts (forecaster, forecaster_version);

CREATE TABLE IF NOT EXISTS journal_settlements (
  target         text PRIMARY KEY REFERENCES journal_calendars (target),
  outcome        smallint NOT NULL CHECK (outcome IN (0, 1)),
  realized_value numeric,
  source         text NOT NULL,
  settled_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journal_scores (
  forecaster         text NOT NULL,
  forecaster_version text NOT NULL,
  cadence            text NOT NULL,
  baseline           text NOT NULL,
  n_targets          integer NOT NULL DEFAULT 0,
  n_settled          integer NOT NULL DEFAULT 0,
  brier              numeric(8,6),
  brier_baseline     numeric(8,6),
  bss                numeric(10,6),
  reliability        jsonb NOT NULL DEFAULT '[]'::jsonb,
  murphy             jsonb NOT NULL DEFAULT '{}'::jsonb,
  calibration_ready  boolean NOT NULL DEFAULT false,
  gate_status        text NOT NULL DEFAULT 'SHADOW' CHECK (gate_status IN ('SHADOW', 'PROMOTED')),
  gate_reasons       jsonb NOT NULL DEFAULT '[]'::jsonb,
  computed_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (forecaster, forecaster_version)
);

-- ── guards ──────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION journal_calendar_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.cutoff_at <= now() THEN
      RAISE EXCEPTION 'journal: calendar cutoff % for % is not in the future', NEW.cutoff_at, NEW.target
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'journal: journal_calendars rows are immutable (%)', TG_OP USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_forecast_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  cutoff timestamptz;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT c.cutoff_at INTO cutoff FROM journal_calendars c WHERE c.target = NEW.target;
    IF cutoff IS NULL THEN
      RAISE EXCEPTION 'journal: no calendar row for target %', NEW.target USING ERRCODE = 'foreign_key_violation';
    END IF;
    NEW.frozen_at := now();
    NEW.rebuilt := false;
    IF NEW.frozen_at >= cutoff THEN
      RAISE EXCEPTION 'journal: freeze for % refused, cutoff % has passed', NEW.target, cutoff
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    IF NEW.rebuilt AND NOT OLD.rebuilt AND (to_jsonb(NEW) - 'rebuilt') = (to_jsonb(OLD) - 'rebuilt') THEN
      RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'journal: journal_forecasts rows are immutable (%; only rebuilt false->true is allowed)', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_settlement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  cutoff timestamptz;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT c.cutoff_at INTO cutoff FROM journal_calendars c WHERE c.target = NEW.target;
    IF cutoff IS NULL OR now() < cutoff THEN
      RAISE EXCEPTION 'journal: settlement for % refused before its cutoff %', NEW.target, cutoff
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.settled_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'journal: journal_settlements rows are immutable (%)', TG_OP USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'journal: TRUNCATE of % is refused (audit trail)', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

DROP TRIGGER IF EXISTS journal_calendars_guard ON journal_calendars;
CREATE TRIGGER journal_calendars_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_calendars
  FOR EACH ROW EXECUTE FUNCTION journal_calendar_guard();
DROP TRIGGER IF EXISTS journal_forecasts_guard ON journal_forecasts;
CREATE TRIGGER journal_forecasts_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_forecasts
  FOR EACH ROW EXECUTE FUNCTION journal_forecast_guard();
DROP TRIGGER IF EXISTS journal_settlements_guard ON journal_settlements;
CREATE TRIGGER journal_settlements_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_settlements
  FOR EACH ROW EXECUTE FUNCTION journal_settlement_guard();

DROP TRIGGER IF EXISTS journal_calendars_no_truncate ON journal_calendars;
CREATE TRIGGER journal_calendars_no_truncate BEFORE TRUNCATE ON journal_calendars
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();
DROP TRIGGER IF EXISTS journal_forecasts_no_truncate ON journal_forecasts;
CREATE TRIGGER journal_forecasts_no_truncate BEFORE TRUNCATE ON journal_forecasts
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();
DROP TRIGGER IF EXISTS journal_settlements_no_truncate ON journal_settlements;
CREATE TRIGGER journal_settlements_no_truncate BEFORE TRUNCATE ON journal_settlements
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();

-- ── client access: none ─────────────────────────────────────────────────────
ALTER TABLE journal_calendars   ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_forecasts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_scores      ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON journal_calendars, journal_forecasts, journal_settlements, journal_scores
  FROM anon, authenticated;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_migration_pg.py -v`
Expected: 8 passed.

- [ ] **Step 5: Mutation check (do not commit the mutation)**

Temporarily delete the `IF NEW.frozen_at >= cutoff` block in `journal_forecast_guard`, run `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_migration_pg.py -k after_the_cutoff`, expect FAIL, then restore the file (`git checkout -- market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql` if it was already committed, else undo the edit).

- [ ] **Step 6: Fix the migration-ordering test** that asserted `…000013` is the newest file. Apply this change to `tests/test_migration_exception_conditions.py`:

```diff
diff --git a/tests/test_migration_exception_conditions.py b/tests/test_migration_exception_conditions.py
index 14ada0f..07b89dc 100644
--- a/tests/test_migration_exception_conditions.py
+++ b/tests/test_migration_exception_conditions.py
@@ -673,14 +673,15 @@ def _objects_touched(sql: str) -> set[str]:
     return names
 
 
-def test_the_follow_up_exists_and_is_numbered_after_everything_else():
+def test_the_follow_up_exists_and_is_numbered_after_what_it_completes():
+    """It must apply after the migration it finishes. Later migrations (the journal's 000014 and
+    onward) may sort after it; "newest file in the folder" was never the requirement, and asserting
+    it would have failed the moment any migration was added."""
     assert FOLLOW_UP.is_file(), f"{FOLLOW_UP.name} is missing"
-    others = [p for p in _migration_files() if p != FOLLOW_UP]
-    assert others, "no other migrations to be numbered after"
-    highest = max(others)
-    assert FOLLOW_UP.name > highest.name, (
-        f"{FOLLOW_UP.name} must sort after {highest.name}; migrations apply in name order"
-    )
+    earlier = [p for p in _migration_files() if p.name < FOLLOW_UP.name]
+    assert ORIGINAL in earlier, f"{FOLLOW_UP.name} must sort after {ORIGINAL.name}; migrations apply in name order"
+    clashes = [p.name for p in _migration_files() if p != FOLLOW_UP and p.name[:14] == FOLLOW_UP.name[:14]]
+    assert not clashes, f"another migration shares {FOLLOW_UP.name[:14]}: {clashes}"
     assert FOLLOW_UP.name.endswith("_signal_events_publication_and_rls.sql")
     assert "20260428000013" in FOLLOW_UP.name
 
```

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_migration_exception_conditions.py` — Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql tests/test_journal_migration_pg.py tests/test_migration_exception_conditions.py
git commit -m "feat(journal): migration 000014 with trigger-enforced freeze and immutability"
```

---

### Task 2: Contract and scoring

**Files:**
- Create: `tradehub/journal/__init__.py`, `tradehub/journal/contract.py`, `tradehub/journal/scoring.py`
- Test: `tests/test_journal_scoring.py`

**Interfaces:**
- Consumes: `tradehub.track_record.bucketize`, `tradehub.track_record.BUCKETS` (existing; confidence-space 50–60 … 90–100).
- Produces: `score(forecasts: list[dict], settlements: dict[str,int], calendar: dict[str,dict], cadence: str) -> dict` with keys `cadence, baseline, n_targets, n_settled, brier, brier_baseline, bss, reliability, murphy, calibration_ready, gate_status, gate_reasons` (exactly the non-key columns of `journal_scores` minus `computed_at`). Rows are `journal_forecasts` dicts; `calendar` maps target → `journal_calendars` row.

- [ ] **Step 1: Write the failing tests** (`tests/test_journal_scoring.py`)

```python
from datetime import UTC, datetime

import pytest

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.scoring import MIN_BUCKET_TARGETS, murphy, reliability, score, settled_pairs


def _row(target, prob, market=None, rebuilt=False):
    return {"target": target, "probability": prob, "market_prob": market, "rebuilt": rebuilt}


def test_contract_rejects_naive_times_and_bad_values():
    with pytest.raises(ValueError, match="timezone-aware"):
        CalendarEntry("t", "fam", "daily", datetime(2026, 10, 1, 8))  # noqa: DTZ001
    with pytest.raises(ValueError, match="cadence"):
        CalendarEntry("t", "fam", "hourly", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="probability"):
        Forecast("f", "v1", "t", 1.2)
    with pytest.raises(ValueError, match="outcome"):
        Settlement("t", 2, "src")


def test_source_hash_is_stable_and_input_sensitive():
    a = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 2})
    b = Forecast("f", "v1", "t", 0.6, payload={"y": 2, "x": 1})
    c = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 3})
    assert a.source_hash == b.source_hash != c.source_hash


def test_rebuilt_and_unsettled_rows_are_never_counted():
    rows = [_row("a", 0.9), _row("b", 0.9, rebuilt=True), _row("c", 0.9)]
    pairs = settled_pairs(rows, {"a": 1, "b": 1})
    assert [p["target"] for p in pairs] == ["a"]
    card = score(rows, {"a": 1, "b": 1}, {}, "daily")
    assert card["n_targets"] == 2 and card["n_settled"] == 1


def test_bss_uses_market_where_it_exists_else_climatology():
    rows = [_row("m", 0.8, market=0.6), _row("c", 0.7)]
    cal = {"c": {"climatology_prob": 0.5}}
    card = score(rows, {"m": 1, "c": 1}, cal, "daily")
    ours = ((0.8 - 1) ** 2 + (0.7 - 1) ** 2) / 2
    base = ((0.6 - 1) ** 2 + (0.5 - 1) ** 2) / 2
    assert card["bss"] == pytest.approx(1 - ours / base, abs=1e-6)
    assert card["baseline"] == "market"


def test_a_target_with_no_baseline_is_scored_but_excluded_from_bss():
    card = score([_row("x", 0.9)], {"x": 1}, {}, "daily")
    assert card["brier"] == pytest.approx(0.01)
    assert card["bss"] is None and card["baseline"] == "none"
    assert "no baseline" in " ".join(card["gate_reasons"])


def test_gate_counts_monthly_at_50_and_daily_at_200():
    rows = [_row(f"t{i}", 0.9, market=0.6) for i in range(60)]
    settle = {f"t{i}": 1 for i in range(60)}
    monthly = score(rows, settle, {}, "monthly")
    daily = score(rows, settle, {}, "daily")
    assert not any("settled targets" in r for r in monthly["gate_reasons"])
    assert any("need 200" in r for r in daily["gate_reasons"])


def test_promotion_needs_positive_skill_and_calibrated_buckets():
    good = [_row(f"g{i}", 0.95, market=0.6) for i in range(MIN_BUCKET_TARGETS * 3)]
    card = score(good, {r["target"]: 1 for r in good}, {}, "monthly")
    assert card["calibration_ready"] and card["bss"] > 0
    assert card["gate_status"] == "PROMOTED", card["gate_reasons"]
    worse = [_row(f"w{i}", 0.6, market=0.95) for i in range(60)]
    card = score(worse, {r["target"]: 1 for r in worse}, {}, "monthly")
    assert card["gate_status"] == "SHADOW" and any("not positive" in r for r in card["gate_reasons"])


def test_reliability_is_confidence_space_and_murphy_adds_up():
    pairs = [{"probability": 0.3, "outcome": 0}, {"probability": 0.7, "outcome": 1},
             {"probability": 0.7, "outcome": 0}, {"probability": 0.2, "outcome": 0}]
    buckets = {b["bucket"]: b for b in reliability(pairs)}
    assert buckets["70-80"]["n"] == 3  # 0.3 and both 0.7s
    m = murphy(pairs)
    brier = sum((p["probability"] - p["outcome"]) ** 2 for p in pairs) / len(pairs)
    # Binned Murphy is exact when every bin holds a single forecast value, as here.
    assert m["reliability"] - m["resolution"] + m["uncertainty"] == pytest.approx(brier, abs=1e-6)
```

- [ ] **Step 2: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradehub.journal'`.

- [ ] **Step 3: Implement**

`tradehub/journal/__init__.py`:

```python
"""The prediction journal (v2 spec): freeze -> settle -> score -> render, one contract for every forecaster."""
```

`tradehub/journal/contract.py`:

```python
"""The forecaster contract (v2 spec §3): what every forecaster implements and what the pipeline stores.

A forecaster names its upcoming targets (with their freeze cutoffs), gives one probability per target
before the cutoff, and settles targets once their outcome is public. Everything else -- storage,
the freeze guarantees, scoring, gates -- is the pipeline's job and is identical for every forecaster.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

CADENCES = ("daily", "monthly", "meeting")


def require_aware(value: datetime, name: str) -> datetime:
    """Every journal timestamp is timezone-aware: naive local time rotted fixtures in #46."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware, got naive {value!r}")
    return value


@dataclass(frozen=True)
class CalendarEntry:
    """One target and the moment after which nobody may forecast it."""

    target: str
    family: str
    cadence: str
    cutoff_at: datetime
    market_linked: bool = False
    climatology_prob: float | None = None

    def __post_init__(self) -> None:
        if not self.target or not self.family:
            raise ValueError("target and family are required")
        if self.cadence not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}, got {self.cadence!r}")
        require_aware(self.cutoff_at, "cutoff_at")
        if self.climatology_prob is not None and not 0.0 < self.climatology_prob < 1.0:
            raise ValueError("climatology_prob must be in (0, 1)")


@dataclass(frozen=True)
class Forecast:
    """One frozen probability that `target` resolves to 1."""

    forecaster: str
    forecaster_version: str
    target: str
    probability: float
    market_prob: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {self.probability}")
        if self.market_prob is not None and not 0.0 <= self.market_prob <= 1.0:
            raise ValueError(f"market_prob must be in [0, 1], got {self.market_prob}")

    @property
    def source_hash(self) -> str:
        """Hash of the inputs the forecaster recorded, so the row is auditable against its payload."""
        blob = json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Settlement:
    """The realised outcome of one target (1 = the event happened)."""

    target: str
    outcome: int
    source: str
    realized_value: float | None = None

    def __post_init__(self) -> None:
        if self.outcome not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {self.outcome}")
        if not self.source:
            raise ValueError("a settlement must name its source")


class Forecaster(Protocol):
    """What plans (b)-(f) implement. The runner calls these in order: targets, forecast, settle."""

    name: str
    version: str
    cadence: str  # one of CADENCES; sets the gate's settled-target minimum

    def targets(self, now: datetime) -> list[CalendarEntry]:
        """Upcoming targets (cutoff in the future) this forecaster will forecast."""

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        """The forecast for `entry`, or None when the inputs are not available (a gap, never a guess)."""

    def settle(self, target: str, now: datetime) -> Settlement | None:
        """The outcome of `target` if it is public by `now`, else None (retried next run)."""
```

`tradehub/journal/scoring.py`:

```python
"""Scoring (v2 spec §3 step 3, §10): pure functions from frozen rows + settlements to a scorecard.

Idempotent by construction: the same rows give the same scorecard, so the score job can recompute
everything every run. Rebuilt rows are displayed elsewhere but never reach these functions' counts.
"""

from __future__ import annotations

from typing import Any

from tradehub.track_record import BUCKETS, bucketize

MIN_SETTLED = {"daily": 200, "monthly": 50, "meeting": 50}
MIN_BUCKET_TARGETS = 20
MURPHY_BINS = 10


def _brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def settled_pairs(forecasts: list[dict[str, Any]], settlements: dict[str, int]) -> list[dict[str, Any]]:
    """Counted, settled forecasts: rebuilt rows excluded, unsettled targets excluded.

    One forecast per (forecaster, version, target) is enforced by the table's UNIQUE constraint, so
    every row here is a distinct target: counts are targets, never rows (spec §10 counting rule).
    """
    out = []
    for row in forecasts:
        if row.get("rebuilt"):
            continue
        outcome = settlements.get(row["target"])
        if outcome is None:
            continue
        out.append({**row, "outcome": int(outcome)})
    return out


def baseline_prob(row: dict[str, Any], calendar: dict[str, dict[str, Any]]) -> tuple[float | None, str]:
    """The no-skill reference for one target: the market where one exists, else climatology."""
    if row.get("market_prob") is not None:
        return float(row["market_prob"]), "market"
    clim = (calendar.get(row["target"]) or {}).get("climatology_prob")
    if clim is not None:
        return float(clim), "climatology"
    return None, "none"


def reliability(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Confidence-space buckets (a 0.30 forecast is 70% confidence in 'no'), as in `bucketize`."""
    groups: dict[str, list[tuple[float, bool]]] = {b: [] for b in BUCKETS}
    for row in pairs:
        prob = float(row["probability"])
        favored_yes = prob >= 0.5
        confidence = prob if favored_yes else 1.0 - prob
        hit = (row["outcome"] == 1) if favored_yes else (row["outcome"] == 0)
        groups[bucketize(prob)].append((confidence, hit))
    out = []
    for bucket in BUCKETS:
        members = groups[bucket]
        if not members:
            continue
        out.append({
            "bucket": bucket,
            "n": len(members),
            "predicted": round(sum(c for c, _ in members) / len(members), 4),
            "observed": round(sum(1 for _, h in members if h) / len(members), 4),
        })
    return out


def murphy(pairs: list[dict[str, Any]]) -> dict[str, float] | None:
    """Binned Murphy decomposition: Brier ~= reliability - resolution + uncertainty."""
    n = len(pairs)
    if n == 0:
        return None
    base = sum(r["outcome"] for r in pairs) / n
    bins: dict[int, list[dict[str, Any]]] = {}
    for row in pairs:
        idx = min(int(float(row["probability"]) * MURPHY_BINS), MURPHY_BINS - 1)
        bins.setdefault(idx, []).append(row)
    rel = res = 0.0
    for members in bins.values():
        k = len(members)
        f = sum(float(r["probability"]) for r in members) / k
        o = sum(r["outcome"] for r in members) / k
        rel += k * (f - o) ** 2
        res += k * (o - base) ** 2
    return {"reliability": round(rel / n, 6), "resolution": round(res / n, 6),
            "uncertainty": round(base * (1 - base), 6)}


def score(forecasts: list[dict[str, Any]], settlements: dict[str, int],
          calendar: dict[str, dict[str, Any]], cadence: str) -> dict[str, Any]:
    """The scorecard for one (forecaster, version).

    `brier` covers every settled target; `bss` compares the forecaster with its baseline on exactly
    the targets that have a baseline (same contracts on both sides), and `baseline` says which
    baseline dominates so the tile can label it.
    """
    if cadence not in MIN_SETTLED:
        raise ValueError(f"unknown cadence {cadence!r}")
    counted = [r for r in forecasts if not r.get("rebuilt")]
    pairs = settled_pairs(forecasts, settlements)
    brier = sum(_brier(float(r["probability"]), r["outcome"]) for r in pairs) / len(pairs) if pairs else None

    ours_on_base, theirs, kinds = [], [], {"market": 0, "climatology": 0}
    for row in pairs:
        prob, kind = baseline_prob(row, calendar)
        if prob is None:
            continue
        kinds[kind] += 1
        ours_on_base.append(_brier(float(row["probability"]), row["outcome"]))
        theirs.append(_brier(prob, row["outcome"]))
    brier_base = sum(theirs) / len(theirs) if theirs else None
    ours_b = sum(ours_on_base) / len(ours_on_base) if ours_on_base else None
    bss = (1.0 - ours_b / brier_base) if (ours_b is not None and brier_base) else None
    baseline = "none" if not theirs else ("market" if kinds["market"] >= kinds["climatology"] else "climatology")

    buckets = reliability(pairs)
    calibration_ready = bool(buckets) and all(b["n"] >= MIN_BUCKET_TARGETS for b in buckets)
    reasons = []
    if len(pairs) < MIN_SETTLED[cadence]:
        reasons.append(f"only {len(pairs)} settled targets, need {MIN_SETTLED[cadence]} ({cadence})")
    if bss is None:
        reasons.append("no baseline to compare against")
    elif bss <= 0:
        reasons.append(f"Brier skill {bss:.4f} vs {baseline} is not positive")
    if not calibration_ready:
        reasons.append(f"a calibration bucket has fewer than {MIN_BUCKET_TARGETS} settled targets")
    return {
        "cadence": cadence,
        "baseline": baseline,
        "n_targets": len(counted),
        "n_settled": len(pairs),
        "brier": round(brier, 6) if brier is not None else None,
        "brier_baseline": round(brier_base, 6) if brier_base is not None else None,
        "bss": round(bss, 6) if bss is not None else None,
        "reliability": buckets,
        "murphy": murphy(pairs) or {},
        "calibration_ready": calibration_ready,
        "gate_status": "PROMOTED" if not reasons else "SHADOW",
        "gate_reasons": reasons,
    }


def headline(cards: list[dict[str, Any]]) -> dict[str, int]:
    """The journal's hero numbers (spec §10 display gate): headline counts cover calibrated forecasters only."""
    calibrated = [c for c in cards if c.get("calibration_ready")]
    return {
        "forecasters": len(cards),
        "calibrated": len(calibrated),
        "settled_calibrated": sum(int(c.get("n_settled") or 0) for c in calibrated),
        "promoted": sum(1 for c in cards if c.get("gate_status") == "PROMOTED"),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_scoring.py -v` — Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal/__init__.py tradehub/journal/contract.py tradehub/journal/scoring.py tests/test_journal_scoring.py
git commit -m "feat(journal): forecaster contract and scoring (Brier, BSS, reliability, Murphy, gates)"
```

---

### Task 3: Store, runner, registry and hourly CLI

**Files:**
- Create: `tests/journal_fakes.py`, `tradehub/journal/store.py`, `tradehub/journal/runner.py`, `tradehub/journal/registry.py`, `tradehub/scripts/journal_run.py`
- Test: `tests/test_journal_runner.py`

**Interfaces:**
- Consumes: Task 2's `contract` and `score`.
- Produces: `run_journal(supa, forecasters, now) -> {"as_of": str, "forecasters": {"name@version": summary}, "failures": [str]}` where summary is `{registered, frozen, missed, settled, gate_status}` or `{error}`; `store.freeze(supa, Forecast) -> bool`; `store.settle(supa, Settlement) -> bool`; `FORECASTERS: list[Forecaster]`.

- [ ] **Step 1: Write the fake database** (`tests/journal_fakes.py`). It mirrors the trigger rules so the Python pipeline can be tested for how it reacts to refusals; Task 1 proves the real rules. Tests import it as `from journal_fakes import FakeJournalDB` (the repo's `tests/` is on `sys.path`, same as other helper modules).

```python
"""An in-memory Supabase stand-in for the journal, including the migration's trigger rules.

It mirrors the database guarantees (tests/test_journal_migration_pg.py proves the real ones) so the
Python pipeline can be tested for how it *reacts* to refusals: late freeze, no calendar row,
settlement before cutoff, immutability. `clock` is what "now()" means inside the fake database.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db: FakeJournalDB, table: str):
        self.db, self.table, self.filters, self.lo, self.hi, self.op, self.payload = db, table, [], None, None, "select", None
        self.order_by: tuple[str, ...] = ()

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.filters.append(lambda r, c=col, v=vals: r.get(c) in v)
        return self

    def order(self, *cols, desc=False, **_k):
        self.order_by, self.desc = cols, desc
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def limit(self, n):
        self.lo, self.hi = 0, n - 1
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def upsert(self, row, on_conflict):
        self.op, self.payload, self.conflict = "upsert", row, on_conflict.split(",")
        return self

    def execute(self):
        if self.op == "insert":
            return _Result([self.db.insert(self.table, dict(self.payload))])
        if self.op == "upsert":
            return _Result([self.db.upsert(self.table, dict(self.payload), self.conflict)])
        rows = [r for r in self.db.tables[self.table] if all(f(r) for f in self.filters)]
        if self.order_by:
            rows.sort(key=lambda r: tuple(r.get(c) for c in self.order_by), reverse=getattr(self, 'desc', False))
        if self.lo is not None:
            rows = rows[self.lo:self.hi + 1]
        return _Result([dict(r) for r in rows])


class FakeJournalDB:
    def __init__(self, clock: Callable[[], datetime]):
        self.clock = clock
        self.tables: dict[str, list[dict[str, Any]]] = {
            "journal_calendars": [], "journal_forecasts": [], "journal_settlements": [], "journal_scores": [],
            "backtest_runs": [], "track_record": [],
        }
        self._id = 0

    def table(self, name):
        return _Query(self, name)

    def _cutoff(self, target):
        for row in self.tables["journal_calendars"]:
            if row["target"] == target:
                return datetime.fromisoformat(row["cutoff_at"])
        return None

    def insert(self, table, row):
        now = self.clock()
        if table == "journal_calendars":
            if datetime.fromisoformat(row["cutoff_at"]) <= now:
                raise RuntimeError("journal: calendar cutoff is not in the future")
            if any(r["target"] == row["target"] for r in self.tables[table]):
                raise RuntimeError("duplicate key")
        elif table == "journal_forecasts":
            cutoff = self._cutoff(row["target"])
            if cutoff is None:
                raise RuntimeError("journal: no calendar row for target")
            if now >= cutoff:
                raise RuntimeError("journal: freeze refused, cutoff has passed")
            key = (row["forecaster"], row["forecaster_version"], row["target"])
            if any((r["forecaster"], r["forecaster_version"], r["target"]) == key for r in self.tables[table]):
                raise RuntimeError("duplicate key")
            self._id += 1
            row.update(id=self._id, frozen_at=now.isoformat(), rebuilt=False)
        elif table == "journal_settlements":
            cutoff = self._cutoff(row["target"])
            if cutoff is None or now < cutoff:
                raise RuntimeError("journal: settlement refused before its cutoff")
            if any(r["target"] == row["target"] for r in self.tables[table]):
                raise RuntimeError("duplicate key")
            row["settled_at"] = now.isoformat()
        self.tables[table].append(row)
        return row

    def upsert(self, table, row, conflict):
        if table != "journal_scores":
            raise RuntimeError(f"{table} is immutable")
        rows = self.tables[table]
        for i, existing in enumerate(rows):
            if all(existing.get(c) == row.get(c) for c in conflict):
                rows[i] = row
                return row
        rows.append(row)
        return row
```

- [ ] **Step 2: Write the failing runner tests** (`tests/test_journal_runner.py`)

```python
from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.runner import run_journal

T0 = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class StubForecaster:
    """Three daily targets, one per day; forecasts 0.8 unless told otherwise; settles to 1."""

    name, version, cadence = "stub", "v1", "daily"

    def __init__(self, prob=0.8, missing=(), outcome=1):
        self.prob, self.missing, self.outcome = prob, set(missing), outcome

    def targets(self, now):
        return [CalendarEntry(f"test:day{i}", "test", "daily", T0 + timedelta(days=i), market_linked=True)
                for i in range(1, 4)]

    def forecast(self, entry, now):
        if entry.target in self.missing:
            return None
        return Forecast(self.name, self.version, entry.target, self.prob, market_prob=0.6, payload={"t": entry.target})

    def settle(self, target, now):
        return Settlement(target, self.outcome, "stub-source")


class Boom(StubForecaster):
    name = "boom"

    def targets(self, now):
        raise RuntimeError("feed down")


def test_freezes_every_open_target_once_and_never_twice():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    first = run_journal(db, [StubForecaster()], clock())
    again = run_journal(db, [StubForecaster()], clock())
    assert first["forecasters"]["stub@v1"]["frozen"] == 3
    assert again["forecasters"]["stub@v1"]["frozen"] == 0
    assert len(db.tables["journal_forecasts"]) == 3


def test_a_missing_input_is_a_gap_not_a_backfill():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    out = run_journal(db, [StubForecaster(missing={"test:day2"})], clock())
    assert out["forecasters"]["stub@v1"]["missed"] == 1
    clock.t = T0 + timedelta(days=5)  # day2's cutoff is long gone; the input "arrives" now
    later = run_journal(db, [StubForecaster()], clock())
    assert later["forecasters"]["stub@v1"]["frozen"] == 0
    assert "test:day2" not in {r["target"] for r in db.tables["journal_forecasts"]}


def test_settles_only_after_the_cutoff_and_scores_idempotently():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    run_journal(db, [StubForecaster()], clock())
    clock.t = T0 + timedelta(days=1, hours=1)  # only day1's cutoff has passed
    out = run_journal(db, [StubForecaster()], clock())
    assert out["forecasters"]["stub@v1"]["settled"] == 1
    card = db.tables["journal_scores"][0]
    assert card["n_settled"] == 1 and card["brier"] == pytest.approx(0.04)
    assert card["baseline"] == "market" and card["bss"] == pytest.approx(1 - 0.04 / 0.16)
    run_journal(db, [StubForecaster()], clock())
    assert len(db.tables["journal_scores"]) == 1 and db.tables["journal_scores"][0]["brier"] == card["brier"]


def test_one_failing_forecaster_does_not_stop_the_others():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    out = run_journal(db, [Boom(), StubForecaster()], clock())
    assert out["failures"] == ["boom@v1"]
    assert out["forecasters"]["stub@v1"]["frozen"] == 3


def test_now_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        run_journal(FakeJournalDB(lambda: T0), [], datetime(2026, 10, 1, 8))  # noqa: DTZ001
```

- [ ] **Step 3: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradehub.journal.runner'`.

- [ ] **Step 4: Implement**

`tradehub/journal/store.py`:

```python
"""Journal I/O against Supabase (service role). The freeze guarantees live in the database triggers
(migration 20260428000014); this module only reads, inserts, and reports what the database refused.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement

log = logging.getLogger(__name__)

CALENDARS = "journal_calendars"
FORECASTS = "journal_forecasts"
SETTLEMENTS = "journal_settlements"
SCORES = "journal_scores"
PAGE = 1000  # PostgREST returns at most 1000 rows per request, so reads page explicitly.
IN_CHUNK = 200  # keep `in.(...)` filters well under URL length limits


def select_all(supa, table: str, build: Callable[[Any], Any], order: tuple[str, ...]) -> list[dict[str, Any]]:
    """Read every matching row through ordered `.range()` pages (see api/main.py `_fetch_all`)."""
    rows: list[dict[str, Any]] = []
    lo = 0
    while True:
        chunk = build(supa.table(table).select("*")).order(*order).range(lo, lo + PAGE - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        lo += PAGE


def _chunks(items: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(items), IN_CHUNK):
        yield items[i:i + IN_CHUNK]


def fetch_calendar(supa, targets: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(sorted(set(targets))):
        for row in select_all(supa, CALENDARS, lambda q, c=chunk: q.in_("target", c), ("target",)):
            out[row["target"]] = row
    return out


def register_calendar(supa, entries: list[CalendarEntry], now: datetime) -> int:
    """Insert calendar rows that do not exist yet and whose cutoff is still ahead. Returns the count."""
    existing = fetch_calendar(supa, [e.target for e in entries])
    fresh = [e for e in entries if e.target not in existing and e.cutoff_at > now]
    for entry in fresh:
        supa.table(CALENDARS).insert({
            "target": entry.target, "family": entry.family, "cadence": entry.cadence,
            "cutoff_at": entry.cutoff_at.isoformat(), "market_linked": entry.market_linked,
            "climatology_prob": entry.climatology_prob,
        }).execute()
    return len(fresh)


def fetch_forecasts(supa, forecaster: str, version: str) -> list[dict[str, Any]]:
    return select_all(supa, FORECASTS,
                      lambda q: q.eq("forecaster", forecaster).eq("forecaster_version", version), ("id",))


def freeze(supa, forecast: Forecast) -> bool:
    """Insert one frozen forecast. False when the database refused it: a gap, never a backfill."""
    try:
        supa.table(FORECASTS).insert({
            "forecaster": forecast.forecaster, "forecaster_version": forecast.forecaster_version,
            "target": forecast.target, "probability": round(forecast.probability, 5),
            "market_prob": round(forecast.market_prob, 5) if forecast.market_prob is not None else None,
            "source_hash": forecast.source_hash, "payload": forecast.payload,
        }).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - the trigger's refusal is the expected failure mode
        log.warning("journal: freeze refused for %s/%s %s: %s", forecast.forecaster, forecast.forecaster_version,
                    forecast.target, exc)
        return False


def fetch_settlements(supa, targets: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for chunk in _chunks(sorted(set(targets))):
        for row in select_all(supa, SETTLEMENTS, lambda q, c=chunk: q.in_("target", c), ("target",)):
            out[row["target"]] = int(row["outcome"])
    return out


def settle(supa, settlement: Settlement) -> bool:
    try:
        supa.table(SETTLEMENTS).insert({
            "target": settlement.target, "outcome": settlement.outcome,
            "realized_value": settlement.realized_value, "source": settlement.source,
        }).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - e.g. a race with another run; retried next run
        log.warning("journal: settlement refused for %s: %s", settlement.target, exc)
        return False


def upsert_score(supa, forecaster: str, version: str, card: dict[str, Any], now: datetime) -> None:
    supa.table(SCORES).upsert({"forecaster": forecaster, "forecaster_version": version,
                               **card, "computed_at": now.isoformat()},
                              on_conflict="forecaster,forecaster_version").execute()
```

`tradehub/journal/runner.py`:

```python
"""One journal run: for every registered forecaster, freeze -> settle -> score, isolated per forecaster.

Failure rules (spec §4): a missed freeze is a gap that is logged and never backfilled; an unsettled
target is retried on the next run; scoring is an idempotent recompute.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from tradehub.journal import store
from tradehub.journal.contract import Forecaster, require_aware
from tradehub.journal.scoring import score

log = logging.getLogger(__name__)


def run_forecaster(supa, fc: Forecaster, now: datetime) -> dict[str, Any]:
    summary: dict[str, Any] = {"registered": 0, "frozen": 0, "missed": 0, "settled": 0, "gate_status": None}
    entries = [e for e in fc.targets(now) if e.cadence == fc.cadence]
    summary["registered"] = store.register_calendar(supa, entries, now)

    existing = store.fetch_forecasts(supa, fc.name, fc.version)
    frozen = {row["target"] for row in existing}
    for entry in entries:
        if entry.target in frozen or entry.cutoff_at <= now:
            continue
        forecast = fc.forecast(entry, now)
        if forecast is None:
            summary["missed"] += 1
            log.info("journal: %s/%s has no forecast for %s (gap, not backfilled)", fc.name, fc.version, entry.target)
            continue
        if forecast.forecaster != fc.name or forecast.forecaster_version != fc.version or forecast.target != entry.target:
            raise ValueError(f"{fc.name}: forecast identity does not match its forecaster/target")
        if store.freeze(supa, forecast):
            summary["frozen"] += 1
        else:
            summary["missed"] += 1

    rows = store.fetch_forecasts(supa, fc.name, fc.version)
    targets = [r["target"] for r in rows]
    calendar = store.fetch_calendar(supa, targets)
    settled = store.fetch_settlements(supa, targets)
    for target in targets:
        cutoff = calendar.get(target, {}).get("cutoff_at")
        if target in settled or cutoff is None or datetime.fromisoformat(str(cutoff)) > now:
            continue
        result = fc.settle(target, now)
        if result is not None and store.settle(supa, result):
            settled[target] = result.outcome
            summary["settled"] += 1

    card = score(rows, settled, calendar, fc.cadence)
    store.upsert_score(supa, fc.name, fc.version, card, now)
    summary["gate_status"] = card["gate_status"]
    return summary


def run_journal(supa, forecasters: list[Forecaster], now: datetime) -> dict[str, Any]:
    require_aware(now, "now")
    out: dict[str, Any] = {"as_of": now.isoformat(), "forecasters": {}, "failures": []}
    for fc in forecasters:
        key = f"{fc.name}@{fc.version}"
        try:
            out["forecasters"][key] = run_forecaster(supa, fc, now)
        except Exception as exc:
            log.exception("journal: %s failed", key)
            out["forecasters"][key] = {"error": f"{type(exc).__name__}: {exc}"}
            out["failures"].append(key)
    return out
```

`tradehub/journal/registry.py`:

```python
"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each."""

from __future__ import annotations

from tradehub.journal.contract import Forecaster

FORECASTERS: list[Forecaster] = []
```

`tradehub/scripts/journal_run.py`:

```python
"""Cron entrypoint: one prediction-journal run (freeze -> settle -> score for every forecaster).

Run hourly by the VPS `tradehub-journal.timer` (vps-stack). Each forecaster decides from its own
calendar whether anything is due, so an hourly run is cheap when nothing is.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.journal.registry import FORECASTERS
from tradehub.journal.runner import run_journal


def main() -> int:
    load_local_env()
    summary = run_journal(get_client(), FORECASTERS, datetime.now(UTC))
    print(json.dumps(summary, default=str))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run to verify pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_runner.py -v` — Expected: 5 passed.
Smoke the CLI import: `.venv/bin/python -c "import tradehub.scripts.journal_run"` — Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add tests/journal_fakes.py tests/test_journal_runner.py tradehub/journal/store.py tradehub/journal/runner.py tradehub/journal/registry.py tradehub/scripts/journal_run.py
git commit -m "feat(journal): store, isolated runner, registry and hourly CLI"
```

---

### Task 4: The journal is the gate's ledger of record

**Files:**
- Modify: `tradehub/gate_status.py` (`latest_gate_statuses`, new `_journal_rows`)
- Modify: `tests/test_scan.py` (its hand-rolled fake must answer `journal_scores`)
- Test: `tests/test_journal_runner.py` (append)

**Interfaces:**
- Consumes: `journal_scores` rows from Task 3.
- Produces: `latest_gate_statuses(supa, pairs)` unchanged signature; for a pair with a journal row the journal alone decides; a missing `journal_scores` table (not deployed yet) falls back to legacy tables; any other error propagates (callers already fail closed).

- [ ] **Step 1: Append the failing tests** to `tests/test_journal_runner.py`:

```python
def test_the_gate_uses_the_journal_scorecard_alone_once_a_forecaster_is_on_it():
    from tradehub.gate_status import latest_gate_statuses

    db = FakeJournalDB(lambda: T0)
    # Legacy tables say PROMOTED; the journal says SHADOW. The journal is the ledger of record.
    db.tables["backtest_runs"].append({"engine": "cpi", "engine_version": "v1", "gate_status": "PROMOTED",
                                       "created_at": "2026-09-01"})
    db.tables["track_record"].append({"engine": "cpi", "engine_version": "v1", "gate_status": "PROMOTED"})
    assert latest_gate_statuses(db, {("cpi", "v1")}) == {("cpi", "v1"): "PROMOTED"}  # not on the journal yet
    db.tables["journal_scores"].append({"forecaster": "cpi", "forecaster_version": "v1", "gate_status": "SHADOW"})
    assert latest_gate_statuses(db, {("cpi", "v1")}) == {("cpi", "v1"): "SHADOW"}


def test_the_gate_falls_back_when_the_journal_table_is_not_deployed_yet():
    from tradehub.gate_status import latest_gate_statuses

    class NoJournal(FakeJournalDB):
        def table(self, name):
            if name == "journal_scores":
                raise RuntimeError("Could not find the table 'public.journal_scores' in the schema cache")
            return super().table(name)

    assert latest_gate_statuses(NoJournal(lambda: T0), {("cpi", "v1")}) == {("cpi", "v1"): "SHADOW"}
```

- [ ] **Step 2: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_runner.py -k gate -v`
Expected: `test_the_gate_uses_the_journal_scorecard_alone…` FAILS (returns PROMOTED from the legacy tables).

- [ ] **Step 3: Implement** — apply to `tradehub/gate_status.py`:

```diff
diff --git a/tradehub/gate_status.py b/tradehub/gate_status.py
index 6aeea1a..c6246ce 100644
--- a/tradehub/gate_status.py
+++ b/tradehub/gate_status.py
@@ -25,6 +25,26 @@ log = logging.getLogger(__name__)
 DEFAULT_GATE_STATUS = "SHADOW"
 
 
+def _journal_rows(supa, engine: str, version: str) -> list[dict]:
+    """The journal scorecard row for this pair, or [] when the journal table does not exist yet.
+
+    Deploy order: code can reach production before migration 20260428000014 is applied. A missing
+    `journal_scores` table then means "no forecaster has moved onto the journal yet", which is
+    exactly what falling through to the legacy tables says. Any other error propagates, and callers
+    already treat a failed lookup as SHADOW.
+    """
+    try:
+        result = supa.table("journal_scores").select("gate_status") \
+            .eq("forecaster", engine).eq("forecaster_version", version).limit(1).execute()
+    except Exception as exc:  # noqa: BLE001 - narrowed just below
+        text = str(exc)
+        if "journal_scores" in text and ("schema cache" in text or "does not exist" in text or "PGRST205" in text):
+            log.info("gate: journal_scores not present yet; using the legacy gate tables")
+            return []
+        raise
+    return list(result.data or [])
+
+
 def latest_gate_statuses(supa, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
     """{pair: "PROMOTED" | "SHADOW"} for every requested (engine, engine_version) pair.
 
@@ -33,6 +53,15 @@ def latest_gate_statuses(supa, pairs: set[tuple[str, str]]) -> dict[tuple[str, s
     """
     statuses: dict[tuple[str, str], str] = {}
     for engine, version in pairs:
+        # One ledger of record (v2 spec §4): a forecaster that publishes through the journal is
+        # gated by its journal scorecard alone. Its old `backtest_runs`/`track_record` rows are
+        # pre-journal history and must not be able to promote it.
+        journal_rows = _journal_rows(supa, engine, version)
+        if journal_rows:
+            statuses[(engine, version)] = (
+                "PROMOTED" if journal_rows[0].get("gate_status") == "PROMOTED" else DEFAULT_GATE_STATUS
+            )
+            continue
         backtest = supa.table("backtest_runs") \
             .select("engine,engine_version,gate_status,created_at") \
             .eq("engine", engine).eq("engine_version", version) \
```

and to `tests/test_scan.py` (the fake records every call; the journal lookup must not appear in its expected call list):

```diff
diff --git a/tests/test_scan.py b/tests/test_scan.py
index e128f79..4da4d57 100644
--- a/tests/test_scan.py
+++ b/tests/test_scan.py
@@ -100,6 +100,8 @@ def test_latest_gate_statuses_requires_latest_backtest_and_matching_track_record
             return self
 
         def execute(self):
+            if self.name == "journal_scores":
+                return type("Result", (), {"data": []})()  # no forecaster is on the journal here
             calls.append((self.name, dict(self.filters), self.ordered, self.limit_value))
             if self.name == "backtest_runs":
                 row = backtests.get(self.filters["engine"])
```

- [ ] **Step 4: Run to verify pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_runner.py tests/test_scan.py tests/test_scoreboard_api.py -v` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/gate_status.py tests/test_scan.py tests/test_journal_runner.py
git commit -m "feat(journal): gate reads journal_scores first; tolerate the table not existing yet"
```

---

### Task 5: Read-only journal API

**Files:**
- Modify: `tradehub/api/main.py` (insert a block immediately before the `# Sports edges (rollout step 7)` section banner)
- Test: `tests/test_journal_api.py`

**Interfaces:**
- Consumes: existing `get_supabase`, `_fetch_all`, `_table_fault`, `DEFAULT_GATE_STATUS` in `tradehub/api/main.py`.
- Produces: `GET /api/journal`, `GET /api/journal/feed` (shapes in File Structure). The headline is computed server-side by `tradehub.journal.scoring.headline` (Task 2's file), so the page never sums anything. Plan (f) (/journal UI) renders these; it must not recompute any number.

- [ ] **Step 1: Write the failing tests** (`tests/test_journal_api.py`)

```python
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app

T0 = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)


def _client(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def teardown_function(_fn):
    app.dependency_overrides.clear()


def test_journal_returns_precomputed_scorecards_in_order():
    db = FakeJournalDB(lambda: T0)
    db.tables["journal_scores"] += [
        {"forecaster": "labor", "forecaster_version": "v1", "gate_status": "SHADOW", "n_settled": 9,
         "calibration_ready": False},
        {"forecaster": "cpi", "forecaster_version": "v1", "gate_status": "PROMOTED", "n_settled": 60,
         "calibration_ready": True},
    ]
    res = _client(db).get("/api/journal")
    assert res.status_code == 200
    body = res.json()
    assert [r["forecaster"] for r in body["forecasters"]] == ["cpi", "labor"]
    # headline counts cover calibrated forecasters only (spec §10); the page renders, never sums
    assert body["headline"] == {"forecasters": 2, "calibrated": 1, "settled_calibrated": 60, "promoted": 1}


def test_feed_is_newest_first_with_calibration_and_provisional_flag():
    db = FakeJournalDB(lambda: T0)
    for i in (1, 2, 3):
        db.tables["journal_forecasts"].append({"id": i, "forecaster": "cpi", "forecaster_version": "v1",
                                               "target": f"t{i}", "probability": 0.6, "market_prob": 0.5,
                                               "frozen_at": T0.isoformat(), "rebuilt": False, "source_hash": "h"})
    db.tables["journal_scores"].append({"forecaster": "cpi", "forecaster_version": "v1", "gate_status": "SHADOW",
                                        "reliability": [{"bucket": "60-70", "n": 3}], "calibration_ready": False})
    body = _client(db).get("/api/journal/feed", params={"forecaster": "cpi", "version": "v1", "limit": 2}).json()
    assert [f["target"] for f in body["forecasts"]] == ["t3", "t2"]
    assert body["calibration"] == [{"bucket": "60-70", "n": 3}]
    assert body["gate_status"] == "SHADOW" and body["provisional"] is True


def test_feed_rejects_bad_paging_and_503s_without_supabase():
    db = FakeJournalDB(lambda: T0)
    assert _client(db).get("/api/journal/feed", params={"forecaster": "x", "version": "v1", "limit": 0}).status_code == 422
    app.dependency_overrides[get_supabase] = lambda: None
    assert TestClient(app).get("/api/journal").status_code == 503


def test_a_missing_journal_table_names_the_migration():
    class NoJournal(FakeJournalDB):
        def table(self, name):
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")

    res = _client(NoJournal(lambda: T0)).get("/api/journal")
    assert res.status_code == 503
```

- [ ] **Step 2: Run to verify failure**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_api.py -v` — Expected: FAIL with 404s.

- [ ] **Step 3: Implement** — apply to `tradehub/api/main.py`:

```diff
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index dd69e23..d36f38b 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -32,6 +32,7 @@ from tradehub.engines.cpi import CPI_MIN_TRAIN, DEFAULT_CPI_ERROR
 from tradehub.engine_catalogue import engine_catalogue
 from tradehub.engine_health import engine_health
 from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
+from tradehub.journal.scoring import headline as journal_headline
 from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report
 from tradehub.scoreboard import current_runs, market_comparison
 from tradehub.scripts.shadow_performance import MissingCredentialError, build_shadow_timeline_response
@@ -445,6 +446,59 @@ async def get_track_record(supabase=Depends(get_supabase)):
     return result.data or []
 
 
+# ════════════════════════════════════════════════════════════════════════════
+# Prediction journal (v2 spec §3-§4, §11): precomputed scorecards and frozen forecasts.
+# The frontend renders these numbers; it never recomputes them.
+# ════════════════════════════════════════════════════════════════════════════
+JOURNAL_PAGE_MAX = 500
+
+
+@app.get("/api/journal", tags=["Journal"])
+def get_journal(supabase=Depends(get_supabase)):
+    """Every (forecaster, version) scorecard, ordered by forecaster, plus the precomputed headline."""
+    if supabase is None:
+        raise HTTPException(status_code=503, detail="Supabase is not configured")
+    try:
+        rows = _fetch_all(supabase, "journal_scores", lambda q: q.select("*"),
+                          order=("forecaster", "forecaster_version"))
+    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
+        raise _table_fault("journal_scores", exc) from exc
+    return {"as_of": datetime.now(timezone.utc).isoformat(), "forecasters": rows, "headline": journal_headline(rows)}
+
+
+@app.get("/api/journal/feed", tags=["Journal"])
+def get_journal_feed(forecaster: str, version: str, limit: int = 100, offset: int = 0,
+                     supabase=Depends(get_supabase)):
+    """Frozen forecasts for one forecaster (newest first) plus its calibration buckets.
+
+    The `/api/kalshi-feed` shape, so downstream consumers read the journal the way the hub reads the
+    predictors: frozen snapshots and calibration, never a recomputed number.
+    """
+    if supabase is None:
+        raise HTTPException(status_code=503, detail="Supabase is not configured")
+    if limit < 1 or limit > JOURNAL_PAGE_MAX or offset < 0:
+        raise HTTPException(status_code=422, detail=f"limit must be 1..{JOURNAL_PAGE_MAX} and offset >= 0")
+    try:
+        rows = supabase.table("journal_forecasts").select("*") \
+            .eq("forecaster", forecaster).eq("forecaster_version", version) \
+            .order("id", desc=True).range(offset, offset + limit - 1).execute().data or []
+        card = supabase.table("journal_scores").select("*") \
+            .eq("forecaster", forecaster).eq("forecaster_version", version).limit(1).execute().data or []
+    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
+        raise _table_fault("journal_forecasts", exc) from exc
+    score = card[0] if card else None
+    return {
+        "forecaster": forecaster,
+        "forecaster_version": version,
+        "generated_at": datetime.now(timezone.utc).isoformat(),
+        "forecasts": [{k: r.get(k) for k in ("target", "probability", "market_prob", "frozen_at", "rebuilt",
+                                              "source_hash")} for r in rows],
+        "calibration": (score or {}).get("reliability", []),
+        "gate_status": (score or {}).get("gate_status", DEFAULT_GATE_STATUS),
+        "provisional": not bool((score or {}).get("calibration_ready")),
+    }
+
+
 # ════════════════════════════════════════════════════════════════════════════
 # Sports edges (rollout step 7): candidate edges with review verdicts and links
 # ════════════════════════════════════════════════════════════════════════════
```

- [ ] **Step 4: Run to verify pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_api.py tests/test_scoreboard_api.py -v` — Expected: all pass (`test_the_fail_closed_default_is_one_named_constant` fails if you wrote the `"SHADOW"` literal).

- [ ] **Step 5: Commit**

```bash
git add tradehub/api/main.py tests/test_journal_api.py
git commit -m "feat(journal): GET /api/journal and /api/journal/feed"
```

---

### Task 6: Full verification, PR, then deploy wiring

- [ ] **Step 1: Full suite at both CI clocks** (CI clock flakes bit PRs #11, #14, #16):

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline: 1353 passed).

- [ ] **Step 2: Lint the new files**

```bash
.venv/bin/python -m ruff check tradehub/journal tradehub/scripts/journal_run.py tests/journal_fakes.py tests/test_journal_*.py
```
Expected: `All checks passed!` (the repo has pre-existing ruff debt elsewhere; do not fix it in this PR).

- [ ] **Step 3: Open the PR** titled `feat: prediction journal pipeline (wave 1 plan a)`. The body must state: migration `20260428000014` needs applying **before merge**; the registry is empty, so nothing is journaled until plans b–f land; `/api/journal` returns `[]` until then.

- [ ] **Step 4 (reviewer/Kevin, not the implementing agent): apply the migration** via the Supabase connector (project `wuhpbvgidnrrdndhkehl`) using the exact file, then run `NOTIFY pgrst, 'reload schema';`, then verify with `select count(*) from journal_scores;` (0 rows, no error). Only then merge.

- [ ] **Step 5 (vps-stack follow-up, reviewer/Kevin):** add a `journal` case to the `tradehub-job` dispatcher that runs `python -m tradehub.scripts.journal_run`, plus a `tradehub-journal.timer` (`OnCalendar=hourly`, `Persistent=true`, `RandomizedDelaySec=120`) and matching `.service`. Hourly is enough: the earliest wave-1 cutoff granularity is daily, and the runner only freezes targets whose cutoff is still ahead.

## Self-Review (done by the plan author)

- **Spec coverage:** §3 contract → Task 2; §4 ledger, triggers, failure rules (gap/retry/idempotent) → Tasks 1, 3; §5 gates (per-target minimums, BSS baseline, calibration 4×20 rule as ≥20 per populated bucket) → Task 2; one ledger of record → Task 4; §11 API → Task 5; ops (timer, migration order) → Task 6. Per-forecaster models, the /journal page and legacy-table migration are plans b–f by design.
- **Placeholders:** none; every step has the code or command.
- **Type consistency:** `score()` keys equal `journal_scores` columns (Task 1) minus the PK and `computed_at`, which `store.upsert_score` adds; `FakeJournalDB` table names equal `store` constants; `Forecaster.cadence` values equal the migration's CHECK and `MIN_SETTLED` keys.

# Step 2b: Promotion-Gate and Settlement Hardening — evidence report

Plan: `docs/superpowers/plans/2026-09-25-gate-hardening.md`
Branch: `plan/2026-09-25-gate-hardening`
Base: `98432bc` (PR #4 reconciled head; PR #4 still open, continuation explicitly authorized)

## Baseline

Recorded before Task 1, on a clean tree at `98432bc`.

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 63%]
........................................................................ [ 84%]
.....................................................                    [100%]
341 passed in 4.77s
```

```
$ /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

Baseline: **full pytest 341 passed; scoped Ruff clean.**

---

## Task 1 — Hardening migration

Migration `20260416000007_predictions_hardening.sql` (reserved for this plan) plus
`tests/test_predictions_hardening_migration.py`.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_predictions_hardening_migration.py -q
E       FileNotFoundError: [Errno 2] No such file or directory:
          '.../market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql'
=========================== short test summary info ============================
FAILED tests/test_predictions_hardening_migration.py::test_hardening_migration_covers_step_2b
1 failed in 0.06s
```

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_predictions_hardening_migration.py -q
.                                                                        [100%]
1 passed in 0.01s
```

### Extra validation — throwaway `postgres:16-alpine` (Docker was available, so the optional check was run)

`20260416000003` then `20260416000007` twice, with a stubbed `auth` schema:

```
applied 20260416000003_predictions_ledger
applied 20260416000007_predictions_hardening
applied 20260416000007_predictions_hardening
```

The second `000007` run emitted only `NOTICE ... skipping` lines, confirming idempotency.
Behavioural checks against the live throwaway database:

```
== track_record_pkey ==
PRIMARY KEY (engine, engine_version)

== two versions of one engine side by side ==
 engine  | engine_version | n_settled
---------+----------------+-----------
 weather | v1             |         5
 weather | v2             |         7
(2 rows)

== SETTLED without result is rejected (expect ERROR) ==
ERROR:  new row for relation "predictions" violates check constraint "predictions_settled_has_result"

== policies on predictions / track_record ==
predictions :: predictions_owner_read :: SELECT
track_record :: track_record_owner_read :: SELECT

== any FOR ALL policy? (expect empty) ==
<no rows>
```

All four Intent items hold: the two new columns exist, `predictions_settled_has_result`
rejects a resultless `SETTLED` row, `track_record_pkey` is `(engine, engine_version)` and
holds two versions side by side, and only the `*_owner_read` SELECT policies remain.

### Implementation summary

- Added `predictions.settlement_payload jsonb` and `predictions.settled_at timestamptz`
  (`IF NOT EXISTS`, so re-runs are no-ops).
- Added `predictions_settled_has_result CHECK (status <> 'SETTLED' OR result IS NOT NULL)`
  behind a `pg_constraint` existence guard.
- Added the `(engine, engine_version, status)` index used by the per-version refresh.
- Rebuilt `track_record_pkey` as `(engine, engine_version)`; the guard joins
  `pg_attribute` and only drops the constraint when it is a single-column key, so
  re-running after the rebuild is a no-op.
- Dropped the old `FOR ALL` `predictions_owner` / `track_record_owner` policies and created
  read-only `*_owner_read` SELECT policies scoped by `auth.uid() = user_id`. Service-role
  jobs bypass RLS, so settlement and the refresh job keep writing; clients lose writes.

### Deviations

None. The migration and test were taken verbatim from the plan; both applied without
conflict on this base.

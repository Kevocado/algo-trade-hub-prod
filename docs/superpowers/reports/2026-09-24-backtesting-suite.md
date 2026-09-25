# Evidence Report — Backtesting Suite

- Plan: `docs/superpowers/plans/2026-09-24-backtesting-suite.md`
- Branch: `plan/2026-09-24-backtesting-suite`
- Base: `8ebf0f4` (local `main` with step 2 merged)
- Venv: `.venv/bin/python`
- Test environment: every pytest command uses process-only `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Baseline: `165 passed in 5.76s`.

## Task 1 — `backtest_runs` migration

- **Files changed:** `market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql`, `tests/test_repo_layout.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-1-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_backtest_runs_migration_defines_table -q
  ```
  RED output tail:
  ```text
  E       AssertionError: backtest_runs migration is missing
  E       assert False
  E        +  where False = is_file()
  E        +    where is_file = PosixPath('/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql').is_file
  tests/test_repo_layout.py:156: AssertionError
  =========================== short test summary info ============================
  FAILED tests/test_repo_layout.py::test_backtest_runs_migration_defines_table
  1 failed in 0.05s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
  ```
  GREEN output tail:
  ```text
  ...............                                                          [100%]
  15 passed in 0.37s
  ```
- **Migration review:** Added the exact idempotent `backtest_runs` table definition with the specified columns, engine/created-time index, row-level security, and owner-scoped policy.
- **Deviation:** None. The migration was intentionally not applied; Supabase deployment remains a manual step. The pre-existing evidence report was untracked and is included in this task commit as required.

## Task 2 — Point-in-time types and leakage guard

_Pending implementation._

## Task 3 — Kalshi public-history client

_Pending implementation._

## Task 4 — Conservative fill model

_Pending implementation._

## Task 5 — Metrics and runner

_Pending implementation._

## Task 6 — ALFRED and Open-Meteo sources

_Pending implementation._

## Task 7 — Reproducible run storage

_Pending implementation._

## Verification

_Pending implementation._

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- The step-2 PR remains open remotely; this prerequisite branch uses the local fast-forward merge requested by the user and does not push.

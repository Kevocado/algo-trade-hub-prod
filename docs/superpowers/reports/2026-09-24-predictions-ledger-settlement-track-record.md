# Evidence Report — Predictions Ledger + Settlement + Track Record

- Plan: `docs/superpowers/plans/2026-09-24-predictions-ledger-settlement-track-record.md`
- Branch: `plan/2026-09-24-predictions-ledger-settlement-track-record`
- Base: `7e01378` (`main`)
- Venv: `.venv/bin/python`
- Test environment: every pytest command uses process-only `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Baseline: `120 passed in 5.24s`.

## Task 1 — Predictions ledger + track_record migrations

- **Files changed:** `market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql`, `tests/test_repo_layout.py`.
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_predictions_ledger_migration_defines_both_tables -v
  ```
  Expected failing output tail:
  ```text
  E       AssertionError: predictions ledger migration is missing
  E       assert False
  E        +  where False = is_file()
  =============================== 1 failed in 0.06s ===============================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -v
  ```
  Passing output tail:
  ```text
  tests/test_repo_layout.py::test_predictions_ledger_migration_defines_both_tables PASSED [100%]
  ============================== 14 passed in 0.44s ==============================
  ```
- **Migration review:** Added idempotent `predictions` and `track_record` tables with the specified columns, indexes, constraints, and owner-scoped RLS policies.
- **Deviation:** None. The pre-existing evidence report was untracked and is included in this task commit as required.

## Task 2 — Prediction writer

- **Files changed:** `tradehub/predictions.py`, `tests/test_predictions.py`.
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_predictions.py -v
  ```
  Expected failing output tail:
  ```text
  E   ImportError: cannot import name 'predictions' from 'tradehub' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_predictions.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  ============================== 1 error in 0.11s ===============================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_predictions.py -v
  ```
  Passing output tail:
  ```text
  tests/test_predictions.py::test_record_predictions_batch_inserts PASSED [100%]
  ============================== 8 passed in 0.01s ===============================
  ```
- **Deviation:** None. The RED run produced the brief-approved collection error variant (`ImportError` rather than `ModuleNotFoundError`).

## Task 3 — Settlement math

- **Files changed:** `tradehub/settlement.py`, `tests/test_settlement.py`.
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v
  ```
  RED output tail:
  ```text
  collecting ... collected 0 items / 1 error

  ==================================== ERRORS ====================================
  __________________ ERROR collecting tests/test_settlement.py ___________________
  ImportError while importing test module '/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tests/test_settlement.py'.
  Hint: make sure your test modules/packages have valid Python names.
  Traceback:
  ../../../.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
      return _bootstrap._gcd_import(name[level:], package, level)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  tests/test_settlement.py:3: in <module>
      from tradehub import settlement
  E   ImportError: cannot import name 'settlement' from 'tradehub' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_settlement.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  ============================== 1 error in 0.15s ===============================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v
  ```
  GREEN output tail:
  ```text
  tests/test_settlement.py::test_settle_prediction_row_open_market_returns_none PASSED [ 92%]
  tests/test_settlement.py::test_settle_prediction_row_canceled_marks_canceled_without_fabricating_result PASSED [100%]

  ============================== 13 passed in 0.02s ==============================
  ```
- **Deviation:** None. The RED run produced the brief-approved collection-error variant (`ImportError` rather than `ModuleNotFoundError`).

## Task 4 — Settlement I/O

- **Files changed:** `tradehub/settlement.py`, `tradehub/core/kalshi_feed.py`, `tests/test_settlement.py`.
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v
  ```
  RED output tail:
  ```text
  tests/test_settlement.py::test_run_settlement_pass_no_open_predictions FAILED [100%]
  =========================== short test summary info ============================
  FAILED tests/test_settlement.py::test_fetch_open_predictions_returns_only_open
  FAILED tests/test_settlement.py::test_run_settlement_pass_settles_finalized_and_skips_others
  FAILED tests/test_settlement.py::test_run_settlement_pass_is_idempotent
  FAILED tests/test_settlement.py::test_run_settlement_pass_no_open_predictions
  ========================= 4 failed, 13 passed in 0.10s =========================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py -v
  ```
  Expected: 17 passed (13 pure + 4 I/O).
  GREEN output tail:
  ```text
  tests/test_settlement.py::test_run_settlement_pass_no_open_predictions PASSED [100%]

  ============================== 17 passed in 0.02s ==============================
  ```
- **Deviation:** None. The RED run produced the expected missing-I/O-function failures (4 failed, 13 passed); GREEN produced the expected 17 passed.

## Task 5 — Track record + promotion gate

_Pending implementation._

## Task 6 — Cron entrypoint

_Pending implementation._

## Verification

_Pending implementation._

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- The rollout tracker status will be updated in the final task commit, as required by the tracker's same-commit status rule.

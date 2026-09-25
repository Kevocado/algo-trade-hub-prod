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

- **Files changed:** `tradehub/track_record.py`, `tests/test_track_record.py`, and this Task 5 section of the evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-predictions-ledger-settlement-track-record/task-5-report.md`.
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record.py -v
  ```
  RED output tail:
  ```text
  E   ImportError: cannot import name 'track_record' from 'tradehub' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_track_record.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  ============================== 1 error in 0.11s ===============================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record.py -v
  ```
  GREEN output tail:
  ```text
  tests/test_track_record.py::test_gate_monthly_cadence_needs_only_50_contracts PASSED [100%]
  ============================== 14 passed in 0.02s ==============================
  ```
- **Deviation:** None. The RED run produced the brief-approved collection-error variant (`ImportError` rather than `ModuleNotFoundError`).


## Task 6 — Cron entrypoint

- **Files changed:** `tradehub/scripts/settle_predictions.py`, `tests/test_settle_predictions.py`, this evidence report, and `docs/superpowers/plans/2026-09-24-rollout-tracker.md`. A detailed handoff was written to `.superpowers/sdd/2026-09-24-predictions-ledger-settlement-track-record/task-6-report.md` (ignored by the repository and not staged).
- **RED command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settle_predictions.py -v
  ```
  RED output tail:
  ```text
  E   ImportError: cannot import name 'settle_predictions' from 'tradehub.scripts' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/scripts/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_settle_predictions.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  ============================== 1 error in 0.12s ===============================
  ```
- **GREEN command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settle_predictions.py -v
  ```
  GREEN output tail:
  ```text
  tests/test_settle_predictions.py::test_main_wires_pass_and_refresh PASSED [100%]

  ============================== 2 passed in 0.03s ===============================
  ```
- **Implementation review:** The entrypoint has module-level bindings for the real Supabase client, Kalshi market fetcher, settlement pass, and track-record refresh; runs exactly one settlement pass; refreshes each configured `(engine, cadence)` once; passes `simulated_pnl_after_fees=None`; emits one JSON summary; and exits through `sys.exit(main())` without an always-on loop.
- **Deviation:** The RED run produced the equivalent package-import collection error (`ImportError`) rather than the brief's illustrative `ModuleNotFoundError`, because `tradehub.scripts` already exists. The brief's unused `pytest` import was omitted from the final test file; the specified assertions and test behavior are unchanged.

## Verification

- **Full test suite command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/ -v
  ```
  Output tail:
  ```text
  tests/test_track_record.py::test_gate_monthly_cadence_needs_only_50_contracts PASSED [100%]

  ============================== 162 passed in 4.20s ==============================
  ```
- **Lint command:**
  ```sh
  cd /Users/sigey/Documents/Projects/algo-trade-hub-prod && .venv/bin/ruff check tradehub/predictions.py tradehub/settlement.py tradehub/track_record.py tradehub/scripts/settle_predictions.py tradehub/core/kalshi_feed.py tests/test_predictions.py tests/test_settlement.py tests/test_track_record.py tests/test_settle_predictions.py tests/test_repo_layout.py
  ```
  Pre-fix output tail:
  ```text
  UP017 [*] Use `datetime.UTC` alias
     --> tradehub/track_record.py:153:36
  ...
  Found 21 errors.
  [*] 4 fixable with the `--fix` option (3 hidden fixes can be enabled with the `--unsafe-fixes` option).
  ```
  The earlier claim that all 21 findings were pre-existing was incorrect: 15 were baseline findings (14 in `tradehub/core/kalshi_feed.py` and one in `tests/test_repo_layout.py`), and six were introduced by this branch (`tradehub/predictions.py`, `tradehub/settlement.py`, `tradehub/track_record.py`, `tests/test_predictions.py`, and `tests/test_track_record.py`). The final-review-fix section below records the now-clean aggregate gate.
- **Tracker update:** Step 2 in `docs/superpowers/plans/2026-09-24-rollout-tracker.md` now reads `🟡 implemented on branch, review pending`, as authorized by the handoff contract.

## Final review fix wave

- **Fix commit identity:** the single additional commit containing this section has exact subject `fix: address settlement review findings` and exact trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Its full object ID is recorded post-commit in the ignored final-fix report and returned in the handoff, because a Git commit cannot accurately embed its own object ID.
- **Files changed:** `tradehub/predictions.py`, `tradehub/settlement.py`, `tradehub/track_record.py`, `tradehub/core/kalshi_feed.py`, `tests/test_predictions.py`, `tests/test_settlement.py`, `tests/test_track_record.py`, `tests/test_repo_layout.py`, this evidence report, and only the authorized Step 2 count in `docs/superpowers/plans/2026-09-24-rollout-tracker.md`.
- **Correctness fixes:** market Brier aggregation now fails closed if any settled yes/no row lacks a score; open predictions are fetched in id-ordered inclusive pages until a short page; settlement updates remain id-based but additionally require `status=OPEN`, return a bool, and count a zero-row conditional update as skipped.
- **Ruff disposition:** all 21 pre-fix findings are clean: 15 baseline findings (14 legacy `kalshi_feed` findings plus one `test_repo_layout` finding) and six branch-introduced findings. Required broad fetch-error handling remains behavior-preserving and uses narrow targeted Ruff suppressions; `ValueError` for invalid `as_of` and the public `fetch_market` signature are unchanged.

### Regression TDD evidence

1. Partial market-Brier coverage:
   - RED command:
     ```sh
     SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_track_record.py::test_partial_market_brier_coverage_fails_closed_and_blocks_gate -v
     ```
   - RED tail:
     ```text
     >       assert summary["brier_market"] is None
     E       assert 0.16 is None
     =========================== short test summary info ============================
     FAILED tests/test_track_record.py::test_partial_market_brier_coverage_fails_closed_and_blocks_gate
     ============================== 1 failed in 0.07s ==============================
     ```
   - GREEN command: the same focused command.
   - GREEN tail:
     ```text
     tests/test_track_record.py::test_partial_market_brier_coverage_fails_closed_and_blocks_gate PASSED [100%]
     =============================== 1 passed in 0.01s ===============================
     ```

2. Open-prediction pagination and ordering:
   - RED command:
     ```sh
     SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py::test_fetch_open_predictions_pages_past_page_size_and_orders_by_id -v
     ```
   - RED tail:
     ```text
     >       monkeypatch.setattr(settlement, "PAGE_SIZE", 3)
     E       AttributeError: <module 'tradehub.settlement' ...> has no attribute 'PAGE_SIZE'
     =========================== short test summary info ============================
     FAILED tests/test_settlement.py::test_fetch_open_predictions_pages_past_page_size_and_orders_by_id
     ============================== 1 failed in 0.06s ==============================
     ```
   - GREEN command: the same focused command.
   - GREEN tail:
     ```text
     tests/test_settlement.py::test_fetch_open_predictions_pages_past_page_size_and_orders_by_id PASSED [100%]
     ============================== 1 passed in 0.01s ==============================
     ```

3. Conditional-update overlap:
   - RED command:
     ```sh
     SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_settlement.py::test_run_settlement_pass_counts_conditional_update_miss_as_skipped -v
     ```
   - RED tail:
     ```text
     >       assert summary == {"checked": 2, "settled": 1, "canceled": 0, "skipped": 1}
     E       AssertionError: assert {'checked': 2... 'skipped': 0} == {'checked': 2... 'skipped': 1}
     E         Differing items:
     E         {'skipped': 0} != {'skipped': 1}
     E         {'settled': 2} != {'settled': 1}
     =========================== short test summary info ============================
     FAILED tests/test_settlement.py::test_run_settlement_pass_counts_conditional_update_miss_as_skipped
     ============================== 1 failed in 0.06s ==============================
     ```
   - GREEN command: the same focused command.
   - GREEN tail:
     ```text
     tests/test_settlement.py::test_run_settlement_pass_counts_conditional_update_miss_as_skipped PASSED [100%]
     ============================== 1 passed in 0.01s ===============================
     ```

### Final verification

- Full-suite command:
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/ -v
  ```
- Full-suite output tail:
  ```text
  tests/test_track_record.py::test_gate_monthly_cadence_needs_only_50_contracts PASSED [100%]
  ============================= 165 passed in 4.49s ==============================
  ```
- Exact Ruff command:
  ```sh
  .venv/bin/ruff check tradehub/predictions.py tradehub/settlement.py tradehub/track_record.py tradehub/scripts/settle_predictions.py tradehub/core/kalshi_feed.py tests/test_predictions.py tests/test_settlement.py tests/test_track_record.py tests/test_settle_predictions.py tests/test_repo_layout.py
  ```
- Exact Ruff output:
  ```text
  All checks passed!
  ```
- Tracker count: Step 2 was updated from the stale `39/39` to the evidence-confirmed `42/42`; no other rollout-tracker content was changed.

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- The rollout tracker status was updated in this final task commit, as required by the tracker's same-commit status rule.
- No simulated-P&L implementation was added; the cron passes `None` so the promotion gate remains blocked on that criterion.

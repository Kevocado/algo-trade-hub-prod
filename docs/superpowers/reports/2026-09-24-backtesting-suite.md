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

- **Files changed:** `tradehub/backtest/__init__.py`, `tradehub/backtest/pit.py`, `tests/test_backtest_pit.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-2-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_pit.py:5: in <module>
      from tradehub.backtest.pit import Decision, LeakageError, Observation, check_no_lookahead
  E   ModuleNotFoundError: No module named 'tradehub.backtest'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_pit.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.20s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 0.01s
  ```
- **Behavior:** Added frozen `Observation` and `Decision` dataclasses with the exact specified fields, `LeakageError`, timezone-awareness validation, and a point-in-time guard that names every feature published after the decision while allowing equality.
- **Deviation:** None. The handoff report is intentionally not staged because the requested commit staging list is explicit.

## Task 3 — Kalshi public-history client

- **Files changed:** `tradehub/backtest/http.py`, `tradehub/backtest/kalshi_history.py`, `tests/test_backtest_kalshi_history.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-3-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_kalshi_history.py:5: in <module>
      from tradehub.backtest import kalshi_history as kh
  E   ImportError: cannot import name 'kalshi_history' from 'tradehub.backtest' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/backtest/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_backtest_kalshi_history.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.18s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  ..........                                                               [100%]
  10 passed in 0.02s
  ```
- **Behavior:** Added the injected-`get_json` Kalshi public-history client, the 30-second `requests` wrapper, public production base URL, candle/trade parsers, cursor pagination, historical/live paths, and oldest-first output ordering specified by the brief.
- **Deviation:** No functional implementation or test deviation. The RED failure was an `ImportError` rather than the brief's literal `ModuleNotFoundError` wording because the Task 2 package marker already existed; it was still the expected collection failure caused by the missing client module. Tests use only injected canned responses, so no live network calls were made.

## Task 4 — Conservative fill model

- **Files changed:** `tradehub/backtest/fills.py`, `tests/test_backtest_fills.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-4-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_fills.py:6: in <module>
      from tradehub.backtest.fills import MIN_TAKER_PRICE, maker_fill, quote_at, taker_fill
  E   ModuleNotFoundError: No module named 'tradehub.backtest.fills'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_fills.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 2.42s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q
  ```
  GREEN output tail:
  ```text
  ............                                                             [100%]
  12 passed in 0.42s
  ```
- **Behavior:** Added the frozen `Fill` record, decision-time `quote_at` lookup, conservative taker pricing at the visible ask/one-minus-bid, 10-cent taker floor, after-fee edge gating, and maker fills only from later opposite-side taker trades at or through the decision-time bid/one-minus-ask limit. Fee dollars are derived from the shared Kalshi fee helper.
- **Deviation:** None. The tests and implementation follow the brief verbatim; only the requested Task 4 report and handoff report were updated. The handoff report is intentionally not staged because the requested staging list is explicit.

## Task 5 — Metrics and runner

- **Files changed:** `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py`, `tests/test_backtest_runner.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-5-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_runner.py:7: in <module>
      from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
  E   ModuleNotFoundError: No module named 'tradehub.backtest.metrics'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_runner.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.62s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  ...........                                                              [100%]
  11 passed in 0.43s
  ```
- **Behavior:** Added shared fill P&L, peak-to-trough drawdown, market midpoint, and settled prediction-row metrics. The runner sorts decisions, runs the point-in-time leakage check before market lookup or fills, rejects decisions at/after close, skips non-binary markets, uses the specified taker/maker fill modes, computes turnover and fee-aware P&L/drawdown, and delegates summary, calibration, and promotion-gate evaluation to the live track-record code. Walk-forward fits use only strictly earlier events.
- **Deviation:** None. The RED failure was the expected missing-`metrics` collection error, and the exact eleven-test GREEN command passed. The handoff report is intentionally not staged because the requested staging list names only the two production files, focused test, and evidence report.

## Task 6 — ALFRED and Open-Meteo sources

- **Files changed:** `tradehub/backtest/sources/__init__.py`, `tradehub/backtest/sources/alfred.py`, `tradehub/backtest/sources/open_meteo.py`, `tests/test_backtest_sources.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-6-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_sources.py:5: in <module>
      from tradehub.backtest.sources.alfred import FRED_OBSERVATIONS_URL, AlfredSource
  E   ModuleNotFoundError: No module named 'tradehub.backtest.sources'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_sources.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.09s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 0.02s
  ```
- **Behavior:** Added the exact ALFRED and Open-Meteo Previous Runs URLs, injected `get_json` clients, and `Observation` construction. ALFRED queries the prior UTC day's vintage, skips `None`, empty, and `.` values, preserves descending vintage order, and publishes values at the vintage date plus one day. Open-Meteo validates `lead_days` in `1..7`, requests the previous-day hourly temperature variable in Fahrenheit, removes null values, returns the maximum, and converts target-date 23:00 local time minus the lead lag to UTC.
- **Tests:** Created the exact four focused tests from the brief before production code; all use canned payloads and perform no live network requests.
- **Deviation:** None. The handoff report is intentionally not staged because the requested commit staging list is explicit.

## Task 7 — Reproducible run storage

_Pending implementation._

## Verification

_Pending implementation._

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- The step-2 PR remains open remotely; this prerequisite branch uses the local fast-forward merge requested by the user and does not push.

# Evidence Report — Data Layer + Weather & Gas Engines

- Plan: `docs/superpowers/plans/2026-09-24-data-layer-weather-gas-engines.md`
- Branch: `plan/2026-09-24-data-layer-weather-gas-engines`
- Base: `6e0ffa2` (local `main` with step 2 and step 3 merged)
- Venv: `.venv/bin/python`
- Test environment: every pytest command uses process-only `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Baseline: pending fresh prerequisite-branch verification.

## Task 1 — `kalshi_edges` migration

- **Files changed:** `market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql`, `tests/test_repo_layout.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-1-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_kalshi_edges_urls_energy_migration -q
  ```
  RED output tail:
  ```text
  E       AssertionError: kalshi_edges urls/energy migration is missing
  E       assert False
  E        +  where False = is_file()
  E        +    where is_file = PosixPath('/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql').is_file
  tests/test_repo_layout.py:175: AssertionError
  =========================== short test summary info ============================
  FAILED tests/test_repo_layout.py::test_kalshi_edges_urls_energy_migration
  1 failed in 0.05s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
  ```
  GREEN output tail:
  ```text
  .................                                                        [100%]
  17 passed in 0.30s
  ```
- **Migration review:** Added idempotent `market_url` and `source_url` text columns, replaced the inline edge-type check with one allowing `WEATHER`, `MACRO`, `SPORTS`, `CRYPTO`, and `ENERGY`, and added the required idempotent unique `market_id` index.
- **Deviation:** None. The migration was intentionally not applied; production deployment remains a manual step. The detailed handoff report is not included in the requested staging list and remains repository-ignored.

## Task 2 — Market geometry

- **Files changed:** `tradehub/markets.py`, `tests/test_markets.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-2-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_markets.py -q
  ```
  RED output tail:
  ```text
  tests/test_markets.py:6: in <module>
      from tradehub.markets import event_date, market_url, parse_market, prob_in_interval, yes_interval
  E   ModuleNotFoundError: No module named 'tradehub.markets'
  =========================== short test summary info ============================
  ERROR tests/test_markets.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.08s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_markets.py -q
  ```
  GREEN output tail:
  ```text
  .......                                                                  [100%]
  7 passed in 0.01s
  ```
- **Implementation:** Added the frozen `KalshiMarket` model and pure parser, event-date parsing, half-resolution strike intervals with infinite bounds, normal-CDF interval probability with positive-sigma validation, and the Kalshi market URL helper. The seven specified tests cover parsing, dates, weather/gas geometry, unknown strikes, probability, and URLs.
- **Deviation:** None. The tests were written before production code, the exact RED and GREEN commands were run with the requested environment and interpreter, and no dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed.

## Task 3 — Kalshi live markets and settled values

- **Files changed:** `tradehub/edges.py`, `tradehub/data/__init__.py`, `tradehub/data/kalshi_live.py`, `tests/test_kalshi_live.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-3-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_live.py -q
  ```
  RED output tail:
  ```text
  tests/test_kalshi_live.py:6: in <module>
      from tradehub.data.kalshi_live import KalshiLive, quote_from_market_raw, settlement_observations
  E   ModuleNotFoundError: No module named 'tradehub.data'
  =========================== short test summary info ============================
  ERROR tests/test_kalshi_live.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.09s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_live.py -q
  ```
  GREEN output tail:
  ```text
  .....                                                                    [100%]
  5 passed in 0.02s
  ```
- **Implementation:** Added the frozen `Quote` and `LiveMarket` dataclasses, quote normalization with empty-side suppression, one earliest-settlement observation per event sorted by event date, paginated open-market quote pairing, and merged historical/live settled values. The exactly five specified tests use a local fake getter; no live network was used.
- **Deviation:** None. The exact tests, RED command, implementation, and GREEN command from the brief were followed. The case-insensitive working directory's broad `Data/` ignore rule matched `tradehub/data/`, so those two required package files were explicitly force-staged without editing `.gitignore`. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed.

## Task 4 — Weather data and station-note fix

- **Files changed:** `tradehub/data/weather.py`, `tests/test_weather_data.py`, `research/weather_notes/Markets/Kalshi_Weather_Market_Mapping.md`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-4-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_data.py -q
  ```
  RED output tail:
  ```text
  tests/test_weather_data.py:5: in <module>
      from tradehub.data.weather import (
  E   ModuleNotFoundError: No module named 'tradehub.data.weather'
  =========================== short test summary info ============================
  ERROR tests/test_weather_data.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.09s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_data.py -q
  ```
  GREEN output tail:
  ```text
  ...                                                                      [100%]
  3 passed in 0.01s
  ```
- **Implementation:** Added frozen `City` and the three settlement-station city mappings, the exact `FORECAST_URL` and `WEATHER_MODELS`, live multi-model hourly maximums with `now` as each observation's publication stamp, and historical previous-run observations through `forecast_daily_high`, skipping models that return no values. Updated the mapping note and front matter only as specified. No live network was used; the exact three tests use a local recorder.
- **Deviation:** None. The exact three tests, RED command, implementation, and GREEN command from the brief were followed. The broad case-insensitive `Data/` ignore rule matched the required `tradehub/data/weather.py`; it is explicitly force-staged without editing `.gitignore`. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed.

## Task 5 — Weather engine

- **Files changed:** `tradehub/engines/weather.py`, `tests/test_weather_engine.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-5-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py -q
  ```
  RED output tail:
  ```text
  tests/test_weather_engine.py:5: in <module>
      from tradehub.engines.weather import DEFAULT_ERROR, MIN_SIGMA, ErrorModel, fit_error_model, weather_prob
  E   ModuleNotFoundError: No module named 'tradehub.engines.weather'
  =========================== short test summary info ============================
  ERROR tests/test_weather_engine.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.09s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py -q
  ```
  GREEN output tail:
  ```text
  ......                                                                   [100%]
  6 passed in 0.01s
  ```
- **Implementation:** Added the pure weather engine with `ErrorModel`, `DEFAULT_ERROR`, `MIN_SIGMA`, `TEMP_RESOLUTION`, and `WEATHER_ENGINE_VERSION` constants. `fit_error_model` returns the default below the minimum pair count, otherwise fits mean bias and sample standard deviation with the sigma floor. `weather_prob` shifts the blended forecast mean by bias, adds forecast-model pvariance to error variance, maps the result through the market YES interval, and rejects empty forecast highs with `ValueError`. The exact six tests cover default fallback, bias/sample-sigma fitting, sigma flooring, normal probability equivalence, bias/disagreement widening behavior, and empty-highs validation.
- **Deviation:** None. The exact six tests, RED command, implementation, and GREEN command from the brief were followed. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed. The handoff report is not included in the requested staging list and remains repository-ignored.

## Task 6 — RBOB input and gas engine

- **Files changed:** `tradehub/data/rbob.py`, `tradehub/engines/gas.py`, `tests/test_gas_engine.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-6-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py -q
  ```
  RED output tail:
  ```text
  tests/test_gas_engine.py:8: in <module>
      from tradehub.data.rbob import rbob_closes
  E   ModuleNotFoundError: No module named 'tradehub.data.rbob'
  =========================== short test summary info ============================
  ERROR tests/test_gas_engine.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.59s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py -q
  ```
  GREEN output tail:
  ```text
  .....                                                                    [100%]
  5 passed in 0.41s
  ```
- **Implementation:** Added `RBOB_SYMBOL = "RB=F"` and injected `rbob_closes(history_fn)` with 18:00 America/New_York settlement timestamps converted to UTC, dated observation names, and publication-time sorting. Added the pure gas engine constants and frozen `GasModel`, known-close `rbob_change`, consecutive-calendar-day training pairs, OLS fitting with `n-2` residual sigma and the `MIN_GAS_SIGMA` floor, and horizon-scaled normal `gas_prob`. The exact five specified tests cover all requested behavior; no yfinance request was made.
- **Deviation:** None. The case-insensitive working directory's broad `Data/` ignore rule matched the required `tradehub/data/rbob.py`; it is explicitly force-staged without editing `.gitignore`. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed. The handoff report is not included in the requested staging list and remains repository-ignored.

## Task 7 — Edge layer and shared side selection

- **Files changed:** `tradehub/edges.py`, `tradehub/backtest/fills.py`, `tests/test_edges.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-7-report.md`; the review fix is documented in `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-7-fix-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py -q
  ```
  RED output tail:
  ```text
  tests/test_edges.py:4: in <module>
      from tradehub.edges import MIN_TAKER_PRICE, Quote, best_side, evaluate_edge
  E   ImportError: cannot import name 'MIN_TAKER_PRICE' from 'tradehub.edges' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/edges.py)
  =========================== short test summary info ============================
  ERROR tests/test_edges.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.59s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py tests/test_backtest_fills.py tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  .....................................                                    [100%]
  37 passed in 0.52s
  ```
- **Review-fix RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py -q
  ```
  Review-fix RED output tail:
  ```text
  F.....                                                                   [100%]
  tests/test_edges.py:13: in test_best_side_public_signature_has_no_contract_count
      assert list(parameters) == ["our_prob", "yes_price", "no_price", "maker"]
  E   AssertionError: assert ['our_prob', ..., 'contracts'] == ['our_prob', ...ice', 'maker']
  =========================== short test summary info ============================
  FAILED tests/test_edges.py::test_best_side_public_signature_has_no_contract_count
  1 failed, 5 passed in 0.48s
  ```
- **Review-fix GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py -q
  ```
  Review-fix GREEN output tail:
  ```text
  ......                                                                   [100%]
  6 passed in 0.34s
  ```
- **Unchanged fill/runner command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_edges.py tests/test_backtest_fills.py tests/test_backtest_runner.py -q
  ```
  Unchanged fill/runner output tail:
  ```text
  ......................................                                   [100%]
  38 passed in 0.24s
  ```
- **Implementation:** Replaced the Task 3 `Quote`-only module with the complete frozen quote/edge model, `MIN_TAKER_PRICE = 0.10`, after-fee `best_side`, and maker-first `evaluate_edge`. `evaluate_edge` checks maker bid/NO `1 - ask` first, falls back to taker ask/NO `1 - bid`, enforces positive/min-edge rules, returns the midpoint as `market_prob`, and suppresses missing quotes. The fill model imports and re-exports `MIN_TAKER_PRICE` and `best_side`, uses that exact public selector for side/price, and recomputes the selected side's after-fee edge with the requested contract count so the hardened fill thresholds remain intact.
- **Deviation:** The public `best_side` signature is now exactly `(our_prob, yes_price, no_price, *, maker)`. Fill threshold behavior is preserved by selecting side/price through that public function and recomputing the selected side's after-fee edge with `net_edge_pct(..., contracts=requested_contracts, maker=...)`. The checkout has 38 tests in the requested command after adding the interface regression (6 edge, 17 fill, 15 runner), rather than the brief's stale `28 passed` count. The repository graph rebuild command was attempted but could not run because the `graphify` module is not installed (`ModuleNotFoundError: No module named 'graphify'`); no dependency changes were made. The tracked evidence report is included in the task commit as authorized scope required by the handoff contract; the separate handoff/fix report remains repository-ignored. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No amend/reset/clean/push/subagent operation was performed.

## Task 8 — Per-engine config

- **Files changed:** `tradehub/config/engines.yaml`, `tradehub/engine_config.py`, `tests/test_engine_config.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-8-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_engine_config.py -q
  ```
  RED output tail:
  ```text
  E   ModuleNotFoundError: No module named 'tradehub.engine_config'
  =========================== short test summary info ============================
  ERROR tests/test_engine_config.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.10s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_engine_config.py -q
  ```
  GREEN output tail:
  ```text
  ...                                                                      [100%]
  3 passed in 0.06s
  ```
- **Implementation:** Added the exact frozen `EngineConfig` dataclass and `CONFIG_PATH`, plus YAML-backed `load_engine_config`. Unknown engines raise `KeyError`; `min_edge_pct` and `prefer_maker` retain the specified defaults/conversions; all remaining keys are converted to floats in `params`. The exact three specified tests were written before production code and cover repository defaults, unknown engines, and extra parameters.
- **Deviation:** None. The exact three tests, RED command, implementation, and GREEN command from the brief were followed. No dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed. The handoff report is not included in the requested staging list and remains repository-ignored.

## Task 9 — One-shot scan and deep links

- **Files changed:** `tradehub/scripts/scan.py`, `tradehub/core/supabase_client.py`, `tests/test_scan.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-9-report.md`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q
  ```
  RED output tail:
  ```text
  tests/test_scan.py:10: in <module>
      from tradehub.scripts import scan
  E   ImportError: cannot import name 'scan' from 'tradehub.scripts' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/scripts/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_scan.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.65s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 1.41s
  ```
- **Implementation:** Added the one-shot suggest-only `tradehub/scripts/scan.py` with exact edge-row keys and deep links, midpoint market probabilities, LST weather-date filtering, forecast-based weather prediction rows, published-at-filtered AAA gas inputs and training pairs, positive-horizon gas predictions, `WEATHER`/`ENERGY` edge typing, and the one-shot JSON summary main entry point. The scan writes predictions and upserts edges only; it never places orders. `upsert_opportunities` now accepts `ENERGY` and writes `market_url` and `source_url`.
- **Deviation:** None. The exact four tests, RED command, implementation, and GREEN command from the brief were followed. No live services were contacted, no orders were placed, and no dependencies, migrations, specs, other plans, environment files, or unrelated files were changed. No push/reset/clean/subagent operation was performed. The handoff report is not included in the requested staging list and remains repository-ignored.


## Task 10 — Point-in-time backtests

- **Files changed:** `tradehub/scripts/backtest_engines.py`, `tests/test_backtest_engines.py`, and this evidence report. A detailed handoff was written to `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-10-report.md`; that handoff report is not included in the requested staging list.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_engines.py:9: in <module>
      from tradehub.scripts.backtest_engines import (
  E   ModuleNotFoundError: No module named 'tradehub.scripts.backtest_engines'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_engines.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.75s
  ```
  The exact five tests were created before production code; collection failed for the expected missing module.
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py -q
  ```
  GREEN output tail:
  ```text
  .....                                                                    [100%]
  5 passed in 0.62s
  ```
- **Supplemental verification:**
  ```text
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  272 passed in 7.76s

  .venv/bin/ruff check --select F401,F811,F821 tradehub tests
  All checks passed!

  grep -rn "shared.config" tradehub/markets.py tradehub/edges.py tradehub/data tradehub/engines/weather.py tradehub/engines/gas.py tradehub/engine_config.py tradehub/scripts/scan.py tradehub/scripts/backtest_engines.py
  (no matches)
  ```
- **Implementation:** Added the exact `WEATHER_DECISION_TIME = time(23, 30)` and `GAS_DECISION_LEAD = timedelta(hours=2)` constants; LST-zone weather decision timestamps; walk-forward weather error fitting from actuals and forecasts knowable at each decision; decision-time AAA and RBOB filtering for gas decisions; point-in-time `Decision` features; public history construction; and the `--engine`, date range, `--mode`, `--series`, `--train-days`, and `--record` CLI. The CLI selects the default weather or gas series, pulls Kalshi history, runs `run_backtest`, preserves the additive `log_loss` field through `build_backtest_run_row`, emits the result JSON, and records through `record_backtest_run` only when requested.
- **Deviation:** None in the initial Task 10 round. The exact five tests and exact RED/GREEN commands from the brief were followed. The final review-fix evidence below records the explicitly requested public-data attempts; no Supabase writes or orders were made.

## Task 10 final review fix — point-in-time inputs and tier coverage

- **Files changed:** `tradehub/scripts/backtest_engines.py`, `tradehub/backtest/kalshi_history.py`, `tests/test_backtest_engines.py`, `tests/test_backtest_kalshi_history.py`, this evidence report, and the Step 4 status in `docs/superpowers/plans/2026-09-24-rollout-tracker.md`.
- **Focused RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py tests/test_backtest_kalshi_history.py -q
  ```
  RED output tail:
  ```text
  FAILED tests/test_backtest_engines.py::test_weather_decisions_filter_current_forecasts_published_after_decision
  FAILED tests/test_backtest_engines.py::test_weather_training_ignores_forecasts_published_after_decision
  FAILED tests/test_backtest_engines.py::test_histories_use_merged_candles_and_trades_with_series_context
  FAILED tests/test_backtest_engines.py::test_backtest_cli_uses_merged_markets_and_reproducible_metadata
  FAILED tests/test_backtest_kalshi_history.py::test_merged_settled_markets_combines_tiers_and_deduplicates_ticker
  5 failed, 20 passed in 0.54s
  ```
- **Focused GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  25 passed in 0.47s
  ```
- **Implementation:** Current and training weather forecasts are filtered by publication time before use; `merged_settled_markets` combines historical/live settled markets by ticker; `_histories` uses `merged_candles` with series context and bounded `merged_trades`; CLI config includes `train_days`; and date bounds are explicit UTC-aware timestamps. The additive `log_loss` field remains preserved.
- **Full verification:**
  ```text
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  277 passed in 4.61s

  .venv/bin/ruff check --select F401,F811,F821 tradehub tests
  All checks passed!

  grep -rn "shared.config" tradehub/markets.py tradehub/edges.py tradehub/data tradehub/engines/weather.py tradehub/engines/gas.py tradehub/engine_config.py tradehub/scripts/scan.py tradehub/scripts/backtest_engines.py
  (no matches; grep exit status 1 is expected)
  ```
- **Public-data dry run:** Succeeded without Supabase or `--record`.
  ```text
  weather 36 preds 12 edges
  gas 17 preds 3 edges
  KXHIGHNY-26SEP25-T67 yes 5.0 pp maker
  KXHIGHNY-26SEP25-B73.5 yes 11.5 pp maker
  KXHIGHNY-26SEP25-B71.5 no 24.4 pp maker
  KXHIGHNY-26SEP25-B69.5 no 10.1 pp maker
  KXHIGHCHI-26SEP25-T64 yes 31.5 pp maker
  ```
- **Weather backtest command:** `.venv/bin/python -m tradehub.scripts.backtest_engines --engine weather --series KXHIGHNY --start 2026-06-01 --end 2026-07-24` produced no stdout/stderr before the 300000 ms execution timeout; no JSON was fabricated.
- **Gas backtest command:** `.venv/bin/python -m tradehub.scripts.backtest_engines --engine gas --start 2026-06-01 --end 2026-07-24` produced no stdout/stderr before the 300000 ms execution timeout; no JSON was fabricated.
- **Tracker:** Step 4 only was changed to `🟡 implemented on branch, review pending`.
- **Deviation:** The two exact public backtest commands exceeded the execution timeout; actual timeout results are recorded. No Supabase access, orders, migrations, dependency changes, spec/other-plan edits, `.env` edits, push/reset/clean, or subagent dispatches occurred.

## Task 10 bounded-performance follow-up

- **Files changed:** `tradehub/scripts/backtest_engines.py`, `tests/test_backtest_engines.py`, and this evidence report. The ignored fix report was extended at `.superpowers/sdd/2026-09-24-data-layer-weather-gas-engines/task-10-fix-report.md`.
- **Focused RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py::test_fetch_weather_forecasts_is_bounded_concurrent_and_date_stable -q
  ```
  RED output tail:
  ```text
  FAILED tests/test_backtest_engines.py::test_fetch_weather_forecasts_is_bounded_concurrent_and_date_stable
  AttributeError: module 'tradehub.scripts.backtest_engines' has no attribute 'fetch_weather_forecasts'
  1 failed in 1.14s
  ```
- **Focused GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py::test_fetch_weather_forecasts_is_bounded_concurrent_and_date_stable -q
  ```
  GREEN output tail:
  ```text
  1 passed in 0.43s
  ```
  The complete `tests/test_backtest_engines.py` run passed: `10 passed in 0.50s`.
- **Implementation:** Added finite `ThreadPoolExecutor` forecast fetching with `WEATHER_FETCH_MAX_WORKERS = 8`, sorted/deduplicated date keys, deterministic ordered results, bounded worker count, propagated errors, and no skipped training dates. The CLI retains `--train-days` and routes all target/training dates through the helper.
- **Full verification:**
  ```text
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  278 passed in 5.20s

  .venv/bin/ruff check --select F401,F811,F821 tradehub tests
  All checks passed!

  grep -rn "shared.config" tradehub/markets.py tradehub/edges.py tradehub/data tradehub/engines/weather.py tradehub/engines/gas.py tradehub/engine_config.py tradehub/scripts/scan.py tradehub/scripts/backtest_engines.py
  (no matches; grep exit status 1 is expected)
  ```
- **Live dry run output (no `--record`, no Supabase):**
  ```text
  weather 36 preds 12 edges
  gas 0 preds 0 edges
  KXHIGHNY-26SEP25-T67 yes 12.0 pp maker
  KXHIGHNY-26SEP25-B73.5 yes 6.9 pp maker
  KXHIGHNY-26SEP25-B71.5 no 29.6 pp maker
  KXHIGHNY-26SEP25-B69.5 no 10.1 pp maker
  KXHIGHNY-26SEP25-B67.5 yes 5.1 pp maker
  ```
- **Weather backtest output:** The exact command completed within 300 seconds:
  ```text
  {
    "engine": "weather",
    "mode": "taker",
    "n_decisions": 324,
    "n_fills": 152,
    "pnl_after_fees": -1.5319,
    "max_drawdown": 4.3077,
    "brier_ours": 0.12569,
    "brier_market": 0.10255,
    "gate_status": "SHADOW",
    "gate_reasons": [
      "model Brier 0.12569 is not below market Brier 0.10255",
      "simulated P&L after fees/spread is not positive",
      "calibration miss 15.3% in bucket 50-60 (limit 10pp)"
    ]
  }
  ```
- **Gas backtest:** The exact command was attempted at 300 seconds and retried at 600 seconds. Both attempts produced no stdout/stderr before timeout; no gas JSON was fabricated.
- **Deviation:** The gas backtest remains an actual timeout. No Supabase access, orders, migrations, dependency changes, spec/other-plan edits, `.env` edits, push/reset/clean, or subagent dispatches occurred.

## Verification

Final Task 10 gas-history verification (no `--record` and no Supabase access).

### Exact live dry-run command

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -c "
from datetime import datetime, timezone
from tradehub.data.kalshi_live import KalshiLive
from tradehub.engine_config import load_engine_config
from tradehub.scripts.scan import scan_weather, scan_gas
now = datetime.now(timezone.utc); live = KalshiLive()
wp, we = scan_weather(live, now, load_engine_config('weather'))
gp, ge = scan_gas(live, now, load_engine_config('gas'))
print('weather', len(wp), 'preds', len(we), 'edges'); print('gas', len(gp), 'preds', len(ge), 'edges')
for e in (we + ge)[:5]: print(e['market_ticker'], e['side'], round(e['edge']*100,1), 'pp', 'maker' if e['maker'] else 'taker')"
```

Output:

```text
weather 36 preds 13 edges
gas 0 preds 0 edges
KXHIGHNY-26SEP25-T67 yes 12.0 pp maker
KXHIGHNY-26SEP25-B73.5 yes 6.9 pp maker
KXHIGHNY-26SEP25-B71.5 no 30.6 pp maker
KXHIGHNY-26SEP25-B69.5 no 10.1 pp maker
KXHIGHNY-26SEP25-B67.5 yes 5.1 pp maker
```

### Exact focused RED command and output tail

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py::test_histories_skip_trade_fetch_for_taker_mode tests/test_backtest_kalshi_history.py::test_cutoff_timestamps_are_cached_across_repeated_merged_candle_calls -q
```

```text
FF                                                                       [100%]
FAILED tests/test_backtest_engines.py::test_histories_skip_trade_fetch_for_taker_mode
TypeError: _histories() got an unexpected keyword argument 'mode'
FAILED tests/test_backtest_kalshi_history.py::test_cutoff_timestamps_are_cached_across_repeated_merged_candle_calls
AssertionError: assert 2 == 1
2 failed in 0.82s
```

### Exact focused GREEN command and output tail

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_engines.py::test_histories_skip_trade_fetch_for_taker_mode tests/test_backtest_kalshi_history.py::test_cutoff_timestamps_are_cached_across_repeated_merged_candle_calls -q
```

```text
..                                                                       [100%]
2 passed in 0.51s
```

The combined backtest-engine/history tests passed: `28 passed in 0.62s`.

### Exact full verification commands and output tails

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
```

```text
280 passed in 4.72s
```

```sh
.venv/bin/ruff check --select F401,F811,F821 tradehub tests
```

```text
All checks passed!
```

```sh
grep -rn "shared.config" tradehub/markets.py tradehub/edges.py tradehub/data tradehub/engines/weather.py tradehub/engines/gas.py tradehub/engine_config.py tradehub/scripts/scan.py tradehub/scripts/backtest_engines.py
```

```text
(no matches; grep exit status 1 is expected for no matches)
```

### Exact public backtest commands and outcomes

Weather command:

```sh
.venv/bin/python -m tradehub.scripts.backtest_engines --engine weather --series KXHIGHNY --start 2026-06-01 --end 2026-07-24
```

Final rerun output before JSON:

```text
requests.exceptions.HTTPError: 429 Client Error: Too Many Requests for url: https://previous-runs-api.open-meteo.com/v1/forecast?latitude=40.7789&longitude=-73.9692&hourly=temperature_2m_previous_day1&models=ecmwf_ifs025&temperature_unit=fahrenheit&timezone=Etc%2FGMT%2B5&start_date=2026-03-05&end_date=2026-03-05
```

Gas command:

```sh
.venv/bin/python -m tradehub.scripts.backtest_engines --engine gas --start 2026-06-01 --end 2026-07-24
```

Taker mode does not fetch trades. The command reached the public Kalshi candle endpoint and received HTTP 429 before JSON output; no gas JSON was fabricated:

```text
requests.exceptions.HTTPError: 429 Client Error: Too Many Requests for url: https://api.elections.kalshi.com/trade-api/v2/historical/markets/KXAAAGASD-26JUL23-4.175/candlesticks?start_ts=1784725800&end_ts=1784779140&period_interval=60
```

The exact public endpoint paths and 429 evidence above are the final rerun results. The prior weather run before this follow-up completed with 324 decisions and 152 fills; the gas history fix is locally verified, while the final gas JSON is blocked by the public endpoint rate limit in this run.

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- Step 2 and step 3 are locally merged prerequisites; their PRs are open remotely and are not required to be remotely merged for this local implementation order.
- The user authorized opening a PR for this plan after final verification.

## Follow-up fixes — 2026-09-25

### Merge baseline

- `git merge plan/2026-09-24-backtesting-suite` completed with `Already up to date.` The prerequisite branch is already an ancestor of this target branch, so no rebase or synthetic merge commit was created.
- Post-merge full-suite baseline:
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  280 passed in 5.50s
  ```

### Fix 1 — strictly future weather climate days

- **Files changed:** `tradehub/scripts/scan.py`, `tests/test_scan.py`, and this evidence report.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_scan_weather_predicts_only_strictly_future_lst_climate_days -q
  ```
  RED output tail:
  ```text
  E       assert [datetime.dat...(2026, 9, 25)] == [datetime.date(2026, 9, 25)]
  E         Left contains one more item: datetime.date(2026, 9, 25)
  1 failed in 0.65s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q
  ```
  GREEN output tail:
  ```text
  4 passed in 0.32s
  ```
- **Implementation:** Weather scan eligibility is now `target > today_LST`; markets for today and past climate days are neither forecast nor predicted.

### Fix 2 — one point-in-time weather error model and bounded probabilities

- **Files changed:** `tradehub/engines/weather.py`, `tradehub/markets.py`, `tradehub/scripts/scan.py`, `tradehub/scripts/backtest_engines.py`, `tests/test_scan.py`, `tests/test_weather_engine.py`, `tests/test_markets.py`, and this evidence report.
- **RED commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_scan_and_backtest_share_walk_forward_weather_error_model -q
  ```
  ```text
  E       TypeError: scan_weather() got an unexpected keyword argument 'historical_forecast_fn'
  1 failed in 0.56s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py::test_weather_prob_bias_shifts_without_adding_model_spread_twice tests/test_weather_engine.py::test_weather_probability_is_clamped_away_from_zero_and_one -q
  ```
  ```text
  FF
  2 failed, 2 passed in 0.06s
  ```
- **GREEN commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_scan_and_backtest_share_walk_forward_weather_error_model -q
  ```
  ```text
  1 passed in 0.63s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_weather_engine.py tests/test_backtest_engines.py -q
  ```
  ```text
  18 passed in 0.62s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  282 passed in 4.09s
  ```
- **Implementation:** `walk_forward_error_model()` is now shared by scan and backtest. It accepts only settled actuals and lead-1 forecast observations published by the decision time, and uses YAML `error_bias`/`error_sigma` only when fewer than 20 usable pairs exist. `weather_prob()` no longer adds model spread on top of fitted sigma, and `prob_in_interval()` clamps all engine probabilities to `[1e-4, 1-1e-4]`. The parity test verifies the scan row (four-decimal ledger serialization) matches the backtest decision probability.

### Fix 3 — shadow edge gate metadata and stale-row cleanup

- **Files changed:** `market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql`, `tradehub/core/supabase_client.py`, `tradehub/scripts/scan.py`, `tests/test_scan.py`, `tests/test_repo_layout.py`, and this evidence report.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_edge_row_shape tests/test_scan.py::test_latest_gate_statuses_default_non_promoted_to_shadow tests/test_scan.py::test_remove_stale_edges_only_targets_requested_edge_types -q
  ```
  RED output tail:
  ```text
  E           KeyError: 'gate_status'
  E           AttributeError: module 'tradehub.scripts.scan' has no attribute 'latest_gate_statuses'
  E           AttributeError: module 'tradehub.scripts.scan' has no attribute 'remove_stale_edges'
  3 failed, 1 passed in 0.46s
  ```
- **GREEN commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py tests/test_repo_layout.py -q
  ```
  ```text
  24 passed in 0.98s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  284 passed in 4.07s
  ```
- **Implementation:** The unapplied migration now adds `gate_status`, `updated_at`, and `expires_at`; scan edge rows carry the market close as expiry, and the writer persists gate/timestamp fields. Scan reads the newest `backtest_runs` row per engine, defaults every non-`PROMOTED` result to `SHADOW`, still writes the edge, and removes only stale `WEATHER`/`ENERGY` rows after a successful scan.

### Fix 4 — retrying backtest HTTP and merged live settlements

- **Files changed:** `tradehub/backtest/http.py`, `tradehub/data/kalshi_live.py`, `tests/test_backtest_http.py`, `tests/test_kalshi_live.py`, and this evidence report.
- **RED commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_http.py -q
  ```
  ```text
  FFF.F
  4 failed, 1 passed in 0.05s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_live.py::test_settled_values_reuses_merged_settled_markets -q
  ```
  ```text
  E       Failed: network should not be called
  1 failed in 0.50s
  ```
- **GREEN commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_http.py tests/test_kalshi_live.py tests/test_backtest_kalshi_history.py -q
  ```
  ```text
  28 passed in 0.35s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  290 passed in 3.86s
  ```
- **Implementation:** The shared JSON getter retries only 429/5xx responses for five bounded attempts, honors numeric and HTTP-date `Retry-After` values, and falls back to capped exponential backoff. All backtest/live JSON sources already route through this getter. `KalshiLive.settled_values()` now delegates directly to `merged_settled_markets()`.

### Fix 5 — isolated scan failures, counts, and strict write errors

- **Files changed:** `tradehub/scripts/scan.py`, `tradehub/core/supabase_client.py`, `tests/test_scan.py`, and this evidence report.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_scan_weather_isolates_city_failures_when_requested tests/test_scan.py::test_scan_main_isolates_engine_failure_and_returns_nonzero tests/test_scan.py::test_upsert_opportunities_propagates_execute_failure -q
  ```
  RED output tail:
  ```text
  FF.
  E       TypeError: scan_weather() got an unexpected keyword argument 'failures'
  E       TypeError: main() got an unexpected keyword argument 'now'
  2 failed, 1 passed in 0.41s
  ```
- **GREEN commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py -q
  ```
  ```text
  10 passed in 0.46s
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  293 passed in 3.86s
  ```
- **Implementation:** `scan_weather()` records and continues past a city failure when invoked by the orchestrator; `main()` runs weather and gas independently, logs per-engine/per-city counts, writes successful engine batches separately, preserves a parseable JSON summary, and returns `1` for any scan or write failure. `upsert_opportunities()` no longer catches or prints persistence errors.

### Fix 6 — RBOB roll-safe windows and bounded backtest history

- **Files changed:** `tradehub/data/rbob.py`, `tradehub/engines/gas.py`, `tradehub/scripts/backtest_engines.py`, `tests/test_gas_engine.py`, `tests/test_backtest_engines.py`, and this evidence report.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py -q
  ```
  RED output tail:
  ```text
  E       ImportError: cannot import name 'rbob_change_window' from 'tradehub.engines.gas'
  1 error in 0.56s
  ```
- **GREEN commands:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_gas_engine.py tests/test_backtest_engines.py::test_gas_decision_omits_rbob_features_for_roll_crossing_window tests/test_backtest_engines.py::test_gas_cli_sizes_rbob_from_backtest_start -q
  ```
  ```text
  10 passed in 0.56s
  ```
  ```sh
  .venv/bin/ruff check --select F401,F811,F821 tradehub tests
  ```
  ```text
  All checks passed!
  ```
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  298 passed in 5.06s
  ```
- **Implementation:** RBOB observations carry the expected front contract code and a roll boundary; `rbob_change_window()` rejects any window containing mixed or unknown contracts, and gas decisions attach only the exact same-contract observations used by the feature. The yfinance history call now uses explicit `start`/`end` bounds derived from `--start --train-days` through `--end`; live scans retain the two-year default.

## Final verification — 2026-09-25

- The prerequisite merge was already satisfied (`git merge plan/2026-09-24-backtesting-suite` returned `Already up to date.`); no rebase was used. The six requested implementation commits are `89740f3`, `7801ef8`, `ccd9c4c`, `16d4ae0`, `8a2be47`, and `fa5b179`.
- Final full suite:
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  ```text
  299 passed in 5.05s
  ```
- Final lint:
  ```sh
  .venv/bin/ruff check --select F401,F811,F821 tradehub tests
  ```
  ```text
  All checks passed!
  ```
- The required graph rebuild was attempted with `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"`; this checkout does not have the `graphify` module installed, so it returned `ModuleNotFoundError` and no dependency was changed.
- No prediction dedupe was added and `tradehub/track_record.py` was not changed.

### Gas dry run — 12:00 ET point-in-time public-market replay

The live `KXAAAGASD` endpoint returned zero open markets immediately after the prior close, so a normal quote-backed live call had no rows. To obtain a non-zero, no-write verification without inventing a quote, the production `scan_gas` path was run at **12:00 ET** against the latest public settled AAA/RBOB observations and a real gas-market shape with `Quote(None, None)`. The scan timestamp and input cutoff were explicit; no Supabase writes or orders were made.

```json
{
  "mode": "point_in_time_public_market_replay",
  "scan_at": "2026-09-24T16:00:00+00:00",
  "scan_at_et": "2026-09-24T12:00:00-04:00",
  "gas": {
    "predictions": 1,
    "edges": 0
  },
  "tickers": [
    "KXAAAGASD-26SEP25-4.5150"
  ]
}
```

### Completed backtests

Weather command:

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_engines --engine weather --series KXHIGHNY --start 2026-06-01 --end 2026-07-24
```

```json
{
  "engine": "weather",
  "mode": "taker",
  "n_decisions": 324,
  "n_fills": 151,
  "pnl_after_fees": -4.4403,
  "max_drawdown": 6.4677,
  "brier_ours": 0.12725,
  "brier_market": 0.10255,
  "gate_status": "SHADOW",
  "gate_reasons": [
    "model Brier 0.12725 is not below market Brier 0.10255",
    "simulated P&L after fees/spread is not positive",
    "calibration miss 19.0% in bucket 50-60 (limit 10pp)"
  ]
}
```

Gas command:

```sh
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_engines --engine gas --start 2026-06-01 --end 2026-07-24
```

```json
{
  "engine": "gas",
  "mode": "taker",
  "n_decisions": 937,
  "n_fills": 176,
  "pnl_after_fees": -1.4506,
  "max_drawdown": 5.4479,
  "brier_ours": 0.12648,
  "brier_market": null,
  "gate_status": "SHADOW",
  "gate_reasons": [
    "no market Brier recorded; gate cannot be evaluated",
    "simulated P&L after fees/spread is not positive"
  ]
}
```

## Review remediation — 2026-09-25

### Weather parity and backtest configuration

- **Files changed:** `tradehub/scripts/scan.py`, `tradehub/scripts/backtest_engines.py`, `tradehub/engines/weather.py`, `tests/test_scan.py`, `tests/test_backtest_engines.py`, and this report.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py::test_scan_and_backtest_use_all_available_calibration_pairs tests/test_scan.py::test_scan_and_backtest_share_yaml_fallback_below_minimum_samples tests/test_backtest_engines.py::test_backtest_cli_uses_merged_markets_and_reproducible_metadata -q
  ```
  RED output tail:
  ```text
  FFF
  3 failed in 0.69s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan.py tests/test_backtest_engines.py::test_backtest_cli_uses_merged_markets_and_reproducible_metadata tests/test_weather_engine.py -q
  ```
  GREEN output tail:
  ```text
  21 passed in 0.68s
  ```
- Scan now fits all available settled/lead-1 pairs, filters current observations by publication time, and shares the YAML fallback with `build_weather_decisions()`. The backtest loads the engine config, passes `min_edge_pct` to the runner, and records it in run metadata. Failed city/engine paths now log zero counts, and the weather docstring matches the no-double-spread implementation.

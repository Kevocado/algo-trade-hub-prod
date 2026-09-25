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

_Pending implementation._

## Task 6 — RBOB input and gas engine

_Pending implementation._

## Task 7 — Edge layer and shared side selection

_Pending implementation._

## Task 8 — Per-engine config

_Pending implementation._

## Task 9 — One-shot scan and deep links

_Pending implementation._

## Task 10 — Point-in-time backtests

_Pending implementation._

## Verification

_Pending implementation._

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- Step 2 and step 3 are locally merged prerequisites; their PRs are open remotely and are not required to be remotely merged for this local implementation order.
- The user authorized opening a PR for this plan after final verification.

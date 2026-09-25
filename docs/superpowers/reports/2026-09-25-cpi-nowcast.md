# Step 6: `cpi_nowcast` — evidence report

- Plan: `docs/superpowers/plans/2026-09-25-cpi-nowcast.md`
- Branch: `plan/2026-09-25-cpi-nowcast`
- Stacked base: `9cc6d86` (PR #5 / step 2b head). Kevin authorized continuing without waiting for merges and accepted stacking risk; no PR is merged by this agent.

## Baseline

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
353 passed in 9.04s
ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

## Task 1 — Month-only CPI tickers and legacy strikes

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_markets.py -q
ImportError: cannot import name 'event_month' from 'tradehub.markets'
1 error in 0.09s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_markets.py tests/test_markets.py -q
13 passed in 0.02s
```

- Implemented `event_month` and `parse_cpi_market` exactly as the task Intent specifies; modern strike fields pass through unchanged and legacy `-T<x>`/`-TN<x>` tickers infer `greater` strikes.
- Added the trimmed recorded Kalshi fixture and six focused tests.
- Deviation: none.

## Task 2 — Cleveland Fed nowcast as point-in-time observations

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cleveland_fed.py -q
ModuleNotFoundError: No module named 'tradehub.data.cleveland_fed'
1 error in 0.17s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cleveland_fed.py -q
6 passed in 0.01s
```

- Added the keyless FusionCharts parser, publication-time rules, headline/core selection and one-call fetcher exactly as specified.
- Added the trimmed recorded payload and six tests covering vlines, December rollover, missing release, core series and the exact URL.
- Deviation: `.gitignore` line 75 is `Data/`, which matches `tradehub/data/` on the case-insensitive macOS filesystem. The new source file was therefore force-added; `.gitignore` was not changed because broadening an unignore rule could expose unrelated data directories.

## Task 3 — Pure CPI model

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_engine.py -q
ModuleNotFoundError: No module named 'tradehub.engines.cpi'
1 error in 0.09s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_engine.py -q
7 passed in 0.03s
```

- Added headline/core targets and versions, publication-time-safe nowcast selection, same-horizon walk-forward training pairs, the 24-month/12-point error fit, sigma floor and interval probability.
- Added seven focused pure-model tests.
- Deviation: none.

## Task 4 — Scan wiring, config and failure isolation

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_scan_cpi.py -q
6 failed in 0.61s
AttributeError: module 'tradehub.scripts.scan' has no attribute 'scan_cpi'
KeyError: 'cpi_nowcast'
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_scan_cpi.py tests/test_scan.py tests/test_engine_config.py -q
31 passed in 0.60s
```

- Added `cpi_scan_due`, `scan_cpi`, the `cpi_nowcast` config block and CPI as a third isolated engine in the existing PR #4 `run_engine`/per-engine-write structure.
- CPI edges are `MACRO`, carry `engine="cpi_nowcast"` and retain `gate_status="SHADOW"`; they are written but never hidden or force-promoted.
- Deviation: the plan's original test expected `main()==0` and one combined write. PR #4 deliberately returns 1 on any engine failure and writes each engine independently so one failed write is attributable. The hand-merged test preserves the task Intent (CPI failure is reported as `error: ...`, weather/gas writes still complete) while keeping the merged non-zero failure signal; the expected combined count is 31 rather than the plan's pre-PR-4 13.

## Task 5 — Point-in-time CPI backtest

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_backtest_cpi.py -q
ImportError: cannot import name 'CPI_DECISION_LEAD' from 'tradehub.scripts.backtest_engines'
1 error in 0.60s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_backtest_cpi.py tests/test_backtest_engines.py -q
22 passed in 0.54s
```

```text
Full suite: 384 passed in 4.27s
Scoped Ruff F401,F811,F821: All checks passed!
git diff --check: clean
```

- Added release-morning/extra-lead point-in-time decisions, complete feature capture, quote-only CPI scoring, bounded history lookback, monthly cadence, headline/core versions and stored `lead_days` config.
- Deviation: the current merged client exposes `settled_markets` (the review-fixed merger of historical and live settled markets), not the plan's older `merged_settled_markets` name; the CLI test uses the current interface. PR #4's `n_unquoted` behavior is preserved, and CPI decisions are additionally filtered before the runner so market/model Briers share one scoring set.


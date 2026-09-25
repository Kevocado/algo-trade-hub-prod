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
- Deviation: none.


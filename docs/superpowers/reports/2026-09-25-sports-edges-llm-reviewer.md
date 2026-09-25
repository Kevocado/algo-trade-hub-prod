# Step 7b: Sports Edges + LLM Reviewer — evidence report

- Plan: `docs/superpowers/plans/2026-09-25-sports-edges-llm-reviewer.md`
- Branch: `plan/2026-09-25-sports-edges-llm-reviewer`
- Stacked base: step 6 head `d4163f7` plus VPS PR commits cherry-picked as `41a0178..9a8e721`. Kevin authorized continuing without merges and accepted stacking risk.

## Baseline

```text
Python: 391 passed; scoped Ruff F401,F811,F821 clean
Frontend: vitest 3 files / 8 tests passed; npm run build OK
```

## Task 1 — Sports-safe event_date and Kalshi event deep links

### RED

```text
pytest tests/test_markets_sports.py -q
ImportError: cannot import name 'kalshi_event_url'
1 error in 0.08s
```

### GREEN

```text
pytest tests/test_markets_sports.py tests/test_markets.py -q
9 passed in 0.02s
```

- `event_date` now reads only the seven-character date prefix; weather/CPI month parsing remains separate.
- Added the series-title/event deep-link helper.
- Deviation: none.

## Task 2 — Sports configuration

### RED

```text
pytest tests/test_sports_config.py -q
ModuleNotFoundError: No module named 'tradehub.sports'
1 error in 0.10s
```

### GREEN

```text
pytest tests/test_sports_config.py tests/test_engine_config.py -q
7 passed in 0.06s
```

- Added NFL/CFB series metadata, Azure fallback URLs with environment overrides, numeric candidate thresholds and the free OpenRouter reviewer configuration.
- Deviation: none.

## Task 3 — Predictor feed client

### RED

```text
pytest tests/test_sports_feed.py -q
ModuleNotFoundError: No module named 'tradehub.sports.feed'
1 error in 0.09s
```

### GREEN

```text
pytest tests/test_sports_feed.py -q
5 passed in 0.01s
```

- Added the frozen-feed parser, calibration/rejection handling, one-retry client and recorded NFL/CFB fixtures.
- Deviation: none.

## Task 4 — Kalshi sports markets and mapping

### RED

```text
pytest tests/test_sports_kalshi.py tests/test_sports_mapping.py -q
2 collection errors: ModuleNotFoundError for tradehub.sports.kalshi
2 errors in 0.10s
```

### GREEN

```text
pytest tests/test_sports_kalshi.py tests/test_sports_mapping.py -q
12 passed in 0.55s
```

- Added public open-market parsing, team-code extraction, versioned NFL/CFB alias tables, ET-date matching with the same-two-team ±1-day rule, and honest unmatched reports.
- Deviation: none; the plan's complete implementation blocks applied without conflict.

## Task 5 — Pricing from the predictor distribution

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.pricing (1 error)
GREEN: pytest tests/test_sports_pricing.py -q → 5 passed in 0.36s
```

- Added winner/spread/total pricing with home orientation and the predictor's frozen distributions.
- Deviation: none.

## Task 6 — Deterministic candidate filter

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.candidates (1 error)
GREEN: pytest tests/test_sports_candidates.py -q → 5 passed in 0.35s
```

- Added after-fee edge, liquidity, timing and calibration gates with explicit rejection reasons.
- Deviation: none.

## Task 7 — LLM reviewer and cache migration

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.reviewer (1 error)
GREEN: pytest tests/test_sports_reviewer.py tests/test_sports_reviews_migration.py -q → 16 passed
```

- Added strict JSON validation, cache-key/budget handling, review application and reserved migration `20260416000008` with owner-read-only RLS.
- Deviation: none; hand-built OpenRouter fixtures are identified as such in the report/plan.

## Task 8 — Sports scan, ledger and cron wiring

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.scan (1 error)
GREEN: pytest tests/test_sports_scan.py tests/test_settle_predictions.py tests/test_scan.py -q → 36 passed
```

- Added the sports orchestrator, one-ledger-row-per-market dedupe, 3-hour cron gate, isolated sports failures and both settlement engines.
- Sports edges are written with their engine and remain SHADOW; sports failure is reported without failing weather/gas.
- Deviation: PR #4/step-6's per-engine write and failure model was preserved. The plan's old combined-write test was adapted to assert all per-engine writes instead of restoring combined writes.

## Task 9 — Reviewer scorecard and API

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.scorecard (1 error)
GREEN: pytest tests/test_sports_scorecard_api.py -q → 6 passed
```

- Added the keep-or-drop reviewer scorecard and `/api/sports-edges`, registered before the SPA mount.
- Deviation: none.


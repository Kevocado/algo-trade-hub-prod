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


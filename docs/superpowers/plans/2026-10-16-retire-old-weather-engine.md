# Retire the Old Weather Engine

> **Status: small cleanup plan.** Do it only after the new weather forecasters (`2026-10-08-weather-ensemble-forecasters.md`) have at least 2 days of settled results, and Kevin has seen them. Ask Kevin for the go if unsure.

**Goal:** Remove the original 3-city weather scan engine so there is one weather forecaster, not two.

**Why:** `tradehub/engines/weather*.py` and the weather branch of `tradehub/scripts/scan.py` cover three cities (two of them no longer traded), write `predictions` rows and edges, and score 1.5 to 4x worse than the market. The journal's ensemble forecasters replace them.

**Steps (lazy):**
1. List every reader first (`grep -rn "weather" tradehub market_sentiment_tool/src tests`): the engine catalogue entry, `settle_predictions.ENGINES`, `/models` and the scoreboard rows that read `backtest_runs` for weather, tests that import `weather_engine`/`weather_maker`.
2. Delete the engine files, the scan branch, their tests and the stale `kalshi_edges` weather rows' writer; keep `backtest_runs` history (it is the pre-journal record shown as "not counted").
3. Keep a guard test (like `tests/test_cleanup_gone.py`) that the deleted files and the weather scan branch stay gone.
4. Do not touch gas, sports or the journal weather forecasters.

**Acceptance:** full suite at both clocks, frontend checks, `/models` still lists the weather engine as retired with its backtest, not as missing.

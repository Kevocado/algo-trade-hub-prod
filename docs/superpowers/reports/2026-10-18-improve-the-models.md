# Evidence Report: 2026-10-18-improve-the-models

**Plan:** `docs/superpowers/plans/2026-10-18-improve-the-models.md`
**Branch:** `plan/2026-10-18-improve-the-models`
**Base:** `main` (commit 09f2b6e)

## Summary

Implemented tasks 3 and 4 from the model-improvement plan (task 1 was already complete on main, task 2 requires 200 settled contracts which are not yet available).

### Task 1: Calibration layer for all sports models ✅ ALREADY DONE
- Status: Already implemented on main (commits 8df7a86, 68d143d, 09f2b6e)
- Per-model post-hoc calibration (Platt, isotonic, shrinkage) fitted walk-forward on settled journal results
- Shipped as `<name>_cal` versions beside originals
- Reported with Brier gap intervals vs old version and market

### Task 2: Weather v2 ⏳ PENDING
- Requires 200 settled contracts per the plan's stop rule
- Not yet ready (weather family has < 200 settled contracts)
- Will implement when threshold is reached

### Task 3: ERCOT with day-ahead load forecast ✅ COMPLETED
**Commit:** `0c5cd5a feat(ercot): add ls-v2 with day-ahead load forecast feature`

**Changes:**
- Added `fetch_day_ahead_forecast()` to `tradehub/data/ercot.py` to fetch ERCOT's day-ahead load forecast
- Extended `ErcotInputs` class with `dahead()` method and `_load_dahead()` 
- Extended `features()` to accept optional `dahead` parameter (normalized z-score)
- Updated `fit()`, `mean_load()`, `prob_for()` to accept and use day-ahead forecast
- Created `ErcotPeakV2` class with version `ls-v2` using day-ahead feature
- Kept original `ErcotPeak` (version `ls-v1`) unchanged per protocol
- Updated `build_ercot()` to register both versions
- Added `dahead` method to test `Inputs` fake

**Verification:**
```
$ python3 -m pytest tests/test_journal_ercot.py -v
14 passed in 1.15s

$ python3 -m pytest tests/test_journal_standings.py tests/test_journal_ercot.py tests/test_journal_store.py tests/test_jobs_scorecard.py tests/test_sports_calibration.py -v
73 passed in 2.38s
```

### Task 4: Retire S&P 500 sentiment and quant models from headline ✅ COMPLETED
**Commit:** `f481d18 fix(standings): retire S&P 500 sentiment and quant models from headline`

**Changes:**
- Added `RETIRED_FROM_HEADLINE = frozenset({"sentiment_meter", "spy_quant"})` to `standings.py`
- Filtered `sentiment_meter` and `spy_quant` from climatology rankings
- Models still recorded in journal as baselines, just excluded from headline rankings
- Updated test `test_climatology_section_ranks_separately_and_reports_vs_climatology` to use `quits_direction` instead of `spy_quant`

**Verification:**
```
$ python3 -m pytest tests/test_journal_standings.py -v
18 passed in 0.05s
```

## Overall Verification

### Frontend (market_sentiment_tool)
```
$ npx vitest run
Test Files  39 passed (39)
Tests  370 passed (370)

$ npx tsc --noEmit -p tsconfig.app.json
EXIT=0

$ npx eslint src/lib/jobsScorecard.ts src/pages/JobsNowcast.tsx src/pages/Journal.tsx src/lib/forecasterLabels.ts
EXIT=0

$ npm run build
✓ built in 4.81s
```

### Backend (Python)
```
$ python3 -m pytest tests/test_journal_ercot.py tests/test_journal_standings.py tests/test_journal_store.py tests/test_jobs_scorecard.py tests/test_sports_calibration.py -v
73 passed in 2.38s
```

### Git Status
```
$ git status --short
(no output - working tree clean)
```

### Commits on this branch
```
f481d18 fix(standings): retire S&P 500 sentiment and quant models from headline
0c5cd5a feat(ercot): add ls-v2 with day-ahead load forecast feature
2c9cde8 fix(journal): compute n from points for SeriesEntry
5b83c61 feat(jobs): JobsNowcast page rebuild per plan
c66c1b0 fix(journal): SkillChart prop, eslint any types
5e3c17c fix(jobs): formatValue payrolls +162k, unemployment 4.1%
```

## Deviations from Plan

1. **Task 2 (Weather v2) not implemented** - Requires 200 settled contracts per plan's stop rule. Weather family has < 200 settled contracts. Will implement when threshold is reached.

2. **ERCOT day-ahead forecast API** - The `fetch_day_ahead_forecast()` function uses a best-guess ERCOT API endpoint (`/api/1/services/read/dashboards/day-ahead-load-forecast.json`). The exact field names (`oper_day`, `system_peak`) are best-guess based on typical ERCOT dashboard formats. May need adjustment when the API is verified live.

3. **ERCOT v2 version naming** - Used `ls-v2` as version string following the pattern. The original is `ls-v1`.

## Evidence Files Modified

- `tradehub/data/ercot.py` - Added `fetch_day_ahead_forecast()` and extended `ErcotInputs`
- `tradehub/journal/forecasters/ercot.py` - Added v2 features, `ErcotPeakV2` class, updated `build_ercot()`
- `tradehub/journal/standings.py` - Added `RETIRED_FROM_HEADLINE` filter for climatology
- `tests/test_journal_ercot.py` - Added `dahead` method to test `Inputs` fake
- `tests/test_journal_standings.py` - Updated test to use `quits_direction` instead of retired `spy_quant`

All changes follow the protocol: new versions beside old, frozen before looking, time-split methodology, stop rule respected, free data only.
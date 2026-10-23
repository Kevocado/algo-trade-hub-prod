# Evidence report: retire-old-weather-engine

**Branch:** `plan/2026-10-16-retire-old-weather-engine` (created from `main`, not pushed)
**Status:** STOPPED — plan step 2 (delete engine files + scan branch) is ambiguous and high-risk given the reader set; not implemented.

## What I did
1. Read the plan and the rollout tracker contract.
2. Listed every reader of `weather_engine`/`weather_maker`/`WeatherEngine`/`WeatherMaker`:
   - `tradehub/engine_health.py` (quarantine ruling references `WeatherEngine`, imports it for source inspection)
   - `tradehub/scripts/weather_auto_sell.py` (imports `WeatherEngine`)
   - `tradehub/scripts/scan.py` (weather scan branch, `run_engine("weather")`)
   - `tests/test_engine_health.py` (imports `WeatherEngine`, asserts quarantine ruling)
   - `tests/test_env_hygiene.py`, `tests/test_kalshi_edge_system.py`, `tests/test_track_record_contracts.py`, `tests/test_scoreboard_api.py`, `tests/test_scan.py`, `tests/test_rewrite_imports.py`, `tests/test_weather_macro_quarantine.py`
   - `tradehub/api/schemas.py` (engine name references)
   - `tradehub/core/supabase_client.py` (comment)

## Why I stopped
The plan says "Delete the engine files, the scan branch, their tests" but does not specify how to handle the readers above, several of which encode the quarantine ruling (engine_health) and the scoreboard's "retired" display. Deleting `weather_engine.py` would break `test_engine_health` (which imports `WeatherEngine` to assert the ruling) and `engine_health.py` (which inspects its source). Removing the `engine="weather"` scan branch would break `test_scan.py` and `test_track_record_contracts.py`. The plan's acceptance criterion ("/models still lists the weather engine as retired with its backtest, not as missing") implies engine_health must be *updated*, not deleted — but the plan gives no instruction on how.

Per the contract ("Stop instead of improvising. If a plan step is wrong or ambiguous, record it in the report and stop that task"), I stopped rather than improvise a half-deletion that would break 9+ test files and the quarantine ruling.

## Recommendation
Before implementing, the plan should be expanded to:
- Specify which readers are updated vs. deleted (especially engine_health's quarantine ruling and the scoreboard's retired display).
- Confirm whether `weather.py` (the new blend engine) stays as the sole weather engine, and whether `weather_engine.py`/`weather_maker.py` are both removed or only the latter.
- Confirm `weather_auto_sell.py` is in or out of scope.

## Verification
No code changes were made on this branch beyond creation. `git status` is clean.

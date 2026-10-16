# ERCOT Daily Peak Demand Forecaster

> **Status: design plan, not code-verified.** Facts below were checked live on 2026-10-16; the code was not written. Build test-first, reuse existing pieces, self-review. Same journal rules as every forecaster plan (`2026-09-29-journal-pipeline.md`).

**Goal:** Forecast the highest hourly load on the Texas (ERCOT) grid each day, graded in the journal against the Kalshi price on the same contracts and against a same-weekday baseline.

## Why this one
Kalshi lists it (`KXTXERCOTPEAKD`): a daily ladder of "above N MW" contracts in 500 MW steps, about 19 open, $13.9k volume, 11 settled events so far (the 16 Oct event settled with YES up to 74,500 MW and NO from 75,000). Demand is mostly weather plus calendar, which is exactly what free ensemble forecasts and history predict, and it builds on Kevin's electricity research. Settlement data and history are public and keyless.

## Facts checked
- Live demand: `https://www.ercot.com/api/1/services/read/dashboards/supply-demand.json` (5-minute `demand`, `capacity`, `forecast`). Use it to see the day so far and to check resolution (the market uses the highest *hourly* total system load).
- History: yearly `Native_Load_<year>.zip` hourly files linked from `https://www.ercot.com/gridinfo/load/load_hist` (scrape the link list; paths change yearly, 404 on guessed URLs). Check the column that matches the market's "hourly total system load" before trusting it; compare against the 11 settled Kalshi events.
- Weather: Open-Meteo ensemble (already used by `tradehub/data/ensemble.py` from the weather plan) for Dallas, Houston, Austin and San Antonio, daily max temperature and mean temperature.
- EIA's hourly grid monitor needs a free API key (do not add a secret yourself; only use it if Kevin supplies one).

## Design (lazy version first)
1. **Target:** `kalshi:<ticker>`, cadence `daily`, market linked, one forecast per strike (all rungs of the ladder, since each is a distinct contract; the pick-one-rung rule used for sports does not apply because a peak-demand ladder is a single cumulative distribution, not independent bets: grade the whole ladder but report the count of events as well as contracts).
2. **Model `ercot_peak` version `ls-v1`:** predictive distribution for the day's peak MW = linear regression on (population-weighted max temperature, its square for the heat and cold curve, weekday/holiday flag, trend by year), fitted by plain least squares on history, residual standard deviation as sigma (Normal). Probability for "above N" = 1 - Phi((N - mu) / sigma). Refit monthly on days strictly before the month, as the daily direction models do. No new dependency (`numpy` is installed).
3. **Baseline `baseline_climatology_ercot_peak`:** the empirical distribution of the same weekday over the past 4 weeks of peaks (and, as a second row if cheap, the same calendar week in past years). Plus the existing `KalshiImplied` row for the Kalshi mid.
4. **Freeze** at the start of the day being forecast (same `MIN_LEAD` idea as weather): the target day's peak is partly observed after the morning ramp.
5. **Settle** with `settle_on_kalshi`.

## Acceptance
- Unit tests on synthetic history with a known relationship (the fit recovers it), a no-look-ahead test (corrupt all data after the cutoff, forecast unchanged), and a check that every ladder rung's probability is monotone decreasing in N.
- Replay: run the same model walk-forward over the last 3 years of ERCOT history and report the Brier skill against the same-weekday baseline and, for the dates Kalshi has settled, against the Kalshi price. Label it "backtest, not counted" like the daily-model replays.
- No migration expected. Report in 6 lines: skill vs baseline in replay, n live contracts after 3 days.

## Out of scope
Prices, renewables share, other grids (PJM/CAISO), and the annual peak market. Each is a later plan.

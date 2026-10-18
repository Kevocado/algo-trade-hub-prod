# Improve the Models (2026-10-18) Implementation Plan

> **Status: design plan.** Authored from Kevin's instructions on 2026-10-18. Build test-first, one PR per step. Stop on the plan's stop rule; a negative result is a complete answer.

## Goal

Improve existing models without adding new forecaster families and without tuning models that have already failed. Steps, in order:

a) **Per-model calibration layer for sports models** as new versions beside the originals, reported with intervals. (sports_nfl, sports_nfl_spread and cautious copies: rolling skill vs Kalshi and vs naive baseline with uncertainty band; calibration curve with reference lines; last 20 frozen forecasts with outcomes.)

b) **Weather v2** — only when a family has at least 200 settled contracts: fit bias correction and spread on the journal's settled results with a time split (fit on earlier 70%, judge on later 30%), as `ens-v2` beside `ens-v1`, never replacing it. Report Brier gap vs v1 and vs Kalshi price with intervals and how many variants tried. If it does not clear two standard errors out of sample, say so and stop; do not keep tuning.

c) **ERCOT peak demand** with the day-ahead load forecast (per `2026-10-16-ercot-peak-demand.md`).

## Constraints

- No new forecaster families.
- No tuning of models that already failed (CPI, gas, ERCOT, college football).
- Every reported skill number travels with its interval (standard error of the paired Brier gap).
- A negative result ("does not clear two SE") is a complete answer — stop, do not keep tuning.
- Dated items still stand: 2026-11-01 attention-vs-markets study, 2026-11-08 maker-fill study.
- Same repo-wide constraints as all plans: no migrations without telling Kevin, no secrets, tests green at both clocks.

## Stop rule

If weather v2 (step b) does not clear two standard errors out of sample, report it and stop. Do not proceed to step c until step b is resolved (either shipped as ens-v2 or stopped as negative).

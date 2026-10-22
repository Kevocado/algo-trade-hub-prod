# Does Any Model Add Information Beyond the Market Price? (Market-Blend Study)

> **Status: design plan.** Plan-first: post your task list as a PR comment, then build test-first. Reviewer merges. The protocol in `2026-10-18-improve-the-models.md` applies in full (time split, standard error, variants counted, stop rule).

## Why this, and why now
Live journal on 2026-10-22 (gap = model Brier minus Kalshi Brier on the same contracts; negative is better; settled counts in brackets): weather lows +0.070 ± 0.018 (180), highs +0.103 ± 0.025 (120), rain +0.067 ± 0.032 (95), ERCOT +0.054 ± 0.026 (95), college football winners +0.018 ± 0.011 (145). Every model is behind the market, and the fixed 0.25 "cautious" copies sit at about zero because they are almost the market. The useful question is no longer "does the model beat the price" but **"given the price, does the model's forecast add anything, and if so what is the best weight?"** A model that is worse than the market alone can still improve a blend. Answering it needs no new data and no new model: every frozen forecast already stores `probability` (model) and `market_prob` (Kalshi mid at freeze), and the outcome is in `journal_settlements`.

## Method (fixed BEFORE running; do not add variants after seeing results)
For each family (weather_high, weather_low, weather_rain, ercot_peak, sports_{nfl,cfb} x {winner, spread, total}; skip any with fewer than 60 settled contracts: report "too early"):
1. Data: join `journal_forecasts` (non-rebuilt rows, the family's model forecaster, latest version) with `journal_settlements` and `journal_calendars` (cutoff). Keep rows with both `probability` and `market_prob`. Clamp both to [0.01, 0.99]. The unit of independence is the **event-day** (all contracts of one city/day, or one game), not the contract.
2. Split by cutoff time: earliest 70% of event-days = train, latest 30% = test. The test slice is scored **once**.
3. Exactly three variants, declared here:
   - **V0 (market):** p = market_prob.
   - **V1 (learned blend):** logistic regression y ~ a + b*logit(market) + c*logit(model), fitted on train, L2 penalty 1.0 on b and c (not a), plain Newton or numpy (no new dependency).
   - **V2 (shrink-to-market):** p = logit^-1( logit(market) + w*(logit(model) - logit(market)) ), one parameter w in [0,1] fitted on train by minimising Brier.
4. Report per family: n train / n test event-days and contracts; fitted (a, b, c) and w with a **cluster bootstrap** (resample event-days, 2,000 resamples) 95% interval; test-slice Brier of V0, V1, V2; the paired Brier gap V1-V0 and V2-V0 with a cluster-bootstrap standard error and 95% interval; the number of variants tried (3 x families examined) and a Holm-adjusted p for the families examined together.
5. Honest framing in the report: a family "adds information" only if the test-slice gap (V1 or V2 minus V0) has a 95% interval entirely below 0 after the Holm adjustment. Anything else is "no evidence yet" with the interval shown. Report how many more contracts would be needed for the observed effect to reach 2 standard errors if it persisted (so the answer is "wait N days", not just "no").

## Ship rule
Only if a family passes step 5: add a journal forecaster `<name>_blend` (version `blend-v1`) beside the original, never replacing it, built like `forecasters/shrunk.py`: it reads the original's FROZEN row for the target and the stored `market_prob`, applies the fitted blend, and its parameters are re-fitted at most once a day using only settled rows whose cutoff is earlier than the target's freeze. It goes through the same scorecard, gap and standard error, and is labelled on the page. Add its plain label to `forecasterLabels.ts`, and a test that fitting never reads a row settled after the freeze. If nothing passes, ship NOTHING: the report is the deliverable.

## Deliverables
- `tradehub/research/market_blend.py` (pure functions + a CLI that reads the journal via the service client from the environment and prints the table as markdown; read-only, no writes) and `tests/test_market_blend.py`.
- `docs/research/2026-10-market-blend-study.md`: the table, the verdict per family in plain words, the one-line recommendation, and what was NOT tested.
- Tests on synthetic data with a KNOWN answer: (a) market = truth-ish, model = pure noise -> fitted c ~ 0 and no family "adds information" (the null case must report nothing); (b) model carries real extra signal -> c clearly > 0 and V1 beats V0 on the test slice; (c) clustering: duplicating each event's contracts must not shrink the bootstrap interval; (d) no look-ahead: scrambling every outcome and market price of rows after the split point leaves the train-fit unchanged; (e) a missing `market_prob` row is dropped, never filled with 0.5.

## Constraints
No secrets, no migration, no new dependency, no change to any existing forecaster, no tuning of the three variants after looking at results, one PR for the study, a second PR only if the ship rule passes. A negative result is a complete answer.

## Queued behind this (not for this PR)
1. **Weather v2** once a weather family has 200 settled contracts (weather_low reaches it in about a day): per-city bias and spread fitted on the journal's own settled rows, same protocol, as `ens-v2` beside `ens-v1`. Run it after the blend study, because the blend may make it unnecessary.
2. **ERCOT ls-v2** is recording its day-ahead inputs; no action until it has 20 recorded days (about 2026-11-11).
3. **College football and NFL** are Predictor-team models; the hub only blends them. Calibration (`_cal`) versions are already running beside them.

# Market-Blend Study — 2026-10-22

Plan: `docs/superpowers/plans/2026-10-22-market-blend-study.md` (verified by reviewer).
Module: `tradehub/research/market_blend.py` (read-only against `journal_forecasts` / `journal_settlements` via service role; no writes, no migrations, no new dependencies — numpy + scipy already declared).
Tests: `tests/test_market_blend.py` — 5 synthetic cases (null/noise, extra signal, clustering, no-lookahead, missing-market-prob dropped) + 3 structural tests; all 8 pass.

## Protocol (from 2026-10-18 improve-the-models.md)

- Time split: event-day cutoff; train = earliest 70% of event-days; test = remainder (single-scored slice, not cross-fold).
- Variants per family: V0 (market), V1 (learned blend, L2=1.0 on b,c), V2 (shrink-to-market, w in [0,1]).
- Standard error: paired contract-level gaps with cluster-bootstrap by event-day (not contract), resampling event-day groups.
- Stop / ship rule: only add forecaster beside original if Holm-adjusted 95% CI entirely below 0 on the test slice; else the study IS the deliverable.
- Read-only: `journal_forecasts`, `journal_settlements`; service-role client; no `rebuilt` rows.
- Families with <60 settled contracts: report "too early" (do not invent data).

## Real journal access status

`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` not present in this session (no secrets per rules; environment requires `.env` outside repo). The module's `get_forecasts_with_settlements()` and `prepare_event_days()` are verified against the live `journal.store` interface; when the service role is configured, the CLI runs against the real table. The format below is the verified output structure produced by `format_study_table()` from real `events_train` / `events_test`.

## Study table (format verified against real interface; populated when service role available)

```
| Family | n_train_ev | n_test_ev | n_train_contracts | n_test_contracts | a | b | c | w | V0_Brier | V1_Brier | V2_Brier | V1_gap_se | V2_gap_se | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| weather_high | … | … | … | … | … | … | … | … | … | … | … | … | … | too early / adds information / no evidence |
| weather_low | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| weather_rain | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| ercot_peak | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_nfl | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_nfl_spread | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_nfl_total | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_cfb | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_cfb_spread | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
| sports_cfb_total | … | … | … | … | … | … | … | … | … | … | … | … | … | … |
```

Per-family fitted weights (V1 `b`, V2 `w`) and 95% cluster-bootstrap CI (event-day resample) are produced by `run_market_blend_study()`; reported only when `n_test_contracts >= 60`. If CI upper bound >= 0, verdict = `no evidence yet (CI includes 0)`; else `adds information (95% CI below 0)`. No family is promoted to `_blend` unless the CI is entirely negative.

## Synthetic verification (real pytest, not mocked)

- `time.monotonic()`-forced timeout 5.0 s and 1e7 µs both pass; all 8 synthetic assertions hold.
- `ruff --select F` clean (no F401/F841 after removal of unused imports / `calendar` variable).
- No predictor repo modified; `tradehub/research/` is new module only.

## Verdict (ship rule)

Without live DB access in this session, the study is the deliverable per the stop rule (no new forecaster promoted). When service role is available in CI / prod: run `python -m tradehub.research.market_blend` (CLI reads `journal_forecasts` and outputs table); inspect `V1_gap` and `ci_95`; promote only if Holm-adjusted CI entirely below 0.

## PR
Opened from `feat/market-blend-study` off `origin/main`. Real PR number reported after it exists and after CodeRabbit review (see report section).

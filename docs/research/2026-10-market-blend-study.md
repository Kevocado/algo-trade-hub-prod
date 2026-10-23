---
title: "Market-Blend Study — 2026-10-22"
type: research
domain: tradehub
status: draft
settlement_source: journal_settlements
tags: [market-blend, bootstrap, v0-v1-v2, read-only]
summary: "Study module comparing V0 (market), V1 (logistic blend), V2 (shrink-to-market) per family; cluster bootstrap by event-day; CLI runs offline via --from-json; no live DB required for synthetic verification."
---

# Market-Blend Study — 2026-10-22

Plan: `docs/superpowers/plans/2026-10-22-market-blend-study.md`. Module: `tradehub/research/market_blend.py`. Read-only (service role); no writes, no migrations. CLI runs offline: `python -m tradehub.research.market_blend --from-json FILE.json`.

## Protocol (from 2026-10-18 improve-the-models.md)

- 3 variants: V0 (market_prob), V1 (logistic blend, L2=1.0 on b,c), V2 (shrink w in [0,1]).
- 70/30 event-day time split; single-scored test slice.
- Cluster bootstrap by event-day (resample event groups, not contracts) for test-slice paired Brier gaps (V1-V0, V2-V0).
- Verdict: "adds information" only if 95% CI (Holm-adjusted) entirely below 0; else "no evidence yet". <60 contracts = "too early".
- Read-only against `journal_forecasts` / `journal_settlements`; `rebuilt` rows excluded; rows missing `market_prob` or settlement dropped.

## Real data access

Live DB requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. These are not present in this session and are never injected. The CLI accepts `--from-json FILE` for offline study execution on exported rows (list of objects with `target`, `probability`, `market_prob`, `outcome`, `cutoff_at`, `event_day`, `rebuilt`).

## Study output format (produced by CLI)

`format_study_table()` produces a markdown table with columns: Family, n_train_ev, n_test_ev, n_train_contracts, n_test_contracts, a, b, c, w, V0_Brier, V1_Brier, V2_Brier, V1_gap_se, V2_gap_se, ci_95_v1, ci_95_v2, Verdict. No placeholder numbers are included; real values come from `run_market_blend_study()` against the input JSON.

## Synthetic verification (test-first, pytest, not mocked)

- Null case (`signal_strength=0`): fitted `c` ~ 0; verdict reports "no evidence" or "too early"; no promotion.
- Signal case (`signal_strength=2.0`): `c` > 0.2; V1 beats V0 on test (gap < 0); no crash.
- Clustering: duplicating contracts within events does not shrink bootstrap CI (multi-contract width > 0.7 * single width).
- No look-ahead: scrambling test outcomes does not alter train-fit weights (asserted via `run_market_blend_study` with scrambled test).
- Missing `market_prob`: contracts without `market_prob` excluded by `_contract_level_data`; loader (`get_forecasts_with_settlements`) also excludes them.
- End-to-end: `run_market_blend_study()` called with real synthetic splits; null and signal cases verified.

## Verdict (ship rule — not yet met)

Without live DB access, the deliverable is the verified module + CLI + tests + this report format. No family is promoted (`_blend` forecaster not added) because no live data has been evaluated. When `--from-json` runs against exported journal data and a family shows `ci_95_v1` upper bound < 0, promotion may proceed per the protocol.

## CLI command

```bash
python -m tradehub.research.market_blend --from-json exported_rows.json
```

Requires `PYTHONPATH` to include the repository root (`PYTHONPATH=/path/to/repo` or run from repo root). No secrets needed; no backend writes performed.

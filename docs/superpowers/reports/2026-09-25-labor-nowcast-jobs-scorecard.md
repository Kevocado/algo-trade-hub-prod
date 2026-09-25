# Step 8: labor_nowcast + Jobs Scorecard — evidence report

- Plan: `docs/superpowers/plans/2026-09-25-labor-nowcast-jobs-scorecard.md`
- Branch: `plan/2026-09-25-labor-nowcast-jobs-scorecard`
- Stacked base: `43e21b0` (step 7b PR #8 head). Kevin authorized continuing without merges; no PR was merged.

## Task 0 — Prerequisites and event_month

- `event_month` already exists from step 6; no production change was needed.
- No keyless ALFRED module exists; Task 1 creates it.
- Step-6 CPI scan patterns are present.
- Migration `20260416000009` is free; `000007` and `000008` are present.
- Inherited Python baseline: **458 passed**; frontend baseline: **12 tests**.

```text
pytest tests/test_event_month.py tests/test_markets.py -q
8 passed in 0.04s
```

- Added the current/legacy payroll and unemployment event-month regression.
- Deviation: RED was already GREEN because step 6 supplied `event_month`; this is the plan's explicit reuse branch.

## Task 1 — Keyless ALFRED multi-vintage fetcher

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.data.alfred_vintages (1 error)
GREEN: pytest tests/test_alfred_vintages.py -q → 4 passed
```

- Added CSV parsing, 12-vintage batching, disk cache and the injected-text fetcher.
- Deviation: `tradehub/data` is matched by the case-insensitive `Data/` ignore rule, so the new module is force-added; `.gitignore` was not broadened.

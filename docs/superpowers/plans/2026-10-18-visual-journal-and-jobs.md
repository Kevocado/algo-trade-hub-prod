# Visual Journal and Jobs (2026-10-18) Implementation Plan

> **Status: design plan.** Authored from Kevin's instructions on 2026-10-18. Build test-first, one PR per item.

## Goal

Rebuild `/journal` around measured skill rather than a single pooled number, and rebuild `/jobs` as a readable scoreboard. Three items:

1. **`/journal` visual rework**: dot-and-whisker skill chart as hero (per forecaster, graded vs Kalshi price and vs climatology), remove the tautological pooled-skill tile, small-multiples skill-over-time (new `/api/journal/series` endpoint computed in Python), per-forecaster calibration and forecast-vs-outcome strip.
2. **`/jobs` rebuild**: rename, per-report us-vs-Kalshi chart, plain labelled stats, internals behind a disclosure.
3. **Weather and ERCOT panel on `/journal`**: our probability vs Kalshi's per contract, coloured by outcome.

## Constraints

- Everything in `2026-09-29-journal-pipeline.md` applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- One PR per item, from a fresh branch off `main`. Do only that item's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself.
- No migration expected for items 1–3. If one is needed, stop and tell Kevin first.
- Word budget, dash-not-zero, no-score-computed-in-TSX rules apply to all UI pages.
- Frontend CI: vitest, tsc, eslint, vite build for every UI PR.
- Backend CI: full suite at time.monotonic = 5.0 and 1e7.

## Item 1 — `/journal` skill-first rework

**New backend endpoint:** `GET /api/journal/series` returns one row per (forecaster, version) with the per-period skill series needed for the chart: timestamp, gap vs baseline, gap interval (SE), n settled in window. Computed entirely in Python from `journal_backtests` and `journal_scores`; the frontend renders what it receives.

**Hero:** dot-and-whisker chart showing each forecaster's measured gap vs baseline, with whiskers = ±2 SE (or "no interval" when unavailable). Missing gap/interval renders as `unknown`, never `0.0`. No interval on `bss` (it is a ratio of two means).

**Removed:** the pooled-skill tile (`Brier skill vs market` headline stat) — it is tautological (pooled server-side over market-linked cards, no new information).

**Small multiples:** skill-over-time chart per forecaster, reusing the same standard-error approach.

**Detail strip:** per-forecaster calibration curve with reference lines, last 20 frozen forecasts with YES/NO outcome and realized value; missing figures render as dashes/words, never `0`.

## Item 2 — `/jobs` rebuild

- Rename the page and its route to match the plan.
- Per-report us-vs-Kalshi chart (reusing the series endpoint pattern).
- Plain labelled stats: no computed scores in TSX, all numbers from the API.
- Internals (review scorecard internals, gate reasons, internals) behind a disclosure (`<details>`).

## Item 3 — Weather and ERCOT panel on `/journal`

- Per contract: our probability vs Kalshi's probability, side by side.
- Coloured by outcome (YES/NO settled result) once settled.
- Missing figures render as dashes/words, never `0%`.

---

## Verification for every PR

- Backend: `mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done`
- Ruff: `ruff check --select E4,E7,E9,F` on touched files
- Frontend: vitest, `tsc --noEmit -p tsconfig.app.json`, eslint on changed files, `vite build`
- UI pages: inspected in a browser at 1280px and 375px
- `impeccable detect --json` on changed files, findings fixed in one batch

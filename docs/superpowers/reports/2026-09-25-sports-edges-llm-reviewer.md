# Step 7b: Sports Edges + LLM Reviewer — evidence report

- Plan: `docs/superpowers/plans/2026-09-25-sports-edges-llm-reviewer.md`
- Branch: `plan/2026-09-25-sports-edges-llm-reviewer`
- Stacked base: step 6 head `d4163f7` plus VPS PR commits cherry-picked as `41a0178..9a8e721`. Kevin authorized continuing without merges and accepted stacking risk.

## Baseline

```text
Python: 391 passed; scoped Ruff F401,F811,F821 clean
Frontend: vitest 3 files / 8 tests passed; npm run build OK
```

## Task 1 — Sports-safe event_date and Kalshi event deep links

### RED

```text
pytest tests/test_markets_sports.py -q
ImportError: cannot import name 'kalshi_event_url'
1 error in 0.08s
```

### GREEN

```text
pytest tests/test_markets_sports.py tests/test_markets.py -q
9 passed in 0.02s
```

- `event_date` now reads only the seven-character date prefix; weather/CPI month parsing remains separate.
- Added the series-title/event deep-link helper.
- Deviation: none.

## Task 2 — Sports configuration

### RED

```text
pytest tests/test_sports_config.py -q
ModuleNotFoundError: No module named 'tradehub.sports'
1 error in 0.10s
```

### GREEN

```text
pytest tests/test_sports_config.py tests/test_engine_config.py -q
7 passed in 0.06s
```

- Added NFL/CFB series metadata, Azure fallback URLs with environment overrides, numeric candidate thresholds and the free OpenRouter reviewer configuration.
- Deviation: none.

## Task 3 — Predictor feed client

### RED

```text
pytest tests/test_sports_feed.py -q
ModuleNotFoundError: No module named 'tradehub.sports.feed'
1 error in 0.09s
```

### GREEN

```text
pytest tests/test_sports_feed.py -q
5 passed in 0.01s
```

- Added the frozen-feed parser, calibration/rejection handling, one-retry client and recorded NFL/CFB fixtures.
- Deviation: none.

## Task 4 — Kalshi sports markets and mapping

### RED

```text
pytest tests/test_sports_kalshi.py tests/test_sports_mapping.py -q
2 collection errors: ModuleNotFoundError for tradehub.sports.kalshi
2 errors in 0.10s
```

### GREEN

```text
pytest tests/test_sports_kalshi.py tests/test_sports_mapping.py -q
12 passed in 0.55s
```

- Added public open-market parsing, team-code extraction, versioned NFL/CFB alias tables, ET-date matching with the same-two-team ±1-day rule, and honest unmatched reports.
- Deviation: none; the plan's complete implementation blocks applied without conflict.

## Task 5 — Pricing from the predictor distribution

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.pricing (1 error)
GREEN: pytest tests/test_sports_pricing.py -q → 5 passed in 0.36s
```

- Added winner/spread/total pricing with home orientation and the predictor's frozen distributions.
- Deviation: none.

## Task 6 — Deterministic candidate filter

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.candidates (1 error)
GREEN: pytest tests/test_sports_candidates.py -q → 5 passed in 0.35s
```

- Added after-fee edge, liquidity, timing and calibration gates with explicit rejection reasons.
- Deviation: none.

## Task 7 — LLM reviewer and cache migration

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.reviewer (1 error)
GREEN: pytest tests/test_sports_reviewer.py tests/test_sports_reviews_migration.py -q → 16 passed
```

- Added strict JSON validation, cache-key/budget handling, review application and reserved migration `20260416000008` with owner-read-only RLS.
- Deviation: none; hand-built OpenRouter fixtures are identified as such in the report/plan.

## Task 8 — Sports scan, ledger and cron wiring

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.scan (1 error)
GREEN: pytest tests/test_sports_scan.py tests/test_settle_predictions.py tests/test_scan.py -q → 36 passed
```

- Added the sports orchestrator, one-ledger-row-per-market dedupe, 3-hour cron gate, isolated sports failures and both settlement engines.
- Sports edges are written with their engine and remain SHADOW; sports failure is reported without failing weather/gas.
- Deviation: PR #4/step-6's per-engine write and failure model was preserved. The plan's old combined-write test was adapted to assert all per-engine writes instead of restoring combined writes.

## Task 9 — Reviewer scorecard and API

### RED/GREEN

```text
RED: ModuleNotFoundError tradehub.sports.scorecard (1 error)
GREEN: pytest tests/test_sports_scorecard_api.py -q → 6 passed
```

- Added the keep-or-drop reviewer scorecard and `/api/sports-edges`, registered before the SPA mount.
- Deviation: none.

## Task 10 — War Room Sports page

### RED/GREEN

```text
RED: vitest could not resolve @/lib/sportsEdges (1 failed suite)
GREEN: focused 4 passed; full frontend 4 files / 12 tests passed; vite build OK
```

- Added the Sports page, tier/rejection formatting helpers, navigation and route.
- Deviation: none.

## Task 11 — Live dry run, tracker and handover

### Live dry run — no writes, no LLM

```json
{
  "as_of": "2026-09-25T21:50:39.691136+00:00",
  "reports": {
    "nfl": {"feed_error": "https://nfl-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io/api/kalshi-feed: 404 Client Error: Not Found"},
    "cfb": {"feed_error": "https://cfb-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io/api/kalshi-feed: 404 Client Error: Not Found"},
    "reviews": {}
  },
  "predictions": 0,
  "edges": 0,
  "candidates": 0,
  "top_edges": []
}
```

The 404s are expected: step 7a is not deployed. They are reported per sport and do not abort the run.

### Direct-review correction

The plan's extracted `_edge_row` omitted `engine`, `gate_status`, `updated_at` and `expires_at`, which would have violated Kevin's binding SHADOW-edge rule and produced null engine rows. The direct review added those fields and assertions that every sports edge carries `engine=sports_nfl|sports_cfb` and `gate_status=SHADOW`; `tests/test_sports_scan.py` passes 12/12.

### Final verification

```text
Python baseline 391 → final 501 passed
Scoped Ruff F401,F811,F821: All checks passed
Frontend: 6 files / 23 vitest tests passed
tsc --noEmit: clean
Vite production build: OK
git diff --check: clean
```

### Merge order / stacking

This branch was stacked on step 6 plus cherry-picked VPS commits. **It now also contains the step-6
follow-up branch** (`plan/2026-09-26-cpi-followup`, PR #10), merged with `git merge` — no rebase,
no force-push, no rewritten history. Review/merge in order: #5, #6, #7, #10, then this PR.

The merge of the follow-up branch was resolved by hand, not by auto-merge. The auto-merge of
`origin/main` had silently dropped `remove_closed_cpi_edges` (step-6 fix 5) because that fix lives
on the follow-up branch and not yet on `main`; the resulting `tradehub/scripts/scan.py` was then
audited line by line to confirm the `(engine, engine_version)` pair gate, the CPI cleanup entry and
the new function were all still present alongside the sports wiring.

## Round 3 — fixes from the PR #10 review and the round-2 gaps

Merged `origin/main` first (PR #10 is on main). Merge was clean; the gating audit was re-run on
the merged tree and `501 passed` before any round-3 edit. One commit per numbered fix.

### A1. `remove_closed_cpi_edges` is now one atomic DELETE

- Was: `SELECT market_id,expires_at WHERE engine='cpi_nowcast'`, then a Python loop comparing
  timestamps and issuing **one DELETE per closed market**, every hour. The round trip count grew
  with the number of closed markets, and rows with a null `expires_at` were skipped in Python.
- Now: `DELETE FROM kalshi_edges WHERE engine='cpi_nowcast' AND expires_at <= <now>` — the whole
  predicate is expressible in PostgREST, so the database does the comparison in one statement.
- RED: the two new tests failed with `IndexError: list index out of range` (no delete was issued
  at all, because the old code needed a `SELECT` result).
- GREEN: `pytest tests/test_scan_cpi.py -q` → 12 passed.
- The old fake `Query` overwrote `self.value` on every `.eq`, so it silently kept only the last
  filter and could not express a two-predicate delete. Replaced with `_RecordingQuery`, which
  keeps **every** filter, records the op chain, and supports `.lte`.
- `test_remove_closed_cpi_edges_is_one_atomic_delete` asserts exactly one `delete` call, no
  `select`, and the exact filter dict. `..._sends_a_comparable_expiry_bound` pins that the bound
  is the tz-aware `now.isoformat()`, since PostgREST compares the stored text.

### A2. main()-level tests for the closed-CPI cleanup

- New `tests/test_scan_cpi_closed_cleanup.py`, 3 tests.
- (a) with `cpi_scan_due` False the cleanup still runs — 09:00 ET is not a CPI scan hour, and an
  edge from the 08:05 run for a market closing 08:25 must be gone before 09:00, not at noon.
- (b) when the cleanup raises, the message lands in `failures`, `status` is `partial_failure`, the
  exit code is 1, and the weather/gas/CPI upserts and the other engines' stale-edge cleanups still
  run. A cleanup failure is not allowed to take the scan down.
- GREEN: 3 passed.
- Test-hygiene note: these stub `scan_cpi` as well. Without it the CPI engine ran against the
  `object()` stub client and the failure under test was masked by an unrelated `open_markets`
  `AttributeError`.

### A2b. December 2021 date correction, and the vacuous assertion

- The comments (and the step-6 report) said the December 2021 CPI print landed on **2021-12-10**.
  It did not: the chart dates the actual to the BLS release day **2022-01-12 08:30 ET**, so the
  first print of December 2021 CPI was published in January 2022. Corrected in
  `tests/test_cleveland_fed.py` and in the step-6 report.
- Dropped `assert DEC_2021_REVISION_GAP > 0.1`. It compared `DEC_2021_FIRST_PRINT` and
  `DEC_2021_BLS_REVISED`, two constants defined three lines apart, so it could only fail if
  someone edited a constant — it tested the test, not the data, and gave false assurance that the
  pin could not go stale. The load-bearing check is
  `test_first_print_pin_detects_a_switch_to_revised_values`, which proves the pin *misses* when
  the payload carries the revised value. That test is unchanged and still passes.

### B3. `tsc --noEmit -p tsconfig.app.json` now exits 0

`npx tsc --noEmit` had been reporting success in earlier rounds, but it resolves `tsconfig.json`
rather than the app project, so it was not the check that matters. Run directly, the app project
failed with 4 errors — the test files were never type-checked:

```text
src/lib/sportsEdgeGate.test.ts(46,28): error TS2322: Type 'string' is not assignable to type '"SHADOW" | "PROMOTED"'.
src/lib/sportsEdgeGate.test.ts(47,28): error TS2820: Type '"promoted "' is not assignable to type '"SHADOW" | "PROMOTED"'.
src/lib/sportsEdgeGate.test.ts(48,28): error TS2320: Type '"weird"' is not assignable to type '"SHADOW" | "PROMOTED"'.
src/lib/sportsEdges.test.ts(5,7):   error TS2739: Type '{...}' is missing the following properties from type 'SportsEdge': engine, engine_version, gate_status
```

- `sportsEdges.test.ts`: the shared `base` fixture predated the round-2 gate fields and was
  missing `engine`, `engine_version` and `gate_status`. Added, which is what the type was telling
  us: the fixture no longer described a real API row.
- `sportsEdgeGate.test.ts`: split the conflated case. The narrow `SportsEdge.gate_status` union
  belongs to the *API response type*; `edgeGate` itself takes `EdgeGateInput`, whose
  `gate_status` is `string | null | undefined` — and that is the contract that matters, because
  the column is free text at the boundary. The normalisation cases (`"promoted "`, `"weird"`,
  `""`) now go through `edgeGate` directly on widened input rather than being forced through a
  full `SportsEdge` with a cast. This is stronger than the `as any` alternative: it tests the
  real signature and keeps the `SportsEdge` type honest.
- Added `"typecheck": "tsc --noEmit -p tsconfig.app.json"` to `package.json`, so CI and humans
  run the project that includes `src` rather than the default one.
- Command for the record: `cd market_sentiment_tool && ./node_modules/.bin/tsc --noEmit -p tsconfig.app.json`
  → **exit 0** (also `npm run typecheck`).
- vitest: 6 files / 25 tests passed (the two gate suites gained cases).

### B4. `/api/sports-edges` pages with `.range()` and ranks before it slices

Two real defects, both silent:

- **PostgREST's 1000-row cap.** A single `.execute()` returns at most 1000 rows whatever
  `limit` says. On a larger table `total` was computed from a truncated page, so the endpoint
  would have reported "3 of 1000" against 2,500 real rows and everything past the cap was
  invisible. The same applied to `sports_reviews` and the settled-prediction read — a truncated
  review scan would quietly *deflate* the keep/drop scorecard, which is the number used to decide
  whether to keep the reviewer at all.
- **Ranking after slicing.** `edges.sort(...)` ran on `rows[offset:offset+limit]`, so each
  offset window was ranked independently. A `top_pick` could be stranded on a later page behind
  `filtered` rows while a `filtered` row led page 1.

New `_fetch_all(supa, table, build, cap=...)` pages with `.range(lo, lo+page-1)` until a short
page, and ranking is now applied to **all** matching rows before the slice.

- `sport`, `edge_type` and the not-started test are pushed into the query. The not-started
  filter uses `expires_at` (an indexed column); Python still re-checks `start_utc` from
  `raw_payload` because a malformed one must never be shown. `tier` genuinely cannot be filtered
  by the database, so that one stays in Python — now over a fully-paged read rather than a
  truncated one.
- RED: 8 of 10 new tests failed. The decisive one:
  `AssertionError: total was 999, expected 2500: a single execute() is silently capped at 1000
  rows by PostgREST`. The 999 (rather than 1000) is what surfaced an off-by-one: PostgREST
  `Range: lo-hi` is **inclusive** of `hi`, so `range(lo, lo+page-1)` was yielding `page` rows and
  the loop advanced correctly, but the test fake modelled it as exclusive. The fake now matches
  the server, and the advance is documented at the call site.
- GREEN: `pytest tests/test_sports_api_range_paging.py -q` → 10 passed, plus 24 across the three
  API test files. The fake enforces the 1000-row cap and raises on an unknown column, so a
  regression to a single `.execute()` or a misnamed column fails here rather than in production.
- The round-2 fixtures in `test_sports_api_pagination.py` and `test_sports_scorecard_api.py` had
  no `expires_at` and no `.range()`/`.gte()`; both updated, which is what the type of the change
  required.

## Second review round — fixes 1-7

One commit per numbered fix. RED first in each case, evidence below.

### 1. Reviewer cache did not fail open

`SupabaseReviewStore.cached/calls_since/save` called `.execute()` with no guard, so a Supabase
blip propagated out of `review_candidates` and killed the whole sports scan — contradicting this
module's own contract that "any failure leaves the edge unreviewed and never blocks it".

- RED: 4 of 5 new tests failed (`cached` raised `ConnectionError` through to the caller).
- GREEN: `pytest tests/test_sports_reviewer_failopen.py tests/test_sports_reviewer.py -q` → 21 passed.
- The cache degrades to a **miss** (one extra LLM call is cheaper than losing the scan).
- The budget count deliberately fails **closed** — an unknown count must not become unbounded
  spend. `test_an_unmeasurable_budget_stops_new_llm_calls` proves no reviewer call is made.
- A failed insert no longer discards a verdict already paid for.
- A control test pins `MemoryReviewStore` so the fail-open tests cannot pass for the wrong reason.

### 2. Sports edges were not gated per version and had no badge

`_edge_row` hardcoded `gate_status="SHADOW"` and carried no `engine_version`, so sports edges
could never be promoted and had no key to look up.

- RED: 4 new tests in `tests/test_sports_gate_pair.py` failed; the two `scan.main` sports tests
  also failed because their stub rows had no `engine` (the pair set is built from `row["engine"]`).
- GREEN: `pytest tests/test_sports_gate_pair.py tests/test_sports_scan.py -q` → 16 passed.
- Sports edges now join the `(engine, engine_version)` pair set and go through
  `apply_gate_statuses`; a version with no backtest row fails closed to SHADOW
  (`test_an_unmatched_sports_edge_version_stays_shadow`).
- The API returns `gate_status`, `engine` and `engine_version`; the Sports Edges page renders
  `GateBadge` plus the predictor version. New `sportsEdgeGate.test.ts`, 3 vitest tests.

### 3. Sports edges were never cleaned up

- RED: 2 of 6 new tests failed; the three "must not prune" tests passed from the start.
- GREEN: `pytest tests/test_sports_cleanup.py -q` → 6 passed.
- Cleanup runs only when the sport ran AND its edge write succeeded — a failed upsert must never
  read as "the engine produced nothing". Per-sport engine names, so a silent sport cannot prune
  another sport's rows (`test_a_silent_sport_cannot_prune_another_sport`).
- A structural test asserts the allowlist still contains `sports_nfl`/`sports_cfb`.

### 4. `/api/sports-edges` was unbounded

It selected every SPORTS row, every ok review and every settled sports prediction with no filter
and no limit. With finding 3 unfixed, that table grew all season.

- RED: 7 of 8 new tests failed (`KeyError: 'total'`).
- GREEN: `pytest tests/test_sports_api_pagination.py -q` → 8 passed.
- `sport` and `tier` filters, `limit` (default 100, max 200) and `offset`; `total` is counted
  after filtering and before paging so the UI can say "20 of 240". Bad pagination and unknown
  filter values are 422, not silent clamps. Review/settlement reads are capped.
- Also fixed: a row whose `start_utc` does not parse used to raise and 500 the endpoint.

### 5. Sports scan ignored the deadline; one bad row killed a series

- RED: 5 of 6 new tests failed.
- GREEN: `pytest tests/test_sports_robustness.py -q` → 6 passed.
- `run_sports_for_cron` now takes `deadline` and passes it to `SportsKalshi`; `scan.main` hands
  over the same `SCAN_DEADLINE_SECONDS` budget the other engines get, so sports can no longer
  overrun the hourly timer and overlap the next run.
- `parse_markets_tolerantly` skips rows that do not parse instead of losing the whole series, and
  returns the rejected rows so a broken series cannot look like an empty one.
- `scan_sport` isolates a per-market pricing failure and reports `markets_skipped`.

### 6. Prediction Lab ignored the sports tier

Sports edges render in the Lab with a prominent "Execute Trade" button. A candidate the filter
**rejected** (predictor miscalibrated in that bucket, wide quote, starts too soon) looked
identical to a Top Pick.

- `sportsTierOf` / `isExecutableSportsEdge` in `sportsEdges.ts`; new `sportsTier.test.ts`,
  8 vitest tests covering unknown tiers, null `raw_payload` and non-sports rows.
- The Lab now shows the tier badge, and a `filtered` edge gets "Rejected by candidate filter —
  not tradeable" with its reject reasons instead of the trade button.

### 7. Kevin checklist was stale

Rewritten with the real variable names, the reserved migration range, what is optional versus
required, and the `(engine, engine_version)` warning so a future reader does not "fix" the gate
by keying on the engine alone. See the checklist and handover risks above.

### Incidental fix found while testing

`test_scan_main_includes_sports_when_due` and `test_scan_main_survives_a_sports_crash` called
`scan.main()` with the wall clock. `cpi_nowcast` only runs at 08/12/16 ET, so both tests failed
whenever the suite ran inside one of those hours — they had been passing only because of when
they were executed. Both now stub `cpi_scan_due`.

### Kevin checklist — pending

Reviewed and updated after the second review round; numbering is unchanged, the content is not.

1. Apply `20260416000008_sports_reviews.sql` after migrations `000003`–`000007`. Reserved range for
   this rollout: `000007` step 2b, `000008` step 7b, `000009` step 8. Do not renumber.
2. Add `OPENROUTER_API_KEY` to the VPS stack environment. **Optional**: with no key every
   candidate is written as `unreviewed` and still appears on the board, so the sports scan runs
   correctly before the reviewer is configured. With a key, also confirm the model in
   `tradehub/sports/config.yaml` (`sports_reviewer.model`) is one your OpenRouter account can
   actually route to; the reviewer sends `provider.require_parameters`, so a model that ignores
   `response_format` will return `status=invalid` and every edge will read `unreviewed`.
3. Point the feed at the deployed predictor sites. Optional overrides, per sport:
   `SPORTS_NFL_BASE_URL` / `SPORTS_NFL_SITE_URL` and `SPORTS_CFB_BASE_URL` /
   `SPORTS_CFB_SITE_URL`. Use VPS hostnames after cutover. With no overrides the YAML defaults
   are used, and until step 7a is deployed those return 404 — which the scan already reports as
   `{"feed_error": "404"}` per sport rather than failing.
4. `SPORTS_SCAN_EVERY_RUN=1` forces sports onto every hourly run instead of every third UTC
   hour. Leave unset in production unless you want the extra load.
5. Record one real OpenRouter review and replace the hand-built OK fixture.
6. After ≥100 settled reviewed picks, read `reviewer_scorecard.verdict`; drop the reviewer if it
   says drop. The endpoint pages, so read `total` and page with `limit`/`offset` rather than
   assuming the first page is everything.

### Handover risks

- The live feed is 404 until 7a is deployed; the dry run above is the expected result, not a
  passing scored run. Sports edges stay non-scored until 7a's rebuilt-picks PRs and pre-game
  feed are merged and deployed.
- Do not suppress large predictor-vs-market gaps; the calibration gate blocks them and Kevin's
  rule keeps all edges visible as SHADOW. A losing engine's edges keep their `engine` and are
  tagged `SHADOW`; they are never hidden.
- The promotion gate is keyed on `(engine, engine_version)`, where the sports version is
  `feed:<predictor model_version>`. A new predictor snapshot therefore starts at SHADOW on its
  own, which is intended. Do not "fix" this by keying on the engine alone — that would merge
  the headline/core CPI track records in step 6 and let one version's promotion leak to another.
- Stale-edge cleanup now covers sports, but only after a successful edge write for that sport
  and only for a sport that actually ran. A sport that produced nothing (feed down) is
  deliberately left alone rather than having its rows treated as stale.
- `remove_stale_edges` deletes by `engine`, so the sport engines (`sports_nfl`, `sports_cfb`) are
  in its allowlist. Anything else writing to `kalshi_edges` is out of scope by design.
- CFB spread/total calibration may remain empty because recorded sportsbook lines are mostly null.
- Reviewer budget/fixture follow-ups are in the plan's Kevin checklist and were not executed.
- No Supabase write, LLM call, migration application or deployment was performed.

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

### Final verification (round 3)

```text
Python baseline 391 → final 535 passed
Scoped Ruff F401,F811,F821: All checks passed
Frontend: 7 files / 25 vitest tests passed
tsc --noEmit -p tsconfig.app.json: exit 0
Vite production build: OK
git diff --check: clean
```

Typecheck command of record:
`cd market_sentiment_tool && ./node_modules/.bin/tsc --noEmit -p tsconfig.app.json` (also
`npm run typecheck`, added in B3).

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
- Rank order is `top_pick`, then any other candidate, then the rest; within a tier by `edge_pct`
  descending. Extracted as `_sports_rank`. A `filtered` row is one the candidate filter already
  rejected, so it ranks below every candidate regardless of how large its gap is — a 0.90 edge
  that the filter refused must not lead the board. Pinned by
  `test_top_pick_beats_candidates_which_beat_filtered`, which gives the filtered row nine times
  the edge of the candidates and still asserts it sorts last.

### B7. Kevin checklist: paths, ordering, and the two-places rule

Rewritten, because the previous version would have led to a silently broken deploy.

- **Migration before deploy, stated first.** The scan writes to `sports_reviews` every run and
  the store fails open, so a missing table is indistinguishable from a working one: reviews are
  discarded, nothing caches, the scorecard stays empty, and no error surfaces anywhere. Called
  out in the handover risks too.
- **`/opt/stack/.env` is not enough.** All five variables must ALSO be in the `tradehub`
  service's `environment:` block in `vps-stack/compose.yml`. The scan runs in that container and
  does not inherit `.env` wholesale; only what is listed in `environment:` is visible. The
  failure mode is spelled out — feeds silently fall back to the YAML defaults and 404 until 7a
  is deployed, with `{"nfl": {"feed_error": "404"}}` as the only clue.
- **Reviewer model config path corrected** to `tradehub/config/engines.yaml` under
  `sports_reviewer`. The round-2 checklist said `tradehub/sports/config.yaml`, which does not
  exist; `CONFIG_PATH` is shared with the engine configs.
- Optional-vs-required is now explicit for each variable, and the 1000-row paging note was
  corrected to say the server pages internally so `total` is trustworthy.

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

Rewritten in round 3 with the exact variable names, file paths and ordering. **The two things
that are easy to get wrong are called out first.**

#### Order matters: migration BEFORE the deploy

1. **Apply `20260416000008_sports_reviews.sql` BEFORE deploying the image that contains this
   PR.** The sports scan writes to `sports_reviews` on every run; without the table the
   reviewer store fails open (by design — it will not take the scan down) but every review is
   silently discarded, so nothing is ever cached and the `reviewer_scorecard` stays empty. The
   failure is invisible by construction, which is exactly why the order has to be deliberate.
   Apply it after migrations `000003`–`000007`. Reserved range for this rollout: `000007` step
   2b, `000008` step 7b, `000009` step 8. Do not renumber.
2. Then deploy. Migration first, always.

#### Environment variables — two places, not one

3. Add all five to **`/opt/stack/.env`** on the VPS:

   ```dotenv
   SPORTS_NFL_BASE_URL=https://<nfl-predictor-host>
   SPORTS_NFL_SITE_URL=https://<nfl-predictor-host>
   SPORTS_CFB_BASE_URL=https://<cfb-predictor-host>
   SPORTS_CFB_SITE_URL=https://<cfb-predictor-host>
   OPENROUTER_API_KEY=sk-or-...
   ```

4. **They must ALSO be added to the `tradehub` service's `environment:` block in
   `vps-stack/compose.yml`.** This is the step that is easy to miss: the scan runs in the
   `tradehub` container, which does **not** inherit `/opt/stack/.env` wholesale. Only the
   variables listed in that service's `environment:` are visible to it. Setting them in
   `/opt/stack/.env` alone means the container sees none of them, the feeds fall back to the
   YAML defaults, and — until step 7a is deployed — those defaults 404. The symptom is
   `{"nfl": {"feed_error": "404"}}` in the scan summary with no other error anywhere.

#### Optional vs required

5. `OPENROUTER_API_KEY` is **optional**. With no key every candidate is written as
   `unreviewed` and still appears on the board. With a key, confirm the model configured under
   `sports_reviewer` in **`tradehub/config/engines.yaml`** is one your OpenRouter account can
   actually route to. (The path is `tradehub/config/engines.yaml`, not
   `tradehub/sports/config.yaml` — `CONFIG_PATH` is shared with the engine configs.) The
   reviewer sends `provider.require_parameters`, so a model that ignores `response_format`
   returns `status=invalid` and every edge reads `unreviewed` even with a valid key.
6. The four `SPORTS_*` variables are optional overrides. With none set, the YAML defaults in
   `tradehub/config/engines.yaml` are used.
7. `SPORTS_SCAN_EVERY_RUN=1` forces sports onto every hourly run instead of every third UTC
   hour. Leave unset in production unless you want the extra load.

#### After it is running

8. Record one real OpenRouter review and replace the hand-built OK fixture.
9. After ≥100 settled reviewed picks, read `reviewer_scorecard.verdict`; drop the reviewer if it
   says drop. The endpoint pages past PostgREST's 1000-row cap server-side, so `total` is the
   real count — but read it and page with `limit`/`offset` rather than assuming one page is
   everything.

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
- The reviewer store fails open by design, which means a **missing `sports_reviews` table looks
  exactly like a working one** — reviews are simply discarded and nothing is cached. If the
  scorecard stays empty and no `status=ok` row ever appears, check the migration before
  suspecting the model or the key.
- CFB spread/total calibration may remain empty because recorded sportsbook lines are mostly null.
- Reviewer budget/fixture follow-ups are in the plan's Kevin checklist and were not executed.
- No Supabase write, LLM call, migration application or deployment was performed.

## Round 4 — the review of 9847837

One commit per numbered item, test-first. Each section below records the RED output verbatim and
what the GREEN changed. Nothing here was applied to a database, a container or a deploy.

### 1. Started games are not actually removed

**The defect.** `remove_started_sports_edges` deleted on `expires_at`, and `expires_at` is the
Kalshi `close_time`. For a sports market that is about **two days after kickoff** — the recorded
fixtures close `2026-09-29T17:00Z` for games kicking off `2026-09-27T17:00Z`. So the predicate
`expires_at <= now` was false for every game that had started, and the rows stayed up for days.
`useMarketEdges.ts` and `useSupabaseData.ts` read `kalshi_edges` directly, so they were on the
board the whole time. The docstring claimed "for a sports market [expires_at] is the start", which
was simply wrong.

**RED** — `pytest tests/test_sports_started_games.py -q`:

```
9 failed, 1 passed in 0.66s
FAILED test_a_started_game_produces_no_edges_or_predictions
FAILED test_started_games_are_reported_not_silently_dropped
FAILED test_a_game_that_has_not_started_yet_is_not_skipped
FAILED test_started_rows_are_deleted_on_start_utc_not_expires_at
FAILED test_one_failing_sport_delete_is_isolated_and_reported
FAILED test_there_is_no_errors_twin_of_the_started_cleanup
FAILED test_main_calls_the_tested_started_cleanup_and_reports_its_failures
FAILED test_the_migration_adds_an_indexed_filterable_start_utc
FAILED test_the_edge_writer_persists_start_utc_as_a_column
E   KeyError: 'start_utc'
```

(the one that passed is the fixture-reproduction check: it only asserts facts about the recorded
feed, and the two-day gap is still there.)

**GREEN** — 545 passed (was 535).

- `kalshi_edges.start_utc timestamptz` + `kalshi_edges_sports_start_idx (engine, start_utc)` in
  migration `20260416000008`, which is still unapplied, so it is edited rather than renumbered.
- The backfill matters and is easy to miss: rows written before the column existed have the start
  inside `raw_payload`, and a NULL `start_utc` matches **no** `<= now` predicate, so without the
  `UPDATE ... FROM raw_payload->>'start_utc'` those started games would be kept forever. The
  `~ '^\d{4}-\d{2}-\d{2}[T ]'` guard means a malformed value is skipped instead of failing the
  migration.
- `upsert_opportunities` now writes `start_utc` as a top-level column. It writes
  `"start_utc": op.get("start_utc")` for every engine, so weather/gas/CPI rows get a NULL there;
  the delete is engine-scoped, so that is inert for them.
- `scan_sport` skips a matched game whose `start_utc <= now` — no edge, no prediction, and
  `games_started` in the report so the skip is visible rather than looking like an empty sport.
  The boundary is pinned both ways: exactly at kickoff counts as started, one second earlier does
  not.
- The `_errors` twin is gone. `remove_started_sports_edges` is the one function: it isolates a
  failure per sport, returns the error strings, and `scan.main` puts them in `failures` (so the
  exit code is 1). `test_main_calls_the_tested_started_cleanup_and_reports_its_failures` fails if
  main ever grows a second copy.

**Worth repeating:** two independent writers of the same idea is how this survived a review.
`remove_started_sports_edges_errors` was a line-for-line copy of `remove_started_sports_edges`
with the `try` added, and main called the copy, so the tested function was not the one running.

### 2. The deadline only covered Kalshi, and only before the review loop

Round 3 threaded `SCAN_DEADLINE_SECONDS` into `SportsKalshi` and checked `should_review` **once**,
before `review_candidates`. That left three holes:

- the check was not repeated **per call**, so a 40-candidate list that started inside the margin
  walked straight past it;
- each OpenRouter call used the reviewer's configured timeout, not the time actually left, so one
  slow call could sit past the deadline — once per candidate;
- `fetch_feed` had its own 60s timeout and an **unconditional** retry: up to 122 seconds of
  predictor call inside a 15-minute scan that also has to serve weather, gas and CPI.

**RED** — the new module did not exist, so the first failure was at import:

```
ImportError while importing test module 'tests/test_sports_review_deadline.py'
E   ImportError: cannot import name 'deadline' from 'tradehub.sports'
```

**GREEN** — 563 passed (was 545); `tests/test_sports_review_deadline.py` is 18 tests.

- `tradehub/sports/deadline.py` is the single definition of the rule: the 60s margin,
  `remaining_seconds`, `should_review` and `clamp_timeout`. The orchestrator, the feed client and
  the reviewer all import it, so a second copy of the margin cannot drift from the first — which
  is exactly how the one-shot check survived review.
- `_clock` is a module global rather than a direct `time.monotonic()` call, so the tests drive a
  real clock through the real predicate instead of monkeypatching the stdlib `time` module out
  from under everything else in the process.
- `review_candidates(..., deadline=...)` re-checks `should_review` **before every call**. Skipped
  requests come back as `skipped_deadline`, which is deliberately *not* written to
  `sports_reviews`: that table is append-only with a `status IN ('ok','invalid','error')` CHECK,
  and a skip logged there would both fail the constraint and corrupt the exact daily budget count.
  Cache hits are still applied with the budget gone — no API call, and that verdict was paid for.
- `OpenRouterReviewer(..., deadline=...)` clamps each call's timeout to the remaining time, with a
  1s floor so an abandoned request never gets a zero timeout. A configured 30s timeout still wins
  when there is time, and a reviewer built without a deadline behaves exactly as before.
- `fetch_feed(..., deadline=...)` clamps each attempt and skips the retry when what is left cannot
  cover one more attempt (`left < per_attempt + RETRY_PAUSE_SECONDS`). It raises
  `FeedUnavailable` without issuing a request when the budget is already gone, so a sport skipped
  for time is reported like any other feed error rather than looking like a cold predictor.

**Worth repeating:** a deadline check that is evaluated once is not a deadline. The Kalshi client
was genuinely bounded, the two HTTP paths around it were not, and the test suite could not see it
because the fakes never spent time. The mid-list test now advances a fake clock 10s per reviewer
call, which is the only way the "stops part-way through" claim can be checked.

### 3. Paged reads had no ORDER BY

`_fetch_all` paged with `.range()` and no `.order()`. PostgREST without ORDER BY returns rows in
whatever order the query plan produces, and that order is **not guaranteed to be the same between
two requests** — so `.range(0,999)` followed by `.range(1000,1999)` can repeat a row and skip
another. On this endpoint that means a `total` that does not match the sum of its pages, and a
reviewer keep/drop scorecard computed over a set with duplicates in it.

**RED** — the fake in `tests/test_sports_api_range_paging.py` now raises on any `.range()` that was
not preceded by an `.order()`, which turned 11 previously-passing tests red plus the 3 new ones:

```
AssertionError: kalshi_edges was paged with .range() and no .order(): the pages are not
guaranteed to line up (['select', 'eq', 'gte:expires_at', 'range:0,999'])
14 failed
```

**GREEN** — 566 passed (was 563). `_fetch_all` orders by `id`, the only column that is unique and
immutable on all three tables read here (`kalshi_edges`, `sports_reviews`, `predictions`), so it
is the only safe tiebreak; a non-unique column can repeat a row across a page boundary.

The new boundary test is the one the old suite could not see: **exactly** 1000 rows is one full
page, so the loop must ask for a second page and get nothing. It asserts both round trips
(`range:0,999` then `range:1000,1999`) and `total == 1000`, so a `<` vs `<=` slip in the paging
loop cannot hide.

**Worth repeating:** the fake, not the assertion, is what makes this class of bug testable. A fake
that returns rows in insertion order and ignores `.order()` will happily pass a test that claims
the pages line up.

### 4a. A feed 404 was invisible in the logs

A 404 from a predictor is the **expected** state until 7a's feed is deployed, so it correctly
stays out of `failures` and the exit code stays 0. But it was also completely silent: the only
trace was `"feed_error": "404"` inside the JSON run summary, so `journalctl -u tradehub-scan`
showed nothing and a sport that produced no edges had to be explained by hand.

**RED**

```
AssertionError: a 404 predictor produced no log record at all
assert []
1 failed, 7 passed
```

**GREEN** — 568 passed. One `log.warning` with the sport, the URL and the reason, placed where the
feed error is turned into a report entry. It is still not a failure: `test_a_feed_404_still_does_
not_fail_the_scan` runs the real `scan.main` and asserts exit code 0 and an empty `failures`
alongside the log line, so this cannot quietly become a red timer either way.

### 4b. A failed series pruned that series' rows

This is the one that could delete live data. `prune_sports_if_healthy` prunes a sport when its
feed fetch and edge write both succeeded, but it never knew whether **every series** fetched. If
`KXNFLGAME` (the winner series) returned 500 while spread and total were fine, the produced set
held only spread and total market_ids — and `remove_stale_edges` deletes every row for the engine
whose market_id is absent from that set. So one failing series would delete **every winner row**
for that engine, and it would look exactly like a healthy cleanup.

**RED** — 4 of 6 new tests failed:

```
AssertionError: a sport with a failed series pruned the winner rows
AssertionError: a state with no series verdict pruned anyway
AssertionError: {'nfl': {'feed_ok': True, 'edges': []}}   # no series_ok at all
4 failed, 10 passed
```

**GREEN** — 573 passed.

- `run_sports_scan` now records `series_ok` per sport, and `prune_sports_if_healthy` requires all
  three verdicts: the feed fetch, the edge write and every series.
- `series_ok` is **required, not defaulted to True**. A caller that does not state that every
  series was fetched gets no pruning. Rows that go stale in that state are cleaned up on the next
  healthy run, whereas deleting a market type is not recoverable. That choice is pinned by
  `test_pruning_requires_an_explicit_series_ok`, and it is why four earlier tests had to say
  `series_ok: True` rather than the fix being invisible to them.
- Per-series pruning was considered and rejected: `remove_stale_edges` deletes by engine and
  market_id, and the series lives inside `raw_payload` with no column to filter on, so the honest
  answer is to skip the sport's prune and log a warning saying which engine and why.

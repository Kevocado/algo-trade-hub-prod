# Step 8 — `labor_nowcast` + Jobs Scorecard: evidence report

Plan: [`2026-09-25-labor-nowcast-jobs-scorecard.md`](../plans/2026-09-25-labor-nowcast-jobs-scorecard.md).
Branch: `plan/2026-09-25-labor-nowcast-jobs-scorecard`.

**Suggest-only. Nothing places orders, no migration was applied, no deploy was made, no PR was
merged, and the only network used was the public Kalshi API and keyless ALFRED.**

## Where the branch started, and what the merge changed

The branch predated four merges. `git merge origin/main` (merge `e0fa925`, never a rebase) was
**clean with zero file overlap** — `comm -12` over the two changed-file sets came back empty — so
no manual resolution was needed. That is worth stating explicitly: step 7b's merge silently dropped
`remove_closed_cpi_edges`, and the reason is that both sides edited `tradehub/scripts/scan.py`.
This branch's own commits touch none of the files step 6/7b rewrote.

Baseline after the merge: **606 passed**, which is main's 606 (573 from step 7b's merge plus
PR #11) with this branch's Tasks 0–4 (33 tests) folded in.

### Task 0's prerequisite check, re-run after the merge

| Check | Result |
|---|---|
| `def event_month` in `tradehub/markets.py` | **present** (line 59, from step 6). So Task 0 Step 3 was skipped and only the test was added — which is exactly what commit `6008bad` contains. |
| `tradehub/data/alfred_vintages.py` / `alfredgraph` | **this branch's own Task 1 module**, not a step-6 leftover. Step 6 dropped ALFRED, as the plan predicted, so there is no interface clash to reconcile. |
| `cpi_preds` in `scan.py` | **absent**, but for a stronger reason than the plan anticipated: `main()` has been restructured twice since (step 6 then step 7b). See "Deviations" below. |
| `refresh_track_record(supa, engine, cadence, simulated_pnl_after_fees)` | still no `engine_version` **argument**; it derives versions from the settled rows' `engine_version`. Unchanged by this plan. |
| Migrations | `000008` taken (step 7b), **`000009` free** — used as the plan specifies, no renumbering. |
| Full suite | all green before any edit. |

## Tasks 0–4 — already on the branch before this session

`6008bad` (event_month), `6639c3c` (keyless ALFRED multi-vintage fetcher), `9441840` (strike
geometry, first prints, estimate paths), `7adf2ce` (point-in-time features + ridge nowcast),
`c9de3c0` (Kalshi ladders, Brier, CRPS). Their RED/GREEN evidence is in the plan's "Validation
already done" section and is not repeated here.

One fix was needed before anything else: scoped Ruff flagged `F401 tradehub.markets.prob_in_interval
imported but unused` in `tradehub/engines/ladder.py`, left over from Task 4. It was genuinely
unused — `normal_ladder` has a comment explaining why it deliberately does **not** use it (the
`1e-4` floor is for tradable YES probabilities, not an unbounded survival curve). Removed in
`97b4f80`; the comment explaining the decision stays.

## The three step-7b review follow-ups (`bbac0e6`)

Folded in here, as the round-4 instruction asked:

1. `run_sports_scan`'s `fetch` annotation is now `Callable[..., Feed]` — the scan passes
   `deadline=` and the old signature said it did not.
2. `should_review` is `>=` the 60s margin, not `>`. The margin is a floor on what one call may
   consume, so exactly 60s left was skipping a call and the edge silently read `unreviewed`. Two
   new tests pin the boundary, and the mid-list test now expects 4 calls down to the margin rather
   than 3.
3. `upsert_opportunities` sends `start_utc` **only when the engine set it**. It is the one writer
   for every engine and PostgREST rejects a payload containing a column the table does not have, so
   always sending it made a missing migration break weather and gas too, not just sports. Omitting
   the key also leaves an existing row's value alone on conflict instead of nulling it. Three
   tests, including one whose fake rejects unknown columns the way PostgREST does.

## Task 5 — labor inputs loader + walk-forward nowcasts (`5e75c5b`)

`tradehub/data/labor_inputs.py`, `tests/labor_fakes.py`, `tests/test_labor_inputs.py`, exactly the
plan's code.

```
RED:   ModuleNotFoundError: No module named 'tradehub.data.labor_inputs'
       ERROR tests/test_labor_inputs.py
       !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
GREEN: 5 passed in 0.12s
```

`payroll_nowcasts` fits each target month only on months strictly before it
(`n_train == 41` for a 2013-06 target, asserted), and the nowcast beats the naive 3-month average
because the synthetic claims series carries the surprise.

## Task 6 — the scan (`0fa6f51`)

**This is the task where the plan no longer applied, and the handoff contract's "make the change by
hand so the task's Intent holds" clause was used.** The plan appends labor to one
`record_predictions` / `upsert_opportunities` pair. On current `main`, `scan.main`:

- runs every engine through `run_engine`, which isolates failures, records per-engine `errors`,
  `ran` and `complete`;
- looks the promotion gate up **once**, per `(engine, engine_version)` pair, across all produced
  edges, then applies it to each engine's rows;
- writes predictions and edges per engine with its own `ok`/`failed` status;
- cleans up stale edges per engine behind a **"ran AND wrote ok AND complete"** guard;
- deletes closed CPI markets on every scan;
- runs **sports last**, gated and written separately.

So labor is wired in as a **peer of `cpi_nowcast`**, not appended to a shared write. Concretely:
`labor_scan_due` gates it, `run_labor_step` returns `skipped` / `ok` / `error: ...`, its outcome is
registered in `engine_states` with the same shape as every other engine (a failed step sets
`complete=False`, so it can never prune), it joins `all_edges` for the shared gate lookup and
`apply_gate_statuses`, it gets its own row in both write loops, and `labor_nowcast` is added to
`remove_stale_edges`'s allowlist — which the plan does not mention, and without which the cleanup
call is a silent no-op and stale payroll edges stay up for ever.

`run_labor_step` logs the traceback **at the point it catches** the exception, so the status string
that reaches `main()` does not cost the run its cause. `test_a_labor_failure_is_logged_with_a_traceback`
fails if that moves.

```
RED:   14 failed
       FAILED test_scan_labor_predicts_only_months_that_have_ended
       FAILED test_repo_config_has_labor_nowcast - KeyError
       FAILED test_main_isolates_a_labor_failure - AttributeError
       FAILED test_labor_is_in_the_stale_edge_allowlist
GREEN: 14 passed in 0.56s
```

The main()-level tests mirror the CPI ones, as the reviewer asked: isolation (a labor failure costs
no other engine's write, exit code 1, summary status), gating (labor's pair reaches the lookup, an
unmatched `labor-v2` fails closed to `SHADOW` instead of inheriting `labor-v1`'s promotion),
cleanup (only on a due hour, and never after a failed write), and Kevin's decision that every edge
carries `engine` + `engine_version` and is tagged `SHADOW` when the gate says nothing.

One deviation inside `scan_labor`: each market's pricing is wrapped in its own `try`, matching what
step 6 did for CPI after a review found that one unpriceable strike aborted the engine. The
plan's loop had no guard.

## Task 7 — point-in-time backtest CLI (`fb949e9`)

```
RED:   ImportError: cannot import name 'ThrottledGetJson' from 'tradehub.backtest.http'
GREEN: 26 passed in 0.57s   (with tests/test_backtest_kalshi_history.py)
```

`ThrottledGetJson` uses the module's existing `REQUEST_TIMEOUT_SECONDS` rather than a literal `30`.
`tradehub/backtest/http.py` already imported `time`, so only `Callable` was added to its typing
import.

## Task 8 — `jobs_scorecard` table + row builder (`6f3f67c`)

```
RED:   ModuleNotFoundError: No module named 'tradehub.jobs_scorecard'
GREEN: 5 passed in 0.09s
```

Migration `20260416000009_jobs_scorecard.sql`, as the plan numbers it. PK `(series,
reference_month)`, owner-read-only RLS with **no** client write policy (the builder writes with the
service role), and `NOWHERE` an unbounded column list: 28 columns, all nullable except the two key
columns and `n_strikes`, so the builder can insert a row before the first print exists and fill the
scores on a later run (that is the `scorecard_row` early-return path, tested).

## Task 9 — `build_jobs_scorecard` CLI (`e1b4a65`)

```
RED:   ModuleNotFoundError: No module named 'tradehub.scripts.build_jobs_scorecard'
GREEN: 3 passed in 0.58s
```

## Task 10 — `GET /api/jobs-scorecard` (`e48f5e8`)

```
RED:   2 failed  (404 != 200, 404 != 503)
GREEN: 23 passed in 2.07s  (with tests/test_kalshi_edge_system.py)
```

**Second place the plan no longer applied.** It says to insert the route "directly above
`# ── Dev entrypoint`". On current `main` that line sits **after** `mount_frontend(app,
FRONTEND_DIST)`, and `mount_frontend` does `app.mount("/", SPAStaticFiles(...), name="frontend")` —
a catch-all. A route registered after it is shadowed, and the endpoint would answer with the app
shell instead of JSON. The route is registered **before** the mount instead, and
`test_the_route_is_registered_before_the_spa_catch_all` pins the order (it skips when `dist/` is
absent, because the hazard only exists when the SPA is built).

No `limit` on the read, deliberately: the table holds one row per `(series, reference_month)`, so
it is two rows per month of history rather than a growing event log.

## Task 11 — the `/jobs` page (`4556b71`)

```
RED:   FAIL src/lib/jobsScorecard.test.ts
       Error: Failed to resolve import "@/lib/jobsScorecard" from "src/lib/jobsScorecard.test.ts"
GREEN: Test Files  7 passed (7)
       Tests  29 passed (29)
       typecheck exit 0
       ✓ built in 4.52s
```

`node_modules` was missing in this worktree, so `npm install` ran once (as the plan allows);
`market_sentiment_tool/package-lock.json` was restored with `git checkout --` before committing and
`git status` is clean.

Third place the plan's exact text no longer matched: the lucide import in `App.tsx` is
`{..., LineChart, Trophy}` (step 7b added `Trophy` for the Sports link), not the plan's
`{..., LineChart}`. The plan's replacement would have dropped the Sports icon's import. The nav link
and the `/jobs` route were added alongside the existing `/sports` entries.

## Task 12 — verification and live runs

### Full suite, lint, frontend

```
pytest              644 passed in 12.55s
ruff                All checks passed!   (F401,F811,F821 over tradehub tests shared)
tsc                 exit 0              (npm run typecheck: tsc --noEmit -p tsconfig.app.json)
vitest              7 files / 29 tests passed
vite build          ✓ built in 4.52s
git status          clean
git diff --check    clean
```

`SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` for every pytest run. The suite went 606
(after the merge) → 644 across Tasks 5–11.

### A real bug the live run caught, which 644 green tests could not

`python -m tradehub.scripts.backtest_labor --start 2023-03 --end 2026-08` died on its first call:

```
File "tradehub/scripts/backtest_labor.py", line 125, in main
    all_raws = client.merged_settled_markets(PAYROLL_SERIES)
AttributeError: 'KalshiHistoryClient' object has no attribute 'merged_settled_markets'
```

The plan names `merged_settled_markets`; the real method is `settled_markets(series_ticker)`, which
**already** merges the `/historical/markets` and `/markets?status=settled` endpoints and dedupes by
ticker — so the intent was right and only the name was stale. The same call was in
`build_jobs_scorecard.py`.

The unit tests never construct a `KalshiHistoryClient`, which is why 644 tests were green while the
first line of the CLI could not run. Fixed to `settled_markets` in both scripts, plus a structural
guard that is the cheap answer to that whole class of drift:

```python
def test_the_clis_only_call_methods_the_real_client_has():
    for module in (backtest_labor, build_jobs_scorecard):
        for name in set(re.findall(r"\bclient\.(\w+)\(", inspect.getsource(module))):
            assert hasattr(KalshiHistoryClient, name), ...
```

While fixing it I also replaced `client._paginate("/markets", ...)` in the scorecard builder with a
public `KalshiHistoryClient.open_markets(series_ticker)`. A script reaching into a private method
for the open tail of a ladder is the same smell as a renamed method, and the public seam is now
tested.

### Live scan smoke (public Kalshi, no ALFRED needed)

```
$ python -c "scan_labor(KalshiLive(), now, load_engine_config('labor_nowcast'))"
2026-09-26T18:54:23.718152+00:00 0 predictions 0 edges
```

The expected result: on 2026-09-26 no open payroll event's reference month has ended, so the engine
returns nothing **without touching ALFRED**. Between a month ending and its release
(2026-09-30 → 2026-10-02) it returns one prediction per open strike of that month.

### Live Kalshi leg of the backtest (the half that does not need ALFRED)

```
settled payroll markets: 383
events: 42   2023-03-01 -> 2026-08-01
settled with a numeric first print: 376
in 2023+: 376
candles for KXPAYROLLS-26JUL-T0 = 43
```

This matches the plan's 2026-09-25 validation (383 settled markets in 42 events; 370 *quoted*
contracts after the unquoted ones are dropped). So the market, event and candle side is confirmed
live against the current API; the only thing the full run still needs is ALFRED.

### The full backtest and the scorecard dry run could not be reproduced here: ALFRED

```
RuntimeError: ALFRED request failed after retries: HTTPSConnectionPool(host='alfred.stlouisfed.org',
port=443): Read timed out. (read timeout=60)

$ curl -A 'Mozilla/5.0' 'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-09-24'
curl: (92) HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR (err 2)     # three attempts
curl --http1.1 ...: curl: (56) Recv failure: Operation timed out
```

DNS resolves (`research.stlouisfed.org.edgekey.net` → Akamai), and the same URL through a
different egress returns `application/csv`, so the data and the service are fine — the plain
`requests`/`curl` path from this machine is blocked. The plan documented exactly this on
2026-09-25 and said to record it and retry later rather than work around it, so nothing was
worked around: no proxy, no vendored CSV, no change to the fetcher.

**Therefore these plan figures are the prior evidence and were NOT reproduced in this session:**

| Run | Plan's 2026-09-25 figure |
|---|---|
| `--start 2023-03 --end 2026-08` | 370 decisions, 41 months, Brier ours 0.1792 vs Kalshi 0.1659, gate SHADOW, MAE 68.5k both sides |
| `--features all` | Brier 0.1833, MAE 75.2k — worse, so `labor-v1` ships core features only |
| `--mode maker` | 194 fills, +$19.50 |

`build_jobs_scorecard --since 2023-01 --dry-run` fails the same way (86 rows, 42 payroll / 44 U3,
85 with a first print, on the plan's run). Its Kalshi half is the code path verified above.

**This is the one open item that needs a machine that can reach ALFRED** — see Kevin's follow-up 2.

## Kevin's follow-ups (do not edit `vps-stack` or Supabase from this branch)

1. **Apply migration `20260416000009_jobs_scorecard.sql`** before deploying this branch, then run
   once, with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` set:
   `python -m tradehub.scripts.build_jobs_scorecard --since 2023-01`.
   Only this PR needs it. Nothing else in this branch reads or writes `jobs_scorecard`, so unlike
   step 7b's migration there is no cross-engine blast radius: if the table is missing, the War Room
   page shows its error card and the builder fails loudly. The `/api/jobs-scorecard` read is
   service-role, so the owner-only RLS does not need relaxing.
   `--record` on the backtest is Kevin's too (it writes a `backtest_runs` row).
2. **ALFRED from the VPS — still unverified, and now the blocking item.** On the VPS:
   `curl -s -A 'Mozilla/5.0' 'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-09-24' | head -2`
   Expect `observation_date,ICSA_20260924`. **If the VPS cannot reach ALFRED, the labor scan will
   report `labor_nowcast: {"status": "error: RuntimeError: ALFRED request failed after retries"}`
   three times a day and write nothing** — isolated, so weather, gas, CPI and sports are unaffected
   (that is what the Task 6 tests pin), but the engine will be dead until egress is fixed. This is
   the single thing standing between this branch and a working scan.
3. **Vintage cache volume.** The job containers are throwaway (`docker compose run --rm`), so mount
   a host dir (e.g. `/opt/stack/data/alfred`) into the `tradehub` service and set
   `TRADEHUB_ALFRED_CACHE` to it. Without it every labor scan re-downloads about 20 small CSVs, three
   times a day. Past vintages never change, so the cache never needs invalidating.
4. **Scorecard timer** in `vps-stack`: a `tradehub-jobs-scorecard.timer` running
   `python -m tradehub.scripts.build_jobs_scorecard --since 2023-01` weekly on Fridays at 10:15
   America/New_York (after the 08:30 release). The upsert is keyed on `(series, reference_month)`,
   so re-running is idempotent. Needs a `jobs-scorecard` case in `bin/tradehub-job`.
5. **Scan timer: nothing to change.** `scan_labor` runs inside the existing hourly `scan` at 07, 12
   and 17 ET, via the same `scan` job name.
6. **No new environment variable** is required by this branch. `TRADEHUB_ALFRED_CACHE` is optional
   (it defaults to `~/.cache/tradehub/alfred`); there is no key of any kind — ALFRED's
   `alfredgraph.csv` is keyless by design.

## Deviations from the plan, and why

| # | Plan said | Did | Why |
|---|---|---|---|
| 1 | Task 6: append labor to the shared prediction/edge write | Wired labor as a peer of `cpi_nowcast`: shared pair gate, own write status, own cleanup guard, allowlist entry | `scan.main` was restructured by step 6 and 7b after the plan was written. The reviewer's step-8 instructions require exactly this shape. |
| 2 | Task 6: `edge_row(market, suggestion, "MACRO")` | `edge_row(..., "MACRO", engine="labor_nowcast", engine_version=LABOR_ENGINE_VERSION, updated_at=now)` | `edge_row` has required `engine`/`engine_version` since step 6, and they are what the (engine, engine_version) gate keys on. |
| 3 | Task 6: `run_labor_step` status only in the summary | Same, plus registration in `engine_states` so the write/cleanup guards see it | Otherwise labor would be the one engine that prunes without the "ran AND wrote ok" guard. |
| 4 | Task 10: insert above the dev entrypoint | Inserted above `mount_frontend` | The dev entrypoint is after a catch-all `app.mount("/")`; the route would be shadowed. |
| 5 | Task 7/9: `client.merged_settled_markets(...)` | `client.settled_markets(...)` | The name does not exist; the existing method already does the merge and dedupe. Caught by the live run, guarded by a test. |
| 6 | Task 9: `client._paginate("/markets", ...)` | `client.open_markets(series)`, new public method | A script should not reach into a private method. |
| 7 | Task 11: lucide import without `Trophy` | Kept `Trophy`, added `Briefcase` | Step 7b added the Sports link; the plan's exact replacement would have broken its icon. |
| 8 | Task 6 loop had no per-market guard | Added one | Step 6 got the same guard after a review finding: one unpriceable strike must not abort the engine. |
| 9 | Task 12 Steps 2–3: run the live backtest and scorecard | Recorded why they could not run; verified the Kalshi half live instead | ALFRED is unreachable from this machine, and the plan says to record that rather than work around it. |

Nothing was skipped. Every task's Intent holds in the delivered code, and where the plan's code
could not apply, the change was made by hand and is listed above.

## Round 1 — the review of 8e3e025

One commit per item, test-first. The RED outputs below are verbatim.

| # | Commit | What |
|---|---|---|
| 1 | `166d2f1` | cache ALFRED vintages at full precision |
| 2 | `12a6924` | the weekly series at each month's own vintage; `--record` refuses a non-PIT PROMOTED run |
| 3 | `e645dc1` | labor runs after the engine writes; the ALFRED fetcher is deadline-bounded and retries 5xx |
| 4 | `32ac75a` + `b466346` | the /jobs page badges the engine's gate status; one shared gate lookup |
| 5 | `1d70a01` | a feature gap does not prune; closed labor markets are deleted every scan |
| — | `1c52785` | a test that was opening a real socket |

### 1. Cache precision

`{v:g}` is **six** significant digits, so CCSA 1,897,123 was cached as `1.897e+06` and read back
as 1897000.0. A cached run and a fresh run therefore produced different nowcasts, and the only
symptom was that two runs disagreed.

```
RED:
E   AssertionError: assert {datetime.date(2026, 8, 31): {date(2026, 8, 1): 1897123.0, ...}}
E                          != {datetime.date(2026, 8, 31): {date(2026, 8, 1): 1897120.0, ...}}
1 failed, 1 passed
GREEN: 6 passed
```

`repr(float)` round-trips exactly. The second test is the property that matters: `fetch_vintages`
is a pure function of the requested vintage dates, warm cache or not.

**Kevin: any cache already written is wrong permanently** — past vintages never change, so
`:g`-written files never self-heal. Delete `TRADEHUB_ALFRED_CACHE` (or the volume behind it) once
after this deploys.

### 2. Point-in-time leak — the one that mattered

`load_labor_inputs` handed ICSA/CCSA/JTSHIL/JTSJOL over from **one latest vintage**, so every
historical month was described with claims and JOLTS data revised months or years later.
`check_no_lookahead` could not see it: the `Observation` timestamps are the weeks' nominal
publication dates either way, so the leakage guard passed on inputs that were not point-in-time.
Every historical backtest month was fitted on knowledge it did not have (spec §5a).

```
RED: 2 failed
  E   AssertionError: January's claims change used a later vintage's revision
  E   AssertionError: 'icsa' still takes a flat series: Mapping[date, float]
GREEN: 654 passed
```

- The four weekly parameters are now `Mapping[date, Vintage]`, the same shape PAYEMS and ADP
  already had. **The type is the fix**: a flat `{week: value}` map *is* the leak, and a signature
  that cannot express it stops it being reintroduced. A test asserts the annotations.
- A month whose own vintage is missing returns `None` — a feature gap the caller must handle —
  rather than falling back on today's data.
- `point_in_time_ok(inputs, months)` and `record_guard(row, inputs, months)`: `--record` refuses
  to store a **PROMOTED** run that fails it, so a leak cannot become a promotion by accident.
  SHADOW runs are untouched, because SHADOW is this engine's expected outcome and blocking it
  would make `--record` useless.
- Two existing tests asserted the leaky contract and were updated rather than worked around:
  `test_load_labor_inputs_requests_point_in_time_vintages` asserted the weekly series were fetched
  **once**, and `test_labor_features_are_point_in_time` passed flat maps. Both now assert the
  correct thing — the first is now a much stronger test than its name suggested.

**Cost, corrected:** the plan's follow-up 3 said "about 20 small CSVs" per scan. With the weekly
series at every month end it is ~85 (5 series × 17 batches of 12), once, if
`TRADEHUB_ALFRED_CACHE` is a mounted volume. Without the volume it is that, three times a day.

### 3. Deadline

```
RED: 8 failed
  E   AssertionError: a retry was started with less time than one attempt needs
  E   NameError: name 'text' is not defined        (a bug in my own new test fake)
GREEN: 663 passed
```

- The labor step now runs **after** the weather/gas/CPI writes and before sports, with its own
  gate lookup, write status and cleanup — the shape sports already had. An ALFRED hang can no
  longer delay another engine's writes. `_ensure_scan_deadline` runs first, and an exhausted
  budget reports `skipped: scan deadline reached before the labor step` rather than starting work
  it cannot finish.
- `default_get_text`: the per-request timeout is clamped to the time remaining, and a retry only
  starts when `remaining >= timeout + backoff`. The old flat 60s × 4 unconditional attempts was up
  to ~246s of predictor call inside a 15-minute scan.
- HTTP 5xx is retried too. FRED's edge returns 503 under load, and retrying only transport errors
  turned a transient 503 into a dead engine for the whole run.
- The deadline travels `scan → scan_labor → load_labor_inputs → fetch_vintages → the HTTP
  request`. `remaining_seconds` grew an optional `clock` so a caller that owns its clock does not
  have to reach into another module's global — the first version of this took a `clock` argument
  and silently ignored it, which the fake-clock test caught immediately.

**A pre-existing crash this exposed:** with no Supabase client, `main()` raised
`UnboundLocalError` on `sports_summary` instead of reporting the failure — the one situation where
a clear report matters most. `test_main_reports_rather_than_crashes_without_a_supabase_client`
pins it.

### 4. Gate status on `/jobs`

The scorecard is built out of band, so `gate_status` is not on the row and has to be looked up at
read time, per `(engine, engine_version)`, defaulting to SHADOW. The unemployment panel maps to no
engine on purpose: `u3-naive-v0` is a naive baseline, and it must not borrow `labor_nowcast`'s
promotion (there is a test for exactly that). A lookup error fails closed to SHADOW rather than
taking the page down when the rows are readable.

The lookup moved to `tradehub/gate_status.py` so the scan and the API share one implementation —
two copies is how the War Room and the scan would start disagreeing about whether an edge is
tradable. A test asserts `scan.latest_gate_statuses is latest_gate_statuses`.

```
RED: 4 failed (KeyError 'gate_status')
GREEN: 669 passed; vitest 7 files / 32 tests; tsc exit 0
```

### 5. Pruning safety

`scan_labor` returned only `(predictions, edges)`, so a month whose markets existed but produced
no nowcast — a missing ALFRED vintage, a claims gap — looked exactly like an engine that produced
nothing, and the "ran AND wrote ok" cleanup guard then deleted its live edges.

- `scan_labor` / `run_labor_step` now return a 4-tuple carrying `months_without_nowcast`. A gap
  marks the run **incomplete**, so it does not prune, and the months are listed in the summary:
  silently keeping rows is recoverable, silently deleting them is not.
- `remove_closed_labor_edges`: one atomic `DELETE ... WHERE engine='labor_nowcast' AND
  expires_at <= now`, engine-scoped, like `remove_closed_cpi_edges`, and run on **every** scan —
  a monthly ladder closes on its own schedule, not on the engine's 07/12/17 ET cadence. Its
  failure is reported and not fatal.
- Six new tests: a gap does not prune, a healthy run still prunes, the gap is visible in the
  summary, the delete is engine-scoped, it runs on a non-due hour, and its failure is reported.
- The new cleanup needed stubbing in ~20 pre-existing main()-level test doubles across six files,
  exactly as those tests already stubbed the CPI one. That is the honest cost of adding an
  unconditional DB call, and every one of them was an incomplete double rather than a behaviour to
  preserve.

### Minor: a test that opened a real socket

`test_sports_scan_passes_the_deadline_into_the_client` patched `sports_scan.fetch_feed`, which did
nothing: `run_sports_scan`'s `fetch` default binds `fetch_feed` at definition time, so the real one
ran and made a real HTTPS request to `nfl-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io`.
The test still passed, because a 404 is handled as a feed error.

Two things were stacked there. The `_feed_stub` it meant to use was itself broken — `Feed` was
constructed without `generated_at` or `calibration` — and had **never been called**. Both are
fixed, `fetch=` is now passed explicitly, the test asserts the stub was used, and the whole suite
now passes with `socket.getaddrinfo` and `socket.create_connection` disabled (675 passed).

Worth stating plainly: this test was green for three unrelated reasons at once, and no amount of
reading it would have shown that. Disabling the socket turned it red in one run.

### Round 2 — the re-review of 115ae9d: one regression, and a flake it exposed

**The regression was mine, introduced in round 1.** To classify 5xx I moved `raise_for_status()` out
of the `try` block, and in doing so made **429 fatal on the first call**. A 429 raises `HTTPError`,
which *is* a `RequestException` — but raised from the `else:` clause, which the `except` (which only
wraps `get`) cannot see. Before round 1 the 429 was caught and retried; after it, it escaped as a
bare `HTTPError` rather than the documented `RuntimeError: ALFRED request failed after retries`.

```
RED:
E   requests.exceptions.HTTPError: 429            # escaped the retry loop entirely
4 failed, 10 passed
GREEN: 14 passed
```

The fix classifies the status **before** calling `raise_for_status()`: retryable is
`429 or 500 <= status <= 599`, everything else is final. Two related points, both now pinned:

- **A 4xx fails fast but with the same error *type*.** A 404 means the series or vintage does not
  exist, so retrying it four times only delays the same failure by ~9s of backoff. But callers and
  log readers should not have to tell "404, do not retry" from "404 after four tries" by
  exception class, so the non-retryable path raises `RuntimeError` too, with a message that says it
  was not retried.
- **A 429 still respects the deadline.** Retrying is still skipped when the budget cannot afford
  one more attempt, which is the whole point of the clamp.

#### The optional item: a missing JOLTS vintage

I took the warning option, not "mark the month incomplete", and the reason is worth recording:
JOLTS is genuinely optional. `labor-v1` ships `CORE_FEATURES`, which do not use it, and its
vintages start years after payrolls — so treating a missing JOLTS vintage as a feature gap would
mark nearly every early month incomplete and **block pruning for the entire backtest window**.
That would have been a much worse bug than the silence it fixed. A missing input and a zero input
are different facts, and `values` is where the difference disappears, so it is now logged with
that distinction stated. Two tests: a missing vintage warns, a present one does not.

#### A flake the fix exposed, which was ten files wide

`test_scan_main_includes_sports_when_due` began failing — at 17:12 ET, a `labor_scan_due` hour.
`scan.main()` defaults to the wall clock, and the real `scan_labor` ran against `live=object()`.
This is the same trap that made two sports tests time-of-day flaky for CPI at 08/12/16 ET, and the
labor window (07/12/17 ET) is wide enough that **a reviewer running the suite in the afternoon
would have hit it**. An AST scan found **ten files** driving `scan.main()` without pinning
`labor_scan_due`; all ten are fixed.

I could not prove the fix with a frozen clock — patching `datetime.datetime` globally segfaults a C
extension (exit 139) — so the property is now a standing static guard: every test file that drives
`scan.main()` must either stub `labor_scan_due` or pass an explicit `now=`. That covers future
engines with fixed hours too, which is the part worth having.

#### Round 2 verification

```
pytest              683 passed in 5.69s      (675 at 115ae9d)
ruff                All checks passed!
npm run typecheck   exit 0
vitest              7 files / 32 tests passed
vite build          ✓ built
```


---

# Follow-up: Kalshi tier for settled markets, and per-row isolation

Branch `fix/scorecard-kalshi-tiers`. Opened from the review comment on PR #18: the FRED half of
`build_jobs_scorecard --since 2023-01` now completes on the VPS, and the build then dies on Kalshi.

## The bug

```text
404 .../series/PROLLS/markets/PROLLS-23MAR-T0/candlesticks?...
```

`event_ladders` asked for candles like this:

```python
candles = client.merged_candles(market.ticker, first - CANDLE_LOOKBACK, last,
                                series_ticker=market.series_ticker)
```

`merged_candles` picks the tier from `market_settled_at`, and **a missing settlement timestamp means
"still live"** — so every call took the live path
(`/series/{series}/markets/{ticker}/candlesticks`). That path 404s for every market that settled
before `/historical/cutoff`'s `market_settled_ts`, which is *all* of them in a historical scorecard.
The legacy `PROLLS-*` tickers in the report are pre-2024, so the very first event failed the build.

The fix is the one-line the reviewer asked for — pass each market's own `settlement_ts` — and the
client's existing tier logic does the rest. An **open** market has `settlement_ts is None` and
correctly stays on the live path, so the fix does not over-correct; there is a test for each direction
that asserts the actual URL, not just that a kwarg was passed.

## One missing ladder no longer kills the build

Isolated at two levels, because they fail for different reasons:

- **Per market** (`event_ladders`): a strike whose candles 404 or come back empty is dropped with a
  WARNING naming the ticker and the event, and the rest of the ladder stands. One dead strike costs
  one strike.
- **Per row** (`build_rows`): a row whose ladder cannot be built at all is still written, with null
  Kalshi fields. The nowcast, the first print and the revisions come from ALFRED, not Kalshi, and
  they are the reason the table exists — dropping the row would leave that release with no record at
  all.

The `except` around a market is deliberately broad. The failure modes are HTTP (404 on the wrong
tier, 429, 5xx) and payload shape, and one unbuildable strike must not end a monthly job.

## Counts and exit code

```json
{"rows": 42, "by_series": {...}, "written": 42, "with_first_print": 40,
 "rows_with_full_ladder": 39, "rows_skipped": 1}
```

- `rows_with_full_ladder` — every strike in the event contributed a usable mid at **both** moments.
  A partial ladder is neither full nor skipped, which is the distinction that matters when reading the
  number: "39 full, 1 skipped" and "39 full, 3 partial" are different problems.
- `rows_skipped` — the row has no Kalshi ladder at all.
- `scorecard_exit_code` returns non-zero **only** when every row was skipped. A partial outage must
  not fail a monthly job that still recorded 40 of 42 releases; a total one must, or the timer would
  report success over an empty table. An empty run (`rows == 0`) is not a failure.

## Idempotence

`upsert_scorecard` was already keyed `on_conflict="series,reference_month"`. What the new tests pin is
the half that was *not* covered: a row whose ladder came back empty must still carry the same
`(series, reference_month)` key and the same content on a rerun, or a partial run would insert a
second row for the same release. Two consecutive builds are asserted equal, key-for-key and
content-for-content, with one event failing in both.

## RED / GREEN

```text
# RED
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q tests/test_build_jobs_scorecard.py
8 failed, 4 passed in 0.80s

  # the first failure is the bug report, verbatim:
  self = <test_build_jobs_scorecard._FakeGet object at 0x10cf7e90>
  url = 'https://api.elections.kalshi.com/trade-api/v2/series/PROLLS/markets/PROLLS-23MAR-T0/candlesticks'
  E   KeyError: '/series/PROLLS/markets/PROLLS-23MAR-T0/candlesticks'

# GREEN
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q tests/test_build_jobs_scorecard.py
12 passed in 1.26s          # 3 pre-existing + 9 new

SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q
722 passed in 29.25s        # 713 baseline + 9 new

.../python -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

## The two clock runs

```text
# a low CI monotonic clock
... -c "import time; time.monotonic = lambda: 5.0; import pytest; pytest.main(['-q'])"
722 passed in 25.91s

# a high one
... -c "import time; time.monotonic = lambda: 1e7; import pytest; pytest.main(['-q'])"
722 passed in 24.36s
```

**I could not reproduce the three failures** — not on this branch, and not on `origin/main` before it
(713 passed at both extremes). The most likely explanation is PR #16 (`test: fixed clock for the
past-deadline ALFRED test`), merged 22:37 today, which is exactly this class of test; if CI is still
red after this merges, the failing test names would pin it down faster than anything I can add here.

## Test-harness bugs of my own, found and fixed in the tests

Three, all caught before they could pass for the wrong reason: a fake client whose `merged_candles`
lacked the new kwarg; a date string built from the wrong slice of an event tag (`2026-JU-007`); and a
fake client that put every market's candles at one shared wall-clock time, so an event that closed in
July got quotes from August and read as an empty ladder. The third is why candle times are now taken
from the requested window.

## Kevin's checklist

1. Merge, then deploy. No migration, no Supabase change, no new env var.
2. Re-run `python -m tradehub.scripts.build_jobs_scorecard --since 2023-01`. Expect completion, and a
   count line — `rows_with_full_ladder` is the number to watch: it should be close to `rows`. A ladder
   per strike is many requests, so a low value on the first run may mean rate limiting rather than
   missing markets, and the per-market WARNINGs will say which.
3. Old markets (`PROLLS-*`, `PAYROLLS-*`, `U3-*`) should now come from `/historical/markets/...`, so
   the 404 above should not appear. If it does, the WARNING names the ticker and the event.
4. Still Kevin's: migration `000009`, and the `tradehub-jobs-scorecard.timer`.

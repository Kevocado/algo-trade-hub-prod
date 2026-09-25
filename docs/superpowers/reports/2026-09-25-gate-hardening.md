# Step 2b: Promotion-Gate and Settlement Hardening — evidence report

Plan: `docs/superpowers/plans/2026-09-25-gate-hardening.md`
Branch: `plan/2026-09-25-gate-hardening`
Base: `98432bc` (PR #4 reconciled head; PR #4 still open, continuation explicitly authorized)

## Baseline

Recorded before Task 1, on a clean tree at `98432bc`.

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 63%]
........................................................................ [ 84%]
.....................................................                    [100%]
341 passed in 4.77s
```

```
$ /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

Baseline: **full pytest 341 passed; scoped Ruff clean.**

---

## Task 1 — Hardening migration

Migration `20260416000007_predictions_hardening.sql` (reserved for this plan) plus
`tests/test_predictions_hardening_migration.py`.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_predictions_hardening_migration.py -q
E       FileNotFoundError: [Errno 2] No such file or directory:
          '.../market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql'
=========================== short test summary info ============================
FAILED tests/test_predictions_hardening_migration.py::test_hardening_migration_covers_step_2b
1 failed in 0.06s
```

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_predictions_hardening_migration.py -q
.                                                                        [100%]
1 passed in 0.01s
```

### Extra validation — throwaway `postgres:16-alpine` (Docker was available, so the optional check was run)

`20260416000003` then `20260416000007` twice, with a stubbed `auth` schema:

```
applied 20260416000003_predictions_ledger
applied 20260416000007_predictions_hardening
applied 20260416000007_predictions_hardening
```

The second `000007` run emitted only `NOTICE ... skipping` lines, confirming idempotency.
Behavioural checks against the live throwaway database:

```
== track_record_pkey ==
PRIMARY KEY (engine, engine_version)

== two versions of one engine side by side ==
 engine  | engine_version | n_settled
---------+----------------+-----------
 weather | v1             |         5
 weather | v2             |         7
(2 rows)

== SETTLED without result is rejected (expect ERROR) ==
ERROR:  new row for relation "predictions" violates check constraint "predictions_settled_has_result"

== policies on predictions / track_record ==
predictions :: predictions_owner_read :: SELECT
track_record :: track_record_owner_read :: SELECT

== any FOR ALL policy? (expect empty) ==
<no rows>
```

All four Intent items hold: the two new columns exist, `predictions_settled_has_result`
rejects a resultless `SETTLED` row, `track_record_pkey` is `(engine, engine_version)` and
holds two versions side by side, and only the `*_owner_read` SELECT policies remain.

### Implementation summary

- Added `predictions.settlement_payload jsonb` and `predictions.settled_at timestamptz`
  (`IF NOT EXISTS`, so re-runs are no-ops).
- Added `predictions_settled_has_result CHECK (status <> 'SETTLED' OR result IS NOT NULL)`
  behind a `pg_constraint` existence guard.
- Added the `(engine, engine_version, status)` index used by the per-version refresh.
- Rebuilt `track_record_pkey` as `(engine, engine_version)`; the guard joins
  `pg_attribute` and only drops the constraint when it is a single-column key, so
  re-running after the rebuild is a no-op.
- Dropped the old `FOR ALL` `predictions_owner` / `track_record_owner` policies and created
  read-only `*_owner_read` SELECT policies scoped by `auth.uid() = user_id`. Service-role
  jobs bypass RLS, so settlement and the refresh job keep writing; clients lose writes.

### Deviations

None. The migration and test were taken verbatim from the plan; both applied without
conflict on this base.

---

## Task 2 — Contract-weighted gate, minimum bucket size, per-version records

`tradehub/track_record.py`, `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py`,
plus `tests/test_track_record_contracts.py`.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_track_record_contracts.py -q
E       TypeError: prediction_row() got an unexpected keyword argument 'market_ticker'
tests/test_track_record_contracts.py:111: TypeError
=========================== short test summary info ============================
FAILED tests/test_track_record_contracts.py::test_hourly_repeats_of_one_market_count_as_one_contract
FAILED tests/test_track_record_contracts.py::test_briers_weight_each_contract_equally
FAILED tests/test_track_record_contracts.py::test_calibration_n_is_effective_contracts
FAILED tests/test_track_record_contracts.py::test_thin_bucket_does_not_block_the_gate
FAILED tests/test_track_record_contracts.py::test_refresh_writes_one_record_per_engine_version
FAILED tests/test_track_record_contracts.py::test_backtest_rows_carry_their_market_ticker
6 failed, 1 passed in 0.28s
```

Matches the plan's prediction: only `test_full_bucket_miss_still_blocks_the_gate` passed
before the change.

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
    tests/test_track_record_contracts.py tests/test_track_record.py \
    tests/test_backtest_runner.py tests/test_backtest_store.py -q
...........................................                              [100%]
43 passed in 0.42s
```

Full suite at this commit, to confirm no wider regression:

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
341 -> 349 passed in 4.71s        (8 new tests, no failures)

$ ... -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

### Implementation summary

- `_contract_key` / `_contract_weights`: each settled row is weighted `1/k` where `k` is the
  number of settled rows sharing its `market_ticker`; a row with no ticker is its own
  contract, so pre-existing callers and tests are unaffected.
- `compute_engine_summary`: `n_settled` is now the distinct contract count, `n_rows` is the
  raw settled row count, and both Briers are contract-weighted via the new `_weighted_mean`.
  The market Brier still fails closed — it stays `None` unless every settled row carries one.
- `compute_calibration`: same weighting; `n` is the effective contract count rounded to 2dp
  and `n_rows` is the raw count, so thin buckets remain visible in `cal_buckets`.
- `check_promotion_gate`: buckets with `n < MIN_BUCKET_CONTRACTS` (20) are skipped, so they
  neither add a reason nor raise `max_cal_dev`.
- `refresh_track_record`: lost its `engine_version` argument, now groups settled rows by
  `engine_version`, and returns one payload per version from the new `_upsert_version`
  helper, upserting on `on_conflict="engine,engine_version"` to match the new primary key.
- `prediction_row` gained a `market_ticker` keyword (defaulted to `None`, so existing
  callers are unaffected) and records it in the row, so the backtest gate counts contracts
  the same way as the live gate.

### Deviations

**`tradehub/backtest/runner.py` was resolved by hand.** `git apply --3way` reported
`Applied patch to 'tradehub/backtest/metrics.py' cleanly.`,
`Applied patch to 'tradehub/track_record.py' cleanly.`, but
`Applied patch to 'tradehub/backtest/runner.py' with conflicts.` PR #4's commit `193b7b5`
("score backtests only on contracts quoted at decision time") had rewritten the same lines,
hoisting `market_prob` into a local and adding an `n_unquoted` skip. The plan's hunk would
have reverted that fix. Resolution keeps PR #4's `market_prob` local and `n_unquoted` guard
and adds only the new keyword, so both the leakage fix and the Task Intent hold:

```python
market_prob = market_mid(quote_at(history.candles, decision.decided_at))
if market_prob is None:
    n_unquoted += 1
    continue
rows.append(prediction_row(decision.our_prob, market_prob, history.result,
                           market_ticker=decision.market_ticker))
```

`metrics.py` and `track_record.py` needed no adjustment; their hunk contexts happened to
survive the PR #4 fixes (`prediction_row` gained a `log_loss` key, which the patch left
untouched).

---

## Task 3 — Settlement keeps engine inputs, caches markets, isolates errors

`tradehub/settlement.py` and `tests/test_settlement.py`.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_settlement.py -q
E           RuntimeError: PostgREST 500
tests/test_settlement.py:293: RuntimeError
=========================== short test summary info ============================
FAILED tests/test_settlement.py::test_settle_prediction_row_canceled_marks_canceled_without_fabricating_result
FAILED tests/test_settlement.py::test_run_settlement_pass_settles_finalized_and_skips_others
FAILED tests/test_settlement.py::test_run_settlement_pass_is_idempotent - Ass...
FAILED tests/test_settlement.py::test_run_settlement_pass_counts_conditional_update_miss_as_skipped
FAILED tests/test_settlement.py::test_run_settlement_pass_no_open_predictions
FAILED tests/test_settlement.py::test_settled_row_keeps_engine_inputs_and_stamps_settlement
FAILED tests/test_settlement.py::test_run_settlement_pass_fetches_each_ticker_once
FAILED tests/test_settlement.py::test_run_settlement_pass_failed_fetch_skips_all_rows_for_that_ticker_once
FAILED tests/test_settlement.py::test_run_settlement_pass_isolates_write_errors
9 failed, 14 passed in 0.12s
```

The `RuntimeError` escaping the pass is itself part of the RED evidence: a single failing
write currently aborts the whole pass.

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python \
    -m pytest tests/test_settlement.py -q
.......................                                                  [100%]
23 passed in 0.02s
```

Full suite at this commit:

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
    /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
349 -> 353 passed in 5.23s        (4 new tests, no failures)

$ ... -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

### Implementation summary

- `settle_prediction_row` gained a keyword-only `now` and now writes the Kalshi JSON to
  `settlement_payload` plus an ISO-UTC `settled_at`, on both the SETTLED and CANCELED
  paths. The `raw_payload` key is gone from the update, so the engine's inputs survive.
- `run_settlement_pass` keeps a per-ticker `markets` cache and a `failed` set. A ticker is
  fetched at most once per pass; a fetch failure records the ticker in `failed`, bumps
  `fetch_errors` once, and skips that ticker's remaining rows without refetching.
- The `apply_prediction_settlement` call is wrapped: an exception bumps `write_errors` and
  `skipped` and continues, so one PostgREST 500 no longer aborts the pass. A conditional
  update that matches no row still counts as `skipped`, as before.
- The summary dict now always carries `checked`, `settled`, `canceled`, `skipped`,
  `fetch_errors` and `write_errors`.
- `now` is computed once per pass and threaded into every row, so all rows settled in a
  pass share one consistent timestamp.

### Deviations

None. Both hunks applied cleanly (`Applied patch to 'tests/test_settlement.py' cleanly.`
and `Applied patch to 'tradehub/settlement.py' cleanly.`); PR #4 had not touched this
module.

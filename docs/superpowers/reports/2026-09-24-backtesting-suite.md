# Evidence Report — Backtesting Suite

- Plan: `docs/superpowers/plans/2026-09-24-backtesting-suite.md`
- Branch: `plan/2026-09-24-backtesting-suite`
- Base: `8ebf0f4` (local `main` with step 2 merged)
- Venv: `.venv/bin/python`
- Test environment: every pytest command uses process-only `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Baseline: `165 passed in 5.76s`.

## Task 1 — `backtest_runs` migration

- **Files changed:** `market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql`, `tests/test_repo_layout.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-1-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_backtest_runs_migration_defines_table -q
  ```
  RED output tail:
  ```text
  E       AssertionError: backtest_runs migration is missing
  E       assert False
  E        +  where False = is_file()
  E        +    where is_file = PosixPath('/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql').is_file
  tests/test_repo_layout.py:156: AssertionError
  =========================== short test summary info ============================
  FAILED tests/test_repo_layout.py::test_backtest_runs_migration_defines_table
  1 failed in 0.05s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
  ```
  GREEN output tail:
  ```text
  ...............                                                          [100%]
  15 passed in 0.37s
  ```
- **Migration review:** Added the exact idempotent `backtest_runs` table definition with the specified columns, engine/created-time index, row-level security, and owner-scoped policy.
- **Deviation:** None. The migration was intentionally not applied; Supabase deployment remains a manual step. The pre-existing evidence report was untracked and is included in this task commit as required.

## Task 2 — Point-in-time types and leakage guard

- **Files changed:** `tradehub/backtest/__init__.py`, `tradehub/backtest/pit.py`, `tests/test_backtest_pit.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-2-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_pit.py:5: in <module>
      from tradehub.backtest.pit import Decision, LeakageError, Observation, check_no_lookahead
  E   ModuleNotFoundError: No module named 'tradehub.backtest'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_pit.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.20s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_pit.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 0.01s
  ```
- **Behavior:** Added frozen `Observation` and `Decision` dataclasses with the exact specified fields, `LeakageError`, timezone-awareness validation, and a point-in-time guard that names every feature published after the decision while allowing equality.
- **Deviation:** None. The handoff report is intentionally not staged because the requested commit staging list is explicit.

## Task 3 — Kalshi public-history client

- **Files changed:** `tradehub/backtest/http.py`, `tradehub/backtest/kalshi_history.py`, `tests/test_backtest_kalshi_history.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-3-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_kalshi_history.py:5: in <module>
      from tradehub.backtest import kalshi_history as kh
  E   ImportError: cannot import name 'kalshi_history' from 'tradehub.backtest' (/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/tradehub/backtest/__init__.py)
  =========================== short test summary info ============================
  ERROR tests/test_backtest_kalshi_history.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.18s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  ..........                                                               [100%]
  10 passed in 0.02s
  ```
- **Behavior:** Added the injected-`get_json` Kalshi public-history client, the 30-second `requests` wrapper, public production base URL, candle/trade parsers, cursor pagination, historical/live paths, and oldest-first output ordering specified by the brief.
- **Deviation:** No functional implementation or test deviation. The RED failure was an `ImportError` rather than the brief's literal `ModuleNotFoundError` wording because the Task 2 package marker already existed; it was still the expected collection failure caused by the missing client module. Tests use only injected canned responses, so no live network calls were made.

## Task 4 — Conservative fill model

- **Files changed:** `tradehub/backtest/fills.py`, `tests/test_backtest_fills.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-4-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_fills.py:6: in <module>
      from tradehub.backtest.fills import MIN_TAKER_PRICE, maker_fill, quote_at, taker_fill
  E   ModuleNotFoundError: No module named 'tradehub.backtest.fills'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_fills.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 2.42s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q
  ```
  GREEN output tail:
  ```text
  ............                                                             [100%]
  12 passed in 0.42s
  ```
- **Behavior:** Added the frozen `Fill` record, decision-time `quote_at` lookup, conservative taker pricing at the visible ask/one-minus-bid, 10-cent taker floor, after-fee edge gating, and maker fills only from later opposite-side taker trades at or through the decision-time bid/one-minus-ask limit. Fee dollars are derived from the shared Kalshi fee helper.
- **Deviation:** None. The tests and implementation follow the brief verbatim; only the requested Task 4 report and handoff report were updated. The handoff report is intentionally not staged because the requested staging list is explicit.

## Task 5 — Metrics and runner

- **Files changed:** `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py`, `tests/test_backtest_runner.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-5-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_runner.py:7: in <module>
      from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
  E   ModuleNotFoundError: No module named 'tradehub.backtest.metrics'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_runner.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.62s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  ...........                                                              [100%]
  11 passed in 0.43s
  ```
- **Behavior:** Added shared fill P&L, peak-to-trough drawdown, market midpoint, and settled prediction-row metrics. The runner sorts decisions, runs the point-in-time leakage check before market lookup or fills, rejects decisions at/after close, skips non-binary markets, uses the specified taker/maker fill modes, computes turnover and fee-aware P&L/drawdown, and delegates summary, calibration, and promotion-gate evaluation to the live track-record code. Walk-forward fits use only strictly earlier events.
- **Deviation:** None. The RED failure was the expected missing-`metrics` collection error, and the exact eleven-test GREEN command passed. The handoff report is intentionally not staged because the requested staging list names only the two production files, focused test, and evidence report.

## Task 6 — ALFRED and Open-Meteo sources

- **Files changed:** `tradehub/backtest/sources/__init__.py`, `tradehub/backtest/sources/alfred.py`, `tradehub/backtest/sources/open_meteo.py`, `tests/test_backtest_sources.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-6-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_sources.py:5: in <module>
      from tradehub.backtest.sources.alfred import FRED_OBSERVATIONS_URL, AlfredSource
  E   ModuleNotFoundError: No module named 'tradehub.backtest.sources'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_sources.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 0.09s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 0.02s
  ```
- **Behavior:** Added the exact ALFRED and Open-Meteo Previous Runs URLs, injected `get_json` clients, and `Observation` construction. ALFRED queries the prior UTC day's vintage, skips `None`, empty, and `.` values, preserves descending vintage order, and publishes values at the vintage date plus one day. Open-Meteo validates `lead_days` in `1..7`, requests the previous-day hourly temperature variable in Fahrenheit, removes null values, returns the maximum, and converts target-date 23:00 local time minus the lead lag to UTC.
- **Tests:** Created the exact four focused tests from the brief before production code; all use canned payloads and perform no live network requests.
- **Deviation:** None. The handoff report is intentionally not staged because the requested commit staging list is explicit.

## Task 7 — Reproducible run storage

- **Files changed:** `tradehub/backtest/store.py`, `tests/test_backtest_store.py`, this evidence report, and `.superpowers/sdd/2026-09-24-backtesting-suite/task-7-report.md` (handoff report; repository-ignored and not staged).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_store.py -q
  ```
  RED output tail:
  ```text
  tests/test_backtest_store.py:6: in <module>
      from tradehub.backtest.store import (
  E   ModuleNotFoundError: No module named 'tradehub.backtest.store'
  =========================== short test summary info ============================
  ERROR tests/test_backtest_store.py
  !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
  1 error in 1.12s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_store.py -q
  ```
  GREEN output tail:
  ```text
  ....                                                                     [100%]
  4 passed in 0.49s
  ```
- **Behavior:** Added stable SHA-256 JSON hashing, order-independent decision and market-history snapshot hashing covering nested features, candles, trades, results, and close times, exact migration-column row construction with ISO date strings, and the Supabase insert/execute wrapper returning the inserted row.
- **Deviation:** None in production code or tests. The handoff report is intentionally not staged because the requested staging list is explicit.

## Verification

- **Full suite command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  Output tail:
  ```text
  ........................................................................ [ 34%]
  ........................................................................ [ 68%]
  ...................................................................      [100%]
  211 passed in 5.32s
  ```
- **Lint command:**
  ```sh
  .venv/bin/ruff check --select F401,F811,F821 tradehub/backtest tests
  ```
  Output tail:
  ```text
  All checks passed!
  ```
- **Import-boundary command:**
  ```sh
  grep -rn "shared.config" tradehub/backtest
  ```
  Output tail:
  ```text
  (no output; exit status 1, as expected)
  ```

## Deviations and rulings

- The required evidence report is included in each task's single task commit because the handoff contract requires a committed report while also requiring one commit per task.
- The step-2 PR remains open remotely; this prerequisite branch uses the local fast-forward merge requested by the user and does not push.

## Final review fix wave

- **Base/branch:** `fc9a4902a0bd66806b70379cc1e49b2652e95447` on `plan/2026-09-24-backtesting-suite`.
- **Scope:** Addressed the eight binding findings in `.superpowers/sdd/2026-09-24-backtesting-suite/final-fix-brief.md` without editing the spec or another plan.
- **TDD order:** Every regression test below was added and run RED before its production fix; focused GREEN commands were run after the implementation. No migrations were applied and no live services were contacted.

### Pre-fix findings and root causes

1. `shared/kalshi_fees.net_edge_pct` added fees to negative gross edges, so a small negative edge could become positive. Fill edge selection also called the helper with its default one-contract size instead of the requested size.
2. `parse_candle` only read historical `close`/`volume`, and `parse_trade` only read legacy `taker_side`; block status was discarded. Live and historical response shapes therefore normalized incorrectly.
3. The cutoff response contained two independent boundaries, but the client exposed only `market_settled_ts`; callers had to choose a tier themselves and had no safe overlap merge.
4. Maker matching returned on the first qualifying print, did not skip block trades, and did not accumulate contract volume.
5. Open-Meteo subtracted the lead in local wall-clock time, which crossed the fall-back DST transition at the wrong UTC instant.
6. Equal-time decisions were stable-sorted only by input order, so identical input permutations could produce different fill/P&L/drawdown ordering despite an order-independent snapshot hash.
7. The spec-required log-loss metric was absent from the backtest row/result/storage contract; the original migration was intentionally left unchanged.
8. Maker/taker threshold calculations did not consistently use requested contracts, risking a different fee-rounding decision from the fill that would actually be recorded.

### Regression RED evidence

- **Fees and fills:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_fills.py -q
  ```
  RED tail:
  ```text
  FAILED tests/test_backtest_fills.py::test_net_edge_pct_subtracts_fees_from_negative_gross_edges
  FAILED tests/test_backtest_fills.py::test_negative_gross_edge_never_fills_even_when_fee_would_flip_the_sign
  FAILED tests/test_backtest_fills.py::test_taker_edge_threshold_uses_requested_contract_count
  FAILED tests/test_backtest_fills.py::test_maker_edge_threshold_uses_requested_contract_count
  FAILED tests/test_backtest_fills.py::test_maker_ignores_block_trades - TypeError: Trade.__init__() takes 6 positional arguments but 7 were given
  FAILED tests/test_backtest_fills.py::test_maker_requires_enough_qualifying_post_decision_volume
  FAILED tests/test_backtest_fills.py::test_maker_fills_when_accumulated_qualifying_volume_reaches_contracts
  7 failed, 12 passed in 0.55s
  ```
- **Live schemas, cutoffs, and tier merges:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  RED tail:
  ```text
  FAILED tests/test_backtest_kalshi_history.py::test_parse_live_candle_uses_dollar_close_and_fixed_point_volume
  FAILED tests/test_backtest_kalshi_history.py::test_parse_trade_prefers_canonical_outcome_side_and_exposes_block_flag
  FAILED tests/test_backtest_kalshi_history.py::test_cutoff_timestamps_exposes_market_and_trade_boundaries
  FAILED tests/test_backtest_kalshi_history.py::test_merged_candles_splits_at_market_cutoff_and_deduplicates_boundary
  FAILED tests/test_backtest_kalshi_history.py::test_merged_trades_combines_tiers_and_deduplicates_overlap
  5 failed, 10 passed in 0.07s
  ```
- **DST boundary:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  RED tail:
  ```text
  E       AssertionError: assert datetime.datetime(2026, 11, 1, 3, 0, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 11, 1, 4, 0, tzinfo=datetime.timezone.utc)
  FAILED tests/test_backtest_sources.py::test_forecast_daily_high_subtracts_lead_days_in_utc_across_fall_back
  1 failed, 4 passed in 0.06s
  ```
- **Runner ordering and log loss:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  RED tail:
  ```text
  E       AttributeError: module 'tradehub.backtest.metrics' has no attribute 'log_loss'
  FAILED tests/test_backtest_runner.py::test_log_loss_is_numerically_clipped_and_propagates_to_result
  FAILED tests/test_backtest_runner.py::test_equal_time_decisions_have_permutation_independent_fill_order_and_drawdown
  2 failed, 11 passed in 0.44s
  ```
- **Storage column:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_store.py -q
  ```
  RED tail:
  ```text
  E       AssertionError: assert {'brier_marke...ta_hash', ...} == {'brier_marke...ta_hash', ...}
  E         Extra items in the right set:
  E         'log_loss'
  FAILED tests/test_backtest_store.py::test_build_row_matches_migration_columns
  1 failed, 3 passed in 0.27s
  ```
- **Structural migration assertion:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_backtest_log_loss_migration_adds_nullable_column -q
  ```
  RED tail:
  ```text
  E       AssertionError: backtest log-loss migration is missing
  E       assert False
  E        +  where False = is_file()
  FAILED tests/test_repo_layout.py::test_backtest_log_loss_migration_adds_nullable_column
  1 failed in 0.05s
  ```

### Focused GREEN evidence

- `tests/test_backtest_fills.py -q` → `19 passed in 0.38s`.
- `tests/test_backtest_kalshi_history.py -q` → `15 passed in 0.02s`.
- `tests/test_backtest_sources.py -q` → `5 passed in 0.01s`.
- `tests/test_backtest_runner.py -q` → `13 passed in 0.32s`.
- `tests/test_backtest_store.py -q` → `4 passed in 0.24s`.
- `tests/test_repo_layout.py -q` → `16 passed in 0.32s`.

The first post-fix runner GREEN run exposed a floating-point complement at the clipped upper endpoint (`log(1.0 - (1.0 - 1e-15))`); the implementation was corrected to clip the outcome-side probability independently, then the focused command was rerun GREEN as shown above. No other focused command required a second fix.

### Full exact verification

- **Full pytest:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
  ```
  Output tail:
  ```text
  ........................................................................ [ 31%]
  ........................................................................ [ 63%]
  ........................................................................ [ 95%]
  ...........                                                              [100%]
  227 passed in 4.10s
  ```
- **Ruff:**
  ```sh
  .venv/bin/ruff check --select F401,F811,F821 tradehub/backtest tests
  ```
  Output tail:
  ```text
  All checks passed!
  ```
- **Import-boundary grep:**
  ```sh
  grep -rn "shared.config" tradehub/backtest
  ```
  Output tail:
  ```text
  (no output; exit status 1, as expected)
  ```

### Fix-wave files and deviations

- Production changes: `shared/kalshi_fees.py`, `tradehub/backtest/fills.py`, `tradehub/backtest/kalshi_history.py`, `tradehub/backtest/metrics.py`, `tradehub/backtest/runner.py`, `tradehub/backtest/sources/open_meteo.py`, `tradehub/backtest/store.py`, and new migration `market_sentiment_tool/supabase/migrations/20260416000006_backtest_log_loss.sql`.
- Regression tests were added to the six focused backtest/layout test files listed by the RED commands above.
- The new migration is intentionally not applied. Existing migration `20260416000004_backtest_runs.sql` was not edited.
- The new log-loss column is nullable; gate and Brier code paths were left unchanged.
- No dependency, spec, other-plan, live-service, push, reset, amend, or clean operation was performed. The ignored detailed handoff is `.superpowers/sdd/2026-09-24-backtesting-suite/final-fix-report.md`.

## Post-review fix wave — finding 1

- **Requirement:** `runner.walk_forward` must require `label_available_at`; training history contains only events whose labels are available strictly before the current decision. A regression covers markets settling 36 hours after their decision.
- **Root cause:** the old implementation filtered by `time_of(e) < time_of(event)` and had no way to account for delayed labels.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  RED output tail:
  ```text
  TypeError: walk_forward() got an unexpected keyword argument 'label_available_at'
  2 failed, 12 passed in 0.48s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  14 passed in 0.30s
  ```
- **Implementation:** added the required callable to the public signature, filtered history with the strict label-time comparison, and excluded the current event from its own history.
- **Deviation:** the first GREEN attempt exposed that the old equal-time fixture declared labels available one second early; the fixture was corrected to make the strict boundary explicit, then the focused command passed. No external service was contacted.

## Post-review fix wave — finding 2

- **Requirement:** `merged_candles` must select exactly one tier for a market: historical when the market settled before `market_settled_ts`, otherwise live. The regression test was corrected accordingly.
- **Root cause:** the old helper split one market's requested candle window at the global cutoff and called both endpoints, even though Kalshi partitions an entire market by its own settlement time.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py::test_merged_candles_uses_one_tier_selected_by_market_settlement -q
  ```
  RED output tail:
  ```text
  TypeError: KalshiHistoryClient.merged_candles() got an unexpected keyword argument 'market_settled_at'
  2 failed in 0.06s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  16 passed in 0.01s
  ```
- **Implementation:** added the explicit per-market `market_settled_at` input, fetched the cutoff once, and issued exactly one `candles` request using the selected tier. Equality with the cutoff selects live data.
- **Deviation:** the method cannot infer a market's settlement timestamp from its ticker alone, so the caller supplies that metadata explicitly. The existing `candles` and `merge_candles` paths remain unchanged.

## Post-review fix wave — finding 3

- **Requirement:** preserve Kalshi's `trade_id` on `Trade`, deduplicate merged trades by that identity, and remove the unused cutoff request.
- **Root cause:** `parse_trade` discarded `trade_id`, so the merge key collapsed distinct trades with identical timestamp/price/count/side; `merged_trades` also fetched and ignored `trades_created_ts`.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py::test_parse_trade tests/test_backtest_kalshi_history.py::test_merged_trades_deduplicates_by_trade_id_without_a_cutoff_call -q
  ```
  RED output tail:
  ```text
  AttributeError: 'Trade' object has no attribute 'trade_id'
  2 failed in 0.06s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  16 passed in 0.02s
  ```
- **Implementation:** added a trailing backward-compatible `trade_id` field, populated it from the raw payload, used IDs as the primary dedupe key, retained a composite fallback for ID-less fixtures, and deleted the discarded cutoff call. Stable tier order is retained for equal trade fields.

## Post-review fix wave — finding 4

- **Requirement:** `settled_markets` must also read live-tier settled markets from `/markets?status=settled&series_ticker=...` and deduplicate the combined result by ticker.
- **Root cause:** the client queried only `/historical/markets`, omitting markets that settled after the historical partition boundary.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py::test_settled_markets_merges_historical_and_live_tiers_by_ticker -q
  ```
  RED output tail:
  ```text
  AssertionError: assert ['A'] == ['A', 'B']
  1 failed in 0.06s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  17 passed in 0.03s
  ```
- **Implementation:** paginated both tiers with the required live filters, retained the first (historical) record for duplicate tickers, and preserved records without a ticker rather than collapsing them.
- **Deviation:** the existing historical-pagination fixture was extended with an empty live response because the client now always checks both partitions.

## Post-review fix wave — finding 5

- **Requirement:** verify Kalshi's published fee rounding and correct `kalshi_fee_cents` if the schedule rounds whole cents per order.
- **Schedule verification:** the official general fee schedule (`https://kalshi.com/fee-schedule`, latest archived publication checked 2026-05-08; the linked PDF is effective 2026-02-05) states `round_up(0.07 × C × P × (1-P))` and says the result rounds to the next cent. The current API fee-rounding page also documents separate six-decimal model-fee and account-balance rounding; this helper models the published order-level total, so it rounds once after applying `C`.
- **Root cause:** the helper multiplied the cent result by 100 before `ceil`, returning fractional cents (1.73¢) instead of the order total rounded to a whole cent (2¢).
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_fees.py -q
  ```
  RED output tail:
  ```text
  AssertionError: assert 1.73 == 2.0
  1 failed in 0.48s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_fees.py tests/test_backtest_fills.py -q
  ```
  GREEN output tail:
  ```text
  20 passed in 0.27s
  ```
- **Implementation:** calculate the total taker or maker fee in cents, apply `ceil` once to that order total, and update the two edge-threshold fixtures whose expected values depended on fractional-cent fees.

## Post-review fix wave — finding 6

- **Requirement:** add a per-model availability lag to Open-Meteo `published_at`, defaulting to 6 hours, and add a spring-forward DST regression.
- **Root cause:** the old stamp represented only the end of the requested lead window and did not reserve time for the model run to become available; it also left the existing fall-back expectation at the pre-lag instant.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  RED output tail:
  ```text
  AssertionError: assert datetime.datetime(2026, 7, 24, 3, 0, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 7, 23, 21, 0, tzinfo=datetime.timezone.utc)
  3 failed, 3 passed in 0.06s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  GREEN output tail:
  ```text
  6 passed in 0.02s
  ```
- **Implementation:** added `DEFAULT_AVAILABILITY_LAG = timedelta(hours=6)`, a per-model override mapping, and an optional `availability_lag` argument. The local target-day boundary is converted to UTC first, then the lead duration and lag are subtracted as absolute durations; the spring-forward test expects `2026-03-07T21:00Z`.
- **Deviation:** the existing July and fall-back expected timestamps were shifted by the new default 6-hour lag.

## Post-review fix wave — finding 7

- **Requirement:** compute maximum drawdown in market settlement order rather than decision/fill-discovery order.
- **Root cause:** `run_backtest` accumulated P&Ls as it iterated decisions, even though a position's realized P&L enters the equity curve at market settlement.
- **RED command (final regression run against the pre-fix runner):**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py::test_max_drawdown_follows_market_settlement_order -q
  ```
  RED output tail:
  ```text
  AssertionError: assert 1.6400000000000001 == 1.06 ± 1.1e-06
  1 failed in 0.44s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  15 passed in 0.41s
  ```
- **Implementation:** retained each fill's `MarketHistory.close_time` as the settlement-order key, sorted by settlement time with deterministic fill tie-breakers, and fed only that ordered P&L sequence to `max_drawdown`; total P&L and fill output order remain unchanged.
- **Deviation:** the regression was first drafted with two markets, which could not distinguish the two orderings; it was strengthened to three markets before the final RED/GREEN cycle.

## Review follow-up — explicit settlement timestamp

- **Finding from final code review:** `MarketHistory.close_time` is the trading-close boundary, not necessarily Kalshi's payout settlement timestamp; using it alone could still order drawdown incorrectly.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py::test_max_drawdown_uses_explicit_settlement_time_not_market_close -q
  ```
  RED output tail:
  ```text
  TypeError: MarketHistory.__init__() takes 6 positional arguments but 7 were given
  1 failed in 0.52s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_runner.py -q
  ```
  GREEN output tail:
  ```text
  16 passed in 0.26s
  ```
- **Implementation:** added a trailing optional `MarketHistory.settled_at`, used it for settlement ordering when present, retained `close_time` for decision/fill validation and as a legacy fallback, and kept total P&L summation in deterministic decision order.
- **Cross-branch note:** the stacked data-layer branch has consumers that predate the new explicit `market_settled_at` candle argument. No files from that separate branch were edited here; its integration must pass market `settlement_ts` when rebased, rather than guessing a tier in this branch.

## User-requested re-review fix — Open-Meteo availability lag

- **Requirement:** a `previous_dayN` value becomes available after the run finishes, so the availability lag is added after subtracting the lead duration.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  RED output tail:
  ```text
  AssertionError: assert datetime.datetime(2026, 7, 23, 21, 0, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 7, 24, 9, 0, tzinfo=datetime.timezone.utc)
  4 failed, 3 passed in 0.07s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_sources.py -q
  ```
  GREEN output tail:
  ```text
  7 passed in 0.02s
  ```
- **Implementation:** changed the absolute-time calculation to `- lead_days + lag`; updated the July, spring-forward, 12-hour, and fall-back expected timestamps; restored `test_forecast_daily_high_validates_lead_and_empty_payload()` as a separate test.
- **Deviation:** None. The report intentionally records the corrected availability direction and the restored test.

## User-requested re-review fix — integer Kalshi fee math

- **Requirement:** calculate fees with integer cent arithmetic so float dust cannot round an order up by one cent.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_fees.py -q
  ```
  RED output tail:
  ```text
  assert 8.0 == 7.0
  assert 64.0 == 63.0
  2 failed, 1 passed in 0.55s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_kalshi_fees.py tests/test_backtest_fills.py -q
  ```
  GREEN output tail:
  ```text
  22 passed in 0.47s
  ```
- **Implementation:** added `ceil_div` and whole-cent price normalization; taker fees use `ceil_div(7*C*p*(100-p), 10000)` and maker fees use denominator `40000`. Added dust regressions (4×50¢ taker and 16×50¢ maker) plus the requested 10¢×100 and 20¢×25 examples.
- **Fee schedule note:** the official published schedule was not independently re-read in this run; the implementation conservatively continues charging maker fees wherever the caller requests them.
- **Deviation:** None beyond retaining the existing maker-fee behavior for callers.

## User-requested re-review fix — Kalshi candle tier selection

- **Requirement:** `merged_candles` must accept `market_settled_at=None` and route unsettled markets to the live tier, reject naive datetimes, and expose no unused `cutoffs`, `merge_candles`, or `merge_trades` aliases.
- **RED command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  RED output tail:
  ```text
  TypeError: KalshiHistoryClient.merged_candles() missing 1 required keyword-only argument: 'market_settled_at'
  TypeError: can't compare offset-naive and offset-aware datetimes
  AssertionError: assert not True
  5 failed, 17 passed in 0.08s
  ```
- **GREEN command:**
  ```sh
  SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_kalshi_history.py -q
  ```
  GREEN output tail:
  ```text
  22 passed in 0.02s
  ```
- **Implementation:** made `market_settled_at` optional; a missing value selects the live tier without a cutoff request, while a known settlement time still compares against the market cutoff. Added timezone-awareness validation for `start`, `end`, and `market_settled_at`, and removed the three unused aliases.
- **Deviation:** None; the existing `cutoff()` and `cutoff_timestamps()` methods remain because they are used by the tier-selection tests and client API.

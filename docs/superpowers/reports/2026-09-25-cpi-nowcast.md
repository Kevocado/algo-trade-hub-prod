# Step 6: `cpi_nowcast` — evidence report

- Plan: `docs/superpowers/plans/2026-09-25-cpi-nowcast.md`
- Branch: `plan/2026-09-25-cpi-nowcast`
- Stacked base: `9cc6d86` (PR #5 / step 2b head). Kevin authorized continuing without waiting for merges and accepted stacking risk; no PR is merged by this agent.

## Baseline

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
353 passed in 9.04s
ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

## Task 1 — Month-only CPI tickers and legacy strikes

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_markets.py -q
ImportError: cannot import name 'event_month' from 'tradehub.markets'
1 error in 0.09s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_markets.py tests/test_markets.py -q
13 passed in 0.02s
```

- Implemented `event_month` and `parse_cpi_market` exactly as the task Intent specifies; modern strike fields pass through unchanged and legacy `-T<x>`/`-TN<x>` tickers infer `greater` strikes.
- Added the trimmed recorded Kalshi fixture and six focused tests.
- Deviation: none.

## Task 2 — Cleveland Fed nowcast as point-in-time observations

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cleveland_fed.py -q
ModuleNotFoundError: No module named 'tradehub.data.cleveland_fed'
1 error in 0.17s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cleveland_fed.py -q
6 passed in 0.01s
```

- Added the keyless FusionCharts parser, publication-time rules, headline/core selection and one-call fetcher exactly as specified.
- Added the trimmed recorded payload and six tests covering vlines, December rollover, missing release, core series and the exact URL.
- Deviation: `.gitignore` line 75 is `Data/`, which matches `tradehub/data/` on the case-insensitive macOS filesystem. The new source file was therefore force-added; `.gitignore` was not changed because broadening an unignore rule could expose unrelated data directories.

## Task 3 — Pure CPI model

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_engine.py -q
ModuleNotFoundError: No module named 'tradehub.engines.cpi'
1 error in 0.09s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_cpi_engine.py -q
7 passed in 0.03s
```

- Added headline/core targets and versions, publication-time-safe nowcast selection, same-horizon walk-forward training pairs, the 24-month/12-point error fit, sigma floor and interval probability.
- Added seven focused pure-model tests.
- Deviation: none.

## Task 4 — Scan wiring, config and failure isolation

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_scan_cpi.py -q
6 failed in 0.61s
AttributeError: module 'tradehub.scripts.scan' has no attribute 'scan_cpi'
KeyError: 'cpi_nowcast'
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_scan_cpi.py tests/test_scan.py tests/test_engine_config.py -q
31 passed in 0.60s
```

- Added `cpi_scan_due`, `scan_cpi`, the `cpi_nowcast` config block and CPI as a third isolated engine in the existing PR #4 `run_engine`/per-engine-write structure.
- CPI edges are `MACRO`, carry `engine="cpi_nowcast"` and retain `gate_status="SHADOW"`; they are written but never hidden or force-promoted.
- Deviation: the plan's original test expected `main()==0` and one combined write. PR #4 deliberately returns 1 on any engine failure and writes each engine independently so one failed write is attributable. The hand-merged test preserves the task Intent (CPI failure is reported as `error: ...`, weather/gas writes still complete) while keeping the merged non-zero failure signal; the expected combined count is 31 rather than the plan's pre-PR-4 13.

## Task 5 — Point-in-time CPI backtest

### RED

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_backtest_cpi.py -q
ImportError: cannot import name 'CPI_DECISION_LEAD' from 'tradehub.scripts.backtest_engines'
1 error in 0.60s
```

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest tests/test_backtest_cpi.py tests/test_backtest_engines.py -q
22 passed in 0.54s
```

```text
Full suite: 384 passed in 4.27s
Scoped Ruff F401,F811,F821: All checks passed!
git diff --check: clean
```

- Added release-morning/extra-lead point-in-time decisions, complete feature capture, quote-only CPI scoring, bounded history lookback, monthly cadence, headline/core versions and stored `lead_days` config.
- Deviation: the current merged client exposes `settled_markets` (the review-fixed merger of historical and live settled markets), not the plan's older `merged_settled_markets` name; the CLI test uses the current interface. PR #4's `n_unquoted` behavior is preserved, and CPI decisions are additionally filtered before the runner so market/model Briers share one scoring set.

## Task 6 — Live verification, evidence and tracker

### Live scan smoke — public sources only, no Supabase writes

```text
2026-09-25T21:14:45.539146+00:00 predictions 25 edges 7
Counter({'cpi-v1': 14, 'cpi-core-v1': 11})
KXCPI-26SEP-T0.9 0.0005 None CPI:2026-09@2026-09-24 0.136
KXCPI-26SEP-T0.8 0.0051 None CPI:2026-09@2026-09-24 0.136
KXCPI-26SEP-T0.7 0.0333 0.035 CPI:2026-09@2026-09-24 0.136
edge KXCPI-26SEP-T0.6 cpi_nowcast MACRO SHADOW no 0.77 True
edge KXCPI-26SEP-T0.5 cpi_nowcast MACRO SHADOW no 0.39 True
edge KXCPI-26SEP-T0.4 cpi_nowcast MACRO SHADOW no 0.07 True
```

The latest usable nowcast is labelled 2026-09-24, exactly yesterday ET. Every sampled edge carries `engine=cpi_nowcast`, `edge_type=MACRO`, `gate_status=SHADOW` and `maker=true`.

### Live headline backtest — read-only, no `--record`

```json
{
  "engine": "cpi_nowcast",
  "mode": "taker",
  "n_decisions": 461,
  "n_fills": 110,
  "pnl_after_fees": -3.26,
  "max_drawdown": 4.51,
  "brier_ours": 0.09877,
  "brier_market": 0.07076,
  "gate_status": "SHADOW",
  "gate_reasons": [
    "model Brier 0.09877 is not below market Brier 0.07076",
    "simulated P&L after fees/spread is not positive"
  ],
  "n_unquoted": 0
}
```

### Live core backtest — read-only, no `--record`

```json
{
  "engine": "cpi_nowcast",
  "mode": "taker",
  "n_decisions": 383,
  "n_fills": 83,
  "pnl_after_fees": 7.64,
  "max_drawdown": 2.13,
  "brier_ours": 0.0841,
  "brier_market": 0.07823,
  "gate_status": "SHADOW",
  "gate_reasons": [
    "model Brier 0.0841 is not below market Brier 0.07823"
  ],
  "n_unquoted": 0
}
```

The Briers match the plan's recorded run. Fill counts and P&L differ because this implementation uses the committed `cpi_nowcast.min_edge_pct: 5.0` directly; the plan's earlier figures used a `min_edge_pct=0` wrapper. The honest result is unchanged: both versions stay SHADOW because the model Brier loses to Kalshi.

### Final verification

```text
Full pytest: 384 passed in 4.30s (baseline 353; +31)
Scoped Ruff F401,F811,F821: All checks passed!
git diff --check: clean
shared.config import-boundary grep: no output
```

- Tracker row 6 now says implemented-on-branch/shadow/review-pending and links to the committed plan.
- The plan file was added with trailing whitespace normalized; SHA-256 `f71c93e3ba3896a19615435e87cf1c4126973b24dc0bcf4a503bcc51ccc25fa0`.
- No Supabase write, `--record`, migration, order placement or deployment was performed.

## Controller handover — direct review, stacked prerequisites, no Claude capacity

Kevin reported that Claude subagent capacity is exhausted and explicitly authorized continuing the roadmap as a stacked chain, accepting risk from unreviewed upstream work. This branch therefore starts at PR #5 head `9cc6d86`, not `origin/main`. No upstream PR was merged by this agent.

Check specifically:

- PR #5 must merge before this PR; rebase/retest if its head changes.
- `tradehub/data/cleveland_fed.py` is intentionally force-added because case-insensitive `.gitignore` pattern `Data/` matches the source directory on macOS. Confirm the file is tracked in review output.
- CPI edges deliberately remain outside gate-status promotion and therefore stay SHADOW; do not hide or suppress them.
- `scan.main()` deliberately retains PR #4's exit 1 on any engine failure while still writing weather/gas; the plan's older exit 0 expectation was deliberately not restored.
- The CLI uses current `settled_markets`, bounded `lookback`, quote-only CPI scoring, monthly cadence and per-version `lead_days` config. Verify those interfaces remain after upstream merges.
- Live results are genuinely SHADOW; do not reinterpret or suppress them.
- Step 7b may be stacked from this branch's PR head, but do not merge any PR yourself.

## Review fix 1 — gate every edge by (engine, engine_version)

- RED: existing scan tests failed after `edge_row` began requiring `engine_version` and pair-keyed gate lookup.
- GREEN: `pytest tests/test_scan.py tests/test_scan_cpi.py -q` → 29 passed including a main()-level test proving only `cpi-core-v1` is PROMOTED while `cpi-v1` remains SHADOW.
- `edge_row` requires and writes `engine_version`; status lookup and application use `(engine, engine_version)` pairs collected from every produced edge.

## Review fix 2 — CPI stale-edge cleanup

- Added `cpi_nowcast` to the engine-scoped cleanup allowlist and main cleanup loop.
- Parametrized main() test proves cleanup runs on a due hour and not on a non-due hour; `tests/test_scan_cpi.py` → 9 passed.

## Review fix 3 — isolate malformed CPI markets

- `scan_cpi` catches per-market parse/probability errors, logs them and continues.
- Regression with one malformed and one valid market keeps the valid prediction; `tests/test_scan_cpi.py` → 10 passed.

## Review fix 4 — reject unknown CPI series

- CLI now calls `parser.error` for any `--engine cpi_nowcast --series` outside `CPI_TARGETS`.
- Regression added; `tests/test_backtest_cpi.py` → 7 passed.

## Review fix 5 — delete closed CPI edges on every hourly scan

- Problem: CPI scans only at 08:00/12:00/16:00 ET, so engine-scoped stale cleanup ran
  three times a day. The 08:05 run leaves edges listed until noon for markets that close
  at 08:25, and the 16:00 run leaves 16-hour-old prices on the board overnight.
- Fix: new `remove_closed_cpi_edges(client, now)` deletes any `cpi_nowcast` row in
  `kalshi_edges` whose `expires_at` has passed. `main()` runs it on every hourly scan
  (including non-CPI-due hours) before gate lookup, wrapped in its own failure boundary
  so a cleanup error is reported without failing the scan.
- RED: existing main() tests started failing because the new cleanup hit the stub client.
- GREEN: `pytest tests/test_scan_cpi.py tests/test_scan.py -q` → 33 passed, including
  `test_remove_closed_cpi_edges_deletes_only_past_expiry` (closed market deleted, still-open
  market retained).
- Behaviour note: this is suggest-only and SHADOW, so no money is at risk; the defect was
  that the board showed edges on closed markets.

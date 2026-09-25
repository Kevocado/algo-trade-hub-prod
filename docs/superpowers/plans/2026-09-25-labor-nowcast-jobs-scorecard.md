# Step 8: `labor_nowcast` + Jobs Scorecard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nowcast the BLS **first print** of the monthly change in payrolls, price every open `KXPAYROLLS` strike from it (suggest-only, shadow), backtest it point-in-time against 41 settled Kalshi ladders, and publish a Jobs Scorecard (nowcast vs Kalshi-implied vs first print vs 2nd/3rd estimates vs benchmark, for payrolls and the unemployment rate) as a Supabase table, an API endpoint, and a `/jobs` page.

**Architecture:**
- **Data.** A keyless ALFRED fetcher (`alfredgraph.csv` with `vintage_date=`, 12 vintages per request, cached on disk) supplies payrolls as published at each month end. That is enough to recover every first print, the 2nd and 3rd estimates, and the February benchmark. Claims and JOLTS come from one recent vintage, filtered by their publication lags.
- **Model.** A small ridge regression on inputs public by the end of the reference month: the latest first print, the 3-month average change, and the reference-week changes in initial and continuing claims. It is trained walk-forward on 2010+ first prints, with 2020-03..2021-06 excluded. Sigma is the RMS of the last 36 in-sample residuals, floored at 40k.
- **Pricing.** Probabilities come from `prob_in_interval`, using a strictly-greater threshold snapped to the 1,000-job grid (`greater_threshold`, verified on 961 settled markets).
- **Scan.** `scan_labor` joins the scan at 07, 12 and 17 ET, isolated from the weather and gas steps.
- **Backtest.** `backtest_labor` decides at 07:29 ET on release day and reuses `run_backtest` and the gate.
- **Scorecard.** `build_jobs_scorecard` upserts one `jobs_scorecard` row per (series, month). `GET /api/jobs-scorecard` serves the rows with the service-role client, and a React page renders them.

**Tech Stack:** Python 3.12 (numpy, requests, FastAPI; nothing new in `pyproject.toml`), pytest, Supabase Postgres, React 18 + Vite + recharts + vitest (already in `market_sentiment_tool/package.json`).

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) — §3.1 (`labor_nowcast` row), §3.4 (Jobs Scorecard view), §4 (engines pure, edge layer, predictions ledger), §5a (point-in-time backtests, leakage guard), §6 (promotion gate, monthly minimum 50 contracts), §10 (Jobs Scorecard fixture tests), §11 (≥ 24 historical months). Rollout tracker: [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md), step 8.

## Kevin's decisions (2026-09-25) — apply throughout

- **Losing engines still show their edges, labelled shadow (spec §6).** Never suppress or skip an edge because this engine's backtest or track record loses to the market (it does today: Brier 0.179 vs 0.166).
  - Every edge row this plan writes carries `"engine": "labor_nowcast"` and goes through `tradehub.scripts.scan.edge_row(...)`, which defaults `gate_status` to `"SHADOW"`.
  - `apply_gate_statuses` sets `PROMOTED` only for an engine whose gate passed. PR #4's follow-up changes it to key on each row's `engine`. Before that, it maps every non-WEATHER row to `gas`, which is wrong for this engine.
  - If `edge_row` has no `engine` argument yet when you start, stop and report. Don't work around it.
  - Add a test asserting that every edge `scan_labor` produces has `gate_status == "SHADOW"` when the gate lookup returns nothing.
  - The War Room shows a "Shadow" badge on these edges (PR #4 follow-up). The `/jobs` page shows the engine's gate status next to the nowcast.
- **Deployment target is the VPS (step 5, [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md)), not Azure.**
  - The code ships in the one `ghcr.io/kevocado/tradehub` image: merge to `main`, then `.github/workflows/deploy-tradehub.yml` runs `ssh deploy@$VPS_HOST deploy tradehub <sha>`.
  - `scan_labor` runs inside the hourly `tradehub-scan` timer (`/opt/stack/bin/tradehub-job scan`); its 07/12/17 ET gate relies on that timer firing every hour.
  - `GET /api/jobs-scorecard` and `/jobs` are served by the always-on `tradehub` container at `trade.<domain>`.
  - Create no Azure resources, jobs or secrets.
  - **Azure is legacy.** It is only where the predictor sites run until the cutover, around **2026-10-27**.
- **VPS follow-ups for Kevin** (Task 12 records them; do not edit `vps-stack` yourself):
  - The job containers are throwaway (`docker compose run --rm`), so `TRADEHUB_ALFRED_CACHE` needs a bind mount on the `tradehub` service in `vps-stack/compose.yml`, e.g. `./volumes/tradehub-cache:/cache` with `TRADEHUB_ALFRED_CACHE=/cache/alfred`. Otherwise every run refetches every vintage.
  - The weekly scorecard build needs a `tradehub-jobs-scorecard` service and timer, plus a `jobs-scorecard` case in `bin/tradehub-job`.
  - Check once from the VPS that it can reach ALFRED (Task 12 Step 4); from the Mac it was unreachable to scripts.

## Global Constraints

- **Prerequisites:** steps 3, 4 (PR #3/#4), 2b, 5 and **step 6 (`cpi_nowcast`) merged to `main`**. This plan was validated on `31b66b1` (PR #4's head) without them. Task 0 checks what step 6 added and says exactly what changes if it is present.
- **Handoff contract** (rollout tracker): branch `plan/2026-09-25-labor-nowcast-jobs-scorecard` from `main`; one commit per task, using the message given; every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; evidence report at `docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md`; stop and record, never improvise. Never push, rewrite history, `git clean` or `git reset --hard`, and never edit the spec, other plans or `.env`.
- **Test runs:** `.venv/bin/python` from the repo root, each pytest run prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` (process-only; never write it to a file). Frontend: `cd market_sentiment_tool && npm install` once if `node_modules` is missing. Don't commit a changed `package-lock.json`: run `git checkout -- market_sentiment_tool/package-lock.json` before committing.
- **No network in tests.** Recorded ALFRED vintages live under `tests/fixtures/labor/`. Kalshi and ALFRED are only reached by the CLIs and the scan.
- **Keyless only.** No FRED API key, BLS key, Kalshi key or Supabase key is needed, except Supabase for `--record`, the scorecard upsert, and the scan's ledger writes, as for the existing engines.
- **Dependencies:** nothing outside `pyproject.toml`. numpy and requests are already core dependencies. No `openpyxl`.
- **Engine identity:** `predictions.engine = "labor_nowcast"` (matches `settle_predictions.ENGINES`, cadence `monthly`), `engine_version = "labor-v1"`, `kalshi_edges.edge_type = "MACRO"` (allowed by migration `20260416000005`).
- **Target is the first print** (Kalshi: "Revisions to the underlying made after Expiration will not be accounted for"). Training targets are ALFRED first prints, never the revised series.
- **Migration number `20260416000009`** (`000007` = step 2b, `000008` = step 7b).
- **ACCY-512 reuse:** only the retry-with-backoff pattern is adapted, credited in `default_get_text` as "Adapted from ACCY-512-Final-Project (K. Sigey, 2026)". Its BLS v2 fetcher is not copied: see the design notes below.
- **Suggest-only.** Nothing places orders. The engine starts in SHADOW, and the gate decides promotion.

## Validation already done (2026-09-25)

Every task below was applied, in order, to a fresh detached worktree of `31b66b1`. The plan's code blocks are generated from the same files the replay applied. Each task's RED command failed with the error shown, and each GREEN command passed.
- **Full suite:** **335 passed** (baseline 280, +55). `ruff check --select F401,F811,F821 tradehub tests` reports "All checks passed!".
- **Frontend:** `npx vitest run` gives **9 passed** (3 files), and `npm run build` succeeds, with the same chunk-size warning as before.
- **Kalshi (public, throttled):**
  - `KXPAYROLLS` holds **383 settled markets in 42 events**, from `PROLLS-23MAR` to `KXPAYROLLS-26AUG`, including the legacy `PROLLS-*`/`PAYROLLS-*` tickers and `PROLLS-23DECB`.
  - `KXU3` holds **585 markets in 62 events**, from `U3-21JUL` on.
  - Open now: **39 payroll markets** (`26SEP`/`26OCT`/`26NOV`) and **42 U3 markets**.
  - `greater_threshold` reproduced the settled result of **all 961 settled markets with a numeric value (0 mismatches)**. That includes floors like `199999` ("200,000 or above") and the float `4.099999` (4.1: `KXU3-25FEB-T4.1` settled NO at 4.1).
- **ALFRED:**
  - First prints recovered from month-end vintages match Kalshi's settlement value in **41/41 payroll months** and **43/43 U3 months**. The exception is Oct-2025, which BLS never published because of the shutdown. Kalshi settled `KXU3-25OCT` at 4.4 and `KXPAYROLLS-25OCT` with a blank value (all NO).
  - Dec-2024 reproduces 256 → 307 → 323 (first → 2nd → 3rd), with the Feb-2025 benchmark vintage at 307.
- **Backtest** (`python -m tradehub.scripts.backtest_labor --start 2023-03 --end 2026-08`, taker, core features), 41 months, 370 quoted contracts at 07:29 ET on release day:
  - Brier: **ours 0.1792 vs Kalshi 0.1659**, so the **gate is SHADOW** ("model Brier … is not below market Brier").
  - Taker P&L: **+$2.63** over 201 one-contract fills, with a max drawdown of $11.73.
  - `--mode maker` (a fill only on a later printed trade through the limit): **+$19.50** over 194 fills, max drawdown $6.73. This is suggestive, but it can't override the Brier criterion.
  - Mean absolute error against the first print: **ours 68.5k vs Kalshi-implied mean 68.5k** (a tie). Ours was closer in 20 of 41 months, and the two estimates correlate at 0.79.
  - `--features all` (ADP, JOLTS hires, ghost-jobs gap, post-2021 flag) was **worse**: MAE 75.2k, Brier 0.1833, and one 80–90 bucket off by 11.8pp. The engine therefore uses the core features, and `all` stays in the CLI for research.
- **Scorecard** (`build_jobs_scorecard --since 2023-01 --dry-run`) built **86 rows**: 42 payroll months (2023-03 → 2026-08) and 44 U3 months (2023-01 → 2026-08). Every row has a Kalshi ladder.
  - Payrolls: MAE ours 72.0k vs Kalshi 69.4k; ladder Brier 0.164 vs 0.145; CRPS 50.9 vs 46.7.
  - U3 (naive last-print baseline): MAE 0.102 vs 0.107; Brier 0.0885 vs 0.0850.
  - Estimates present: 41 second estimates, 40 third, 34 benchmarks.
  - First print → latest drift averages **−66.6k per month** (mean absolute 77k), so the early prints in this window were revised down.
- **Smoke:**
  - Live `scan_labor` at 2026-09-25 14:15Z saw 39 open payroll markets and no month due (September hasn't ended). It returned no rows in 0.3 s without touching ALFRED.
  - The same code replayed at 2026-09-04 07:05 ET on `KXPAYROLLS-26AUG`, with the quotes of the time, produced 19 predictions (μ 58k, σ 94k) and 9 MACRO maker edges, all YES. The print was +162k, so all 9 would have won. That is one month and an anecdote, not evidence.
- **Not verified, open:**
  - From this Mac, `alfred.stlouisfed.org` timed out or reset for plain `requests`/`curl` all day, inside and outside the sandbox. The same URLs returned the expected CSVs through a different egress, and those CSVs were used for the cache and the fixtures.
  - Whether the VPS can reach ALFRED is **unverified**. See Task 12, Step 4.

## Design notes (decisions made while planning)

1. **Why ALFRED month-end vintages.**
   - The newest month in any vintage is at its first estimate, so "value in the first vintage that contains month M" is the first print.
   - Month-end vintages are also exactly what was public before the next release, which makes them the point-in-time payroll features.
   - This keeps the list of vintage dates out of the problem (it is unverified keyless), and costs about 17 requests for 2010–2026.
2. **Why no BLS v2 fetcher from ACCY-512.**
   - BLS v2 returns only the current, revised values, never first prints.
   - The keyless tier is 25 queries/day.
   - `bls.gov` returned "Access Denied" to scripted requests.
   - ALFRED covers everything this plan needs. The ACCY repo has no license and appears to be a team repo, so nothing beyond the retry pattern is copied.
3. **Why the core features only.**
   - ADP (vintages start 2022-09), JOLTS hires and the ghost-jobs-discounted openings gap are implemented and testable (`ALL_FEATURES`).
   - Out of sample, they made the nowcast worse (see validation), so `labor-v1` ships with `CORE_FEATURES`.
   - The spec's ghost-jobs hypothesis stays a documented negative result, not a silent omission.
4. **Unemployment rate.** It has no engine in this step. The scorecard's U3 panel uses a naive last-print baseline (`u3-naive-v0`) so the panel has the same layout. A U3 engine is a follow-up once the scorecard shows whether the baseline beats Kalshi on Brier.
5. **Decision time and ladders.**
   - Decisions are made at min(close, 08:30 ET) − 1h.
   - Kalshi ladders are isotonic-fixed mids, taken from quotes no wider than 15¢, at that moment and at the last pre-release quote.
   - `KXPAYROLLS-26JAN` closed at 10:00 ET, after its release, so its "close" ladder is capped at 08:29 ET.
6. **Scan cadence.**
   - `scan_labor` runs at 07, 12 and 17 ET. The `:05` hourly timer makes 07:05 ET the last run before the 08:30 release.
   - It fetches ALFRED only when an open event's reference month has ended.
   - `with_adp=False`, because the core features don't use ADP.

## Review Focus

- **No lookahead.**
  - `labor_features` uses the PAYEMS vintage dated `month_end(month)` and claims/JOLTS strictly by their publication lag.
  - `training_rows` only includes months `< target`.
  - `run_backtest`'s leakage guard passes on every decision, and `test_labor_features_are_point_in_time` checks the same.
- **Strike geometry:** `greater_threshold(199999, 1000) == 199500` and `greater_threshold(4.099999, 0.1) == 4.15`.
- **The scan never crashes on an ALFRED outage:** `run_labor_step` returns `"error: ..."`, and weather/gas are still written.
- **The migration** grants no client write policy, and the API reads with the service role.

## File Structure

- **Create** `tradehub/data/alfred_vintages.py`: keyless ALFRED multi-vintage fetch + parse + disk cache (Task 1)
- **Create** `tradehub/engines/labor.py`: months, decision times, strike geometry, first prints/revisions (Task 2); PIT features + ridge model (Task 3)
- **Create** `tradehub/engines/ladder.py`: ladder → survival curve, implied mean/median, Brier/CRPS (Task 4)
- **Create** `tradehub/data/labor_inputs.py`: which vintages to fetch; walk-forward nowcasts (Task 5)
- **Modify** `tradehub/markets.py`: `event_month` (Task 0, unless step 6 added it)
- **Modify** `tradehub/scripts/scan.py`, `tradehub/config/engines.yaml` (Task 6)
- **Modify** `tradehub/backtest/http.py` (`ThrottledGetJson`); **create** `tradehub/scripts/backtest_labor.py` (Task 7)
- **Create** `market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql`, `tradehub/jobs_scorecard.py` (Task 8)
- **Create** `tradehub/scripts/build_jobs_scorecard.py` (Task 9)
- **Modify** `tradehub/api/main.py` (Task 10)
- **Create** `market_sentiment_tool/src/lib/jobsScorecard.ts`, `src/hooks/useJobsScorecard.ts`, `src/pages/JobsScorecard.tsx`; **modify** `src/App.tsx` (Task 11)
- **Tests:** `tests/test_event_month.py`, `tests/test_alfred_vintages.py`, `tests/test_labor_engine.py`, `tests/test_labor_model.py`, `tests/test_ladder.py`, `tests/labor_fakes.py`, `tests/test_labor_inputs.py`, `tests/test_scan_labor.py`, `tests/test_backtest_labor.py`, `tests/test_jobs_scorecard.py`, `tests/test_build_jobs_scorecard.py`, `tests/test_api_jobs_scorecard.py`, `tests/fixtures/labor/*.csv`, `market_sentiment_tool/src/lib/jobsScorecard.test.ts`
- **Docs (Task 12):** `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, `docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md`

---

## Task 0: Prerequisites check + `event_month`

**Files:**
- Test: `tests/test_event_month.py`
- Modify: `tradehub/markets.py` (only if step 6 has not added `event_month`)

**Interfaces:**
- Produces: `tradehub.markets.event_month(event_ticker: str) -> date` — first day of the reference month; reads only the first five characters of the second ticker segment (`PROLLS-23DECB` -> 2023-12-01). Identical to step 6's function of the same name.

- [ ] **Step 0: Check prerequisites (read-only).** From the repo root on branch `plan/2026-09-25-labor-nowcast-jobs-scorecard` (created from `main`):

```bash
grep -n "def event_month" tradehub/markets.py                       # step 6 adds it; empty = add it in Step 3 below
ls tradehub/data/alfred_vintages.py 2>/dev/null; grep -rln "alfredgraph" tradehub/   # expected: nothing (step 6 dropped ALFRED)
grep -n "cpi_preds\|def main" tradehub/scripts/scan.py              # cpi_preds present = use Task 6's step-6 variant
grep -n "def refresh_track_record" -A2 tradehub/track_record.py     # step 2b: no engine_version argument
ls market_sentiment_tool/supabase/migrations | tail -4               # expect ...000007 (2b), ...000008 (7b); 000009 must be free
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q | tail -1   # baseline: all pass
```

Decisions from the output:
- **`event_month` exists** (step 6's `event_month(event_ticker) -> date`, first five characters of the second ticker segment, same as below): reuse it; skip Task 0 Step 3; keep the test.
- **A keyless ALFRED module already exists** (`tradehub/data/alfred_vintages.py` or an `alfredgraph` fetcher elsewhere): stop and record it in the report. Task 1 would clash; reconcile the interface (`fetch_vintages(series_id, vintages, *, get_text, cache_dir, today) -> dict[date, dict[date, float]]`) before continuing. As of 2026-09-25 step 6's plan does **not** add one (ALFRED was unreachable from its planning machine), so Task 1 creates it.
- **`scan.py` has `cpi_preds`**: follow the step-6 variant in Task 6 Step 3.
- **Anything in the baseline fails**: stop; fix `main` first.


- [ ] **Step 1: Write the failing test**

Create `tests/test_event_month.py`:

```python
from datetime import date

from tradehub.markets import event_month


def test_event_month_handles_current_and_legacy_tickers():
    assert event_month("KXPAYROLLS-26AUG") == date(2026, 8, 1)
    assert event_month("KXU3-26AUG") == date(2026, 8, 1)
    assert event_month("PAYROLLS-24FEB") == date(2024, 2, 1)
    assert event_month("PROLLS-23DECB") == date(2023, 12, 1)  # odd legacy suffix
    assert event_month("U3-21JUL") == date(2021, 7, 1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_event_month.py -q`

Expected: FAIL — ImportError: cannot import name 'event_month' from 'tradehub.markets'. Validated tail:

```
ERROR tests/test_event_month.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.20s
```

- [ ] **Step 3: Implement**

**If Task 0's prerequisite check found `def event_month` already in `tradehub/markets.py` (step 6 merged), skip this step:** the test already passes in Step 2 (expected `1 passed` instead of the error); note that in the report. Otherwise:

In `tradehub/markets.py`, insert directly above the line `def yes_interval(market: KalshiMarket, resolution: float) -> tuple[float, float]:`:

```python
def event_month(event_ticker: str) -> date:
    """'KXPAYROLLS-26AUG' -> date(2026, 8, 1). Tolerates legacy suffixes such as 'PROLLS-23DECB'."""
    return datetime.strptime(event_ticker.split("-")[1][:5], "%y%b").date()
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_event_month.py tests/test_markets.py -q`

Expected: PASS. Validated tail:

```
........                                                                 [100%]
8 passed in 0.02s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_event_month.py tradehub/markets.py
git commit -m "feat: add event_month for month-coded Kalshi tickers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 1: Keyless ALFRED multi-vintage fetcher

**Files:**
- Create: `tradehub/data/alfred_vintages.py`
- Create: `tests/fixtures/labor/payems_2024_2025.csv`, `tests/fixtures/labor/unrate_2026.csv` (recorded ALFRED vintages)
- Test: `tests/test_alfred_vintages.py`

**Interfaces:**
- Produces (`tradehub/data/alfred_vintages.py`):
  - `Vintage = dict[date, float]` (observation date -> value as published on one vintage date)
  - `parse_alfred_csv(text: str) -> dict[date, Vintage]`
  - `fetch_vintages(series_id: str, vintages: list[date], *, get_text=default_get_text, cache_dir: Path | None = DEFAULT_CACHE_DIR, today: date | None = None) -> dict[date, Vintage]` — only dates `< today`; batches 12 vintages per request; caches each vintage as `<cache_dir>/<SERIES>/<YYYY-MM-DD>.csv`
  - `DEFAULT_CACHE_DIR = ~/.cache/tradehub/alfred`, `VINTAGES_PER_REQUEST = 12`, `ALFRED_GRAPH_CSV`

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/labor/payems_2024_2025.csv`:

```csv
observation_date,PAYEMS_20241231,PAYEMS_20250131,PAYEMS_20250228,PAYEMS_20250331
2024-09-01,159025,159025,158314,158314
2024-10-01,159061,159068,158358,158358
2024-11-01,159288,159280,158619,158619
2024-12-01,,159536,158926,158942
2025-01-01,,,159069,159067
2025-02-01,,,,159218
```

Create `tests/fixtures/labor/unrate_2026.csv`:

```csv
observation_date,UNRATE_20260731,UNRATE_20260831,UNRATE_20260924
2026-05-01,4.3,4.3,4.3
2026-06-01,4.2,4.2,4.2
2026-07-01,,4.1,4.1
2026-08-01,,,4.1
```

Create `tests/test_alfred_vintages.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import ALFRED_GRAPH_CSV, VINTAGES_PER_REQUEST, fetch_vintages, parse_alfred_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS_CSV = (FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8")


def test_parse_multi_vintage_csv_skips_blank_cells():
    vintages = parse_alfred_csv(PAYEMS_CSV)
    assert sorted(vintages) == [date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    assert date(2024, 12, 1) not in vintages[date(2024, 12, 31)]  # not yet published
    assert vintages[date(2025, 1, 31)][date(2024, 12, 1)] == 159536.0
    assert vintages[date(2025, 2, 28)][date(2024, 12, 1)] == 158926.0  # after the Feb-2025 benchmark


def test_parse_rejects_non_csv():
    with pytest.raises(ValueError):
        parse_alfred_csv("<html>Access Denied</html>")


def _fake_server(calls):
    def get_text(url, params):
        assert url == ALFRED_GRAPH_CSV
        days = params["vintage_date"].split(",")
        assert params["id"].split(",") == ["PAYEMS"] * len(days)
        calls.append(days)
        header = "observation_date," + ",".join(f"PAYEMS_{d.replace('-', '')}" for d in days)
        return header + "\n2024-01-01," + ",".join(str(100 + i) for i in range(len(days))) + "\n"
    return get_text


def test_fetch_batches_requests_and_caches_past_vintages(tmp_path):
    calls = []
    days = [date(2024, 1, 1) + (date(2024, 1, 2) - date(2024, 1, 1)) * i for i in range(VINTAGES_PER_REQUEST + 3)]
    out = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert [len(c) for c in calls] == [VINTAGES_PER_REQUEST, 3]
    assert out[days[0]] == {date(2024, 1, 1): 100.0}
    assert (tmp_path / "PAYEMS" / f"{days[0].isoformat()}.csv").is_file()
    again = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert again == out and len(calls) == 2  # served from the cache


def test_fetch_never_requests_today_or_future(tmp_path):
    calls = []
    out = fetch_vintages("PAYEMS", [date(2026, 1, 1), date(2026, 2, 1), date(2025, 12, 31)],
                         get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert calls == [["2025-12-31"]]
    assert list(out) == [date(2025, 12, 31)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_alfred_vintages.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.data.alfred_vintages'. Validated tail:

```
ERROR tests/test_alfred_vintages.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.33s
```

- [ ] **Step 3: Implement**

Create `tradehub/data/alfred_vintages.py`:

```python
"""Keyless ALFRED vintages: a FRED series exactly as it stood on past dates.

`alfredgraph.csv?id=S,S,...&vintage_date=d1,d2,...` returns one column per
requested vintage (header `S_YYYYMMDD`), with no API key. Past vintages
never change, so each one is cached on disk as its own small CSV; only
vintages dated before today are cached.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import requests

ALFRED_GRAPH_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
VINTAGES_PER_REQUEST = 12  # alfredgraph returns at most 12 columns per request
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "tradehub" / "alfred"

Vintage = dict[date, float]  # observation date -> value, as published on the vintage date


def default_get_text(url: str, params: dict) -> str:
    """GET with a browser User-Agent and retries (FRED's edge drops bare clients).

    Retry-with-backoff pattern adapted from ACCY-512-Final-Project (K. Sigey, 2026), fetch_with_retry.
    """
    last: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": BROWSER_UA}, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ALFRED request failed after retries: {last}")


def parse_alfred_csv(text: str) -> dict[date, Vintage]:
    """{vintage date: {observation date: value}} from a (multi-)vintage alfredgraph CSV."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0] != "observation_date":
        raise ValueError(f"not an alfredgraph CSV: {text[:80]!r}")
    columns = []
    for name in rows[0][1:]:
        stamp = name.rsplit("_", 1)[-1]
        columns.append(datetime.strptime(stamp, "%Y%m%d").date())
    out: dict[date, Vintage] = {v: {} for v in columns}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        obs = date.fromisoformat(row[0])
        for vintage, cell in zip(columns, row[1:]):
            if cell not in ("", "."):
                out[vintage][obs] = float(cell)
    return out


def _cache_file(cache_dir: Path, series_id: str, vintage: date) -> Path:
    return cache_dir / series_id / f"{vintage.isoformat()}.csv"


def _write_cache(path: Path, series_id: str, vintage: date, values: Vintage) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"observation_date,{series_id}_{vintage.strftime('%Y%m%d')}"]
    lines += [f"{obs.isoformat()},{values[obs]:g}" for obs in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_vintages(
    series_id: str,
    vintages: list[date],
    *,
    get_text: Callable[[str, dict], str] = default_get_text,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    today: date | None = None,
) -> dict[date, Vintage]:
    """The series as published on each requested date, batching uncached dates per request."""
    today = today or datetime.now(timezone.utc).date()
    wanted = sorted({v for v in vintages if v < today})
    out: dict[date, Vintage] = {}
    missing = []
    for vintage in wanted:
        path = _cache_file(cache_dir, series_id, vintage) if cache_dir else None
        if path is not None and path.is_file():
            out[vintage] = parse_alfred_csv(path.read_text(encoding="utf-8"))[vintage]
        else:
            missing.append(vintage)
    for start in range(0, len(missing), VINTAGES_PER_REQUEST):
        chunk = missing[start:start + VINTAGES_PER_REQUEST]
        params = {"id": ",".join([series_id] * len(chunk)), "vintage_date": ",".join(v.isoformat() for v in chunk)}
        parsed = parse_alfred_csv(get_text(ALFRED_GRAPH_CSV, params))
        for vintage in chunk:
            values = parsed.get(vintage, {})
            out[vintage] = values
            if cache_dir is not None and values:
                _write_cache(_cache_file(cache_dir, series_id, vintage), series_id, vintage, values)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_alfred_vintages.py -q`

Expected: PASS. Validated tail:

```
....                                                                     [100%]
4 passed in 0.03s
```

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/labor/payems_2024_2025.csv tests/fixtures/labor/unrate_2026.csv tests/test_alfred_vintages.py tradehub/data/alfred_vintages.py
git commit -m "feat: keyless ALFRED multi-vintage fetcher with a disk cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: labor engine part 1: strike geometry, first prints and revisions

**Files:**
- Create: `tradehub/engines/labor.py`
- Test: `tests/test_labor_engine.py`

**Interfaces:**
- Consumes: `tradehub.markets.parse_market`, `prob_in_interval`, `KalshiMarket`.
- Produces (`tradehub/engines/labor.py`): constants `LABOR_ENGINE_VERSION = "labor-v1"`, `PAYROLL_SERIES = "KXPAYROLLS"`, `U3_SERIES = "KXU3"`, `PAYROLL_RESOLUTION = 1000.0`, `U3_RESOLUTION = 0.1`, `TRAIN_START`, `CORE_FEATURES`, `ALL_FEATURES`; `Vintage`;
  `add_months(month, k) -> date`, `month_end(month) -> date`, `end_of_day_et(day) -> datetime`,
  `pre_release_time(market) -> datetime` (close, capped at 08:29 ET on release day), `decision_time(market) -> datetime` (one hour before min(close, 08:30 ET)),
  `labor_market(raw) -> KalshiMarket` (fills strike from `-T<k>` when the fields are missing), `greater_threshold(floor, resolution) -> float`,
  `payroll_prob(market, mu_k, sigma_k) -> float` (mu/sigma in thousands), `parse_expiration_value(value) -> float | None`,
  `first_prints(vintages, *, change=True) -> dict[date, float]`, `EstimatePath` (first/second/third/benchmark/latest + their vintage dates), `estimate_path(vintages, month, *, change=True) -> EstimatePath`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_labor_engine.py`:

```python
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import (
    add_months,
    decision_time,
    estimate_path,
    first_prints,
    greater_threshold,
    labor_market,
    month_end,
    parse_expiration_value,
    payroll_prob,
    pre_release_time,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS = parse_alfred_csv((FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8"))
UNRATE = parse_alfred_csv((FIXTURES / "unrate_2026.csv").read_text(encoding="utf-8"))


def _raw(ticker, floor="missing", close="2026-09-04T12:29:00Z"):
    raw = {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "open_time": "2026-08-01T00:00:00Z",
           "close_time": close, "title": ticker}
    if floor != "missing":
        raw.update({"strike_type": "greater", "floor_strike": floor})
    return raw


def test_months():
    assert add_months(date(2025, 12, 1), 1) == date(2026, 1, 1)
    assert add_months(date(2026, 1, 1), -13) == date(2024, 12, 1)
    assert month_end(date(2024, 2, 1)) == date(2024, 2, 29)


def test_labor_market_reads_strike_from_ticker_when_fields_missing():
    old = labor_market(_raw("KXPAYROLLS-25JAN-T256000"))
    assert (old.strike_type, old.floor_strike) == ("greater", 256000.0)
    u3 = labor_market(_raw("U3-22JUL-T4.3"))
    assert u3.floor_strike == pytest.approx(4.3) and u3.series_ticker == "U3"
    assert labor_market(_raw("KXPAYROLLS-26AUG-T150000", floor=150000)).floor_strike == 150000.0


@pytest.mark.parametrize("floor, resolution, cut", [
    (200000, 1000.0, 200500.0),    # "above 200,000": a 200,000 print is NO
    (199999, 1000.0, 199500.0),    # "200,000 or above": a 200,000 print is YES
    (-100001, 1000.0, -100500.0),
    (4.1, 0.1, 4.15),              # KXU3-26AUG-T4.1 settled NO at 4.1
    (4.099999, 0.1, 4.15),         # float-stored 4.1 (KXU3-25FEB-T4.1 settled NO at 4.1)
])
def test_greater_threshold(floor, resolution, cut):
    assert greater_threshold(floor, resolution) == pytest.approx(cut)


def test_payroll_prob_uses_thousands():
    market = labor_market(_raw("KXPAYROLLS-26AUG-T150000", floor=150000))
    assert payroll_prob(market, mu_k=150.5, sigma_k=50.0) == pytest.approx(0.5)
    assert payroll_prob(market, mu_k=400.0, sigma_k=50.0) > 0.99


@pytest.mark.parametrize("raw, value", [("162000", 162000.0), ("119,000", 119000.0), ("-23000", -23000.0),
                                        ("4.10", 4.1), ("4.4%", 4.4), ("", None), (None, None)])
def test_parse_expiration_value(raw, value):
    assert parse_expiration_value(raw) == value


def test_first_prints_from_recorded_vintages():
    prints = first_prints(PAYEMS)
    # Kalshi settled KXPAYROLLS-24DEC at 256,000, -25JAN at 143,000, -25FEB at 151,000.
    assert prints == {date(2024, 11, 1): pytest.approx(227.0), date(2024, 12, 1): 256.0,
                      date(2025, 1, 1): 143.0, date(2025, 2, 1): 151.0}
    assert first_prints(UNRATE, change=False) == {date(2026, 6, 1): 4.2, date(2026, 7, 1): 4.1, date(2026, 8, 1): 4.1}


def test_estimate_path_dec_2024_first_second_third_benchmark():
    path = estimate_path(PAYEMS, date(2024, 12, 1))
    assert (path.first, path.first_vintage) == (256.0, date(2025, 1, 31))
    assert (path.second, path.second_vintage) == (307.0, date(2025, 2, 28))
    assert (path.third, path.third_vintage) == (323.0, date(2025, 3, 31))
    assert (path.benchmark, path.benchmark_vintage) == (307.0, date(2025, 2, 28))
    assert (path.latest, path.latest_vintage) == (323.0, date(2025, 3, 31))


def test_estimate_path_unknown_when_oldest_vintage_already_revised():
    assert estimate_path(PAYEMS, date(2024, 10, 1)).first is None


def test_decision_and_pre_release_times():
    normal = labor_market(_raw("KXPAYROLLS-26AUG-T0", floor=0, close="2026-09-04T12:29:00Z"))
    assert decision_time(normal) == datetime(2026, 9, 4, 11, 29, tzinfo=timezone.utc)
    assert pre_release_time(normal) == normal.close_time
    late = labor_market(_raw("KXPAYROLLS-26JAN-T0", floor=0, close="2026-02-11T15:00:00Z"))  # closed after 8:30 ET
    assert decision_time(late) == datetime(2026, 2, 11, 12, 30, tzinfo=timezone.utc)
    assert pre_release_time(late) == datetime(2026, 2, 11, 13, 29, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_engine.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.engines.labor'. Validated tail:

```
ERROR tests/test_labor_engine.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

- [ ] **Step 3: Implement**

Create `tradehub/engines/labor.py`:

```python
"""labor_nowcast engine (pure): P(first-print payrolls > strike) for Kalshi KXPAYROLLS.

Kalshi settles on the BLS *first print* of the seasonally adjusted change in
nonfarm payrolls ("revisions ... after Expiration will not be accounted
for"), so the model is trained on ALFRED first-release vintages, never on
revised history. The nowcast is a small ridge regression on inputs that were
public by the end of the reference month; its residual spread sets sigma.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tradehub.markets import KalshiMarket, parse_market, prob_in_interval

LABOR_ENGINE_VERSION = "labor-v1"
PAYROLL_SERIES = "KXPAYROLLS"
U3_SERIES = "KXU3"
PAYROLL_RESOLUTION = 1000.0  # BLS prints the payroll change in whole thousands of jobs
U3_RESOLUTION = 0.1  # percentage points
COVID_EXCLUDED = (date(2020, 3, 1), date(2021, 6, 1))  # inclusive; months dropped from training
POST_2021 = date(2021, 7, 1)
GHOST_DISCOUNT = 0.5  # weight on JOLTS openings after 2021 ("ghost jobs")
TRAIN_START = date(2010, 1, 1)
MIN_TRAIN_ROWS = 24
RIDGE_LAMBDA = 20.0
SIGMA_WINDOW = 36
MIN_PAYROLL_SIGMA = 40.0  # thousands
JOLTS_LAG_DAYS = 40
CORE_FEATURES = ("pay_last", "pay_3m", "icsa_ref_chg", "ccsa_ref_chg")
ALL_FEATURES = CORE_FEATURES + ("adp_chg", "adp_missing", "jolts_hires_3m", "ghost_gap_3m", "post_2021")

_ET = ZoneInfo("America/New_York")
_STRIKE_SUFFIX = re.compile(r"-T(-?\d+(?:\.\d+)?)$")

Vintage = Mapping[date, float]  # observation month -> value, as published on one vintage date


# ── months ───────────────────────────────────────────────────────────────────

def add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def month_end(month: date) -> date:
    return add_months(month, 1) - timedelta(days=1)


def end_of_day_et(day: date) -> datetime:
    return datetime.combine(day, time(23, 59), _ET)


RELEASE_TIME_ET = time(8, 30)
DECISION_LEAD = timedelta(hours=1)


def _release_moment(market: KalshiMarket) -> datetime:
    release_day = market.close_time.astimezone(_ET).date()
    return datetime.combine(release_day, RELEASE_TIME_ET, _ET).astimezone(market.close_time.tzinfo)


def pre_release_time(market: KalshiMarket) -> datetime:
    """The market's close, but never after the 8:30 ET release on its closing day.

    Most ladders close at 8:25/8:29 ET; a few (e.g. KXPAYROLLS-26JAN, closed
    10:00 ET) kept trading after the number was out.
    """
    return min(market.close_time, _release_moment(market) - timedelta(minutes=1))


def decision_time(market: KalshiMarket) -> datetime:
    """One hour before min(close, 8:30 ET release): 7:29 ET for a normal 8:29 close."""
    return min(market.close_time, _release_moment(market)) - DECISION_LEAD


# ── Kalshi markets ───────────────────────────────────────────────────────────

def labor_market(raw: dict[str, Any]) -> KalshiMarket:
    """parse_market, tolerating older rows with no strike fields (the ticker's -T<k> is a 'greater' floor)."""
    if raw.get("strike_type") is None or raw.get("floor_strike") is None:
        match = _STRIKE_SUFFIX.search(raw["ticker"])
        if match is None:
            raise ValueError(f"no strike in {raw['ticker']!r}")
        raw = {**raw, "strike_type": "greater", "floor_strike": float(match.group(1))}
    return parse_market(raw)


def greater_threshold(floor: float, resolution: float) -> float:
    """Continuous cut for 'strictly greater than floor' on a value printed on a `resolution` grid.

    Kalshi floors sit on the grid (200000, 4.1 -- sometimes stored as 4.099999)
    or one unit below it (199999 means "200,000 or above"). Floats within 1e-4
    grid units of a grid point snap to it; anything else rounds down.
    """
    units = floor / resolution
    nearest = round(units)
    base = nearest if abs(units - nearest) < 1e-4 else math.floor(units)
    return (base + 0.5) * resolution


def payroll_prob(market: KalshiMarket, mu_k: float, sigma_k: float) -> float:
    """P(YES) for a KXPAYROLLS 'greater' market; mu/sigma are in thousands of jobs, strikes in jobs."""
    if market.strike_type != "greater":
        raise ValueError(f"unsupported strike_type {market.strike_type!r} for {market.ticker}")
    cut_k = greater_threshold(market.floor_strike, PAYROLL_RESOLUTION) / 1000.0
    return prob_in_interval(mu_k, sigma_k, (cut_k, math.inf))


def parse_expiration_value(value: Any) -> float | None:
    """Kalshi's expiration_value comes as '162000', '119,000', '-23000', '4.10', '4.4%' or ''."""
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    return float(text) if text else None


# ── ALFRED vintages -> first prints and revisions ──────────────────────────────

def _change(vintage: Vintage, month: date) -> float | None:
    prev = add_months(month, -1)
    if month in vintage and prev in vintage:
        return vintage[month] - vintage[prev]
    return None


def first_prints(vintages: Mapping[date, Vintage], *, change: bool = True) -> dict[date, float]:
    """{month: its value in the vintage where it first appeared} -- the first print.

    Only months newer than the previous vintage's newest month count, so the
    back history inside the earliest vintage (already revised) is never
    mistaken for a first print. change=True gives the month-over-month change
    (payrolls); False gives the level (unemployment rate).
    """
    out: dict[date, float] = {}
    newest: date | None = None
    for _, vintage in sorted(vintages.items()):
        if not vintage:
            continue
        top = max(vintage)
        fresh = [top] if newest is None else [m for m in vintage if newest < m <= top]
        for month in fresh:
            value = _change(vintage, month) if change else vintage[month]
            if value is not None:
                out[month] = value
        newest = top if newest is None else max(newest, top)
    return out


@dataclass(frozen=True)
class EstimatePath:
    first: float | None = None
    first_vintage: date | None = None
    second: float | None = None
    second_vintage: date | None = None
    third: float | None = None
    third_vintage: date | None = None
    benchmark: float | None = None
    benchmark_vintage: date | None = None
    latest: float | None = None
    latest_vintage: date | None = None


def estimate_path(vintages: Mapping[date, Vintage], month: date, *, change: bool = True) -> EstimatePath:
    """First print, 2nd and 3rd monthly estimates, first annual benchmark, and latest value of one month.

    The k-th estimate is the value in the first vintage whose newest month is
    at least month + (k-1). The benchmark is the value in the first vintage
    dated on/after Feb 20 of the following year (BLS benchmarks in the
    February release).
    """
    ordered = sorted(vintages.items())

    def value(vintage: Vintage) -> float | None:
        return _change(vintage, month) if change else vintage.get(month)

    def first_where(predicate) -> tuple[float | None, date | None]:
        for vintage_date, vintage in ordered:
            if vintage and predicate(vintage_date, vintage):
                found = value(vintage)
                if found is not None:
                    return found, vintage_date
        return None, None

    first = first_where(lambda _d, v: max(v) >= month)
    earliest = [v for _, v in ordered if v]
    if earliest and max(earliest[0]) > month:  # already revised in the oldest vintage we hold
        first = (None, None)
    second = first_where(lambda _d, v: max(v) >= add_months(month, 1))
    third = first_where(lambda _d, v: max(v) >= add_months(month, 2))
    bench = first_where(lambda d, _v: d >= date(month.year + 1, 2, 20))
    latest: tuple[float | None, date | None] = (None, None)
    for vintage_date, vintage in reversed(ordered):
        found = value(vintage)
        if found is not None:
            latest = (found, vintage_date)
            break
    return EstimatePath(first[0], first[1], second[0], second[1], third[0], third[1],
                        bench[0], bench[1], latest[0], latest[1])
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_engine.py -q`

Expected: PASS. Validated tail:

```
...................                                                      [100%]
19 passed in 0.03s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_labor_engine.py tradehub/engines/labor.py
git commit -m "feat: labor_nowcast strike geometry and ALFRED first prints/revisions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: labor engine part 2: point-in-time features and the ridge nowcast

**Files:**
- Modify: `tradehub/engines/labor.py` (imports + append)
- Test: `tests/test_labor_model.py`

**Interfaces:**
- Consumes: Task 2's module (extended in place), `tradehub.backtest.pit.Observation`, numpy.
- Produces: `LaborFeatures(month, values: dict[str, float], sources: tuple[Observation, ...])`;
  `labor_features(month, *, payems, icsa, ccsa, hires, openings, adp, release) -> LaborFeatures | None` (payrolls from the `month_end(month)` vintage; claims/JOLTS filtered by publication lag; ADP from the vintage the day before `release`);
  `PayrollModel` (with `.predict(values) -> float`, `.sigma`, `.n_train`, `.features`, `.coef`); `is_trainable(month) -> bool`;
  `fit_payroll_model(rows, features=CORE_FEATURES, lam=RIDGE_LAMBDA) -> PayrollModel`; `training_rows(features_by_month, targets, before) -> list[tuple[LaborFeatures, float]]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_labor_model.py`:

```python
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.pit import Decision, check_no_lookahead
from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import (
    CORE_FEATURES,
    MIN_PAYROLL_SIGMA,
    LaborFeatures,
    add_months,
    fit_payroll_model,
    is_trainable,
    labor_features,
    training_rows,
)

PAYEMS = parse_alfred_csv(
    (Path(__file__).resolve().parent / "fixtures" / "labor" / "payems_2024_2025.csv").read_text(encoding="utf-8"))


def _weekly(start, weeks, value_fn):
    return {start + timedelta(days=7 * i): value_fn(i) for i in range(weeks)}


def test_labor_features_are_point_in_time():
    month = date(2025, 1, 1)
    icsa = _weekly(date(2024, 11, 2), 16, lambda i: 200000.0 + 1000 * i)
    ccsa = _weekly(date(2024, 11, 2), 16, lambda i: 1800000.0 + 5000 * i)
    jolts = {date(2024, m, 1): 5000.0 + m for m in range(1, 13)}
    adp_vintage = {date(2024, 12, 1): 150000.0, date(2025, 1, 1): 150183.0}
    feats = labor_features(month, payems=PAYEMS, icsa=icsa, ccsa=ccsa, hires=jolts, openings=jolts,
                           adp={date(2025, 2, 6): adp_vintage}, release=date(2025, 2, 7))
    assert feats.values["pay_last"] == 256.0  # Dec first print, from the 2025-01-31 vintage
    assert feats.values["pay_3m"] == pytest.approx((256.0 + 212.0 + 43.0) / 3)  # Dec, Nov, Oct in that vintage
    assert feats.values["icsa_ref_chg"] == pytest.approx(5.0)   # weeks ending Jan 18 vs Dec 14
    assert feats.values["adp_chg"] == 183.0 and feats.values["adp_missing"] == 0.0
    decided = datetime(2025, 2, 7, 12, 29, tzinfo=timezone.utc)
    check_no_lookahead(Decision("KXPAYROLLS-25JAN-T0", decided, 0.5, feats.sources))
    assert max(o.published_at for o in feats.sources if not o.name.startswith("ADP")) <= datetime(
        2025, 2, 1, 5, 0, tzinfo=timezone.utc)


def test_labor_features_missing_vintage_is_none():
    assert labor_features(date(2020, 1, 1), payems=PAYEMS, icsa={}, ccsa={}, hires={}, openings={}, adp={},
                          release=date(2020, 2, 7)) is None


def _row(month, pay_last, icsa_chg, target):
    values = {f: 0.0 for f in CORE_FEATURES}
    values.update(pay_last=pay_last, pay_3m=pay_last, icsa_ref_chg=icsa_chg)
    return LaborFeatures(month, values, ()), target


def test_fit_payroll_model_learns_and_skips_covid():
    rows = []
    month = date(2010, 1, 1)
    for i in range(60):
        pay_last = 100.0 + (i % 7) * 20
        icsa = float((i % 5) - 2)
        rows.append(_row(month, pay_last, icsa, pay_last - 10.0 * icsa))
        month = add_months(month, 1)
    rows.append(_row(date(2020, 4, 1), 0.0, 0.0, -20000.0))  # COVID month: must be ignored
    model = fit_payroll_model(rows, lam=0.01)
    assert model.n_train == 60
    probe = {f: 0.0 for f in CORE_FEATURES} | {"pay_last": 150.0, "pay_3m": 150.0, "icsa_ref_chg": 2.0}
    assert model.predict(probe) == pytest.approx(130.0, abs=1.0)
    assert model.sigma == MIN_PAYROLL_SIGMA  # perfect fit -> floor


def test_fit_payroll_model_needs_history_and_training_rows_is_walk_forward():
    with pytest.raises(ValueError):
        fit_payroll_model([_row(date(2015, 1, 1), 1.0, 0.0, 1.0)])
    table = {date(2015, m, 1): _row(date(2015, m, 1), 1.0, 0.0, 1.0)[0] for m in range(1, 7)}
    targets = {m: 1.0 for m in table}
    assert [f.month for f, _ in training_rows(table, targets, before=date(2015, 4, 1))] == [
        date(2015, 1, 1), date(2015, 2, 1), date(2015, 3, 1)]
    assert not is_trainable(date(2021, 6, 1)) and is_trainable(date(2021, 7, 1)) and not is_trainable(date(2009, 12, 1))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_model.py -q`

Expected: FAIL — ImportError: cannot import name 'CORE_FEATURES' from 'tradehub.engines.labor'. Validated tail:

```
ERROR tests/test_labor_model.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.18s
```

- [ ] **Step 3: Implement**

In `tradehub/engines/labor.py`, replace this exact text:

```python
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tradehub.markets import KalshiMarket, parse_market, prob_in_interval
```

with:

```python
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, parse_market, prob_in_interval
```

Append to the end of `tradehub/engines/labor.py`:

```python


# ── point-in-time features ───────────────────────────────────────────────────

@dataclass(frozen=True)
class LaborFeatures:
    month: date
    values: dict[str, float]
    sources: tuple[Observation, ...]  # every input with the moment it became public


def _reference_week(series: Mapping[date, float], month: date, publish_lag_days: int,
                    as_of: datetime) -> tuple[date, float] | None:
    """Latest weekly value for a week ending on/before the 12th-18th reference Saturday and public by `as_of`."""
    candidates = [
        week for week in series
        if week <= date(month.year, month.month, 18)
        and datetime.combine(week + timedelta(days=publish_lag_days), time(8, 30), _ET) <= as_of
    ]
    if not candidates:
        return None
    week = max(candidates)
    return week, series[week]


def _weekly_obs(name: str, week: date, value: float, lag: int) -> Observation:
    return Observation(f"{name}:{week.isoformat()}", value,
                       datetime.combine(week + timedelta(days=lag), time(8, 30), _ET))


def labor_features(
    month: date,
    *,
    payems: Mapping[date, Vintage],
    icsa: Mapping[date, float],
    ccsa: Mapping[date, float],
    hires: Mapping[date, float],
    openings: Mapping[date, float],
    adp: Mapping[date, Vintage],
    release: date,
) -> LaborFeatures | None:
    """Features for reference month `month`, using only what was public by the end of that month.

    Payrolls come from the PAYEMS vintage dated month_end(month). Claims and
    JOLTS come from one recent vintage, filtered by their publication lag.
    ADP for `month` itself comes from the vintage the day before the jobs
    release (ADP publishes two days earlier).
    """
    vintage_day = month_end(month)
    as_of = end_of_day_et(vintage_day)
    pay = payems.get(vintage_day)
    if not pay:
        return None
    latest = max(pay)
    changes = [_change(pay, add_months(latest, -k)) for k in range(3)]
    if any(c is None for c in changes):
        return None
    sources = [Observation(f"PAYEMS@{vintage_day.isoformat()}:{latest.isoformat()}", pay[latest], as_of)]
    icsa_now = _reference_week(icsa, month, 5, as_of)
    icsa_prev = _reference_week(icsa, add_months(month, -1), 5, as_of)
    ccsa_now = _reference_week(ccsa, month, 12, as_of)
    ccsa_prev = None
    if ccsa_now is not None:
        week_prev = ccsa_now[0] - timedelta(days=28)
        if week_prev in ccsa:
            ccsa_prev = (week_prev, ccsa[week_prev])
    if icsa_now is None or icsa_prev is None or ccsa_now is None or ccsa_prev is None:
        return None
    for name, lag, point in (("ICSA", 5, icsa_now), ("ICSA", 5, icsa_prev), ("CCSA", 12, ccsa_now), ("CCSA", 12, ccsa_prev)):
        sources.append(_weekly_obs(name, point[0], point[1], lag))

    jolts_known = [m for m in hires if m in openings
                   and end_of_day_et(month_end(m) + timedelta(days=JOLTS_LAG_DAYS)) <= as_of]
    hires_3m = ghost_3m = 0.0
    if jolts_known:
        j = max(jolts_known)
        j3 = add_months(j, -3)
        if j3 in hires and j3 in openings:
            def gap(m: date) -> float:
                weight = GHOST_DISCOUNT if m >= POST_2021 else 1.0
                return weight * openings[m] - hires[m]
            hires_3m = hires[j] - hires[j3]
            ghost_3m = gap(j) - gap(j3)
            sources.append(Observation(f"JTSHIL:{j.isoformat()}", hires[j],
                                       end_of_day_et(month_end(j) + timedelta(days=JOLTS_LAG_DAYS))))

    adp_vintage_day = release - timedelta(days=1)
    adp_values = adp.get(adp_vintage_day) or {}
    adp_change = _change(adp_values, month) if month == max(adp_values, default=None) else None
    if adp_change is not None:
        sources.append(Observation(f"ADP@{adp_vintage_day.isoformat()}:{month.isoformat()}",
                                   adp_values[month], end_of_day_et(adp_vintage_day)))

    values = {
        "pay_last": changes[0],
        "pay_3m": sum(changes) / 3.0,
        "icsa_ref_chg": (icsa_now[1] - icsa_prev[1]) / 1000.0,
        "ccsa_ref_chg": (ccsa_now[1] - ccsa_prev[1]) / 1000.0,
        "adp_chg": 0.0 if adp_change is None else adp_change,
        "adp_missing": 1.0 if adp_change is None else 0.0,
        "jolts_hires_3m": hires_3m,
        "ghost_gap_3m": ghost_3m,
        "post_2021": 1.0 if month >= POST_2021 else 0.0,
    }
    return LaborFeatures(month, values, tuple(sources))


# ── ridge nowcast ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PayrollModel:
    features: tuple[str, ...]
    center: tuple[float, ...]
    scale: tuple[float, ...]
    intercept: float
    coef: tuple[float, ...]
    sigma: float
    n_train: int

    def predict(self, values: Mapping[str, float]) -> float:
        z = [(values[f] - c) / s for f, c, s in zip(self.features, self.center, self.scale)]
        return self.intercept + float(np.dot(self.coef, z))


def is_trainable(month: date) -> bool:
    return month >= TRAIN_START and not (COVID_EXCLUDED[0] <= month <= COVID_EXCLUDED[1])


def fit_payroll_model(
    rows: Sequence[tuple[LaborFeatures, float]],
    features: Sequence[str] = CORE_FEATURES,
    lam: float = RIDGE_LAMBDA,
) -> PayrollModel:
    """Ridge on standardized features; sigma = RMS of the last SIGMA_WINDOW in-sample residuals."""
    usable = sorted((r for r in rows if is_trainable(r[0].month)), key=lambda r: r[0].month)
    if len(usable) < MIN_TRAIN_ROWS:
        raise ValueError(f"need >= {MIN_TRAIN_ROWS} training months, got {len(usable)}")
    x = np.array([[feats.values[f] for f in features] for feats, _ in usable], dtype=float)
    y = np.array([target for _, target in usable], dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    z = (x - center) / scale
    intercept = float(y.mean())
    coef = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - intercept))
    residuals = y - (intercept + z @ coef)
    recent = residuals[-SIGMA_WINDOW:]
    sigma = max(MIN_PAYROLL_SIGMA, float(np.sqrt(np.mean(recent ** 2))))
    return PayrollModel(tuple(features), tuple(center.tolist()), tuple(scale.tolist()), intercept,
                        tuple(coef.tolist()), sigma, len(usable))


def training_rows(
    features_by_month: Mapping[date, LaborFeatures],
    targets: Mapping[date, float],
    before: date,
) -> list[tuple[LaborFeatures, float]]:
    """(features, first print) for months strictly before `before` -- walk-forward safe."""
    return [(features_by_month[m], targets[m]) for m in sorted(features_by_month)
            if m < before and m in targets]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_engine.py tests/test_labor_model.py -q`

Expected: PASS. Validated tail:

```
.......................                                                  [100%]
23 passed in 0.07s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_labor_model.py tradehub/engines/labor.py
git commit -m "feat: point-in-time labor features and the walk-forward ridge nowcast

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Kalshi ladder distribution + ladder scores

**Files:**
- Create: `tradehub/engines/ladder.py`
- Test: `tests/test_ladder.py`

**Interfaces:**
- Produces (`tradehub/engines/ladder.py`): `Ladder = list[tuple[float, float]]` (cut, P(X > cut)); `usable_mid(bid, ask, max_spread=0.15) -> float | None`;
  `isotonic_survival(points) -> Ladder`; `implied_mean(ladder) -> float`; `implied_median(ladder) -> float`; `normal_ladder(cuts, mu, sigma) -> Ladder`;
  `ladder_brier(ladder, outcome) -> float`; `ladder_crps(ladder, outcome) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ladder.py`:

```python
import pytest

from tradehub.engines.ladder import (
    implied_mean,
    implied_median,
    isotonic_survival,
    ladder_brier,
    ladder_crps,
    normal_ladder,
    usable_mid,
)


def test_usable_mid_drops_one_sided_and_wide_quotes():
    assert usable_mid(0.40, 0.44) == pytest.approx(0.42)
    assert usable_mid(None, 0.44) is None
    assert usable_mid(0.01, 0.99) is None  # no real market


def test_isotonic_survival_pools_violations():
    ladder = isotonic_survival([(100.0, 0.30), (0.0, 0.90), (50.0, 0.40), (75.0, 0.50)])
    assert [c for c, _ in ladder] == [0.0, 50.0, 75.0, 100.0]
    assert [p for _, p in ladder] == pytest.approx([0.90, 0.45, 0.45, 0.30])


def test_implied_mean_and_median_hand_computed():
    ladder = [(0.0, 0.9), (50.0, 0.5), (100.0, 0.1)]
    # gap 50: 0.1 @ -25, 0.4 @ 25, 0.4 @ 75, 0.1 @ 125
    assert implied_mean(ladder) == pytest.approx(0.1 * -25 + 0.4 * 25 + 0.4 * 75 + 0.1 * 125)
    assert implied_median(ladder) == pytest.approx(50.0)
    assert implied_median([(0.0, 0.9), (100.0, 0.3)]) == pytest.approx(0.0 + (0.9 - 0.5) / 0.6 * 100)


def test_ladder_brier_and_crps_hand_computed():
    ladder = [(0.0, 0.9), (50.0, 0.5), (100.0, 0.1)]
    outcome = 60.0  # yes, yes, no
    assert ladder_brier(ladder, outcome) == pytest.approx((0.01 + 0.25 + 0.01) / 3)
    # widths 50 each (edges -25, 25, 75, 125)
    assert ladder_crps(ladder, outcome) == pytest.approx(50 * (0.01 + 0.25 + 0.01))


def test_normal_ladder_is_survival():
    ladder = normal_ladder([100.0, 0.0], mu=0.0, sigma=10.0)
    assert [c for c, _ in ladder] == [0.0, 100.0]
    assert ladder[0][1] == pytest.approx(0.5)
    assert ladder[1][1] < 1e-6
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_ladder.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.engines.ladder'. Validated tail:

```
ERROR tests/test_ladder.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

- [ ] **Step 3: Implement**

Create `tradehub/engines/ladder.py`:

```python
"""Kalshi 'greater than k' ladders as a probability distribution, plus ladder scoring (pure).

A ladder is a list of (cut, P(X > cut)) points. Mid prices across a ladder
are not always monotone, so the implied survival curve is made
non-increasing with pool-adjacent-violators before it is summarized.
"""

from __future__ import annotations

import math
import statistics
from typing import Sequence

from tradehub.markets import prob_in_interval

MAX_SPREAD = 0.15  # a strike whose yes bid/ask spread is wider than this carries no price information

Ladder = list[tuple[float, float]]  # (cut, P(X > cut)), cuts ascending


def usable_mid(yes_bid: float | None, yes_ask: float | None, max_spread: float = MAX_SPREAD) -> float | None:
    if yes_bid is None or yes_ask is None or yes_ask - yes_bid > max_spread:
        return None
    return (yes_bid + yes_ask) / 2.0


def isotonic_survival(points: Sequence[tuple[float, float]]) -> Ladder:
    """Sort by cut and force P(X > cut) non-increasing (equal-weight pool adjacent violators)."""
    ordered = sorted(points)
    blocks: list[list[float]] = []  # [sum, count]
    for _, prob in ordered:
        blocks.append([min(1.0, max(0.0, prob)), 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    fitted: list[float] = []
    for total, count in blocks:
        fitted.extend([total / count] * int(count))
    return [(cut, prob) for (cut, _), prob in zip(ordered, fitted)]


def _typical_gap(ladder: Ladder) -> float:
    gaps = [b[0] - a[0] for a, b in zip(ladder, ladder[1:]) if b[0] > a[0]]
    return statistics.median(gaps) if gaps else 0.0


def implied_mean(ladder: Ladder) -> float:
    """Mean of the step distribution: bin masses at bin midpoints, tails half a typical gap outside."""
    if not ladder:
        raise ValueError("empty ladder")
    gap = _typical_gap(ladder)
    mean = (1.0 - ladder[0][1]) * (ladder[0][0] - gap / 2.0)
    for (lo, p_lo), (hi, p_hi) in zip(ladder, ladder[1:]):
        mean += (p_lo - p_hi) * (lo + hi) / 2.0
    mean += ladder[-1][1] * (ladder[-1][0] + gap / 2.0)
    return mean


def implied_median(ladder: Ladder) -> float:
    """Where the survival curve crosses 0.5 (linear between cuts, clamped to the ladder's ends)."""
    if not ladder:
        raise ValueError("empty ladder")
    if ladder[0][1] <= 0.5:
        return ladder[0][0]
    for (lo, p_lo), (hi, p_hi) in zip(ladder, ladder[1:]):
        if p_lo >= 0.5 >= p_hi:
            return lo if p_lo == p_hi else lo + (p_lo - 0.5) / (p_lo - p_hi) * (hi - lo)
    return ladder[-1][0]


def normal_ladder(cuts: Sequence[float], mu: float, sigma: float) -> Ladder:
    return [(cut, prob_in_interval(mu, sigma, (cut, math.inf))) for cut in sorted(cuts)]


def ladder_brier(ladder: Ladder, outcome: float) -> float:
    """Mean Brier score over the ladder's strikes against the settled value."""
    if not ladder:
        raise ValueError("empty ladder")
    return sum((p - (1.0 if outcome > cut else 0.0)) ** 2 for cut, p in ladder) / len(ladder)


def ladder_crps(ladder: Ladder, outcome: float) -> float:
    """CRPS restricted to the ladder: sum of per-strike Brier terms times each strike's spacing.

    Same units as the cuts, so ours and Kalshi's are comparable when scored on the same cuts.
    """
    if not ladder:
        raise ValueError("empty ladder")
    cuts = [cut for cut, _ in ladder]
    gap = _typical_gap(ladder) or 1.0
    edges = [cuts[0] - gap / 2.0] + [(a + b) / 2.0 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + gap / 2.0]
    return sum((p - (1.0 if outcome > cut else 0.0)) ** 2 * (edges[i + 1] - edges[i])
               for i, (cut, p) in enumerate(ladder))
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_ladder.py -q`

Expected: PASS. Validated tail:

```
.....                                                                    [100%]
5 passed in 0.02s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_ladder.py tradehub/engines/ladder.py
git commit -m "feat: Kalshi ladder implied distribution and ladder scoring

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Labor inputs loader + walk-forward nowcasts

**Files:**
- Create: `tradehub/data/labor_inputs.py`
- Create: `tests/labor_fakes.py`
- Test: `tests/test_labor_inputs.py`

**Interfaces:**
- Consumes: `fetch_vintages` (Task 1), `labor_features`, `fit_payroll_model`, `training_rows`, `first_prints` (Tasks 2–3).
- Produces (`tradehub/data/labor_inputs.py`): `LaborInputs(payems, unrate, adp, icsa, ccsa, hires, openings)`;
  `load_labor_inputs(*, first_month, last_month, releases, as_of, unrate_from=None, with_adp=True, fetch=fetch_vintages, cache_dir=None) -> LaborInputs` (cache dir defaults to `$TRADEHUB_ALFRED_CACHE` or `~/.cache/tradehub/alfred`);
  `guess_release_date(month) -> date`, `release_date(month, releases) -> date`; `Nowcast(month, mu, sigma, model, features)`;
  `feature_table(inputs, months, releases) -> dict[date, LaborFeatures]`; `payroll_nowcasts(inputs, targets_months, releases, *, train_from, features=CORE_FEATURES) -> dict[date, Nowcast]`.
- Test helper `tests/labor_fakes.py`: `synthetic_inputs() -> LaborInputs`, `true_change(month) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/labor_fakes.py`:

```python
"""Synthetic, internally consistent labor inputs for labor_nowcast tests (no network)."""

from __future__ import annotations

import math
from datetime import date, timedelta

from tradehub.data.labor_inputs import LaborInputs
from tradehub.engines.labor import add_months, month_end

FIRST = date(2009, 1, 1)
LAST = date(2014, 6, 1)


def true_change(month: date) -> float:
    i = (month.year - 2009) * 12 + month.month
    return round(150 + 60 * math.sin(i / 3.0))


def _months(first: date, last: date) -> list[date]:
    out, m = [], first
    while m <= last:
        out.append(m)
        m = add_months(m, 1)
    return out


def synthetic_inputs() -> LaborInputs:
    """PAYEMS vintages at each month end hold data through the prior month (first prints never revised).

    Initial claims in each reference week are 400k - 500 * that month's change, so
    the claims change carries the surprise in the payroll change.
    """
    months = _months(FIRST, LAST)
    levels, level = {}, 130000.0
    for m in months:
        level += true_change(m)
        levels[m] = level
    payems = {}
    for m in months[1:]:
        payems[month_end(m)] = {o: levels[o] for o in months if o < m}
    icsa, ccsa = {}, {}
    saturday = date(2008, 12, 6)
    while saturday <= date(2014, 9, 1):
        ref = saturday.replace(day=1)
        icsa[saturday] = 400000.0 - 500.0 * true_change(ref)
        ccsa[saturday] = 1800000.0
        saturday += timedelta(days=7)
    hires = {m: 5000.0 for m in months}
    openings = {m: 6000.0 for m in months}
    return LaborInputs(payems=payems, unrate={}, adp={}, icsa=icsa, ccsa=ccsa, hires=hires, openings=openings)
```

Create `tests/test_labor_inputs.py`:

```python
from datetime import date

from labor_fakes import synthetic_inputs, true_change
from tradehub.data.labor_inputs import (
    guess_release_date,
    load_labor_inputs,
    payroll_nowcasts,
    release_date,
)


def test_guess_release_date_is_first_friday_of_next_month():
    assert guess_release_date(date(2026, 8, 1)) == date(2026, 9, 4)
    assert guess_release_date(date(2025, 7, 1)) == date(2025, 8, 1)
    assert release_date(date(2025, 11, 1), {date(2025, 11, 1): date(2025, 12, 16)}) == date(2025, 12, 16)


def test_load_labor_inputs_requests_point_in_time_vintages():
    calls = {}

    def fetch(series, days, *, cache_dir, today):
        calls[series] = (days, today)
        return {d: {date(2000, 1, 1): 1.0} for d in days}

    inputs = load_labor_inputs(first_month=date(2026, 6, 1), last_month=date(2026, 8, 1),
                               releases={date(2026, 8, 1): date(2026, 9, 4)}, as_of=date(2026, 9, 25),
                               fetch=fetch, cache_dir=None)
    assert calls["PAYEMS"][0] == [date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
                                  date(2026, 9, 24)]
    assert calls["ADPMNUSNERSA"][0] == [date(2026, 7, 2), date(2026, 8, 6), date(2026, 9, 3)]  # release - 1 day
    for series in ("ICSA", "CCSA", "JTSHIL", "JTSJOL"):
        assert calls[series][0] == [date(2026, 9, 24)]
    assert "UNRATE" not in calls and inputs.unrate == {}
    assert all(today == date(2026, 9, 25) for _, today in calls.values())


def test_load_labor_inputs_fetches_unrate_when_asked():
    seen = {}

    def fetch(series, days, *, cache_dir, today):
        seen[series] = days
        return {}

    load_labor_inputs(first_month=date(2026, 7, 1), last_month=date(2026, 8, 1), releases={},
                      as_of=date(2026, 9, 25), unrate_from=date(2026, 7, 1), fetch=fetch, cache_dir=None)
    assert seen["UNRATE"] == [date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 24)]


def test_load_labor_inputs_can_skip_adp():
    seen = {}

    def fetch(series, days, *, cache_dir, today):
        seen[series] = days
        return {}

    inputs = load_labor_inputs(first_month=date(2026, 7, 1), last_month=date(2026, 8, 1), releases={},
                               as_of=date(2026, 9, 25), with_adp=False, fetch=fetch, cache_dir=None)
    assert "ADPMNUSNERSA" not in seen and inputs.adp == {}


def test_payroll_nowcasts_walk_forward_on_synthetic_inputs():
    inputs = synthetic_inputs()
    target = date(2013, 6, 1)
    nowcasts = payroll_nowcasts(inputs, [target], {}, train_from=date(2010, 1, 1))
    nc = nowcasts[target]
    assert nc.model.n_train == 41  # 2010-01 .. 2013-05: never the target month itself
    naive = abs(nc.features.values["pay_3m"] - true_change(target))
    assert abs(nc.mu - true_change(target)) < naive  # claims carry the surprise
    assert nc.sigma >= 40.0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_inputs.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.data.labor_inputs'. Validated tail:

```
ERROR tests/test_labor_inputs.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.21s
```

- [ ] **Step 3: Implement**

Create `tradehub/data/labor_inputs.py`:

```python
"""Everything labor_nowcast reads, fetched once per run from keyless ALFRED vintages.

- PAYEMS: one vintage per month end (what was known the day before the
  earliest possible release), plus the latest vintage for revisions.
- UNRATE: the same month-end vintages, for the Jobs Scorecard's U3 panel.
- ADPMNUSNERSA: the vintage the day before each jobs release (vintages start 2022-09).
- ICSA, CCSA, JTSHIL, JTSJOL: the latest vintage; their publication lags
  are applied in tradehub.engines.labor.labor_features.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence

from tradehub.data.alfred_vintages import DEFAULT_CACHE_DIR, Vintage, fetch_vintages
from tradehub.engines.labor import (
    CORE_FEATURES,
    LaborFeatures,
    PayrollModel,
    add_months,
    first_prints,
    fit_payroll_model,
    labor_features,
    month_end,
    training_rows,
)

ADP_FIRST_MONTH = date(2022, 9, 1)
CACHE_ENV = "TRADEHUB_ALFRED_CACHE"


@dataclass(frozen=True)
class LaborInputs:
    payems: dict[date, Vintage]
    unrate: dict[date, Vintage]
    adp: dict[date, Vintage]
    icsa: Vintage
    ccsa: Vintage
    hires: Vintage
    openings: Vintage


def cache_dir_from_env() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR)


def guess_release_date(month: date) -> date:
    """First Friday of the following month -- the usual Employment Situation date."""
    first = add_months(month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7)


def release_date(month: date, releases: Mapping[date, date]) -> date:
    return releases.get(month) or guess_release_date(month)


def _months(first: date, last: date) -> list[date]:
    out, month = [], first
    while month <= last:
        out.append(month)
        month = add_months(month, 1)
    return out


def load_labor_inputs(
    *,
    first_month: date,
    last_month: date,
    releases: Mapping[date, date],
    as_of: date,
    unrate_from: date | None = None,
    with_adp: bool = True,
    fetch: Callable[..., dict[date, Vintage]] = fetch_vintages,
    cache_dir: Path | None = None,
) -> LaborInputs:
    """Fetch the vintages needed for reference months first_month..last_month, as known on `as_of`.

    UNRATE (Jobs Scorecard only) is fetched from `unrate_from` on; None skips it.
    with_adp=False skips ADP (the core feature set does not use it; each month is a vintage).
    """
    cache = cache_dir if cache_dir is not None else cache_dir_from_env()
    latest = as_of - timedelta(days=1)
    month_ends = [month_end(m) for m in _months(add_months(first_month, -1), last_month) if month_end(m) < as_of]
    unrate_ends = [] if unrate_from is None else [d for d in month_ends if d >= month_end(unrate_from)]
    adp_days = [release_date(m, releases) - timedelta(days=1)
                for m in _months(max(first_month, ADP_FIRST_MONTH), last_month)]

    def get(series: str, days: list[date]) -> dict[date, Vintage]:
        return fetch(series, sorted({d for d in days if d < as_of}), cache_dir=cache, today=as_of)

    def latest_of(series: str) -> Vintage:
        return get(series, [latest]).get(latest, {})

    return LaborInputs(
        payems=get("PAYEMS", month_ends + [latest]),
        unrate=get("UNRATE", unrate_ends + [latest]) if unrate_from is not None else {},
        adp=get("ADPMNUSNERSA", adp_days) if with_adp else {},
        icsa=latest_of("ICSA"),
        ccsa=latest_of("CCSA"),
        hires=latest_of("JTSHIL"),
        openings=latest_of("JTSJOL"),
    )


@dataclass(frozen=True)
class Nowcast:
    month: date
    mu: float  # thousands of jobs, first print
    sigma: float
    model: PayrollModel
    features: LaborFeatures


def feature_table(inputs: LaborInputs, months: Sequence[date], releases: Mapping[date, date]) -> dict[date, LaborFeatures]:
    out = {}
    for month in months:
        feats = labor_features(month, payems=inputs.payems, icsa=inputs.icsa, ccsa=inputs.ccsa, hires=inputs.hires,
                               openings=inputs.openings, adp=inputs.adp, release=release_date(month, releases))
        if feats is not None:
            out[month] = feats
    return out


def payroll_nowcasts(
    inputs: LaborInputs,
    targets_months: Sequence[date],
    releases: Mapping[date, date],
    *,
    train_from: date,
    features: Sequence[str] = CORE_FEATURES,
) -> dict[date, Nowcast]:
    """Walk-forward nowcast of each target month, fit only on months before it."""
    table = feature_table(inputs, _months(train_from, max(targets_months)), releases)
    prints = first_prints(inputs.payems)
    out = {}
    for month in targets_months:
        feats = table.get(month)
        if feats is None:
            continue
        model = fit_payroll_model(training_rows(table, prints, before=month), features)
        out[month] = Nowcast(month, model.predict(feats.values), model.sigma, model, feats)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_labor_inputs.py -q`

Expected: PASS. Validated tail:

```
.....                                                                    [100%]
5 passed in 0.08s
```

- [ ] **Step 5: Commit**

```bash
git add tests/labor_fakes.py tests/test_labor_inputs.py tradehub/data/labor_inputs.py
git commit -m "feat: load labor_nowcast inputs and walk-forward payroll nowcasts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Scan KXPAYROLLS (suggest-only, isolated)

**Files:**
- Modify: `tradehub/scripts/scan.py`
- Modify: `tradehub/config/engines.yaml`
- Test: `tests/test_scan_labor.py`

**Interfaces:**
- Consumes: `load_labor_inputs`, `payroll_nowcasts` (Task 5); `payroll_prob`, `month_end`, `TRAIN_START` (Task 2); `event_month` (Task 0); `evaluate_edge`, `edge_row`, `build_prediction_row`.
- Produces (`tradehub/scripts/scan.py`): `scan_labor(live, now, cfg, *, inputs_fn=load_labor_inputs) -> (predictions, edges)` — engine `labor_nowcast`, edge_type `MACRO`, only months whose reference month has ended and whose markets are still open;
  `LABOR_SCAN_HOURS_ET = (7, 12, 17)`, `labor_scan_due(now) -> bool`, `run_labor_step(live, now, cfg, *, scan_fn=None) -> (predictions, edges, status)` with status `skipped` / `ok` / `error: ...`; summary key `"labor_nowcast"`.
- Config: `labor_nowcast` block in `tradehub/config/engines.yaml`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_labor.py`:

```python
from datetime import date, datetime, timezone

from labor_fakes import synthetic_inputs
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.labor import labor_market
from tradehub.scripts import scan

QUOTE = Quote(yes_bid=0.02, yes_ask=0.05, yes_bid_size=10.0, yes_ask_size=10.0)


def _lm(month_tag, floor, close):
    ticker = f"KXPAYROLLS-{month_tag}-T{floor}"
    return LiveMarket(labor_market({"ticker": ticker, "event_ticker": f"KXPAYROLLS-{month_tag}", "strike_type": "greater",
                                    "floor_strike": floor, "open_time": "2014-05-01T00:00:00Z", "close_time": close,
                                    "title": ticker}), QUOTE)


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def test_scan_labor_predicts_only_months_that_have_ended():
    now = datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc)
    may = [_lm("14MAY", 0, "2014-06-06T12:29:00Z"), _lm("14MAY", 150000, "2014-06-06T12:29:00Z")]
    june = [_lm("14JUN", 0, "2014-07-03T12:29:00Z")]  # June has not ended: no nowcast yet
    calls = []

    def inputs_fn(**kwargs):
        calls.append(kwargs)
        return synthetic_inputs()

    preds, edges = scan.scan_labor(FakeLive(may + june), now, EngineConfig(min_edge_pct=5.0), inputs_fn=inputs_fn)
    assert {p["market_ticker"] for p in preds} == {"KXPAYROLLS-14MAY-T0", "KXPAYROLLS-14MAY-T150000"}
    assert all(p["engine"] == "labor_nowcast" and p["engine_version"] == "labor-v1" for p in preds)
    assert calls[0]["releases"] == {date(2014, 5, 1): date(2014, 6, 6)} and calls[0]["as_of"] == date(2014, 6, 3)
    assert calls[0]["with_adp"] is False  # the core feature set does not use ADP
    assert preds[0]["raw_payload"]["month"] == "2014-05-01" and preds[0]["raw_payload"]["n_train"] > 24
    zero = next(p for p in preds if p["market_ticker"].endswith("T0"))
    assert zero["our_prob"] > 0.9
    assert all(e["edge_type"] == "MACRO" for e in edges)
    assert {e["market_ticker"] for e in edges} >= {"KXPAYROLLS-14MAY-T0"}  # P(>0) >> 0.05 ask


def test_scan_labor_skips_fetching_when_nothing_is_due():
    def inputs_fn(**_kwargs):
        raise AssertionError("must not fetch")

    june = [_lm("14JUN", 0, "2014-07-03T12:29:00Z")]
    now = datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc)
    assert scan.scan_labor(FakeLive(june), now, EngineConfig(min_edge_pct=5.0), inputs_fn=inputs_fn) == ([], [])


def test_repo_config_has_labor_nowcast():
    cfg = load_engine_config("labor_nowcast")
    assert cfg.min_edge_pct > 0 and cfg.prefer_maker is True


def test_run_labor_step_runs_three_times_a_day_and_isolates_errors():
    live = FakeLive([])
    at_7 = datetime(2026, 10, 2, 11, 5, tzinfo=timezone.utc)   # 07:05 ET
    at_9 = datetime(2026, 10, 2, 13, 5, tzinfo=timezone.utc)   # 09:05 ET
    cfg = EngineConfig(min_edge_pct=5.0)

    def boom(*_a, **_k):
        raise RuntimeError("ALFRED down")

    assert scan.run_labor_step(live, at_9, cfg, scan_fn=boom) == ([], [], "skipped")
    assert scan.run_labor_step(live, at_7, cfg, scan_fn=lambda *a: ([{"p": 1}], [])) == ([{"p": 1}], [], "ok")
    preds, edges, status = scan.run_labor_step(live, at_7, cfg, scan_fn=boom)
    assert (preds, edges) == ([], []) and status.startswith("error: RuntimeError")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan_labor.py -q`

Expected: FAIL — AttributeError: module 'tradehub.scripts.scan' has no attribute 'scan_labor' (and KeyError: 'labor_nowcast' for the config test). Validated tail:

```
FAILED tests/test_scan_labor.py::test_repo_config_has_labor_nowcast - KeyErro...
FAILED tests/test_scan_labor.py::test_run_labor_step_runs_three_times_a_day_and_isolates_errors
4 failed in 0.38s
```

- [ ] **Step 3: Implement**

**Step-6 variant.** If step 6 is merged, `main()` already contains the `cpi_preds`/`cpi_status` block and the two `main()` replacements at the end of this step won't match. Use these two instead (validated by applying them to step 6's `main()` text):

```python
# replace
    record_predictions(get_client(), weather_preds + gas_preds + cpi_preds)
    upsert_opportunities(weather_edges + gas_edges + cpi_edges)
# with
    labor_preds, labor_edges, labor_status = run_labor_step(live, now, load_engine_config("labor_nowcast"))
    record_predictions(get_client(), weather_preds + gas_preds + cpi_preds + labor_preds)
    upsert_opportunities(weather_edges + gas_edges + cpi_edges + labor_edges)
```

and add, directly below the `"cpi_nowcast": {...}` summary line:

```python
        "labor_nowcast": {"predictions": len(labor_preds), "edges": len(labor_edges), "status": labor_status},
```

The import edits and the `scan_labor`/`run_labor_step` insertion are identical in both variants. If step 6 already changed the module docstring's first line, skip that replacement. If `scan.py` already imports `event_month` from `tradehub.markets`, keep that import line as it is instead of replacing it.

In `tradehub/scripts/scan.py`, replace this exact text:

```python
"""One-shot scan (suggest-only): predict every open weather/gas market, flag trade-worthy edges.
```

with:

```python
"""One-shot scan (suggest-only): predict every open weather/gas/payrolls market, flag trade-worthy edges.
```

In `tradehub/scripts/scan.py`, replace this exact text:

```python
from tradehub.data.kalshi_live import KalshiLive
```

with:

```python
from tradehub.data.kalshi_live import KalshiLive
from tradehub.data.labor_inputs import load_labor_inputs, payroll_nowcasts
```

In `tradehub/scripts/scan.py`, replace this exact text:

```python
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, ErrorModel, weather_prob
```

with:

```python
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_SERIES,
    TRAIN_START,
    month_end,
    payroll_prob,
)
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, ErrorModel, weather_prob
```

In `tradehub/scripts/scan.py`, replace this exact text:

```python
from tradehub.markets import KalshiMarket, event_date, market_url
```

with:

```python
from tradehub.markets import KalshiMarket, event_date, event_month, market_url
```

In `tradehub/scripts/scan.py`, insert directly above the line `def main() -> int:`:

```python
def scan_labor(
    live, now: datetime, cfg: EngineConfig, *, inputs_fn: Callable[..., Any] = load_labor_inputs,
) -> tuple[list[dict], list[dict]]:
    """Nowcast the next jobs report once its reference month has ended; predict every open KXPAYROLLS strike."""
    by_month: dict = defaultdict(list)
    for lm in live.open_markets(PAYROLL_SERIES):
        month = event_month(lm.market.event_ticker)
        if month_end(month) < now.astimezone(ZoneInfo("America/New_York")).date() and lm.market.close_time > now:
            by_month[month].append(lm)
    if not by_month:
        return [], []
    releases = {m: min(lm.market.close_time for lm in lms).astimezone(ZoneInfo("America/New_York")).date()
                for m, lms in by_month.items()}
    inputs = inputs_fn(first_month=TRAIN_START, last_month=max(by_month), releases=releases, as_of=now.date(),
                       with_adp=False)
    nowcasts = payroll_nowcasts(inputs, sorted(by_month), releases, train_from=TRAIN_START)
    predictions: list[dict] = []
    edges: list[dict] = []
    for month, markets in sorted(by_month.items()):
        nc = nowcasts.get(month)
        if nc is None:
            continue
        payload = {"month": month.isoformat(), "mu_k": round(nc.mu, 2), "sigma_k": round(nc.sigma, 2),
                   "features": nc.features.values, "n_train": nc.model.n_train,
                   "coef": dict(zip(nc.model.features, nc.model.coef))}
        for lm in markets:
            prob = payroll_prob(lm.market, nc.mu, nc.sigma)
            predictions.append(build_prediction_row(
                market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="labor_nowcast",
                as_of=now, engine_version=LABOR_ENGINE_VERSION, raw_payload=payload,
            ))
            suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                       prefer_maker=cfg.prefer_maker)
            if suggestion:
                edges.append(edge_row(lm.market, suggestion, "MACRO"))
    return predictions, edges


LABOR_SCAN_HOURS_ET = (7, 12, 17)  # the :05 timer's 07:05 ET run is the last one before the 08:30 release


def labor_scan_due(now: datetime) -> bool:
    return now.astimezone(ZoneInfo("America/New_York")).hour in LABOR_SCAN_HOURS_ET


def run_labor_step(
    live, now: datetime, cfg: EngineConfig, *, scan_fn: Callable[..., tuple[list[dict], list[dict]]] | None = None,
) -> tuple[list[dict], list[dict], str]:
    """scan_labor three times a day, isolated: an ALFRED or Kalshi outage returns a status, never raises."""
    if not labor_scan_due(now):
        return [], [], "skipped"
    try:
        predictions, edges = (scan_fn or scan_labor)(live, now, cfg)
    except Exception as exc:  # noqa: BLE001 - isolate the engine, report the error
        return [], [], f"error: {exc!r}"
    return predictions, edges, "ok"
```

In `tradehub/scripts/scan.py`, replace this exact text:

```python
    record_predictions(get_client(), weather_preds + gas_preds)
    upsert_opportunities(weather_edges + gas_edges)
```

with:

```python
    labor_preds, labor_edges, labor_status = run_labor_step(live, now, load_engine_config("labor_nowcast"))
    record_predictions(get_client(), weather_preds + gas_preds + labor_preds)
    upsert_opportunities(weather_edges + gas_edges + labor_edges)
```

In `tradehub/scripts/scan.py`, replace this exact text:

```python
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
```

with:

```python
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
        "labor_nowcast": {"predictions": len(labor_preds), "edges": len(labor_edges), "status": labor_status},
```

Append to the end of `tradehub/config/engines.yaml`:

```yaml
labor_nowcast:
  min_edge_pct: 5.0      # monthly, thin evidence: same bar as weather until the gate says otherwise
  prefer_maker: true
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan_labor.py tests/test_scan.py tests/test_engine_config.py -q`

Expected: PASS. `tests/test_scan.py` and `tests/test_engine_config.py` must keep passing. Validated tail:

```
...........                                                              [100%]
11 passed in 0.39s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_scan_labor.py tradehub/config/engines.yaml tradehub/scripts/scan.py
git commit -m "feat: scan KXPAYROLLS with labor_nowcast (MACRO edges, isolated, 3 runs a day)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Point-in-time backtest CLI

**Files:**
- Modify: `tradehub/backtest/http.py`
- Create: `tradehub/scripts/backtest_labor.py`
- Test: `tests/test_backtest_labor.py`

**Interfaces:**
- Consumes: `run_backtest`, `MarketHistory`, `quote_at`, `build_backtest_run_row`, `data_snapshot_hash`, `record_backtest_run` (step 3); Tasks 2–5.
- Produces: `tradehub.backtest.http.ThrottledGetJson(min_interval=0.25, retries=5, get=requests.get, sleep=time.sleep, clock=time.monotonic)` — a `get_json` for `KalshiHistoryClient`;
  `tradehub/scripts/backtest_labor.py`: `release_dates(raws) -> dict[date, date]`, `settled_ladder(raws, start, end) -> list[dict]`, `build_labor_decisions(markets, nowcasts) -> list[Decision]`,
  `labor_histories(client, markets, results, mode) -> dict[str, MarketHistory]`, `quoted_only(decisions, histories) -> list[Decision]`, `kalshi_implied_means(markets, histories) -> dict[date, float]`, and the CLI
  `python -m tradehub.scripts.backtest_labor --end YYYY-MM [--start YYYY-MM] [--mode taker|maker] [--features core|all] [--cache-dir DIR] [--record]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backtest_labor.py`:

```python
from datetime import date, timedelta

import pytest

from labor_fakes import synthetic_inputs
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.labor_inputs import payroll_nowcasts
from tradehub.engines.labor import labor_market
from tradehub.scripts.backtest_labor import (
    build_labor_decisions,
    kalshi_implied_means,
    quoted_only,
    release_dates,
    settled_ladder,
)


def _raw(tag, floor, result, value, close):
    return {"ticker": f"KXPAYROLLS-{tag}-T{floor}", "event_ticker": f"KXPAYROLLS-{tag}", "strike_type": "greater",
            "floor_strike": floor, "open_time": "2013-01-01T00:00:00Z", "close_time": close, "title": "jobs",
            "result": result, "expiration_value": value}


RAWS = [
    _raw("13MAY", 0, "yes", "175,000", "2013-06-07T12:29:00Z"),
    _raw("13MAY", 200000, "no", "175,000", "2013-06-07T12:29:00Z"),
    _raw("13JUN", 0, "yes", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUN", 100000, "yes", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUN", 150000, "no", "105000", "2013-07-05T12:29:00Z"),
    _raw("13JUL", 0, "no", "", "2013-08-02T12:29:00Z"),  # no first print published: dropped
]


def test_release_dates_and_settled_ladder():
    assert release_dates(RAWS)[date(2013, 6, 1)] == date(2013, 7, 5)
    kept = settled_ladder(RAWS, date(2013, 6, 1), date(2013, 7, 1))
    assert [r["ticker"] for r in kept] == ["KXPAYROLLS-13JUN-T0", "KXPAYROLLS-13JUN-T100000", "KXPAYROLLS-13JUN-T150000"]


def _history(market, result, bid, ask):
    at = market.close_time - timedelta(hours=2)
    return MarketHistory(market.ticker, result, market.close_time, [Candle(at, bid, ask, 10.0)], [])


def test_labor_backtest_end_to_end_is_leak_free():
    raws = settled_ladder(RAWS, date(2013, 5, 1), date(2013, 6, 1))
    markets = [labor_market(r) for r in raws]
    nowcasts = payroll_nowcasts(synthetic_inputs(), [date(2013, 5, 1), date(2013, 6, 1)], {}, train_from=date(2010, 1, 1))
    decisions = build_labor_decisions(markets, nowcasts)
    assert len(decisions) == 5
    assert all(d.decided_at == m.close_time - timedelta(hours=1) for d, m in zip(decisions, markets))
    histories = {m.ticker: _history(m, r["result"], 0.40, 0.44) for m, r in zip(markets, raws)}
    histories[markets[0].ticker] = MarketHistory(markets[0].ticker, "yes", markets[0].close_time, [], [])  # unquoted
    quoted = quoted_only(decisions, histories)
    assert len(quoted) == 4
    result = run_backtest(engine="labor_nowcast", cadence="monthly", decisions=quoted, histories=histories)
    assert result.n_decisions == 4
    assert result.summary["brier_market"] is not None
    assert result.gate["status"] == "SHADOW"  # 4 contracts << the monthly minimum of 50
    means = kalshi_implied_means(markets, histories)
    assert set(means) == {date(2013, 6, 1)}  # May has one quoted strike: not a ladder
    # flat 0.42 ladder at cuts 0.5/100.5/150.5k, typical gap 75k: 0.58 * (0.5 - 37.5) + 0.42 * (150.5 + 37.5)
    assert means[date(2013, 6, 1)] == pytest.approx(0.58 * -37.0 + 0.42 * 188.0)


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


def test_throttled_get_json_spaces_calls_and_retries_429():
    responses = [_Resp(429), _Resp(200, {"ok": 1}), _Resp(200, {"ok": 2})]
    sleeps, clock = [], [0.0]

    def get(url, params=None, timeout=None):
        return responses.pop(0)

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    getter = ThrottledGetJson(min_interval=0.25, get=get, sleep=sleep, clock=lambda: clock[0])
    assert getter("u") == {"ok": 1}
    assert getter("u") == {"ok": 2}
    assert sleeps == [2.0, pytest.approx(0.25)]  # backoff after 429, then minimum spacing
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_labor.py -q`

Expected: FAIL — ImportError: cannot import name 'ThrottledGetJson' from 'tradehub.backtest.http'. Validated tail:

```
ERROR tests/test_backtest_labor.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.13s
```

- [ ] **Step 3: Implement**

Why `quoted_only`: a strike with no two-sided quote at decision time can't be traded, and one unquoted row makes the market Brier undefined, so the gate would report "no market Brier recorded". Dropping them is how the step-4 weather/gas backtests behave too (they only score markets with candles).

In `tradehub/backtest/http.py`, replace this exact text:

```python
from typing import Any

import requests
```

with:

```python
import time
from typing import Any, Callable

import requests
```

Append to the end of `tradehub/backtest/http.py`:

```python


class ThrottledGetJson:
    """GET JSON with a minimum spacing between calls and backoff on HTTP 429.

    Kalshi's public API rate-limits rapid scans (sometimes as empty pages), so
    multi-hundred-market jobs such as the Jobs Scorecard builder go through this.
    """

    def __init__(
        self,
        min_interval: float = 0.25,
        retries: int = 5,
        get: Callable[..., Any] = requests.get,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._min_interval = min_interval
        self._retries = retries
        self._get = get
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def __call__(self, url: str, params: dict | None = None) -> Any:
        for attempt in range(self._retries):
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            resp = self._get(url, params=params, timeout=30)
            if resp.status_code == 429:
                self._sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"rate-limited {self._retries} times: {url}")
```

Create `tradehub/scripts/backtest_labor.py`:

```python
"""Point-in-time backtest of labor_nowcast against settled KXPAYROLLS ladders.

Decisions are made one hour before each market closes (7:29 ET on release
day for the usual 8:29 close), from inputs public by then (checked by run_backtest's leakage guard).
The model for month M is fit only on first prints of months before M.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.fills import quote_at
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.pit import Decision
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
from tradehub.data.labor_inputs import Nowcast, load_labor_inputs, payroll_nowcasts
from tradehub.engines.labor import (
    ALL_FEATURES,
    CORE_FEATURES,
    LABOR_ENGINE_VERSION,
    PAYROLL_RESOLUTION,
    PAYROLL_SERIES,
    TRAIN_START,
    decision_time,
    greater_threshold,
    labor_market,
    parse_expiration_value,
    payroll_prob,
)
from tradehub.engines.ladder import implied_mean, isotonic_survival, usable_mid
from tradehub.markets import KalshiMarket, event_month

CANDLE_WINDOW = timedelta(days=2)
_ET = ZoneInfo("America/New_York")


def release_dates(raws: Iterable[dict[str, Any]]) -> dict[date, date]:
    """{reference month: release day (ET)} from each event's earliest close_time."""
    out: dict[date, date] = {}
    for raw in raws:
        month = event_month(raw["event_ticker"])
        day = datetime.fromisoformat(raw["close_time"].replace("Z", "+00:00")).astimezone(_ET).date()
        out[month] = min(out.get(month, day), day)
    return out


def settled_ladder(raws: Iterable[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Settled payroll markets in [start, end] whose event has a numeric first print (drops e.g. Oct-2025)."""
    return [raw for raw in raws
            if start <= event_month(raw["event_ticker"]) <= end
            and raw.get("result") in ("yes", "no")
            and parse_expiration_value(raw.get("expiration_value")) is not None]


def build_labor_decisions(markets: list[KalshiMarket], nowcasts: Mapping[date, Nowcast]) -> list[Decision]:
    decisions = []
    for market in markets:
        nc = nowcasts.get(event_month(market.event_ticker))
        if nc is None:
            continue
        decisions.append(Decision(market.ticker, decision_time(market),
                                  payroll_prob(market, nc.mu, nc.sigma), nc.features.sources))
    return decisions


def labor_histories(client: KalshiHistoryClient, markets: list[KalshiMarket], results: Mapping[str, str],
                    mode: str) -> dict[str, MarketHistory]:
    out = {}
    for market in markets:
        start = market.close_time - CANDLE_WINDOW
        candles = client.merged_candles(market.ticker, start, market.close_time, series_ticker=market.series_ticker)
        trades = client.merged_trades(market.ticker, start=start, end=market.close_time) if mode == "maker" else []
        out[market.ticker] = MarketHistory(market.ticker, results.get(market.ticker), market.close_time, candles, trades)
    return out


def quoted_only(decisions: list[Decision], histories: Mapping[str, MarketHistory]) -> list[Decision]:
    """Keep decisions whose market had a two-sided quote at decision time.

    A strike nobody quoted can't be traded or scored against the market, and one
    unquoted row would make the market Brier (and so the gate) undefined.
    """
    return [d for d in decisions if quote_at(histories[d.market_ticker].candles, d.decided_at) is not None]


def kalshi_implied_means(markets: list[KalshiMarket], histories: Mapping[str, MarketHistory]) -> dict[date, float]:
    """Kalshi-implied mean first print (thousands) per month, from usable mids one hour before close."""
    points: dict[date, list[tuple[float, float]]] = {}
    for market in markets:
        history = histories.get(market.ticker)
        if history is None:
            continue
        candle = quote_at(history.candles, decision_time(market))
        mid = None if candle is None else usable_mid(candle.yes_bid, candle.yes_ask)
        if mid is not None:
            cut = greater_threshold(market.floor_strike, PAYROLL_RESOLUTION) / 1000.0
            points.setdefault(event_month(market.event_ticker), []).append((cut, mid))
    return {month: implied_mean(isotonic_survival(pts)) for month, pts in points.items() if len(pts) >= 2}


def _month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time backtest for labor_nowcast (KXPAYROLLS).")
    parser.add_argument("--start", type=_month_arg, default=date(2023, 3, 1), help="first reference month, YYYY-MM")
    parser.add_argument("--end", type=_month_arg, required=True, help="last reference month, YYYY-MM")
    parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
    parser.add_argument("--features", choices=["core", "all"], default="core")
    parser.add_argument("--cache-dir", type=Path, default=None, help="ALFRED vintage cache (default $TRADEHUB_ALFRED_CACHE)")
    parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
    args = parser.parse_args(argv)

    client = KalshiHistoryClient(get_json=ThrottledGetJson())
    all_raws = client.merged_settled_markets(PAYROLL_SERIES)
    raws = settled_ladder(all_raws, args.start, args.end)
    markets = [labor_market(raw) for raw in raws]
    results = {raw["ticker"]: raw["result"] for raw in raws}
    releases = release_dates(all_raws)
    months = sorted({event_month(m.event_ticker) for m in markets})
    features = CORE_FEATURES if args.features == "core" else ALL_FEATURES
    inputs = load_labor_inputs(first_month=TRAIN_START, last_month=args.end, releases=releases,
                               as_of=datetime.now(timezone.utc).date(), with_adp=args.features == "all",
                               cache_dir=args.cache_dir)
    nowcasts = payroll_nowcasts(inputs, months, releases, train_from=TRAIN_START, features=features)
    decisions = build_labor_decisions(markets, nowcasts)
    histories = labor_histories(client, markets, results, args.mode)
    quoted = quoted_only(decisions, histories)
    result = run_backtest(engine="labor_nowcast", cadence="monthly", decisions=quoted, histories=histories,
                          mode=args.mode)
    firsts = {event_month(raw["event_ticker"]): parse_expiration_value(raw["expiration_value"]) / 1000.0 for raw in raws}
    kalshi_means = kalshi_implied_means(markets, histories)
    both = [m for m in nowcasts if m in kalshi_means and m in firsts]
    config = {"engine": "labor_nowcast", "series": PAYROLL_SERIES, "mode": args.mode, "features": list(features),
              "start": args.start.isoformat(), "end": args.end.isoformat()}
    row = build_backtest_run_row(
        result, engine_version=LABOR_ENGINE_VERSION, config=config,
        data_hash=data_snapshot_hash(quoted, histories),
        date_from=datetime.combine(args.start, time(0), tzinfo=timezone.utc),
        date_to=datetime.combine(args.end, time(23, 59), tzinfo=timezone.utc),
    )
    report = {key: row[key] for key in ("engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                                        "brier_ours", "brier_market", "gate_status", "gate_reasons")}
    report.update({
        "months": len(nowcasts),
        "unquoted_dropped": len(decisions) - len(quoted),
        "months_with_kalshi_mean": len(both),
        "mae_nowcast_k": round(statistics.fmean(abs(nowcasts[m].mu - firsts[m]) for m in both), 1) if both else None,
        "mae_kalshi_k": round(statistics.fmean(abs(kalshi_means[m] - firsts[m]) for m in both), 1) if both else None,
    })
    print(json.dumps(report, default=str, indent=2))
    if args.record:
        from tradehub.core.supabase_client import get_client

        record_backtest_run(get_client(), row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_labor.py tests/test_backtest_kalshi_history.py -q`

Expected: PASS. `tests/test_backtest_kalshi_history.py` must keep passing. Validated tail:

```
....................                                                     [100%]
20 passed in 0.38s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_backtest_labor.py tradehub/backtest/http.py tradehub/scripts/backtest_labor.py
git commit -m "feat: point-in-time labor_nowcast backtest against settled KXPAYROLLS ladders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: `jobs_scorecard` table + row builder

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql`
- Create: `tradehub/jobs_scorecard.py`
- Test: `tests/test_jobs_scorecard.py`

**Interfaces:**
- Consumes: `EstimatePath` (Task 2); ladder functions (Task 4).
- Produces: migration `20260416000009_jobs_scorecard.sql` (table `jobs_scorecard`, PK `(series, reference_month)`, owner-read-only RLS);
  `tradehub/jobs_scorecard.py`: `JOBS_SCORECARD_TABLE`, `SERIES_PAYROLLS = "payrolls"`, `SERIES_UNEMPLOYMENT = "unemployment"`, `NowcastSnapshot(mu, sigma, engine_version, features)`,
  `scorecard_row(*, series, month, event_ticker, release, close_time, ladder_1h, ladder_close, nowcast, path) -> dict` (keys = table columns), `upsert_scorecard(supa, rows, now) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs_scorecard.py`:

```python
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import EstimatePath, estimate_path
from tradehub.jobs_scorecard import NowcastSnapshot, scorecard_row, upsert_scorecard

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql"
)
LADDER = [(0.5, 0.9), (50.5, 0.5), (100.5, 0.1)]


def test_scorecard_row_scores_against_first_print():
    path = EstimatePath(first=60.0, first_vintage=date(2026, 7, 31), second=55.0, second_vintage=date(2026, 8, 31))
    row = scorecard_row(series="payrolls", month=date(2026, 6, 1), event_ticker="KXPAYROLLS-26JUN",
                        release=date(2026, 7, 2), close_time=datetime(2026, 7, 2, 12, 29, tzinfo=timezone.utc),
                        ladder_1h=LADDER, ladder_close=LADDER,
                        nowcast=NowcastSnapshot(80.0, 50.0, "labor-v1", {"pay_last": 100.0}), path=path)
    assert row["reference_month"] == "2026-06-01" and row["rev2"] == 55.0 and row["rev3"] is None
    assert row["kalshi_ladder_1h"] == [[0.5, 0.9], [50.5, 0.5], [100.5, 0.1]]
    assert row["nowcast_abs_err"] == pytest.approx(20.0)
    assert row["kalshi_abs_err"] == pytest.approx(abs(row["kalshi_mean_1h"] - 60.0))
    assert row["kalshi_brier"] == pytest.approx((0.01 + 0.25 + 0.01) / 3)
    assert 0.0 <= row["nowcast_brier"] <= 1.0 and row["nowcast_crps"] > 0
    assert row["n_strikes"] == 3


def test_scorecard_row_before_release_has_no_scores():
    row = scorecard_row(series="payrolls", month=date(2026, 9, 1), event_ticker="KXPAYROLLS-26SEP",
                        release=date(2026, 10, 2), close_time=None, ladder_1h=[], ladder_close=[],
                        nowcast=NowcastSnapshot(90.0, 60.0, "labor-v1", {}), path=EstimatePath())
    assert row["first_print"] is None and row["nowcast_abs_err"] is None and row["kalshi_mean_1h"] is None
    assert row["nowcast_mu"] == 90.0


def test_scorecard_row_from_recorded_vintages_shows_revisions():
    vintages = parse_alfred_csv((FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8"))
    row = scorecard_row(series="payrolls", month=date(2024, 12, 1), event_ticker="KXPAYROLLS-24DEC",
                        release=date(2025, 1, 10), close_time=None, ladder_1h=[], ladder_close=[], nowcast=None,
                        path=estimate_path(vintages, date(2024, 12, 1)))
    assert (row["first_print"], row["rev2"], row["rev3"], row["benchmark"]) == (256.0, 307.0, 323.0, 307.0)
    assert row["benchmark_vintage"] == "2025-02-28"


def test_upsert_scorecard_is_keyed_and_stamped():
    sent = {}

    class Table:
        def upsert(self, rows, on_conflict):
            sent.update(rows=rows, on_conflict=on_conflict)
            return self

        def execute(self):
            return None

    supa = type("S", (), {"table": lambda self, name: sent.setdefault("table", name) and Table()})()
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    assert upsert_scorecard(supa, [{"series": "payrolls"}], now) == 1
    assert sent["table"] == "jobs_scorecard" and sent["on_conflict"] == "series,reference_month"
    assert sent["rows"][0]["updated_at"] == now.isoformat()
    assert upsert_scorecard(supa, [], now) == 0


def test_jobs_scorecard_migration():
    sql = MIGRATION.read_text(encoding="utf-8")
    for needle in (
        "CREATE TABLE IF NOT EXISTS jobs_scorecard",
        "PRIMARY KEY (series, reference_month)",
        "CHECK (series IN ('payrolls', 'unemployment'))",
        "ENABLE ROW LEVEL SECURITY",
        'CREATE POLICY "jobs_scorecard_owner_read" ON jobs_scorecard FOR SELECT',
    ):
        assert needle in sql, needle
    assert "FOR ALL" not in sql
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_jobs_scorecard.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.jobs_scorecard'. Validated tail:

```
ERROR tests/test_jobs_scorecard.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.13s
```

- [ ] **Step 3: Implement**

The migration is numbered `20260416000009`: `000007` is step 2b and `000008` is step 7b. If `ls market_sentiment_tool/supabase/migrations` shows `000009` already taken, use the next free number and rename the test's `MIGRATION` path to match.

Create `market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql`:

```sql
-- Jobs Scorecard (rollout step 8, spec section 3.4).
-- One row per (series, reference_month): our nowcast, the Kalshi-implied
-- ladder one hour before the release and at the last pre-release quote,
-- the first print (what Kalshi settles on), the 2nd/3rd monthly estimates,
-- the first annual benchmark, the latest value, and the scores.
-- Payroll values are in thousands of jobs; unemployment values in percent.
--
-- Written only by the service-role builder
-- (python -m tradehub.scripts.build_jobs_scorecard); the War Room reads it
-- through GET /api/jobs-scorecard. Clients can at most read their own rows,
-- like the step-2b predictions/track_record policies.
-- Numbered 000009: 000007 is step 2b, 000008 is step 7b.
-- Idempotent.

CREATE TABLE IF NOT EXISTS jobs_scorecard (
  series               text NOT NULL CHECK (series IN ('payrolls', 'unemployment')),
  reference_month      date NOT NULL,
  kalshi_event         text,
  release_date         date,
  kalshi_close_ts      timestamptz,
  nowcast_mu           numeric(12,4),
  nowcast_sigma        numeric(12,4),
  engine_version       text,
  nowcast_features     jsonb NOT NULL DEFAULT '{}'::jsonb,
  kalshi_ladder_1h     jsonb NOT NULL DEFAULT '[]'::jsonb,
  kalshi_ladder_close  jsonb NOT NULL DEFAULT '[]'::jsonb,
  kalshi_mean_1h       numeric(12,4),
  kalshi_median_1h     numeric(12,4),
  kalshi_mean_close    numeric(12,4),
  first_print          numeric(12,4),
  first_print_vintage  date,
  rev2                 numeric(12,4),
  rev2_vintage         date,
  rev3                 numeric(12,4),
  rev3_vintage         date,
  benchmark            numeric(12,4),
  benchmark_vintage    date,
  latest               numeric(12,4),
  latest_vintage       date,
  n_strikes            integer NOT NULL DEFAULT 0,
  nowcast_abs_err      numeric(12,4),
  kalshi_abs_err       numeric(12,4),
  nowcast_brier        numeric(8,6),
  kalshi_brier         numeric(8,6),
  nowcast_crps         numeric(12,4),
  kalshi_crps          numeric(12,4),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  user_id              uuid REFERENCES auth.users(id),
  PRIMARY KEY (series, reference_month)
);

ALTER TABLE jobs_scorecard ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "jobs_scorecard_owner_read" ON jobs_scorecard;
CREATE POLICY "jobs_scorecard_owner_read" ON jobs_scorecard FOR SELECT
  USING (auth.uid() = user_id);
```

Create `tradehub/jobs_scorecard.py`:

```python
"""Jobs Scorecard rows (pure): nowcast vs Kalshi-implied vs first print vs revisions, per release.

One row per (series, reference_month). Payroll values are in thousands of
jobs (Kalshi strikes are converted); unemployment values are in percent.
The Kalshi ladders are isotonic-fixed usable mids (see tradehub.engines.ladder)
one hour before the release and at the last pre-release quote.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from tradehub.engines.labor import EstimatePath
from tradehub.engines.ladder import (
    Ladder,
    implied_mean,
    implied_median,
    ladder_brier,
    ladder_crps,
    normal_ladder,
)

JOBS_SCORECARD_TABLE = "jobs_scorecard"
SERIES_PAYROLLS = "payrolls"
SERIES_UNEMPLOYMENT = "unemployment"


@dataclass(frozen=True)
class NowcastSnapshot:
    mu: float
    sigma: float
    engine_version: str
    features: Mapping[str, float]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _ladder_json(ladder: Ladder) -> list[list[float]]:
    return [[round(cut, 4), round(prob, 4)] for cut, prob in ladder]


def scorecard_row(
    *,
    series: str,
    month: date,
    event_ticker: str | None,
    release: date | None,
    close_time: datetime | None,
    ladder_1h: Ladder,
    ladder_close: Ladder,
    nowcast: NowcastSnapshot | None,
    path: EstimatePath,
) -> dict[str, Any]:
    """Assemble one jobs_scorecard row; scores are filled once the first print exists."""
    first = path.first
    row: dict[str, Any] = {
        "series": series,
        "reference_month": month.isoformat(),
        "kalshi_event": event_ticker,
        "release_date": _day(release),
        "kalshi_close_ts": None if close_time is None else close_time.isoformat(),
        "nowcast_mu": None if nowcast is None else _round(nowcast.mu),
        "nowcast_sigma": None if nowcast is None else _round(nowcast.sigma),
        "engine_version": None if nowcast is None else nowcast.engine_version,
        "nowcast_features": {} if nowcast is None else {k: _round(float(v)) for k, v in nowcast.features.items()},
        "kalshi_ladder_1h": _ladder_json(ladder_1h),
        "kalshi_ladder_close": _ladder_json(ladder_close),
        "kalshi_mean_1h": _round(implied_mean(ladder_1h)) if len(ladder_1h) >= 2 else None,
        "kalshi_median_1h": _round(implied_median(ladder_1h)) if len(ladder_1h) >= 2 else None,
        "kalshi_mean_close": _round(implied_mean(ladder_close)) if len(ladder_close) >= 2 else None,
        "first_print": _round(first),
        "first_print_vintage": _day(path.first_vintage),
        "rev2": _round(path.second),
        "rev2_vintage": _day(path.second_vintage),
        "rev3": _round(path.third),
        "rev3_vintage": _day(path.third_vintage),
        "benchmark": _round(path.benchmark),
        "benchmark_vintage": _day(path.benchmark_vintage),
        "latest": _round(path.latest),
        "latest_vintage": _day(path.latest_vintage),
        "n_strikes": len(ladder_1h),
        "nowcast_abs_err": None,
        "kalshi_abs_err": None,
        "nowcast_brier": None,
        "kalshi_brier": None,
        "nowcast_crps": None,
        "kalshi_crps": None,
    }
    if first is None:
        return row
    if nowcast is not None:
        row["nowcast_abs_err"] = _round(abs(nowcast.mu - first))
    if row["kalshi_mean_1h"] is not None:
        row["kalshi_abs_err"] = _round(abs(row["kalshi_mean_1h"] - first))
    if ladder_1h:
        row["kalshi_brier"] = _round(ladder_brier(ladder_1h, first))
        row["kalshi_crps"] = _round(ladder_crps(ladder_1h, first))
        if nowcast is not None:
            ours = normal_ladder([cut for cut, _ in ladder_1h], nowcast.mu, nowcast.sigma)
            row["nowcast_brier"] = _round(ladder_brier(ours, first))
            row["nowcast_crps"] = _round(ladder_crps(ours, first))
    return row


def upsert_scorecard(supa, rows: list[dict[str, Any]], now: datetime) -> int:
    """Idempotent write keyed on (series, reference_month), stamping updated_at; returns rows sent."""
    if rows:
        stamped = [{**row, "updated_at": now.isoformat()} for row in rows]
        supa.table(JOBS_SCORECARD_TABLE).upsert(stamped, on_conflict="series,reference_month").execute()
    return len(rows)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_jobs_scorecard.py -q`

Expected: PASS. Validated tail:

```
.....                                                                    [100%]
5 passed in 0.06s
```

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql tests/test_jobs_scorecard.py tradehub/jobs_scorecard.py
git commit -m "feat: jobs_scorecard table and scorecard row builder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: `build_jobs_scorecard` CLI

**Files:**
- Create: `tradehub/scripts/build_jobs_scorecard.py`
- Test: `tests/test_build_jobs_scorecard.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5, 7 (`ThrottledGetJson`), 8.
- Produces: `tradehub/scripts/build_jobs_scorecard.py`: `group_events(raws, since, today) -> dict[date, list[KalshiMarket]]`, `event_ladders(client, markets, resolution, unit) -> (ladder_1h, ladder_close)`,
  `u3_baseline(unrate, month) -> NowcastSnapshot | None` (version `u3-naive-v0`), `build_rows(client, *, since, today, cache_dir) -> list[dict]`, and the CLI
  `python -m tradehub.scripts.build_jobs_scorecard [--since YYYY-MM] [--cache-dir DIR] [--dry-run] [--out rows.json]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_jobs_scorecard.py`:

```python
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.kalshi_history import Candle
from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import labor_market
from tradehub.scripts.build_jobs_scorecard import event_ladders, group_events, u3_baseline

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"


def test_group_events_keeps_ended_months_since_start():
    raws = [{"ticker": f"KXU3-{tag}-T4.1", "event_ticker": f"KXU3-{tag}", "open_time": "2026-01-01T00:00:00Z",
             "close_time": "2026-10-02T12:29:00Z", "title": "u3"} for tag in ("26JUL", "26AUG", "26SEP")]
    raws.append({"ticker": "U3-22JUL-T4.3", "event_ticker": "U3-22JUL", "open_time": "2022-07-01T00:00:00Z",
                 "close_time": "2022-08-05T12:25:00Z", "title": "u3"})
    grouped = group_events(raws, since=date(2026, 8, 1), today=date(2026, 9, 25))
    assert list(grouped) == [date(2026, 8, 1)]
    assert grouped[date(2026, 8, 1)][0].floor_strike == pytest.approx(4.1)


def test_u3_baseline_is_last_known_rate():
    unrate = parse_alfred_csv((FIXTURES / "unrate_2026.csv").read_text(encoding="utf-8"))
    snap = u3_baseline(unrate, date(2026, 8, 1))
    assert snap.mu == 4.1 and snap.sigma == pytest.approx(0.2)  # too little history: default spread
    assert snap.engine_version == "u3-naive-v0"
    assert u3_baseline(unrate, date(2026, 1, 1)) is None


def test_event_ladders_one_request_per_strike_both_moments():
    markets = [labor_market({"ticker": f"KXPAYROLLS-26AUG-T{k}", "event_ticker": "KXPAYROLLS-26AUG",
                             "strike_type": "greater", "floor_strike": k, "open_time": "2026-08-01T00:00:00Z",
                             "close_time": "2026-09-04T12:29:00Z", "title": "jobs"}) for k in (0, 100000)]
    calls = []

    class Client:
        def merged_candles(self, ticker, start, end, *, series_ticker):
            calls.append(ticker)
            close = datetime(2026, 9, 4, 12, 29, tzinfo=timezone.utc)
            early = 0.80 if ticker.endswith("T0") else 0.30
            return [Candle(close - timedelta(hours=1, minutes=5), early - 0.02, early + 0.02, 1.0),
                    Candle(close, early + 0.08, early + 0.12, 1.0)]

    ladder_1h, ladder_close = event_ladders(Client(), markets, 1000.0, 1000.0)
    assert calls == ["KXPAYROLLS-26AUG-T0", "KXPAYROLLS-26AUG-T100000"]
    assert ladder_1h == [(0.5, pytest.approx(0.80)), (100.5, pytest.approx(0.30))]
    assert ladder_close == [(0.5, pytest.approx(0.90)), (100.5, pytest.approx(0.40))]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_build_jobs_scorecard.py -q`

Expected: FAIL — ModuleNotFoundError: No module named 'tradehub.scripts.build_jobs_scorecard'. Validated tail:

```
ERROR tests/test_build_jobs_scorecard.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.29s
```

- [ ] **Step 3: Implement**

Create `tradehub/scripts/build_jobs_scorecard.py`:

```python
"""Build (or refresh) the Jobs Scorecard: one jobs_scorecard row per release, payrolls and unemployment.

Idempotent: rows are upserted on (series, reference_month), so it can run
monthly after each Employment Situation release (VPS timer) or be re-run
at any time. Uses only public Kalshi endpoints and keyless ALFRED vintages.

    python -m tradehub.scripts.build_jobs_scorecard --since 2023-01 [--dry-run] [--out rows.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.fills import quote_at
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import PAGE_LIMIT, KalshiHistoryClient
from tradehub.data.labor_inputs import load_labor_inputs, payroll_nowcasts
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_RESOLUTION,
    PAYROLL_SERIES,
    TRAIN_START,
    U3_RESOLUTION,
    U3_SERIES,
    Vintage,
    add_months,
    decision_time,
    estimate_path,
    first_prints,
    greater_threshold,
    labor_market,
    month_end,
    pre_release_time,
)
from tradehub.engines.ladder import Ladder, isotonic_survival, usable_mid
from tradehub.jobs_scorecard import (
    SERIES_PAYROLLS,
    SERIES_UNEMPLOYMENT,
    NowcastSnapshot,
    scorecard_row,
    upsert_scorecard,
)
from tradehub.markets import KalshiMarket, event_month

U3_BASELINE_VERSION = "u3-naive-v0"
MIN_U3_SIGMA = 0.1
CANDLE_LOOKBACK = timedelta(days=2)  # thin ladders can go hours without a two-sided quote
_ET = ZoneInfo("America/New_York")


def group_events(raws: Iterable[dict[str, Any]], since: date, today: date) -> dict[date, list[KalshiMarket]]:
    """{reference month: markets} for months >= since whose reference month has ended."""
    out: dict[date, dict[str, KalshiMarket]] = defaultdict(dict)
    for raw in raws:
        month = event_month(raw["event_ticker"])
        if month >= since and month_end(month) < today:
            market = labor_market(raw)
            out[month][market.ticker] = market
    return {month: sorted(by_ticker.values(), key=lambda m: m.ticker) for month, by_ticker in out.items()}


def event_ladders(client: KalshiHistoryClient, markets: list[KalshiMarket], resolution: float,
                  unit: float) -> tuple[Ladder, Ladder]:
    """Isotonic Kalshi ladders one hour before the release and at the last pre-release quote.

    One candle request per strike covers both moments.
    """
    at_1h: list[tuple[float, float]] = []
    at_close: list[tuple[float, float]] = []
    for market in markets:
        first, last = decision_time(market), pre_release_time(market)
        candles = client.merged_candles(market.ticker, first - CANDLE_LOOKBACK, last,
                                        series_ticker=market.series_ticker)
        cut = greater_threshold(market.floor_strike, resolution) / unit
        for moment, points in ((first, at_1h), (last, at_close)):
            candle = quote_at(candles, moment)
            mid = None if candle is None else usable_mid(candle.yes_bid, candle.yes_ask)
            if mid is not None:
                points.append((cut, mid))
    return isotonic_survival(at_1h), isotonic_survival(at_close)


def u3_baseline(unrate: Mapping[date, Vintage], month: date) -> NowcastSnapshot | None:
    """Naive random walk: last known rate; sigma = RMS of first-print monthly changes over the prior 36 months."""
    vintage = unrate.get(month_end(month))
    if not vintage:
        return None
    last = vintage[max(vintage)]
    prints = first_prints({d: v for d, v in unrate.items() if d <= month_end(month)}, change=False)
    months = sorted(m for m in prints if m < month)[-37:]
    diffs = [prints[b] - prints[a] for a, b in zip(months, months[1:]) if add_months(a, 1) == b]
    sigma = math.sqrt(sum(d * d for d in diffs) / len(diffs)) if len(diffs) >= 6 else 0.2
    return NowcastSnapshot(last, max(MIN_U3_SIGMA, sigma), U3_BASELINE_VERSION, {"last_rate": last})


def _release(markets: list[KalshiMarket]) -> tuple[datetime, date]:
    close = min(m.close_time for m in markets)
    return close, close.astimezone(_ET).date()


def build_rows(client: KalshiHistoryClient, *, since: date, today: date, cache_dir: Path | None) -> list[dict[str, Any]]:
    events: dict[str, dict[date, list[KalshiMarket]]] = {}
    for series in (PAYROLL_SERIES, U3_SERIES):
        raws = client.merged_settled_markets(series)
        raws += client._paginate("/markets", "markets", {"series_ticker": series, "status": "open", "limit": PAGE_LIMIT})
        events[series] = group_events(raws, since, today)
    pay_months = sorted(events[PAYROLL_SERIES])
    releases = {month: _release(markets)[1] for month, markets in events[PAYROLL_SERIES].items()}
    inputs = load_labor_inputs(first_month=TRAIN_START, last_month=max(pay_months), releases=releases, as_of=today,
                               unrate_from=add_months(since, -18), with_adp=False, cache_dir=cache_dir)
    nowcasts = payroll_nowcasts(inputs, pay_months, releases, train_from=TRAIN_START)
    rows = []
    for month in pay_months:
        markets = events[PAYROLL_SERIES][month]
        close, release = _release(markets)
        nc = nowcasts.get(month)
        ladder_1h, ladder_close = event_ladders(client, markets, PAYROLL_RESOLUTION, 1000.0)
        rows.append(scorecard_row(
            series=SERIES_PAYROLLS, month=month, event_ticker=markets[0].event_ticker, release=release,
            close_time=close, ladder_1h=ladder_1h, ladder_close=ladder_close,
            nowcast=None if nc is None else NowcastSnapshot(nc.mu, nc.sigma, LABOR_ENGINE_VERSION, nc.features.values),
            path=estimate_path(inputs.payems, month),
        ))
    for month in sorted(events[U3_SERIES]):
        markets = events[U3_SERIES][month]
        close, release = _release(markets)
        ladder_1h, ladder_close = event_ladders(client, markets, U3_RESOLUTION, 1.0)
        rows.append(scorecard_row(
            series=SERIES_UNEMPLOYMENT, month=month, event_ticker=markets[0].event_ticker, release=release,
            close_time=close, ladder_1h=ladder_1h, ladder_close=ladder_close,
            nowcast=u3_baseline(inputs.unrate, month),
            path=estimate_path(inputs.unrate, month, change=False),
        ))
    return rows


def _month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Jobs Scorecard (jobs_scorecard table).")
    parser.add_argument("--since", type=_month_arg, default=date(2023, 1, 1), help="first reference month, YYYY-MM")
    parser.add_argument("--cache-dir", type=Path, default=None, help="ALFRED vintage cache (default $TRADEHUB_ALFRED_CACHE)")
    parser.add_argument("--dry-run", action="store_true", help="build rows but do not write to Supabase")
    parser.add_argument("--out", type=Path, default=None, help="also write the rows to this JSON file")
    args = parser.parse_args(argv)

    today = datetime.now(timezone.utc).date()
    rows = build_rows(KalshiHistoryClient(get_json=ThrottledGetJson()), since=args.since, today=today,
                      cache_dir=args.cache_dir)
    if args.out:
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    written = 0
    if not args.dry_run:
        from tradehub.core.supabase_client import get_client

        written = upsert_scorecard(get_client(), rows, datetime.now(timezone.utc))
    by_series = defaultdict(int)
    for row in rows:
        by_series[row["series"]] += 1
    print(json.dumps({"rows": len(rows), "by_series": dict(by_series), "written": written,
                      "with_first_print": sum(1 for r in rows if r["first_print"] is not None)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_build_jobs_scorecard.py -q`

Expected: PASS. Validated tail:

```
...                                                                      [100%]
3 passed in 0.42s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_build_jobs_scorecard.py tradehub/scripts/build_jobs_scorecard.py
git commit -m "feat: build_jobs_scorecard CLI (idempotent upsert, payrolls + unemployment)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: `GET /api/jobs-scorecard`

**Files:**
- Modify: `tradehub/api/main.py`
- Test: `tests/test_api_jobs_scorecard.py`

**Interfaces:**
- Consumes: `tradehub.api.dependencies.get_supabase` (service-role client or `None`), table from Task 8.
- Produces: `GET /api/jobs-scorecard?series=payrolls|unemployment` -> rows ordered by `reference_month`; 422 for another series; 503 without Supabase.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_jobs_scorecard.py`:

```python
from fastapi.testclient import TestClient


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, *_a):
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def order(self, column, **_k):
        self.calls.append(("order", column))
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_jobs_scorecard_endpoint():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    query = _Query([{"series": "unemployment", "reference_month": "2026-08-01"}])
    main.app.dependency_overrides[get_supabase] = lambda: type("S", (), {"table": lambda self, n: query})()
    try:
        client = TestClient(main.app)
        ok = client.get("/api/jobs-scorecard?series=unemployment")
        bad = client.get("/api/jobs-scorecard?series=cpi")
    finally:
        main.app.dependency_overrides.clear()
    assert ok.status_code == 200 and ok.json()[0]["reference_month"] == "2026-08-01"
    assert ("eq", "series", "unemployment") in query.calls and ("order", "reference_month") in query.calls
    assert bad.status_code == 422


def test_jobs_scorecard_endpoint_503_without_supabase():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/jobs-scorecard")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 503
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_api_jobs_scorecard.py -q`

Expected: FAIL — 2 failed (404 != 200, 404 != 503). Validated tail:

```
FAILED tests/test_api_jobs_scorecard.py::test_jobs_scorecard_endpoint - asser...
FAILED tests/test_api_jobs_scorecard.py::test_jobs_scorecard_endpoint_503_without_supabase
2 failed in 1.12s
```

- [ ] **Step 3: Implement**

In `tradehub/api/main.py`, insert directly above the line `# ── Dev entrypoint`:

```python
# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/jobs-scorecard (service-role read, like /api/track-record;
# jobs_scorecard keeps owner-only RLS)
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/jobs-scorecard", tags=["Jobs Scorecard"])
async def get_jobs_scorecard(
    series: str = Query("payrolls", pattern="^(payrolls|unemployment)$"),
    supabase=Depends(get_supabase),
):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = (
        supabase.table("jobs_scorecard").select("*").eq("series", series).order("reference_month").execute()
    )
    return result.data or []
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_api_jobs_scorecard.py tests/test_kalshi_edge_system.py -q`

Expected: PASS. `tests/test_kalshi_edge_system.py` (the existing API tests) must keep passing. Validated tail:

```
......................                                                   [100%]
22 passed in 2.03s
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_jobs_scorecard.py tradehub/api/main.py
git commit -m "feat: GET /api/jobs-scorecard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: Jobs Scorecard page (`/jobs`)

**Files:**
- Create: `market_sentiment_tool/src/lib/jobsScorecard.ts`, `src/hooks/useJobsScorecard.ts`, `src/pages/JobsScorecard.tsx`
- Modify: `market_sentiment_tool/src/App.tsx`
- Test: `market_sentiment_tool/src/lib/jobsScorecard.test.ts`

**Interfaces:**
- Consumes: `GET /api/jobs-scorecard` (Task 10), `buildApiUrl` (`src/lib/api.ts`), `recharts` and the shadcn `Card` (both already in `package.json`).
- Produces: `src/lib/jobsScorecard.ts` (`JobsScorecardRow`, `toChartPoints`, `summarizeScorecard`, `formatValue`), `src/hooks/useJobsScorecard.ts`, `src/pages/JobsScorecard.tsx`, route `/jobs` + sidebar link in `src/App.tsx`.

- [ ] **Step 1: Write the failing test**

Create `market_sentiment_tool/src/lib/jobsScorecard.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  formatValue,
  summarizeScorecard,
  toChartPoints,
  type JobsScorecardRow,
} from "@/lib/jobsScorecard";

const row = (overrides: Partial<JobsScorecardRow>): JobsScorecardRow => ({
  series: "payrolls",
  reference_month: "2026-08-01",
  kalshi_event: "KXPAYROLLS-26AUG",
  release_date: "2026-09-04",
  nowcast_mu: 60,
  nowcast_sigma: 90,
  engine_version: "labor-v1",
  kalshi_mean_1h: 45,
  kalshi_median_1h: 44,
  first_print: 162,
  rev2: null,
  rev3: null,
  benchmark: null,
  latest: 162,
  n_strikes: 17,
  nowcast_abs_err: 102,
  kalshi_abs_err: 117,
  nowcast_brier: 0.2,
  kalshi_brier: 0.25,
  ...overrides,
});

describe("jobsScorecard helpers", () => {
  it("sorts chart points by month and keeps missing values as null", () => {
    const points = toChartPoints([
      row({ reference_month: "2026-08-01" }),
      row({ reference_month: "2026-07-01", kalshi_mean_1h: null, first_print: -23 }),
    ]);
    expect(points.map((p) => p.month)).toEqual(["2026-07", "2026-08"]);
    expect(points[0]).toEqual({ month: "2026-07", nowcast: 60, kalshi: null, firstPrint: -23, latest: 162 });
  });

  it("coerces numeric strings from PostgREST numeric columns", () => {
    const [point] = toChartPoints([row({ nowcast_mu: "12.5" as unknown as number })]);
    expect(point.nowcast).toBe(12.5);
  });

  it("summarizes only fully scored months", () => {
    const summary = summarizeScorecard([
      row({}),
      row({ reference_month: "2026-07-01", nowcast_abs_err: 10, kalshi_abs_err: 30, nowcast_brier: 0.1, kalshi_brier: 0.05 }),
      row({ reference_month: "2026-09-01", first_print: null, nowcast_abs_err: null, kalshi_abs_err: null,
            nowcast_brier: null, kalshi_brier: null }),
    ]);
    expect(summary.months).toBe(3);
    expect(summary.scored).toBe(2);
    expect(summary.nowcastMae).toBeCloseTo(56);
    expect(summary.kalshiMae).toBeCloseTo(73.5);
    expect(summary.nowcastBrier).toBeCloseTo(0.15);
    expect(summary.kalshiBrier).toBeCloseTo(0.15);
    expect(summary.nowcastCloser).toBe(2);
  });

  it("formats payrolls in signed thousands and unemployment in percent", () => {
    expect(formatValue("payrolls", 162)).toBe("+162k");
    expect(formatValue("payrolls", -23.4)).toBe("-23k");
    expect(formatValue("unemployment", 4.1)).toBe("4.1%");
    expect(formatValue("payrolls", null)).toBe("—");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/lib/jobsScorecard.test.ts; cd ..`

Expected: FAIL — FAIL ... Failed to resolve import "@/lib/jobsScorecard". Validated tail:

```
 FAIL  src/lib/jobsScorecard.test.ts
Error: Failed to resolve import "@/lib/jobsScorecard" from "src/lib/jobsScorecard.test.ts". Does the file exist?
 Test Files  1 failed (1)
```

- [ ] **Step 3: Implement**

Create `market_sentiment_tool/src/lib/jobsScorecard.ts`:

```ts
export type JobsSeries = "payrolls" | "unemployment";

export type JobsScorecardRow = {
  series: JobsSeries;
  reference_month: string; // YYYY-MM-01
  kalshi_event: string | null;
  release_date: string | null;
  nowcast_mu: number | null;
  nowcast_sigma: number | null;
  engine_version: string | null;
  kalshi_mean_1h: number | null;
  kalshi_median_1h: number | null;
  first_print: number | null;
  rev2: number | null;
  rev3: number | null;
  benchmark: number | null;
  latest: number | null;
  n_strikes: number;
  nowcast_abs_err: number | null;
  kalshi_abs_err: number | null;
  nowcast_brier: number | null;
  kalshi_brier: number | null;
};

export type ScorecardChartPoint = {
  month: string; // YYYY-MM
  nowcast: number | null;
  kalshi: number | null;
  firstPrint: number | null;
  latest: number | null;
};

export type ScorecardSummary = {
  months: number;
  scored: number; // months with a first print, a nowcast and a Kalshi-implied mean
  nowcastMae: number | null;
  kalshiMae: number | null;
  nowcastBrier: number | null;
  kalshiBrier: number | null;
  nowcastCloser: number; // months where our point estimate beat Kalshi's implied mean
};

const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const mean = (values: number[]): number | null =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;

export function toChartPoints(rows: JobsScorecardRow[]): ScorecardChartPoint[] {
  return [...rows]
    .sort((a, b) => a.reference_month.localeCompare(b.reference_month))
    .map((row) => ({
      month: row.reference_month.slice(0, 7),
      nowcast: toNumber(row.nowcast_mu),
      kalshi: toNumber(row.kalshi_mean_1h),
      firstPrint: toNumber(row.first_print),
      latest: toNumber(row.latest),
    }));
}

export function summarizeScorecard(rows: JobsScorecardRow[]): ScorecardSummary {
  const scored = rows.filter(
    (row) =>
      toNumber(row.nowcast_abs_err) !== null && toNumber(row.kalshi_abs_err) !== null,
  );
  const briers = rows.filter(
    (row) => toNumber(row.nowcast_brier) !== null && toNumber(row.kalshi_brier) !== null,
  );
  return {
    months: rows.length,
    scored: scored.length,
    nowcastMae: mean(scored.map((row) => toNumber(row.nowcast_abs_err) as number)),
    kalshiMae: mean(scored.map((row) => toNumber(row.kalshi_abs_err) as number)),
    nowcastBrier: mean(briers.map((row) => toNumber(row.nowcast_brier) as number)),
    kalshiBrier: mean(briers.map((row) => toNumber(row.kalshi_brier) as number)),
    nowcastCloser: scored.filter(
      (row) => (toNumber(row.nowcast_abs_err) as number) < (toNumber(row.kalshi_abs_err) as number),
    ).length,
  };
}

export function formatValue(series: JobsSeries, value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  if (series === "unemployment") return `${n.toFixed(1)}%`;
  const rounded = Math.round(n);
  return `${rounded > 0 ? "+" : ""}${rounded}k`;
}
```

Create `market_sentiment_tool/src/hooks/useJobsScorecard.ts`:

```ts
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { JobsScorecardRow, JobsSeries } from "@/lib/jobsScorecard";

export function useJobsScorecard(series: JobsSeries) {
  const [rows, setRows] = useState<JobsScorecardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl(`/api/jobs-scorecard?series=${series}`))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (!cancelled) {
          setRows(payload as JobsScorecardRow[]);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown scorecard error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [series]);

  return { rows, loading, error };
}
```

Create `market_sentiment_tool/src/pages/JobsScorecard.tsx`:

```tsx
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useJobsScorecard } from "@/hooks/useJobsScorecard";
import { formatValue, summarizeScorecard, toChartPoints, type JobsSeries } from "@/lib/jobsScorecard";

const SERIES: { key: JobsSeries; label: string }[] = [
  { key: "payrolls", label: "Payrolls (KXPAYROLLS)" },
  { key: "unemployment", label: "Unemployment (KXU3)" },
];

const fmtScore = (value: number | null, digits = 3) => (value === null ? "—" : value.toFixed(digits));

export default function JobsScorecard() {
  const [series, setSeries] = useState<JobsSeries>("payrolls");
  const { rows, loading, error } = useJobsScorecard(series);
  const points = useMemo(() => toChartPoints(rows), [rows]);
  const summary = useMemo(() => summarizeScorecard(rows), [rows]);
  const errDigits = series === "payrolls" ? 1 : 2;

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="flex flex-col gap-4 border-b border-slate-900 pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Jobs Scorecard</h1>
            <p className="max-w-3xl text-sm text-slate-400">
              Kalshi settles on the BLS first print, not the revised number. Each row compares our nowcast and the
              Kalshi-implied estimate (one hour before the release) with the first print, then shows how the number
              was revised afterwards.
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-1">
            {SERIES.map((s) => (
              <button
                key={s.key}
                onClick={() => setSeries(s.key)}
                className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest ${
                  series === s.key ? "bg-emerald-500/20 text-emerald-300" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <Card className="border-rose-500/30 bg-rose-500/10">
            <CardContent className="flex items-center gap-3 p-6 text-rose-100">
              <AlertTriangle className="h-5 w-5 text-rose-400" />
              <p className="text-sm">{error}</p>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="flex items-center gap-3 text-slate-300">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" /> Loading scorecard
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Releases scored</CardDescription>
                  <CardTitle className="text-3xl">{summary.scored} / {summary.months}</CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Mean abs error vs first print: ours / Kalshi</CardDescription>
                  <CardTitle className="text-3xl">
                    {fmtScore(summary.nowcastMae, errDigits)} / {fmtScore(summary.kalshiMae, errDigits)}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Ladder Brier: ours / Kalshi</CardDescription>
                  <CardTitle className="text-3xl">
                    {fmtScore(summary.nowcastBrier)} / {fmtScore(summary.kalshiBrier)}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Months our estimate was closer</CardDescription>
                  <CardTitle className="text-3xl">{summary.nowcastCloser}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardHeader>
                <CardTitle>Nowcast vs Kalshi vs first print vs latest</CardTitle>
              </CardHeader>
              <CardContent className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={points}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="month" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                    <Legend />
                    <Line type="monotone" dataKey="firstPrint" name="First print" stroke="#f8fafc" strokeWidth={2} />
                    <Line type="monotone" dataKey="nowcast" name="Our nowcast" stroke="#10b981" />
                    <Line type="monotone" dataKey="kalshi" name="Kalshi implied" stroke="#f59e0b" />
                    <Line type="monotone" dataKey="latest" name="Latest revised" stroke="#64748b" strokeDasharray="4 4" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardContent className="overflow-x-auto p-0">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wider text-slate-400">
                    <tr>
                      {["Month", "Release", "Nowcast ±σ", "Kalshi", "First print", "2nd", "3rd", "Benchmark",
                        "Latest", "|err| ours", "|err| Kalshi"].map((h) => (
                        <th key={h} className="px-4 py-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...rows].reverse().map((row) => (
                      <tr key={row.reference_month} className="border-t border-slate-800">
                        <td className="px-4 py-2 font-mono">{row.reference_month.slice(0, 7)}</td>
                        <td className="px-4 py-2 text-slate-400">{row.release_date ?? "—"}</td>
                        <td className="px-4 py-2">
                          {formatValue(series, row.nowcast_mu)}
                          {row.nowcast_sigma !== null && (
                            <span className="text-slate-500"> ±{formatValue(series, row.nowcast_sigma).replace("+", "")}</span>
                          )}
                        </td>
                        <td className="px-4 py-2">{formatValue(series, row.kalshi_mean_1h)}</td>
                        <td className="px-4 py-2 font-bold">{formatValue(series, row.first_print)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.rev2)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.rev3)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.benchmark)}</td>
                        <td className="px-4 py-2 text-slate-400">{formatValue(series, row.latest)}</td>
                        <td className="px-4 py-2">{fmtScore(row.nowcast_abs_err === null ? null : Number(row.nowcast_abs_err), errDigits)}</td>
                        <td className="px-4 py-2">{fmtScore(row.kalshi_abs_err === null ? null : Number(row.kalshi_abs_err), errDigits)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
```

In `market_sentiment_tool/src/App.tsx`, replace this exact text:

```tsx
import ShadowBacktester from "@/pages/ShadowBacktester";
```

with:

```tsx
import ShadowBacktester from "@/pages/ShadowBacktester";
import JobsScorecard from "@/pages/JobsScorecard";
```

In `market_sentiment_tool/src/App.tsx`, replace this exact text:

```tsx
import { LayoutDashboard, Activity, Wallet, Brain, LineChart } from "lucide-react";
```

with:

```tsx
import { LayoutDashboard, Activity, Wallet, Brain, LineChart, Briefcase } from "lucide-react";
```

In `market_sentiment_tool/src/App.tsx`, replace this exact text:

```tsx
          <LineChart className="w-5 h-5 text-amber-400" /> Shadow
        </NavLink>
```

with:

```tsx
          <LineChart className="w-5 h-5 text-amber-400" /> Shadow
        </NavLink>
        <NavLink
          to="/jobs"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Briefcase className="w-5 h-5 text-sky-400" /> Jobs Scorecard
        </NavLink>
```

In `market_sentiment_tool/src/App.tsx`, replace this exact text:

```tsx
          <Route path="/shadow" element={<ShadowBacktester />} />
```

with:

```tsx
          <Route path="/shadow" element={<ShadowBacktester />} />
          <Route path="/jobs" element={<JobsScorecard />} />
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run && npm run build; cd ..`

Expected: PASS. The build prints a >500 kB chunk-size warning; it was there before this plan. Validated tail:

```
Test Files  3 passed (3)
     Tests  9 passed (9)
✓ built in 3.0s
```

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/App.tsx market_sentiment_tool/src/hooks/useJobsScorecard.ts market_sentiment_tool/src/lib/jobsScorecard.test.ts market_sentiment_tool/src/lib/jobsScorecard.ts market_sentiment_tool/src/pages/JobsScorecard.tsx
git commit -m "feat: Jobs Scorecard page at /jobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 12: Full verification, live runs, tracker row, evidence report

**Files:**
- Modify: `docs/superpowers/plans/2026-09-24-rollout-tracker.md` (step 8 row)
- Create: `docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md`

**Interfaces:** none new. This task proves the whole branch and hands it off.

- [ ] **Step 1: Full suite + lint + frontend**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q | tail -1
.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
(cd market_sentiment_tool && npx vitest run && npm run build) 2>&1 | grep -E "Tests|built"
git checkout -- market_sentiment_tool/package-lock.json 2>/dev/null; git status --short
```

Expected:
- pytest: the baseline count + 55 (validated as `335 passed` on `31b66b1`; with steps 2b/5/6 merged, the baseline is higher);
- ruff: `All checks passed!`;
- frontend: `Tests  9 passed (9)` (plus whatever step 5/6 added) and `✓ built`;
- `git status`: clean.

- [ ] **Step 2: Live backtest (public Kalshi + keyless ALFRED, about 2 minutes once the vintage cache is warm)**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_labor --start 2023-03 --end 2026-08
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_labor --start 2023-03 --end 2026-08 --features all
```

Expected (validated 2026-09-25; later data can move them slightly):
- core: `"n_decisions": 370`, `"brier_ours": 0.17923`, `"brier_market": 0.16586`, `"gate_status": "SHADOW"`, `"months": 41`, `"mae_nowcast_k": 68.5`, `"mae_kalshi_k": 68.5`;
- `--features all`: `"brier_ours": 0.1833`, `"mae_nowcast_k": 75.2`.
- optional `--mode maker`: `"n_fills": 194`, `"pnl_after_fees": 19.502`.

If ALFRED is unreachable you get `RuntimeError: ALFRED request failed after retries`. Record it in the report and retry later; don't work around it. Paste both JSON blocks into the report. Only Kevin (with the Supabase key) adds `--record`.

- [ ] **Step 3: Live scorecard dry run + scan smoke**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.build_jobs_scorecard --since 2023-01 --dry-run --out /tmp/jobs_scorecard_rows.json
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -c "
from datetime import datetime, timezone
from tradehub.data.kalshi_live import KalshiLive
from tradehub.engine_config import load_engine_config
from tradehub.scripts.scan import scan_labor
now = datetime.now(timezone.utc)
preds, edges = scan_labor(KalshiLive(), now, load_engine_config('labor_nowcast'))
print(now.isoformat(), len(preds), 'predictions', len(edges), 'edges')"
```

Expected:
- the scorecard prints `{"rows": 86, "by_series": {"payrolls": 42, "unemployment": 44}, "written": 0, "with_first_print": 85}` (validated 2026-09-25; each new release adds one row per series). It takes about 4 minutes because the Kalshi calls are throttled.
- The scan smoke returns `0 predictions` while no open event's month has ended (e.g. 2026-09-25). Between the end of a month and its release (e.g. 2026-10-01 → 2026-10-02), it returns one prediction per open strike of that month.

- [ ] **Step 4: Record Kevin's follow-ups in the report (do not edit `vps-stack` or Supabase)**

1. **Apply migration** `20260416000009_jobs_scorecard.sql` to Supabase, then run once: `python -m tradehub.scripts.build_jobs_scorecard --since 2023-01` (with `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` set).
2. **ALFRED from the VPS:**
   - run `curl -s -A 'Mozilla/5.0' 'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-09-24' | head -2` on the VPS.
   - Expect `observation_date,ICSA_20260924`. The planning Mac couldn't reach it on 2026-09-25.
3. **Vintage cache volume:**
   - mount a host dir (e.g. `/opt/stack/data/alfred`) into the `tradehub-job` containers and set `TRADEHUB_ALFRED_CACHE` to it.
   - Without it, every labor scan re-downloads about 20 small CSVs. Past vintages never change, so the cache never needs invalidating.
4. **Scorecard timer** in `vps-stack`: a `tradehub-jobs-scorecard.timer` running `python -m tradehub.scripts.build_jobs_scorecard --since 2023-01` weekly on Fridays at 10:15 America/New_York (after the 08:30 release). The upsert is idempotent. This needs a `jobs-scorecard` job name in `bin/tradehub-job`.
5. **Scan timer:** nothing to change. `scan_labor` runs inside the existing hourly `scan` at 07, 12 and 17 ET.

- [ ] **Step 5: Update the tracker row.** In `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, replace the step 8 row (it starts with `| 8 |`) with:

```
| 8 | `labor_nowcast` + Jobs Scorecard | ✅ implemented on `plan/2026-09-25-labor-nowcast-jobs-scorecard`, SHADOW (backtest Brier 0.179 vs Kalshi 0.166); Kevin: migration 000009, VPS ALFRED check, scorecard timer | [2026-09-25-labor-nowcast-jobs-scorecard.md](2026-09-25-labor-nowcast-jobs-scorecard.md) |
```

- [ ] **Step 6: Write the evidence report** `docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md`. For each task 0–12 it lists the RED and GREEN commands with the tail of their output, the Task 0 prerequisite findings (and which variants were taken), the live JSON from Steps 2–3, Kevin's follow-ups from Step 4, and any deviation with its reason.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/plans/2026-09-24-rollout-tracker.md docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md
git commit -m "docs: step 8 labor_nowcast + Jobs Scorecard evidence and tracker row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Hand the branch name to the reviewing session (rollout tracker, "Review").

---

## Out of scope

- **A KXU3 engine.** The scorecard shows a naive baseline only.
- **Daily nowcast snapshots before each release** (spec §3.4, "as of each day leading up to the release"). The table stores one nowcast plus two Kalshi ladders per release. The scan's 3-a-day predictions in the ledger give the intra-week path, and plotting them is a follow-up.
- **Live execution; sizing; any Kalshi key.**
- **Refitting on the openings/ghost-jobs features.** The ghost-jobs hypothesis was tested and did not help out of sample. Revisit only with a new idea and a new `engine_version`.

## Self-Review

1. **Spec coverage.**
   - §3.1 target is the first print → Tasks 2–3, targets from `first_prints`.
   - Claims inputs → Task 3. ADP and JOLTS hires, the ghost-jobs discount and the post-2021 flag → Task 3 (`ALL_FEATURES`), evaluated in Task 12 and not shipped in `labor-v1` (design note 3).
   - ALFRED first-release training → Tasks 1 and 3.
   - Unemployment-rate brackets → scorecard only, a documented gap.
   - §3.4 scorecard (nowcast, Kalshi-implied distribution, first print, 2nd/3rd, benchmark, errors, drift, U3 panel) → Tasks 8–11. The "each day" gap is noted in Out of scope.
   - §4 → pure engine (Tasks 2–4); edge layer via `evaluate_edge`, `kalshi_edges` `MACRO` and predictions rows (Task 6).
   - §5a → Task 7 (walk-forward, fill model, `backtest_runs` via `--record`, leakage guard through `run_backtest`).
   - §6 → the gate is reused (cadence `monthly`).
   - §10 → vintage fixture tests (Tasks 1–2, 8).
   - §11 → 42 payroll / 43 U3 months with a first print.
   - Rollout step 8's ACCY reuse → only credited (design note 2).
2. **Placeholder scan.** Every code step carries the full file or the exact replacement. Commands and expected outputs come from the validation replay.
3. **Type consistency.** The code blocks come from the files the replay applied, and the names in each task's **Interfaces** block were checked against them: `event_month`, `fetch_vintages`, `labor_market`, `greater_threshold`, `payroll_prob`, `first_prints`, `estimate_path`, `labor_features`, `fit_payroll_model`, `load_labor_inputs(with_adp=...)`, `payroll_nowcasts`, `scan_labor`, `run_labor_step`, `ThrottledGetJson`, `scorecard_row`, `upsert_scorecard(supa, rows, now)`, `event_ladders` and `u3_baseline`.

# Trade Hub Rollout Tracker

**Spec:** [../specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) (the §9 rollout order is authoritative)

This file is the index of the rollout: what is done, what has a ready plan, what still needs one, and the contract any implementing agent follows. Keep it current: update the status table in the same commit that finishes a step.

## Status

| Step | What | Status | Plan |
|---|---|---|---|
| 1 | Repo cleanup | ✅ merged to `main` | [2026-09-24-repo-cleanup.md](2026-09-24-repo-cleanup.md) |
| 2 | Predictions ledger + settlement by market result + track record | 🟡 implemented on branch, review pending | [2026-09-24-predictions-ledger-settlement-track-record.md](2026-09-24-predictions-ledger-settlement-track-record.md) |
| 2b | Promotion-gate and settlement hardening (contract-weighted gate, per-version track records, unquoted-prediction exclusion) | 🟡 implemented on branch, review pending | [2026-09-25-gate-hardening.md](2026-09-25-gate-hardening.md) |
| 3 | Backtesting suite | 🟡 implemented on branch, review pending | [2026-09-24-backtesting-suite.md](2026-09-24-backtesting-suite.md) |
| 4 | Shared data layer + `weather` + `gas` engines, suggest-only | 🟡 implemented on branch, review pending | [2026-09-24-data-layer-weather-gas-engines.md](2026-09-24-data-layer-weather-gas-engines.md) |
| 5 | VPS deploy: API + War Room container, hourly scan/settle timers (replaces the Azure plan) | ✅ implemented, pending Kevin's first deploy (Task 5) | [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md) |
| 6 | `cpi_nowcast` (KXCPI + KXCPICORE, Cleveland Fed nowcast) | 🟡 implemented on branch, shadow; backtest loses to market on Brier (headline 0.099 vs 0.071), review pending | [2026-09-25-cpi-nowcast.md](2026-09-25-cpi-nowcast.md) |
| 7 | Sports adapters + LLM reviewer | 🗺️ outline only; detail after step 4 lands | — |
| 8 | `labor_nowcast` + Jobs Scorecard | 🗺️ outline only; detail after step 4 lands | — |

**Implementation order:** 2 → 3 → 4 → 5, each on its own `plan/<basename>` branch, reviewed and merged before the next one starts. Each plan's code was validated before publishing:
- **Step 2:** 42/42 of the plan's own tests pass.
- **Step 2b:** hardens step 2's gate before the hourly scan feeds it — contract-weighted
  Briers and calibration, a 20-contract minimum before a calibration bucket can block
  promotion, one track record per `(engine, engine_version)`, settlement that keeps the
  engine's inputs and fetches each market once per pass, and read-only client RLS. 353/353
  pass. The VPS scan/settle timers must not be enabled until this merges.
- **Steps 3 + 4:** 88/88 pass together on top of step 2's code. A live check against real Kalshi and Open-Meteo data found the v1 weather model not yet beating the market on a small sample, and the gate holds it in SHADOW as designed.
- **Step 5:** 127/127 pass. A real Docker build and container smoke test were run, which found and fixed an out-of-sync frontend lockfile.

Parked (not scheduled): code-enforced risk controls and live execution (spec §7, only after the "pays for itself" trigger); model registry / `feature_hash` (old roadmap Phase 7); remaining frontend cleanup (old roadmap Phase 10), which is done alongside the Track Record and Sports UI work.

## Handoff & review contract (any implementing agent)

An implementing agent (Claude, Codex, Muse, or another) must:

1. **Have shell access.** It must actually run the plan's test and verification commands. An agent that can only edit files must not implement plans. (The earlier Muse run shows why: without shell access it broke 32 tests.)
2. **Work from the repo root with the project venv:** `.venv/bin/python`. If `.venv` is missing: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner`.
3. **Prefix every test run** with the process-only env var `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` until the local `.env` is repaired. Never write it into a file.
4. **Work on one branch per plan,** named `plan/<plan-file-basename>`, created from `main`. Never commit to `main` directly.
5. **Commit once per task,** using the commit message the plan gives and ending with the trailer the plan specifies.
6. **Write an evidence report** to `docs/superpowers/reports/<plan-file-basename>.md`, committed on the branch. For each task it lists the RED/GREEN commands and the tail of their output, and any deviation from the plan with the reason.
7. **Stop instead of improvising.** If a plan step is wrong or ambiguous, record it in the report and stop that task.
8. **Never:**
   - push or force-push, rewrite history, `git clean`, or `git reset --hard`;
   - edit the spec, other plans, or `.env`;
   - delete untracked files (move them to `_attic/`);
   - add dependencies outside `pyproject.toml`.

**Review:** when the branch is done, hand the branch name to the reviewing session. The reviewer checks the branch diff against the plan and spec (superpowers:requesting-code-review) and reports findings. Fixes go back to the implementing agent on the same branch. Merge to `main` locally only after the review is clean.

## Step 3 — Backtesting suite (planned: 2026-09-24-backtesting-suite.md; original scope notes below)

**Goal (spec §5a):** a point-in-time backtest harness that every engine must pass before it ships, sharing its metric code with the promotion gate.

**Depends on:** step 2 (`tradehub/track_record.py`: `compute_calibration`, `compute_engine_summary`, `check_promotion_gate` are reused, not duplicated; `tradehub/settlement.py`: `brier_score`).

**Scope the plan must cover:**
- `tradehub/backtest/` package:
  - fill model: a taker pays the ask plus the Kalshi fee; a maker order fills only on a later trade printed at or through its limit; nothing fills at the midpoint;
  - walk-forward runner: refit and calibrate only on data before decision time t;
  - P&L after fees, max drawdown, and turnover;
  - a `backtest_runs` writer recording engine version, config hash, data-snapshot hash, and date range.
- **Fees:** reuse `shared/kalshi_fees.py`. Read it first and don't re-derive fee math.
- **Kalshi historical client:** `/historical/markets`, `/historical/markets/{ticker}/candlesticks` (bid/ask blocks), `/historical/trades`, with a recorded-response test harness and no live network in CI.
- **Point-in-time source interface:** a `PointInTimeSource` protocol (`fetch(as_of) -> Snapshot`, with every value stamped with its publish time). First implementations:
  - an ALFRED/FRED vintage fetcher (`realtime_start`/`realtime_end`);
  - Open-Meteo Previous Runs / Single Runs.
  Step 4's data layer implements this same protocol.
- **Leakage guard:** a pytest that fails if any feature timestamp is later than its decision time. It runs in the normal suite.
- **Migration:** `backtest_runs` (new timestamped migration; owner RLS like the step 2 tables).
- **Legacy:** decide what to port from `research/legacy/backtester.py` (Kelly/payout math) versus drop (its Azure Blob source).

**Open questions to resolve while planning** (check the live docs, don't guess):
- Kalshi historical endpoint auth and rate limits.
- The candlestick bid/ask field names.
- Open-Meteo Previous Runs coverage per model.
- Whether the Cleveland Fed archives historical nowcasts (this affects step 6).

## Step 4 — Shared data layer + `weather` + `gas` engines (planned: 2026-09-24-data-layer-weather-gas-engines.md; original scope notes below)

**Goal (spec §3.1, §4):** the P&L core producing real `kalshi_edges` rows and `predictions` rows, suggest-only.

**Depends on:** step 2 (`tradehub/predictions.py` `record_predictions`); step 3 (`PointInTimeSource` protocol, backtest harness; each engine ships with a stored backtest run).

**Scope the plan must cover:**
- `tradehub/data/` fetchers implementing `PointInTimeSource`: NWS forecasts and observations, Open-Meteo ensembles, RBOB (`RB=F` via yfinance), EIA weekly retail gasoline, AAA daily average. Each has a recorded-response test.
- Engines as pure functions `(snapshot, market) -> our_prob`: `tradehub/engines/weather.py` and `tradehub/engines/gas.py`. Decide in the plan whether the existing `weather_engine.py`/`weather_maker.py` are refactored into these or retired. Use `research/weather_notes/` (NWS settlement rules, station mapping) as the domain reference.
- Edge layer:
  - `edge_pct` is computed against executable bid/ask after fees;
  - no taker buys under 10¢;
  - entry suggestions prefer maker prices.
- Per-domain `min_edge` / `kelly_fraction` config (old roadmap Phase 3) in one place, not per-engine literals.
- Writes go to `kalshi_edges` (with a `market_url` deep link) and `predictions` (engine names `weather` and `gas`, matching step 2's cron `ENGINES`).
- A one-shot scan entrypoint, `tradehub/scripts/scan.py`, that is cron-ready for step 5.

**Open questions to resolve while planning:**
- The exact Kalshi series tickers and bracket structures for gas (daily, weekly, monthly AAA markets) and for weather (KXHIGH cities, and each city's settlement station).
- AAA daily-average source format and terms.
- How the edge layer reads the live orderbook without an always-on worker.

## Step 5 — Azure deploy (planned: 2026-09-24-azure-deploy.md; original scope notes below)

**Goal (spec §5):** move off the VPS onto Container Apps in `predictor-hub-rg`, following `NFL_Predictor/.github/workflows/deploy-azure-nfl.yml`.

**Depends on:** step 2 (settle entrypoint), step 4 (scan entrypoint).

**Scope the plan must cover:**
- A root `Dockerfile` built from `pyproject.toml`, and a GHCR build/push workflow at the repo root `.github/workflows/`. (No root workflows exist today; the old ones under `SP500 Predictor/` never ran.)
- Container Apps **Jobs** on a cron schedule:
  - `tradehub-scan` (weather/gas hourly; plus CPI/labor on release days once those steps land);
  - `tradehub-settle` (hourly).
- `tradehub-api` (`uvicorn tradehub.api.main:app`, min replicas 0) and `tradehub-web` (Static Web Apps).
- Secrets as Container Apps secrets: Kalshi key (with `KALSHI_PRIVATE_KEY_PATH` pointing at the mounted secret), Supabase service role key.
- Retire the VPS: `Procfile`, `ecosystem.config.js`, the VPS runbook section of `README.md`.
- Read access for the War Room: an anon `SELECT` policy on `track_record`, or serving it through `tradehub.api`. Decide this in the plan.
- A cost check of the scheduled jobs.

**Open questions to resolve while planning:** secret names and whether they already exist in the RG; Static Web Apps versus a min-0 container for the Vite build.

## Step 6 — `cpi_nowcast` (outline)

- **Target:** KXCPI MoM/YoY brackets, monthly.
- **Inputs:** Cleveland Fed nowcast, the `gas` engine output, FRED CPI components (ALFRED vintages for the backtest).
- **Before detailing:** verify the Cleveland Fed archive (from the step 3 questions), the KXCPI bracket and settlement terms, and the release-day scan timing.
- **Starts:** shadow-only; promotion needs ≥50 settled contracts plus the §6 gate.

## Step 7 — Sports adapters + LLM reviewer (outline)

- **Scope:** read-only adapters for the NFL/CFB predictor APIs first (`https://nfl.<domain>/api`, `https://cfb.<domain>/api` on the VPS), then NBA/PL/F1 (`https://nba.<domain>`, `https://pl.<domain>`, `https://f1.<domain>`).
- **Game-to-Kalshi mapping:** a per-sport mapping table plus fixtures.
- **Candidate filter:** a deterministic filter (edge after fees, predictor calibration in that bucket within 10pp, liquidity).
- **LLM reviewer:** an OpenRouter free model, model name in config.
  - It outputs strict JSON (`explainable`, `drivers`, `red_flags`) and never changes a probability.
  - Responses are cached per (game, price bucket).
  - It gets removed if approved picks don't beat rejected picks after 100+ settled reviewed candidates.
- **Before detailing:**
  - each predictor must store pre-game predictions (a leakage check);
  - record the Kalshi game-ticker formats per sport;
  - check the OpenRouter limits (50/day free, 1,000/day after $10 of credit).

## Step 8 — `labor_nowcast` + Jobs Scorecard (outline)

- **Target:** `KXPAYROLLS` and unemployment-rate brackets, **first print** (Kalshi ignores revisions).
- **Inputs:** weekly claims, ADP (`ADPMNUSNERSA`), JOLTS hires. Openings are down-weighted with the ghost-jobs discount; include a post-2021 regime flag. Train on ALFRED first-release vintages.
- **ACCY-512 reuse:** copy its BLS v2 / FRED fetchers (with credit); no runtime dependency on that repo.
- **Jobs Scorecard page:** nowcast vs. the Kalshi-implied distribution vs. first print vs. 2nd/3rd revisions vs. the annual benchmark, for at least 24 historical months.
- **Before detailing:** the `KXPAYROLLS` bracket structure, and ALFRED vintage parsing for payrolls.

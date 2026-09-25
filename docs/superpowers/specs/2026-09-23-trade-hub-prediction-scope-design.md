# Trade Hub Prediction Scope — Design

**Date:** 2026-09-23
**Status:** Draft for user review
**Supersedes (in part):** the target-selection assumptions in [../plans/2026-09-23-algo-trade-hub-roadmap.md](../plans/2026-09-23-algo-trade-hub-roadmap.md). The roadmap's infrastructure phases still apply; this spec decides *what the hub predicts* and *how it runs*.

## 1. Problem

The hub currently runs eight unrelated engines (crypto hourly, weather, Fed/CPI macro, TSA, EIA, NBA, F1, NCAA/football). The sports engines duplicate the dedicated predictor repos. The rest are picked by availability, not by where an edge is plausible. Recent effort (31 of the last 60 commits) went to crypto, which has no settled evidence of an edge yet.

Goal: **P&L first, plus one flagship showcase**, both on the existing scaffolding (Supabase, orchestrator risk gate, Kalshi client, `kalshi_edges`, settlement and track-record work), kept separate in scope from the sports predictors.

## 2. Evidence that drove the choices

- Kalshi Fed/rate markets are near-perfectly calibrated with no significant favorite-longshot bias. Inflation markets are moderately calibrated. **Employment markets are the weakest-calibrated, with significant systematic mispricing.** ([Information Efficiency Across Macro Prediction Markets](https://www.researchgate.net/publication/409472804_Information_Efficiency_Across_Macroeconomic_Prediction_Markets_Evidence_from_Kalshi), [FLB in Unemployment Markets](https://www.researchgate.net/publication/409238145_Market_Efficiency_and_the_Favorite-Longshot_Bias_in_Unemployment_Prediction_Markets))
- Across more than 300k Kalshi contracts, buyers of contracts under 10¢ lose over 60%, and makers outperform takers. ([CEPR](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market), [Whelan](https://www.karlwhelan.com/Papers/Kalshi.pdf))
- Kalshi gas contracts settle on the AAA national average, which lags wholesale RBOB futures by one to three weeks. That lag is a structural edge on free data. ([botforkalshi](https://www.botforkalshi.com/blog/how-to-trade-oil-on-kalshi), [CNBC](https://www.cnbc.com/2026/09/14/prediction-markets-traders-think-gas-prices-will-hit-new-highs-in-2026.html))
- The Cleveland Fed inflation nowcast beats Blue Chip and SPF consensus. It is free, and it is built from daily oil and weekly gasoline prices. ([Cleveland Fed](https://www.clevelandfed.org/publications/economic-commentary/2023/ec-202306-real-time-assessment-inflation-nowcasting-cleveland-fed))
- Weather edge is real but crowded. What survives is late-window and intraday station data, correct station mapping, and maker fills. ([PillarLab](https://pillarlabai.com/blog/weather-model-edge-prediction-markets/))
- The ACCY-512 labor panel (`/Users/sigey/Documents/Projects/ACCY-512-Final-Project`) found that openings-based labor tightness stopped predicting real wages after 2021, and that JOLTS openings are inflated by ghost jobs. This is a testable hypothesis for why employment markets misprice. The project also contains working BLS v2 (JOLTS/LAUS) and FRED fetchers. It is explanatory (state-level, wages, data through 2023), not a payrolls forecaster, so the hub reuses its fetchers and insights rather than its model. It appears to be a team repo, so the fetchers are copied over with credit, and the hub does not depend on it at runtime.
- Kalshi `KXPAYROLLS` settles on the **initial** BLS Employment Situation release. "Revisions to the underlying made after expiration will not be accounted for." ([contract terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/PAYROLLS.pdf)) ALFRED (FRED's archive of past vintages) holds every published version of payrolls for free.
- OpenRouter free models allow 20 requests/min and 50 requests/day. That rises to 1,000/day after a one-time $10 credit purchase. ([OpenRouter FAQ](https://openrouter.ai/docs/faq))
- Point-in-time history exists for free. Kalshi `/historical/markets`, candlesticks (with bid/ask), and trades go back to 2021 ([docs](https://docs.kalshi.com/getting_started/historical_data)). Open-Meteo's Previous Runs and Single Runs APIs return weather forecasts as they were issued ([docs](https://open-meteo.com/en/docs/previous-runs-api)).

## 3. Scope

### 3.1 In scope: the energy-to-inflation chain

| Engine | Kalshi target | Free inputs | Settles | Role |
|---|---|---|---|---|
| `weather` | KXHIGH* temp, rain, snow brackets | NWS api.weather.gov (settlement source), Open-Meteo GFS/ECMWF/ICON ensembles, NWS station observations | daily | P&L core |
| `gas` | KXAAAGAS* (AAA national average) | RBOB futures (yfinance `RB=F`), EIA weekly retail gasoline, AAA daily average | daily/weekly | P&L core |
| `cpi_nowcast` | KXCPI* MoM/YoY brackets | Cleveland Fed nowcast, `gas` engine output, FRED CPI components | monthly | Flagship #1 |
| `labor_nowcast` | `KXPAYROLLS` brackets and unemployment-rate brackets. **Target is the first print**, not the revised value. | FRED initial and continuing claims (weekly), ADP (FRED `ADPMNUSNERSA`), BLS JOLTS hires (ACCY fetchers); openings down-weighted with the ghost-jobs discount; post-2021 regime flag; trained on ALFRED first-release vintages | monthly | Flagship #2 |
| `sports_adapters/*` | Kalshi game markets | Each live predictor's public API (see 3.2) | per game | Suggestions only |

The Fed is an **input feature only** (fed funds futures-implied path), never a product target.

### 3.2 Sports Edge section (read-only consumer)

- Scope stays separate: the NBA, NFL, PL, F1, and CFB predictor repos own their models. The hub never models sports.
- One adapter per predictor calls its public API (NFL/CFB `/predictions/{season}/{week}/batch`, PL `/fixtures`, F1 `/races/{season}/{round}/prediction`, NBA `/games`) and its `/track-record`.
- The adapter maps each game to a Kalshi ticker through a per-sport mapping table and writes a `kalshi_edges` row with `edge_type='SPORTS'`, `source_url` (deep link to the predictor's game page), and `market_url` (deep link to the Kalshi market).
- Known URLs: `nfl-predictor` and `cfb-predictor` at `*.proudbay-f56b8dfa.eastus2.azurecontainerapps.io`. NBA, PL, and F1 base URLs are config values to fill in when those adapters are built.

**Selecting explainable edges.** Sports edges are chosen in two stages, and every stage's output is logged to the ledger.

1. **Deterministic candidate filter.** A game is a candidate only if all three hold:
   - its `edge_pct` after fees clears the sports `min_edge`;
   - the predictor's own `/track-record` is calibrated (within 10 pp) in the probability bucket this prediction falls into;
   - the Kalshi market's liquidity (resting size at the quoted price) clears a configured minimum.
2. **LLM reviewer (OpenRouter free model, model name set in config).**
   - **Input:** a structured fact pack for each candidate:
     - the predictor's probability and drivers (F1 `/explain`, NFL/CFB `/verdict`, team form, head-to-head);
     - the Kalshi price;
     - the calibration for that bucket.
   - **Output:** strict JSON with `explainable: bool`, `drivers: [str]`, and `red_flags: [str]` (for example, facts the model can't see, such as a late injury).
   - **Scope limit:** the LLM never produces or changes a probability.
   - **Top Pick rule:** only candidates marked `explainable` with no red flags are shown as **Top Picks**. Everything else is shown as "unreviewed" or "flagged".
   - **Caching:** responses are cached per (game, price bucket).
   - **Rate limits:** if the daily limit is hit, candidates are shown without a narrative. The free tier covers 50 reviews/day, and a one-time $10 credit raises that to 1,000/day if large college football slates need it.
   - **Keep-or-drop test:** the track record compares LLM-approved picks against LLM-rejected picks. If approval doesn't improve Brier score or P&L after 100 or more settled reviewed candidates, the reviewer is removed.
   - **Data sent:** only public data goes to the LLM.

### 3.4 Jobs Scorecard view

This is a data-rich page that doubles as `labor_nowcast`'s shadow track record. It is useful before the engine ever trades. For each Employment Situation release it shows:
- our nowcast (point estimate and distribution) as of each day leading up to the release;
- the probability distribution implied by Kalshi's `KXPAYROLLS` bracket prices at the same times;
- the **first print**, which is what Kalshi settles on;
- the 2nd and 3rd monthly revisions and the annual benchmark revision, all from ALFRED vintages;
- our error against each of those, and the first-print-to-final revision drift over time.

It includes an unemployment-rate panel with the same layout. All data is free (ALFRED, BLS, Kalshi historical). The page makes explicit why the model targets the first print and not the eventual "true" number.

### 3.3 Out of scope, moved or parked

- NBA, F1, NCAA, and football engines plus `dixon_coles.py` are removed from the hub. The predictor repos cover them.
- TSA and EIA engines move to `research/`. EIA natural gas can return as a weather-driven add-on later.
- The equities/Alpaca swarm graph (`ORCHESTRATOR_MODE=market_sentiment`) is removed. It is not Kalshi and not in scope.
- Crypto hourly is kept in shadow only and runs on a schedule (section 5). It is promoted or retired by the gate in section 6.

## 4. Architecture

```
scheduled job ──► shared data layer ──► engines (pure) ──► edge layer ──► kalshi_edges ──► War Room UI
 (cron, scale     (one fetch per        snapshot+market     fees+spread     + predictions     flags edge, links
  to zero)         source, as-of         → our_prob          vs orderbook     ledger            to Kalshi market
                   timestamped)                                                                  (manual trade)
                                                                  │
                                         settlement job ◄─────────┘ (settles predictions by Kalshi market result)
```

1. **Shared data layer** (`shared/data/`). Each fetcher returns values stamped with an `as_of` time and caches them for the cycle. Engines read the snapshot and never call APIs directly. The `as_of` stamps are what make point-in-time backtests honest. This is roadmap Phase 6.
2. **Engines** (`engines/<name>.py`). Each is a pure function `(snapshot, market) -> our_prob` with no I/O. A new market is a config entry, which is roadmap Phase 9. `min_edge` and `kelly_fraction` come from per-domain config, which is roadmap Phase 3.
3. **Edge layer.** It computes `edge_pct` against the executable bid/ask after fees, not the midpoint. It never flags a taker buy under 10¢. It prefers maker (limit) prices when suggesting an entry.
4. **Predictions ledger.** Every engine output is written as a prediction row (market ticker, `our_prob`, market price at the time, engine, engine version, `as_of`), whether or not anyone trades it.
5. **Settlement job.** It settles *predictions* against the Kalshi market result from the public market endpoint (`GET /markets/{ticker}`, settled result), independent of any position. This feeds the calibration buckets and track record (roadmap Phase 2). Position-based settlement (`get_settlements`) is only needed once live execution exists.
6. **Execution.** Default `EXECUTION_MODE=suggest`: the UI flags the edge and links to the Kalshi market page, and the user trades manually. `EXECUTION_MODE=live` uses the existing orchestrator kill switch and risk gate plus maker-first orders. It is off until section 7's condition is met.

**Scaffolding reused as-is:** Supabase schema (including the Phase 0 migrations), the orchestrator kill switch and risk gate, the Kalshi auth and client, `kalshi_edges`, and the War Room UI (plus a Sports tab and a Track Record view).

## 5. Hosting: Azure, scale to zero

Same resource group (`predictor-hub-rg`) and Container Apps environment as the predictors, using the same GHCR → `az containerapp` deploy pattern as `NFL_Predictor/.github/workflows/deploy-azure-nfl.yml`.

| Component | Azure resource | Schedule | Cost model |
|---|---|---|---|
| `tradehub-scan` | Container Apps **Job** (cron) | weather and gas hourly; CPI and labor daily plus release-day runs; sports every 3h; crypto shadow hourly | pay per run |
| `tradehub-settle` | Container Apps Job (cron) | hourly | pay per run |
| `tradehub-api` | Container App, `--min-replicas 0`, external ingress | on demand | scale to zero |
| `tradehub-web` | Azure Static Web Apps (or Container App at min 0) | on demand | free/scale to zero |

- There is **no always-on worker**, so there is no Kalshi websocket listener. Crypto shadow switches from websocket-driven to a scheduled hourly snapshot.
- Kalshi and Supabase keys are stored as Container Apps secrets.
- The VPS (`Procfile`, `ecosystem.config.js`, `requirements.vps.txt`) and `sync_to_hf.yml` (force-push to a public HF Space) are retired.

## 5a. Backtesting suite

A first-class component in `backtest/`. Every engine must pass it before shipping, and the promotion gate (section 6) imports its metric functions, so backtest numbers and gate numbers cannot disagree.

**Point-in-time data.** Every data-layer fetcher implements `fetch(as_of: datetime)` and returns only what was published by `as_of`:

| Source | Historical as-issued source | Known gap |
|---|---|---|
| Weather forecasts | Open-Meteo Previous Runs / Single Runs APIs | GFS from 2021, most other models from 2024 |
| Weather observations (settlement) | NWS station history | — |
| RBOB futures | yfinance daily history | daily resolution only |
| Retail gas | EIA weekly retail history | No free AAA daily history. Past Kalshi gas settlement values plus EIA weekly data serve as a proxy, labeled as a proxy in reports. |
| CPI, claims, ADP, payrolls, unemployment | ALFRED vintages (FRED API `realtime_start`/`realtime_end`) | — |
| Cleveland Fed nowcast | their archived nowcast history | Availability and granularity must be verified during planning. If it isn't archived, the backtest uses only our own inputs. |
| Kalshi prices | `/historical/markets`, candlesticks with bid/ask, `/historical/trades` | Coverage starts in 2021 |
| Sports predictions | Each predictor's stored pre-game predictions | If a predictor's `/track-record` recomputes past predictions after the fact, it cannot be used. The adapter must verify prediction timestamps are before kickoff. |

**Simulation.**
- **Walk-forward:** at each decision time t, the engine is refit or calibrated only on data available before t, and predicts from the t snapshot.
- **Fill model:**
  - A taker buys at the ask and pays Kalshi's fee.
  - A maker order counts as filled only if a later trade printed at or through the limit price before the market closed. This is conservative.
  - Nothing is filled at the midpoint.
- The edge layer's rules (min edge after fees, no taker buys under 10¢) apply unchanged.

**Metrics:** the engine's Brier score vs. the market price's Brier score on the same contracts, log loss, calibration buckets, P&L after fees, max drawdown, turnover, and settled-contract count. Each run is stored in a `backtest_runs` table with the engine version, config hash, data-snapshot hash, and date range, so any run can be reproduced exactly. Runs are shown in the UI next to the live track record.

**Leakage guard.** A test fails CI if any feature timestamp used for a decision is later than that decision's time.

## 6. Promotion gate: shadow to promoted

An engine is promoted, meaning its edges are shown as "trade-worthy" in the UI and it becomes eligible for live execution later, only when its settled prediction record shows all of:
- at least 200 settled contracts for daily-settling engines, or at least 50 for monthly-release engines;
- a Brier score below the Kalshi price's Brier score on the same contracts;
- positive simulated P&L after fees and spread, using prices it could actually have gotten at the time;
- no calibration bucket off by more than 10 percentage points.

The gate is re-evaluated on every settlement run, and engines that drift below it are demoted. It applies to every engine, including crypto and the flagships. Engines that haven't been promoted still show edges, labeled "shadow".

## 7. "Pays for itself" trigger for live execution

Switching to `EXECUTION_MODE=live` with an always-on worker is proposed (not automatic, and it needs explicit user approval) only when promoted engines' realized P&L from manual trades (or gate-qualified simulated P&L at the intended size) has exceeded projected monthly infra cost for an always-on worker for **2 consecutive months**. Until then the system stays suggest-only.

## 8. Repo cleanup

Goal: the repo contains only what the in-scope system runs, is importable without `sys.path` hacks, and has one source of truth per concern.

| Area | Action |
|---|---|
| `SP500 Predictor/` (name has a space, which forces `sys.path.insert` hacks) | Rename to `core/`. Move `scripts/engines` → `engines/`, `src/*` → `core/`. Delete `streamlit_app.py`, `pages/`, `azure_logger` usage, stale `*.md`/`*.pdf`/`.ipynb` prompt files, and the untracked `kalshi_private_key.pem` from disk (after it's in Container Apps secrets). |
| Sports engines (`nba_engine`, `f1_engine`, `ncaa_engine`, `football_engine`, `dixon_coles`, `ncca_api-1.json`, `f1_cache/`) | Delete from the hub. The predictor repos own sports. |
| `tsa_engine`, `eia_engine` | Move to `research/`. |
| `FPL_Optimizer/` (150 MB, duplicates `Projects/FPL_Optimizer`), `fpl_optimizations` hook | Remove from the hub. |
| `market_sentiment_tool/` | Keep as the frontend plus Supabase migrations. Delete the equities swarm graph code, `supabase_hard_reset.sql`, `chroma_db/`, and the local SQLite tick files. Rename the directory to `web/` in a follow-up. |
| `hf_space_deployment/`, `sync_to_hf.yml`, `Weather/`, empty `website/` | Delete. |
| `quant_research_lab/` | Fold into `research/` (key files already removed in Phase 0). |
| Committed `graphify-out/` (198 generated files) | Add to `.gitignore` and regenerate locally. |
| Root agent/meta clutter (`.bolt`, `.codex`, duplicated `.agent`/`.agents`, `task.md`, `implementation_plan.md`, `Rules.md`, `midterm.html`, `*.pkl` at root, `trades.log`) | Consolidate into `docs/`, or delete if stale. Keep `AGENTS.md`. |
| 11 `requirements*.txt` files | Replace with one `pyproject.toml` with extras: `core`, `research`, `dev`. |
| Root untracked `.pem` files | Delete from disk once their keys are rotated and stored as Azure secrets (they are gitignored, not leaked, but should not live in the working tree). |
| Git history containing the `quant_research_lab/*.txt` keys | Purge with `git filter-repo` plus a force-push. **Requires explicit user approval** and prior key rotation. |

Cleanup runs as its own plan **before** the new engines are built, so the new code lands in the new layout.

## 9. Rollout (each item is its own spec, plan, and build cycle)

1. **Repo cleanup** (section 8).
2. **Predictions ledger and settlement by market result, plus track record.** This is a revision of `docs/superpowers/plans/2026-09-23-settlement-realized-pnl.md`: keep its pure-math tasks, and replace Task 4 (wiring into the always-on crypto loop) with a cron-job entrypoint and settlement by market result.
3. **Backtesting suite** (section 5a), including the Kalshi historical client and the `as_of` interface on the data layer. From here on, every engine ships with a passing backtest report.
4. **Shared data layer, `weather` engine, `gas` engine**, suggest-only, with edges and Kalshi links in the UI.
5. **Azure deployment** (jobs, API, web) and retirement of the VPS and HF sync.
6. **`cpi_nowcast`**.
7. **Sports adapters plus the LLM reviewer**, NFL and CFB first.
8. **`labor_nowcast` plus the Jobs Scorecard**, reusing the ACCY BLS/FRED fetchers.

## 10. Testing

- Engines: pytest unit tests on frozen snapshot fixtures, following the repo's existing plain-function + `monkeypatch` style.
- Fetchers: recorded-response tests. No live network in CI.
- Sports adapters: game-to-Kalshi-ticker mapping fixtures per sport.
- Promotion gate: unit tests on synthetic settled ledgers (pass, fail on each criterion, demotion).
- Backtest suite: unit tests for the fill model (taker at ask plus fee; maker fills only on a print through the limit), walk-forward windowing, and each metric against hand-computed values. Plus the CI leakage guard (section 5a). `backtester.py`'s Kelly/payout math is reused where it fits. Its Azure Blob data source is dropped.
- LLM reviewer: schema-validation tests on recorded responses, including malformed JSON falling back to "unreviewed", and a test that the reviewer's output can never change `our_prob`.
- Jobs Scorecard: fixture tests that ALFRED vintage parsing yields the correct first print and revisions for known historical months.

## 11. Success criteria

- About 8 weeks after rollout step 3, `weather` and `gas` each have a settled prediction record that either passes the gate or is visibly held in shadow.
- `cpi_nowcast` has a settled shadow record for at least 3 releases.
- The Sports tab shows Kalshi edges for NFL and CFB, with links to the predictor site and to Kalshi. Top Picks are LLM-reviewed, and the approved-vs-rejected comparison is visible.
- Every shipped engine has a stored, reproducible backtest run on point-in-time data, and the CI leakage guard is green.
- The Jobs Scorecard shows at least 24 historical months (nowcast vs. Kalshi-implied vs. first print vs. revisions) plus each new release as it lands.
- Everything runs on Azure scale-to-zero. The VPS and HF sync are gone, and monthly infra cost is near zero.
- The repo has no `sys.path` hacks, one dependency manifest, and no sports or equities code.

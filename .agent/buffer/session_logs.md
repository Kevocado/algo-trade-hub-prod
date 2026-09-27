# Session Logs

## 2026-04-09
- Established the repo root as the primary Obsidian-compatible working vault for agent memory.
- Chose deterministic Markdown + YAML frontmatter + manifest indexing over vector search for v1.
- Scoped the first formalized domain to weather research, settlement rules, and schema design.
- Refactored `quant_research_lab/kalshi_weather_research.ipynb` into the canonical Weather Oracle research notebook.
- Chose Chicago / `KORD` as the v1 default city-station pair for ensemble backtesting.
- Standardized notebook features to `ensemble_mean`, `ensemble_std`, `ensemble_skew`, `temp_drift_from_avg`, and `hour_of_forecast`.
- Locked the research edge rule to `abs(Model_PoE - Kalshi_Implied_Prob) > 0.08`.
- Used NWS station observations grouped to the local settlement day as the executable research label path, while preserving CLI/CF6 as the settlement authority to replace the proxy parser later.
- Documented that simulated implied probabilities are acceptable in research mode, but must not be treated as historical Kalshi order-book truth.

## 2026-04-09 Weather Oracle notebook follow-up
- Corrected the Open-Meteo ensemble notebook fetcher to use the documented `gfs_seamless` model name for v1 research.
- Removed conflicting `forecast_days` / `past_days` parameters when explicit `start_date` and `end_date` are supplied.
- Preserved the research limitation note: if Open-Meteo exposes only a single aggregate temperature trace instead of member traces, sigma is treated as a bounded proxy and flagged in notebook metadata.

## 2026-04-13 Graph Architecture Pass
- Added repo-wide graph hygiene rules under `.agent/rules/` and elevated graphify to the primary discovery layer in `AGENTS.md`.
- Installed the official graphify Codex skill, registered `.codex/hooks.json`, and enabled `multi_agent = true` in `~/.codex/config.toml` per the upstream graphify README.
- Built the initial repo graph with `graphify update .`, producing `graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md`.
- Added `.agent/index/SYSTEM_MAP.md` as the graph-backed universal system map from signal to settlement.
- Seeded graphify memory with canonical answers for the trade path and the high-value Kalshi system edges.
- Introduced `shared/feature_engine.py` plus crypto and weather feature-engine bindings to support a canonical cross-domain feature contract.

## 2026-04-15 Cleanup And Unification Pass
- Added canonical signal-event helpers in `market_sentiment_tool/backend/signal_events.py`.
- Introduced a Supabase migration that promotes `signal_events` to the canonical operator event table and exposes `crypto_signal_events` as a compatibility view with write triggers.
- Refactored Telegram scanning/performance commands toward `/scan {domain}` and `/performance {domain}` while preserving crypto aliases.
- Updated the crypto scorecard path to read canonical `signal_events` filtered by domain.
- Archived duplicate FPL prompt packs, legacy architecture specs, the old root `STATE.md`, and `market_sentiment_tool/Complete context.md` under `archive/`.
- Preserved active notebook work and existing local `.obsidian/workspace.json` edits without rewriting them.
- Refreshed the Obsidian note manifest after the archive move; the current repo vault index now covers 32 Markdown notes and excludes archived material from primary retrieval.
- Verified the updated Python modules compile cleanly and re-ran the note-indexer test suite with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` because a broken global `langsmith` pytest plugin blocks default pytest startup in this environment.
- Attempted `graphify update .` after cleanup; the command did not return a stable completion signal in this runner, so `.agent/index/SYSTEM_MAP.md` still references the last verified April 13 graph snapshot until graphify is re-run successfully in a normal shell.

## 2026-09-26 Keyed FRED API path for macro vintages
- Added `fred/series/observations` as the source for `tradehub/data/alfred_vintages.py` when `FRED_API_KEY` is set; the keyless `alfredgraph.csv` path is unchanged and remains the fallback. Branch `plan/2026-09-26-fred-api-vintages`, report `docs/superpowers/reports/2026-09-26-fred-api-vintages.md`.
- Reason: `alfred.stlouisfed.org` is unreachable from this machine (connection failure on both HTTP/2 and HTTP/1.1) while `api.stlouisfed.org` answers, so the labor nowcast's only data source is a host this network cannot reach. Step 8's "verify the VPS can reach ALFRED" is no longer the only way out.
- Equivalence is measured, not assumed: real `fred/series/observations` payloads recorded 2026-09-26 match the repo's recorded alfredgraph CSV column for the same two PAYEMS month-end vintages, including the observation that had not been published yet.
- Blocker for the operator, not the agent: `FRED_API_KEY` must be added to `/opt/stack/.env` AND passed through `vps-stack/compose.yml` (`FRED_API_KEY: ${FRED_API_KEY:-}` in the tradehub `environment:`), or the container silently keeps using the keyless path. The compose line is the reviewer's to add.
- A FRED key rides in the query string, which `requests` copies into every exception it raises; the re-raise now drops the chained cause when a key is in play, because `logger.exception` of the original would print the key. Regression-tested against raised messages, chained causes and log records.
- graphify could not be re-run in this environment (the `graphify` module is not importable from the project venv and `graphify-out/` is absent from this worktree), so the vault graph is unchanged and `.agent/index/SYSTEM_MAP.md` still reflects its last verified snapshot.

## 2026-09-27 — Hub redesign spec (branch `spec/2026-09-27-hub-redesign`)

- Domain switch: predictor rollout (NFL/CFB) → hub product design. Per `.agent/rules/context_hygiene.md`, predictor-side context unloaded; shared infrastructure context (Kalshi utils, Supabase clients, graphify outputs) retained.
- Delivered the product redesign spec after the truthfulness PR (algo-trade-hub-prod#20, unmerged). No implementation here; design only.
- The finding that shapes the whole product: **every engine loses to the market after fees.** gas `KXAAAGASD` Brier 0.1148 vs market 0.0268 (~4x worse), weather CHI 0.1347 vs 0.1124, NY 0.1242 vs 0.0971, MIA 0.1112 vs 0.0993, CPI 0.099 vs 0.071, labor 0.1792 vs 0.1659. A market Brier of 0.0268 on gas means Kalshi prices that morning's AAA print almost exactly 2h before close, so the question is exhausted at that lead rather than the model being slightly worse at the same task.
- Decision: the product must not claim "bet this". It states what the model believes, how sure it is, its record, and how far it is from good enough. Promotion stays settled-results-beat-market-after-fees (spec section 6), and losing engines stay visible labelled Shadow.
- Decision: the gate deadlock is real. `check_candidate` needs n>=20 settled per price bucket, the reviewer needs 100 settled, and zero have settled because the system is 8 days old and the nearest games are CFB week 5 on 2 Oct. Inversion approved: admit on the publishing predictor's own published calibration first (NFL/CFB now ship calibration buckets and a pre-kickoff track record via `/api/kalshi-feed`), hub's own settled ledger second.
- Decision: sports ranked by `edge_pct / sigma` with a floored sigma and a capped score, raw edge stays visible. Sports list is "available now" only and heavily filtered; rejected rows summarised by reason behind a toggle, never as a wall of detail.
- **Correction carried into the spec:** I previously reported that `sports_cfb:` had no parameters in `config/engines.yaml` and therefore inherited NFL's 72h window, and I had asked to widen it to ~168h on that basis. That was wrong — I misread a two-line `grep -A 2` as an empty block. Both engines carry all nine parameters (`sports_cfb` differs only in `min_volume: 500` vs `1000`). The real cause of 86/100 `starts_too_late` rows is that `tradehub/sports/scan.py:121` skips only already-started games and has **no upper bound**, so 144h-out CFB week 5 games are priced, stored, then rejected by the candidate filter. The evidence now points the opposite way to my earlier recommendation: keep 72h and bound the scan by it. The window approval is re-put to the operator for that reason.
- Blocker for the operator, unchanged: `FRED_API_KEY` still needs adding to `/opt/stack/.env` and `vps-stack/compose.yml` (see the entry above). `20260416000011_war_room_tables.sql` and the long-outstanding `20260415090000_signal_events_unification.sql` still need applying; until the latter is applied `/shadow` keeps returning the 503 that names it.
- Carried forward unresolved: `config/engines.yaml` still has 4 `azurecontainerapps` predictor hosts while the predictors are moving to the VPS, so sports pricing stops silently if those go dark before cutover. NBA/PL/F1 have no Kalshi adapter, so a cross-predictor ranked list is NFL+CFB only.
- graphify could not be re-run: the `graphify` module is not importable from the project venv (`ModuleNotFoundError: No module named 'graphify'`) and `graphify-out/` is absent from this worktree. The vault graph is therefore unchanged and `.agent/index/SYSTEM_MAP.md` still reflects its last verified snapshot.
- **Second correction, found by probing rather than by reading (2026-09-27T02:36Z).** I had written in the redesign spec that "the predictors' `model_version` now reaches the feed". It does not. `/api/kalshi-feed` on both NFL and CFB: `sigma`, `margin_mu` and `model_version` are **null on 61/61 games** (NFL 1 game, CFB 60); `p_home` is populated on all 61. Consequences: (a) `feed:unknown` is the hub faithfully reporting an upstream null, not a hub bug — `scan.py:83` stamps `f"feed:{mg.game.model_version or 'unknown'}"` and has nothing else to stamp, so no hub-side work fixes it; (b) the approved `edge_pct / sigma` ranking has **no input** and is gated on a predictor-side task, not a hub change. The spec now says so and lists it as an approval item.
- Two structural facts from the same probe: the **NFL feed publishes 1 game** (week 3 opens 2026-09-28, only PHI @ CHI), so available-now NFL is empty by construction; and **CFB publishes 60 games mostly starting 10-02/10-03** (120–168h out) against a 72h hub window, directly confirming the scan-bound diagnosis for the 86/100 `starts_too_late` rows.
- Retracted: I briefly reported all three `azurecontainerapps` predictor hosts as dead (HTTP 000). **Wrong** — the 000 came from probing `/`, which is not the path the scan uses, and was transient. Retested: `/` returns 200 three times and `/api/kalshi-feed` returns 200 with current data on all three. The Azure hosts are alive; the "if those go dark" risk in the spec stays as a *cutover* risk, not a live outage.

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
- **`/api/shadow-performance` has a SECOND blocker behind the migration** (found 2026-09-27, probe of the real success path with `signal_events` present and empty). `build_shadow_report` also calls `_load_alpaca_client()` and fetches live BTC/ETH bars from `data.alpaca.markets` to mark signal outcomes. `vps-stack/compose.yml` (at `/Users/sigey/Documents/Projects.nosync/vps-stack/`, a sibling of the repos — **not** inside the hub repo, which cost me one false negative when I grepped a path that does not exist) passes `SUPABASE_*`, `SPORTS_*_BASE_URL/SITE_URL`, `OPENROUTER_API_KEY`, `FRED_API_KEY` and `TRADEHUB_ALFRED_CACHE` to the tradehub service, but **no `ALPACA_*`**. So applying `20260415090000_signal_events_unification.sql` will NOT make `/shadow` return 200; it will fail with "Missing Alpaca API credentials" instead of the missing-table error. Operator needs `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` in `/opt/stack/.env` plus an `ALPACA_API_KEY: ${ALPACA_API_KEY:-}` / `ALPACA_SECRET_KEY: ${ALPACA_SECRET_KEY:-}` line in the tradehub `environment:` block — the same shape as the outstanding `FRED_API_KEY` line. **This corrects PR #20's checklist**, which wrongly said `/api/shadow-performance` should return 200 after the migration.
- **`/api/positions` and `/api/pnl_summary` are genuinely unblocked by `20260416000011`** — the success path was exercised with `paper_trades` present and empty and returns an empty list / zeroed `PnLSummary` with `suggest_only: true`, no second defect. So #20's other checklist items stand; only the shadow one was wrong.
- **The sports repoint is an env change, not a code change** (corrects step 3 of PR #21). `vps-stack/compose.yml` lines 163-166 already pass `SPORTS_NFL_BASE_URL`, `SPORTS_CFB_BASE_URL`, `SPORTS_NFL_SITE_URL`, `SPORTS_CFB_SITE_URL`, all defaulting to empty; `tradehub/sports/config.py:54-55` reads `os.getenv(prefix + "BASE_URL") or sources["base_url"]`, so an empty value falls back to the frozen Azure hosts in `engines.yaml`. Setting those four in `/opt/stack/.env` repoints the hub at the VPS with **no repository change at all**, which is the same mechanism already used for `FRED_API_KEY`. Editing `engines.yaml` would be the wrong layer.
- No test anywhere asserted the **success** path of `build_shadow_timeline_response` — both existing references monkeypatch it to fail. That is why the second blocker was invisible; worth adding a success-path test when the Alpaca dependency is made injectable.

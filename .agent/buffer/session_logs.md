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

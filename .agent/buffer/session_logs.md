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

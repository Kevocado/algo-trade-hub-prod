# research/

Parked material. **Nothing in the runtime (`tradehub/`, `shared/`, `market_sentiment_tool/`) may import from here.**
`tests/test_repo_layout.py` enforces this.

| Folder | What | Why it's kept |
|---|---|---|
| `engines/` | TSA throughput and EIA nat-gas engines | Out of scope for now (spec §3.3). EIA may return as a weather-driven add-on. |
| `quant_lab/` | Crypto research notebooks, Kalshi history CSVs, research bots | Reference for the crypto shadow engine and the backtest suite. |
| `weather_notes/` | NWS/Open-Meteo API notes, settlement rules, Kalshi weather market mapping | Input to the weather engine (rollout step 4). |
| `legacy/` | `backtester.py`, `evaluation.py`, `optimizer.py`, `weather_model.py`, `fred_model.py`, `supabase_setup.sql` | Math to reuse in the backtest suite (rollout step 3) and model registry. Not runnable as-is: `backtester.py` depends on a removed Azure Blob logger. |
| `tools/` | `discover_series.py`, `generate_market_snapshot.py` | One-off Kalshi exploration helpers. |

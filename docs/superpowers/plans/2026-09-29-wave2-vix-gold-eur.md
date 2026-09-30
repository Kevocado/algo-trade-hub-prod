# Step 4: Shared data layer + weather + gas engines
# (per spec §3.1, §4)

## Overview
Build the shared data layer that powers the prediction journal:
- **Weather**: NWS forecasts, Open-Meteo ensemble, RBOB (RB=F) via yfinance, EIA weekly retail gasoline
- **Gas**: Daily/weekly/monthly AAA averages (via Stooq/Alpha Vantage)
- **Edge layer**: Compute edge probabilities (entry/exit) from market data

## Architecture
- `tradehub/data/` – unified data fetchers (NWS, Open-Meteo, RBOB, EIA)
- `tradehub/engines/weather.py` – weather forecasting helpers
- `tradehub/engines/gas.py` – gas price/volume aggregators
- `tradehub/edge.py` – edge probability computation (entry/exit signals)
- `tradehub/contracts/edge.py` – contract definitions for edge types

## Dependencies
- `tradehub/data/fred_daily.py` (already exists)
- `tradehub/journal/forecasters/` (already has daily-direction forecasters)
- `tradehub/journal/` (already has registry, targets)

## Implementation Plan
1. **Weather data layer** – fetch NWS forecasts, Open-Meteo, RBOB, EIA
2. **Gas data layer** – fetch AAA daily/weekly/monthly via Stooq/Alpha Vantage
3. **Edge computation** – compute entry/exit probabilities from market data
4. **Integration** – wire into journal forecasters (optional enhancement)

## Next Steps
- Implement weather fetcher (`tradehub/data/weather.py`)
- Implement gas fetcher (`tradehub/data/gas.py`)
- Implement edge probability calculator (`tradehub/edge.py`)
- Write tests for each component

## Verification
- Each module passes its own test suite
- Integration test: weather + gas data flows into the journal pipeline
- Performance: < 2s latency for typical queries

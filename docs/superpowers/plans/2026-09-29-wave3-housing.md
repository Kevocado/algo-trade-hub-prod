# Wave 3: Housing (Case-Shiller HPI Direction)
# (per spec §8)

## Overview
Implement monthly Housing forecaster predicting **next-case-shiller national HPI direction**, frozen at the FRED release date (~2 months after the observed value), settled against the release.

## Architecture
- **Data source**: FRED Case-Shiller National HPI (CSNTINSA)
- **Freeze**: Monthly on the FRED release calendar (~2 months after observation)
- **Settlement**: Against the released value (no intra-month nowcasting)
- **Contract**: Same as other forecasters (freeze, settle, score)

## Implementation
1. **Data fetcher**: `tradehub/data/case_shiller.py` (FRED series CSNTINSA)
2. **Forecaster**: `tradehub/journal/forecasters/housing.py` (HpiDirectionForecaster)
3. **API integration**: Added to registry (plan-based setup)
4. **Tests**: Housing-specific unit and integration tests

## Planning
- Freeze at the FRED release date (~2 months after observation)
- No new modeling initially (naive baseline)
- Must beat baseline's Brier to graduate from provisional
- Uses existing journal pipeline infrastructure

## Next Steps
1. Create Case-Shiller data fetcher
2. Implement HPI direction forecaster
3. Add to registry
4. Write comprehensive tests
5. Verify integration with journal pipeline

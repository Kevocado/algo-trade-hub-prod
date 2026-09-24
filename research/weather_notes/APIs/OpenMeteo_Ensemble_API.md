---
title: Open-Meteo Ensemble API
type: api_spec
domain: weather
status: active
tags: [weather, api, open-meteo, ensemble]
apis: [open-meteo]
cities: [Chicago, New York City, Washington DC]
symbols: []
settlement_source: []
updated_utc: 2026-04-09T00:00:00Z
summary: Captures the request and response schema assumptions for Open-Meteo ensemble forecasts used in weather probability modeling.
---

# Open-Meteo Ensemble API

## Purpose
- Use Open-Meteo ensemble forecasts to estimate a distribution over daily highs and compute probability of exceedance against Kalshi strikes.

## Example Request
```text
https://ensemble-api.open-meteo.com/v1/ensemble?latitude=41.98&longitude=-87.90&hourly=temperature_2m&models=gfs_seamless&forecast_days=16&timezone=America/Chicago
```

## Response Shape to Preserve
```json
{
  "latitude": 41.98,
  "longitude": -87.9,
  "generationtime_ms": 1.23,
  "utc_offset_seconds": -18000,
  "timezone": "America/Chicago",
  "timezone_abbreviation": "CDT",
  "hourly_units": {
    "time": "iso8601",
    "temperature_2m": "°C"
  },
  "hourly": {
    "time": ["2026-04-10T00:00", "2026-04-10T01:00"],
    "temperature_2m": [14.1, 13.8]
  }
}
```

## Required Fields
- `timezone`
- `utc_offset_seconds`
- `hourly.time`
- `hourly.temperature_2m`

## Ensemble Modeling Notes
- The fetcher must preserve enough data to estimate ensemble mean `μ` and dispersion `σ`.
- If the API returns member-level traces, keep them intact until feature aggregation.
- If only aggregate traces are available, document the approximation used to derive `σ`.

## Units and Timezone Assumptions
- Open-Meteo temperatures are commonly returned in Celsius and must be normalized before strike comparison.
- Forecast timestamps must be aligned to the local city timezone before mapping to settlement days.

## Horizon Mapping
- Forecast horizon must map cleanly from hourly forecast timestamps to the local settlement day.
- The daily high candidate for a Kalshi day should reflect the local observation window used by the settlement station, not raw UTC day boundaries.

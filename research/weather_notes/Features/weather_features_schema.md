---
title: Weather Features Schema
type: feature_schema
domain: weather
status: active
tags: [weather, features, schema]
apis: [open-meteo, api.weather.gov]
cities: [Chicago, New York City, Washington DC]
symbols: []
settlement_source: [CLI, CF6]
updated_utc: 2026-04-09T00:00:00Z
summary: Defines the first weather feature contract for ensemble-based Kalshi probability modeling.
---

# Weather Features Schema

## Core Fields
- `city`
- `station_id`
- `forecast_issue_time_utc`
- `settlement_day_local`
- `ensemble_mean_high_f`
- `ensemble_stddev_high_f`
- `model_poe`
- `kalshi_implied_prob`
- `edge`

## Derived Values
- Probability of exceedance:
  - `P(X > K) = 1 - Φ((K - μ) / σ)`
- Edge:
  - `abs(Model_PoE - Kalshi_Implied_Prob) > 0.08`

## Constraints
- `μ` and `σ` must be derived from the same forecast horizon and local settlement day.
- Settlement day boundaries must respect local station time.
- Feature generation must remain deterministic and auditable.

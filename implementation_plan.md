# Weather Oracle Implementation Plan

## Goal
- Build the first weather research artifact around deterministic note retrieval, settlement normalization, and ensemble-based probability of exceedance.

## First Artifact
- Open-Meteo ensemble fetch schema
- NWS settlement normalization
- City-to-station mapping contract
- Probability of exceedance formula
- Edge formula
- Initial supported cities

## Supported Cities v1
- Chicago
- New York City
- Washington, DC

## Core Formulas
- Probability of exceedance: `P(X > K) = 1 - Φ((K - μ) / σ)`
- Edge trigger: `abs(Model_PoE - Kalshi_Implied_Prob) > 0.08`

## Data Contracts
- Open-Meteo ensemble response must provide forecast horizon, mean, and dispersion needed to approximate `μ` and `σ`.
- NWS settlement notes must define station IDs, settlement source type, and publication lag by city.

## Delivery Sequence
1. Formalize weather notes.
2. Refresh manifest.
3. Draft fetcher schema from notes.
4. Implement `shared/weather_features.py` only after note contracts are stable.

---
title: NWS Settlement Rules
type: settlement
domain: weather
status: active
tags: [weather, settlement, nws, kalshi]
apis: [api.weather.gov]
cities: [Chicago, New York City, Washington DC]
station_ids: [KORD, KNYC, KDCA]
settlement_source: [CLI, CF6]
observation_hour_local: "Daily climate summary published after the local observation day closes; official report often appears overnight."
market_family: [daily_high_temperature]
updated_utc: 2026-04-09T00:00:00Z
summary: Defines the official NWS settlement sources, station IDs, and publication timing assumptions for Kalshi weather markets.
---

# NWS Settlement Rules

## Official Settlement Sources
- Kalshi weather markets should be normalized to official NWS climate products rather than consumer weather apps.
- Primary settlement references are the Daily Climate Report (`CLI`) and the Preliminary Monthly Climate Data (`CF6`), depending on market family and exchange wording.
- The implementation must preserve the exact source used by each market family in the market mapping note.

## Station Mapping
- Chicago O'Hare: `KORD`
- New York City Central Park climate report: `KNYC`
- Washington National Airport: `KDCA`

## Publication Timing
- The observed high for a local day is not necessarily official at market close.
- The official climate summary is typically published with lag, often around the overnight or early next-day reporting window.
- Settlement logic must separate:
  - local observation day
  - official publication timestamp
  - market resolution timestamp

## City-Specific Caveats
- Chicago temperature markets should resolve against O'Hare climate station outputs, not generic metro-area forecasts.
- New York City markets may require careful handling because `KNYC` reflects Central Park climate reporting rather than airport stations.
- Washington, DC markets should use `KDCA` unless Kalshi market wording explicitly states otherwise.

## Implementation Constraints
- Do not infer settlement from forecast APIs.
- Do not mix unofficial observed temperatures with official climate-report settlement.
- Always persist the station ID and report type used for a given market family.

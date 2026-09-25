---
title: Kalshi Weather Market Mapping
type: market_mapping
domain: weather
status: active
tags: [weather, kalshi, mapping]
apis: [kalshi]
cities: [Chicago, New York City, Washington DC]
symbols: []
settlement_source: [CLI, CF6]
updated_utc: 2026-04-09T00:00:00Z
summary: Maps city-level weather contracts to station IDs, settlement sources, and strike interpretation rules.
---

# Kalshi Weather Market Mapping

## Daily High Temperature Markets
- Market mapping must store:
  - city
  - Kalshi market family
  - strike interpretation
  - station ID
  - settlement source type
  - local timezone

## Initial Mapping Table
| City | Station ID | Local TZ | Settlement Source | Notes |
| --- | --- | --- | --- | --- |
| Chicago | KORD | America/Chicago | CLI/CF6 | O'Hare climate station |
| New York City | KNYC | America/New_York | CLI/CF6 | Central Park climate reporting |
| Washington, DC | KDCA | America/New_York | CLI/CF6 | Reagan National climate station |

## Strike Handling
- High-temperature strikes must be compared against the final official daily high in local units.
- The model must normalize forecast units before comparison.
- Any market-specific wording differences should be captured as explicit exceptions, not hidden in code.

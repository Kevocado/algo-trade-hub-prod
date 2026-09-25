---
title: Kalshi Weather Market Mapping
type: market_mapping
domain: weather
status: active
tags: [weather, kalshi, mapping]
apis: [kalshi]
cities: [Chicago, New York City, Miami, Washington DC]
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
| City | Settlement station (Kalshi rules) | Local TZ (climate day = LST) | Settlement Source | Notes |
| --- | --- | --- | --- | --- |
| Chicago | CLIMDW (Midway, KMDW) | Etc/GMT+6 | CLI via The Weather Company | Kalshi KXHIGHCHI rules name Midway, not O'Hare (verified 2026-09-24) |
| New York City | CLINYC (Central Park, KNYC) | Etc/GMT+5 | CLI via The Weather Company | KXHIGHNY |
| Miami | CLIMIA (Miami Intl, KMIA) | Etc/GMT+5 | CLI via The Weather Company | KXHIGHMIA |
| Washington, DC | KDCA | Etc/GMT+5 | CLI/CF6 | Not yet in the engine |

## Strike Handling
- High-temperature strikes must be compared against the final official daily high in local units.
- The model must normalize forecast units before comparison.
- Any market-specific wording differences should be captured as explicit exceptions, not hidden in code.

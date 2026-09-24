---
title: NWS API Spec
type: api_spec
domain: weather
status: active
tags: [weather, api, nws]
apis: [api.weather.gov]
cities: [Chicago, New York City, Washington DC]
symbols: []
settlement_source: [CLI, CF6]
updated_utc: 2026-04-09T00:00:00Z
summary: Defines the NWS endpoints and fields needed to anchor official settlement-aware weather workflows.
---

# NWS API Spec

## Purpose
- Capture the authoritative API surfaces needed for station discovery, forecast retrieval, and climate-report linkage.

## Core Endpoints
- `https://api.weather.gov/points/{lat},{lon}`
- `https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast`
- Climate products may require report-specific retrieval paths outside the generic forecast endpoint.

## Required Concepts
- Forecast office
- Grid coordinates
- Station identity
- Local timezone handling
- Official climate-report source vs forecast source

## Implementation Constraints
- Forecast endpoints are useful for context and reconciliation, not final settlement.
- Station IDs in settlement notes must remain the source of truth for final resolution mapping.

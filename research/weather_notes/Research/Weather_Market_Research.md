---
title: Weather Market Research
type: research
domain: weather
status: active
tags: [weather, research, kalshi]
apis: [open-meteo, api.weather.gov, kalshi]
cities: [Chicago, New York City, Washington DC]
symbols: []
settlement_source: [CLI, CF6]
updated_utc: 2026-04-09T00:00:00Z
summary: Consolidates the first-pass research questions and implementation assumptions for the Weather Oracle.
---

# Weather Market Research

## Objective
- Build an Ensemble-Weighted Weather Oracle that converts weather forecast distributions into Kalshi tradable probabilities.

## Immediate Research Questions
- Which Open-Meteo ensemble endpoint gives the most stable city-level hourly traces?
- How should local-day settlement windows map to overnight forecast timestamps?
- Which Kalshi weather family wording requires CLI versus CF6 settlement handling?

## Initial Modeling Direction
- Start with daily high-temperature markets because they have a tractable strike interpretation.
- Use Open-Meteo for forecast distributions and NWS documentation for settlement anchoring.
- Keep station mappings explicit in notes before implementing code.

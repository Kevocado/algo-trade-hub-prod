# Universal Graph Architecture Plan

## Goal
- Establish graphify as the primary discovery engine across code, research, and execution logic.
- Standardize shared feature contracts so domain engines inherit from a canonical `FeatureEngine`.
- Maintain one repo-wide vault protocol for notes, graph outputs, and system maps.

## First Artifacts
- `.graphifyignore`
- `graphify-out/graph.json`
- `graphify-out/GRAPH_REPORT.md`
- `.agent/index/SYSTEM_MAP.md`
- `shared/feature_engine.py`
- `shared/weather_features.py`

## Structural Contracts
- Root vault rules live in `AGENTS.md` and `.agent/rules/`.
- Shared infrastructure context survives domain switches.
- Active Buffer context must be purged on domain switches.
- Graph-backed discovery precedes broad repo search.

## High-Value System Edges
1. `Model_Inference -> depends_on -> Feature_Contract`
2. `Market_Ticker -> resolves_via -> Settlement_Rules`
3. `Strategy_Logic -> calls -> Kalshi_Execution_Bridge`

## Delivery Sequence
1. Install graphify for Codex and register repo hooks.
2. Build and refresh the repo graph.
3. Seed durable system-memory artifacts from graph outputs.
4. Extend runtime generalization work from the shared `FeatureEngine` contract.

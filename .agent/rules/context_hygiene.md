# Context Hygiene Rules

## Retrieval Order
1. `task.md`
2. `implementation_plan.md`
3. `.agent/buffer/session_logs.md`
4. `.agent/index/notes_manifest.json`
5. Broad repo search

## Weather Feature Building
- Unload crypto model, threshold, RSI, and execution-specific working context before reasoning about weather features.
- Load at most 3 notes from weather APIs, settlement rules, and market mapping.
- Prefer `Weather/Settlement/NWS_Settlement_Rules.md`, `Weather/APIs/OpenMeteo_Ensemble_API.md`, and `Weather/Markets/Kalshi_Weather_Market_Mapping.md` as the initial triad.

## Crypto Work
- Unload weather settlement, climate-station, and ensemble-forecast working context before crypto tasks.
- Load only crypto model, execution, and monitoring notes relevant to the current task.

## Domain Switch Procedure
- Append a dated entry to `.agent/buffer/session_logs.md` with current decisions, blockers, and next actions.
- Update `task.md` with the current stop point and immediate next task.
- Refresh `.agent/index/notes_manifest.json` if new notes were added during the session.

## Context Budget
- Never load more than 3 notes at once unless a task explicitly requires a fourth note for conflict resolution.
- Prefer note summaries and headings from the manifest before opening full note bodies.

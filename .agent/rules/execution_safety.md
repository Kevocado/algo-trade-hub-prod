# Execution Safety Rules

## Structural Safety
1. Prefer additive migrations and compatibility layers when renaming canonical tables or interfaces.
2. Do not remove existing execution paths until graph-backed replacements and tests exist.

## Discovery Safety
1. Treat graphify output as advisory until the referenced code paths are verified locally.
2. If a graph edge conflicts with source code, correct the source of truth and regenerate the graph.

## Domain Safety
1. Purge Active Buffer state before switching domains.
2. Preserve Shared Infrastructure state while switching domains to avoid breaking common Kalshi and Supabase contracts.

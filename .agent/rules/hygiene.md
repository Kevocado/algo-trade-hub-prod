# Global Hygiene Rules

## Universal Discovery
1. Use graphify as the primary discovery engine for code, research, and execution logic.
2. Consult `.agent/index/notes_manifest.json` or `.agent/index/notes_manifest.md` before opening Markdown notes directly.
3. Prefer `graphify-out/graph.json`, `graphify-out/report.md`, and `.agent/index/SYSTEM_MAP.md` for repo-wide relationship lookup.

## Buffer Discipline
1. The Active Buffer must contain only the current domain's execution context.
2. Shared Infrastructure context is retained across all domains.
3. Shared Infrastructure includes Kalshi API utilities, Supabase clients, shared feature engines, graphify artifacts, and orchestration contracts.

## Graph Update Triggers
1. Refresh the graph after structural repo changes, new research artifacts, or new execution bridges.
2. Refresh the notes manifest after creating or materially changing durable notes under the repo vault.

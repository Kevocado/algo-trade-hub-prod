# Agent Constitution: Repo Vault Memory Layer

## Primary Vault
- Treat `/Users/sigey/Documents/Projects/algo-trade-hub-prod` as the primary working Obsidian vault.
- Treat `/Users/sigey/Documents/Obsidian Vault` as reference-only in v1 unless a task explicitly requires archival lookup.
- Treat graphify as the primary discovery engine for repo code, research, and execution logic. Prefer graph queries and graph artifacts before broad filesystem search once the graph is available.

## Retrieval Rules
- Consult `.agent/index/notes_manifest.json` or `.agent/index/notes_manifest.md` before opening notes directly.
- Never load more than 3 notes into active context for a single task.
- Prefer deterministic retrieval from YAML frontmatter and manifest metadata over broad semantic search.
- For repo structure and cross-cutting logic, consult `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`, and `.agent/index/SYSTEM_MAP.md` before using broad `rg` scans.

## Offloading Rules
- Append decisions, blockers, and next steps to `.agent/buffer/session_logs.md` before switching domains.
- Use `task.md` for live execution state.
- Use `implementation_plan.md` for the current build specification.

## Domain Hygiene
- For weather work, unload crypto-specific working context and load only the minimum required weather notes.
- For crypto work, unload weather-specific working context and load only the minimum required crypto notes.
- Respect `.agent/rules/context_hygiene.md` as the domain-switch contract.
- Purge the Active Buffer when switching between domains such as Crypto, Weather, and Macro.
- Retain Shared Infrastructure context across domain switches, including Kalshi execution utilities, Supabase clients, graphify outputs, and shared feature contracts.

## Note Standards
- Durable research notes must be plain Markdown with YAML frontmatter.
- All domains must follow one note schema.
- Required frontmatter keys: `title`, `type`, `domain`, `status`, `settlement_source`, `tags`, `summary`.
- Machine-readable notes must stay deterministic and concise so any coding agent can parse them.
- Archive legacy specs, duplicate prompt packs, and scratch material under `archive/` so primary discovery stays focused on canonical surfaces.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

# Agent Constitution: Repo Vault Memory Layer

## Primary Vault
- Treat `/Users/sigey/Documents/Projects/algo-trade-hub-prod` as the primary working Obsidian vault.
- Treat `/Users/sigey/Documents/Obsidian Vault` as reference-only in v1 unless a task explicitly requires archival lookup.

## Retrieval Rules
- Consult `.agent/index/notes_manifest.json` or `.agent/index/notes_manifest.md` before opening notes directly.
- Never load more than 3 notes into active context for a single task.
- Prefer deterministic retrieval from YAML frontmatter and manifest metadata over broad semantic search.

## Offloading Rules
- Append decisions, blockers, and next steps to `.agent/buffer/session_logs.md` before switching domains.
- Use `task.md` for live execution state.
- Use `implementation_plan.md` for the current build specification.

## Domain Hygiene
- For weather work, unload crypto-specific working context and load only the minimum required weather notes.
- For crypto work, unload weather-specific working context and load only the minimum required crypto notes.
- Respect `.agent/rules/context_hygiene.md` as the domain-switch contract.

## Note Standards
- Durable research notes must be plain Markdown with YAML frontmatter.
- Required frontmatter keys: `title`, `type`, `domain`, `status`, `tags`, `summary`.
- Machine-readable notes must stay deterministic and concise so any coding agent can parse them.

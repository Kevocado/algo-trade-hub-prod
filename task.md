# Active Task

## Current Focus
- Complete the cleanup and unification pass across runtime storage, operator interfaces, and primary discovery paths.

## Immediate Next Steps
- Re-run `graphify update .` from a normal shell so the post-cleanup graph snapshot replaces the April 13 baseline.
- Apply the Supabase `signal_events` migration in the target environment before relying on the universal operator interface.
- Use `.agent/index/SYSTEM_MAP.md` as the universal traversal entry point for future repo work.

## Stop Point
- Runtime storage and operator commands now resolve through canonical `signal_events` plus crypto compatibility. The remaining follow-through is environment-level: apply the DB migration and refresh graphify successfully outside this runner.

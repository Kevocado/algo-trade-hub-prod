# Algo-Trade-Hub: Improvement Roadmap

> **Status note (2026-09-23):** Phase 0 (schema consolidation, minus the
> user_settings RLS tightening — see that phase's note below) and the
> `close_position` reachability fix from Phase 1 have already landed
> (uncommitted, on `feat/kalshi-sports-core`). Phase 1's remaining
> settlement-job work has its own detailed implementation plan:
> [2026-09-23-settlement-realized-pnl.md](2026-09-23-settlement-realized-pnl.md).
> Each phase below gets its own such plan doc, written in this same folder,
> as work reaches it — this file stays a roadmap/index, not an execution plan
> in the superpowers:writing-plans sense.

## Context

`algo-trade-hub-prod` (single repo, `github.com/Kevocado/algo-trade-hub-prod`, no separate public repo exists) is a working system: Python engines on a VPS write edges/trades to Supabase, a LangGraph orchestrator gates execution, and a React frontend reads state. The architecture is sound and several "advanced" pieces already exist that a prior write-up assumed were missing — retrain-on-decay (`optimizer.py`, Brier threshold 0.35) and confidence-bucket hit-rate scoring (`shadow_performance.py._probability_bucket`). The real gap is narrower and more structural than "build these features from scratch":

1. A settlement function already exists (`mcp_server.py:close_position`) but is unreachable dead code — nothing ever calls it, so trades sit at PENDING/OPEN forever and no realized P&L or bucket accuracy can be computed.
2. The Supabase schema is split across three uncoordinated sources with no shared status vocabulary, and two tables (`kalshi_portfolio`, `portfolio_metrics`) have no migration at all.
3. Config (`min_edge`, `kelly_fraction`) is duplicated as hardcoded literals per engine instead of centralized, mirroring how secrets *are* centralized in `shared/config.py`.
4. Test coverage is real (~3,288 lines, ~120 tests) but concentrated entirely on the crypto/Kalshi path — the equities orchestrator graph, `mcp_server.py`, `backtester.py`, `evaluation.py`, `optimizer.py`, the scanner loop, and nearly the whole frontend are untested.
5. Frontend does more than read — it writes to Supabase directly from the browser (kill-switch toggle), computes edge_pct as a client-side fallback, and ships a hardcoded mock equity chart as if it were live data.
6. Four files in `quant_research_lab/` (`Demo API Key*.txt`, `Trading Bot.txt`) are tracked in git and sized exactly like PEM private keys — a likely real credential exposure that predates any of this work and should be closed while doing Phase 3 (config/secrets consolidation).

Goal of this roadmap: close the loop — turn "the system records predictions" into "the system knows which edges work" — and clean up the structural debt each item now depends on, in dependency order (schema before settlement before track record before registry, etc.), folding the credential exposure into the phase where secrets/config get touched anyway.

## Recommended Approach

Phased, each phase independently shippable and testable. Phases 0–3 are prerequisites the later phases depend on; do not skip ordering.

### Phase 0 — Schema consolidation (prerequisite for everything else)
Unify the three schema sources into one migration path so "settled trade" and "realized P&L" mean the same thing everywhere.
- Make `market_sentiment_tool/supabase/migrations/` the single source of truth. Add migrations that:
  - Backfill `CREATE TABLE` statements for `kalshi_portfolio` and `portfolio_metrics` (currently only created ad hoc — reverse-engineer columns from `SP500 Predictor/src/supabase_client.py:upsert_kalshi_portfolio`/`upsert_portfolio_metrics`).
  - Replace the free-text `trades.status` with a `CHECK` constraint / enum: `PENDING | OPEN | FILLED | SETTLED | CLOSED | CANCELLED`, matching (or explicitly mapping to) `paper_trades.status`'s `signal|open|closed|aborted` vocabulary from `SP500 Predictor/scripts/supabase_setup.sql`.
  - Split `trades.pnl` into `realized_pnl` and `unrealized_pnl` columns.
  - Fold `shared/migrations/001_add_kalshi_and_macro_tables.sql` and `002_add_pgvector_news.sql` into the CLI-tracked migration folder so `kalshi_edges`/`macro_signals`/`news_embeddings` are tracked the same way.
- Tighten RLS: remove the `"Anon can view/update ..."` policies that run alongside authenticated per-user policies (found in the RLS migrations) — anon should be read-only on public tables, never write.
  - **Landed exception:** `user_settings`'s anon-UPDATE policy was deliberately left alone. It's the *only* write path the frontend's kill-switch toggle has (`useSupabaseData.ts:toggleAutoTrade`) — there's no real auth session wired up (`Auth.tsx`/`AuthContext.tsx` exist but are unrouted). Removing it needs a real auth flow or a server-side toggle endpoint first (Phase 10 territory); tightening it before that lands would silently disable the kill switch.
- **Fold in the credential fix here**: rotate/revoke whatever the `quant_research_lab/*.txt` files reference (user's action), then `git rm` them, add `*.txt` patterns for key-shaped filenames or move to a documented `.gitignore`'d `secrets/` convention, and purge from git history (`git filter-repo` or BFG) since they're already committed.
  - **Landed exception:** the files were `git rm`'d and `.gitignore` was hardened against the pattern recurring. The git-*history* purge (destructive, needs a force-push) and the actual credential rotation are still outstanding and need explicit user go-ahead — not done as part of this pass.
- Critical files: `market_sentiment_tool/supabase/migrations/` (new files), `shared/migrations/001_*.sql`, `SP500 Predictor/scripts/supabase_setup.sql`, `SP500 Predictor/src/supabase_client.py`, `.gitignore`.

### Phase 1 — Settlement + realized-P&L writer
Wire up (or replace) the dead `close_position` path so trades actually reach a terminal state. **See [2026-09-23-settlement-realized-pnl.md](2026-09-23-settlement-realized-pnl.md) for the full bite-sized implementation plan** — summary below.
- Move `close_position()` out from after the blocking `mcp.run()` call in `market_sentiment_tool/backend/mcp_server.py:450-509` so it's actually registered, or extract its settlement math into a standalone function callable both from the MCP tool and from a scheduled settlement job. *(Landed already.)*
- Add a settlement job (new script or extend `orchestrator.py`'s heartbeat) that polls open Kalshi positions via `SP500 Predictor/src/kalshi_portfolio.py`'s existing `/portfolio/settlements` fetch (currently read-only reporting only) and writes `realized_pnl` + `status="SETTLED"` back to `trades` using the Phase 0 schema.
- Update the equities orchestrator's portfolio equity calc (`orchestrator.py` ~line 3015-3052, currently only sums `status=="OPEN"`) to also account for settled trades' realized P&L.
- Critical files: `market_sentiment_tool/backend/mcp_server.py:454-509`, `market_sentiment_tool/backend/orchestrator.py:284 (write_trade_to_supabase)`, `SP500 Predictor/src/kalshi_portfolio.py:154-221`.

### Phase 2 — Track-record ledger with confidence buckets
This is the highest-leverage item and depends on Phase 1 producing real settled rows.
- Add a persisted `confidence_buckets` (or `track_record`) table (bucket range, engine/domain, count, hit_rate, avg_edge_pct, updated_at) rather than the current transient computation.
- Port the existing bucketing logic from `SP500 Predictor/scripts/shadow_performance.py:_probability_bucket()`/`bucket_stats` (lines 246, 389-412) — don't reinvent it, extend it to write to the new table instead of only pushing to Telegram.
- Extend `SP500 Predictor/src/evaluation.py`'s `calibration_curve` usage similarly to persist results per model/domain instead of computing in-memory only.
- Surface this on the frontend as a real "Track Record" view (see Phase 10) instead of duplicating War Room pages.
- Critical files: `SP500 Predictor/scripts/shadow_performance.py`, `SP500 Predictor/src/evaluation.py`, new migration in `market_sentiment_tool/supabase/migrations/`.

### Phase 3 — Centralize `min_edge` / `kelly_fraction` as per-domain config
- Add `min_edge`/`kelly_fraction` (per domain: weather/macro/sports/crypto/nba/f1) to `shared/config.py` alongside the existing secrets/API config, instead of scattered hardcoded literals (`nba_engine.py:88`, `f1_engine.py:48`, `backtester.py:31`, `quant_engine.py`'s `kelly_criterion`, `discord_notifier.py:17`).
- Update each engine constructor and call site (`market_scanner.py:347,362`, `background_scanner.py`, `f1_engine.py:407`) to read from the shared config instead of passing conflicting literals.
- Critical files: `shared/config.py`, `SP500 Predictor/scripts/engines/*.py`, `SP500 Predictor/scripts/market_scanner.py`, `SP500 Predictor/scripts/background_scanner.py`.

### Phase 4 — Wire the orphaned backtester into the pipeline
- `SP500 Predictor/src/backtester.py` currently pulls from Azure Blob logs (`azure_logger.fetch_all_logs`), which no longer fits the Supabase-centric architecture and has zero callers anywhere. Rewrite `fetch_historical_data()` to read from the Phase 0/2 `trades`/`track_record` tables instead of Azure, then call it from a CLI entrypoint or the weekly `ai_optimizer.yml` job so research feeds back into production config (e.g. validating a `min_edge`/`kelly_fraction` change from Phase 3 before it ships).
- Critical files: `SP500 Predictor/src/backtester.py:31 (fetch_historical_data, simulate_backtest)`, `.github/workflows/ai_optimizer.yml`.

### Phase 5 — TDD discipline on the backend execution path
Test coverage is currently ~120 tests but zero on the pieces most people would call "production": the equities orchestrator, `mcp_server.py`, `backtester.py`, `evaluation.py`, `optimizer.py`, and `background_scanner.py`'s main loop.
- Add tests (mirroring the existing style in `SP500 Predictor/tests/test_crypto_kalshi_last_mile.py`) for: `check_kill_switch()`/`check_crypto_trade_switch()`, `write_trade_to_supabase()` status transitions, the new Phase 1 settlement math, and the equities `cio_supervisor` approval/veto logic.
- Critical files: `market_sentiment_tool/backend/orchestrator.py`, `market_sentiment_tool/backend/mcp_server.py`, new test files under `market_sentiment_tool/backend/tests/` (this directory now exists as of the Phase 1 plan above — extend it, don't recreate it).

### Phase 6 — Batched inference
`background_scanner.py:run_scan()` (line 295) calls each engine (Weather/Macro/TSA/EIA/NBA/F1/NCAA/Football) serially, each independently fetching its own external data.
- Introduce a single shared market/context data pull per scan cycle (e.g. a `ScanContext` object built once per 15-minute loop) that engines read from, rather than each engine hitting its own API. Start with the engines that share a data source (e.g. any using the same weather/macro feed).
- Critical files: `SP500 Predictor/scripts/background_scanner.py:81-383`.

### Phase 7 — Model registry
Retrain-on-decay already works (`optimizer.py` Brier threshold, `auto_retrain_regime.py` incumbent-vs-candidate swap) — the gap is versioning, not triggering.
- Add `model_version`/`feature_hash` tracking: a small table or metadata file recording, per model artifact, the feature schema hash (to make `FeatureMismatchError` in `quant_engine.py:16-26` actionable) and a version id, written whenever `retrain_asset()` swaps a model.
- Critical files: `SP500 Predictor/src/optimizer.py:133 (retrain_model)`, `SP500 Predictor/scripts/auto_retrain_regime.py:122 (retrain_asset)`, `quant_engine.py:16-26`.

### Phase 8 — Risk controls before live capital
- Add code-enforced (not just UI-toggle) per-trade position caps and a daily loss limit checked inside `execute_trade`/`market_resolution` in `orchestrator.py`, not only via the Supabase `user_settings.auto_trade_enabled` kill switch.
- Add slippage assumptions into the edge math (`kalshi_edges.edge_pct` calculation and `kelly_criterion`) so `our_prob` vs `market_prob` reflects realistic fill prices, not midpoint.
- This phase needs explicit review before any real-money change ships — flag for a manual go/no-go rather than auto-merging.
- Critical files: `market_sentiment_tool/backend/orchestrator.py:607 (execute_trade)`, `market_sentiment_tool/backend/orchestrator.py:2144 (market_resolution)`.

### Phase 9 — Multi-market abstraction
The system is already partly multi-domain (`kalshi_edges.edge_type CHECK IN (WEATHER,MACRO,SPORTS)`, `signal_events.domain`, per-sport engine files) — this phase extends the existing pattern rather than inventing one.
- New market = a config entry (domain, thresholds from Phase 3, data source) rather than a new engine `.py` file, where the underlying signal logic is shared (e.g. NBA/NCAA/F1 share odds-to-probability math already).
- Critical files: `SP500 Predictor/scripts/engines/`, `shared/config.py`.

### Phase 10 — Frontend cleanup (can run in parallel with backend phases)
- Remove the hardcoded mock equity chart in `market_sentiment_tool/src/pages/Home.tsx` (`chartData`) — either wire it to real `portfolio_metrics` history or remove until real data exists.
- Delete or finish the orphaned duplicate War Room (`Index.tsx`, unused `Sidebar.tsx`/`Layout.tsx`/`ProtectedRoute.tsx`/`AuthContext.tsx`/`Auth.tsx`) — pick one War Room implementation, and build the real auth flow the kill-switch RLS tightening (Phase 0's landed exception) is blocked on.
- Consolidate the two Supabase client instances (`src/lib/supabase.ts` vs `src/integrations/supabase/client.ts`) into one; remove the hardcoded fallback URL/anon key baked into `client.ts`.
- Move `useMarketEdges.ts`'s client-side `edge_pct` derivation from `raw_payload` into the ingestion pipeline (Phase 3 area) so the frontend only reads pre-computed values.
- Regenerate `src/integrations/supabase/types.ts` from the Phase 0 consolidated schema to remove the `as any` casts on `kalshi_edges`/`kalshi_portfolio`/`portfolio_metrics`/`signal_events`.
- Add a CI workflow (`.github/workflows/frontend.yml`) running the already-configured `vitest`/`eslint` — currently zero CI exists for `market_sentiment_tool`.
- Add the Track Record view from Phase 2 as a real page instead of another one-off dashboard.
- Critical files: `market_sentiment_tool/src/pages/Home.tsx`, `market_sentiment_tool/src/lib/supabase.ts`, `market_sentiment_tool/src/integrations/supabase/client.ts`, `market_sentiment_tool/src/hooks/useMarketEdges.ts`, `.github/workflows/`.

## Verification

- Phase 0: run `supabase db diff` / apply migrations to a local Supabase instance and confirm `trades`, `kalshi_portfolio`, `portfolio_metrics` all exist with the new constraints; confirm RLS policies via `supabase test db` or manual anon-role query attempts that should now fail on writes.
- Phase 1: manually trigger `close_position` (or the new settlement job) against a demo Kalshi position and confirm the `trades` row transitions to `SETTLED` with a non-null `realized_pnl`.
- Phase 2: after Phase 1 produces settled rows, run the ported bucket script and confirm rows appear in the new `confidence_buckets`/`track_record` table with sane hit rates.
- Phase 3-4: run `pytest SP500 Predictor/tests/` (existing suite) plus new tests to confirm no regression, and run the rewired `backtester.py` against real `trades` data end-to-end.
- Phase 5: `pytest` across both `market_sentiment_tool/backend/tests/` (new) and `SP500 Predictor/tests/`, confirming coverage now includes the previously-untested orchestrator/mcp_server/backtester/evaluation/optimizer paths.
- Phase 6: confirm scan cycle wall-clock time decreases and API call counts drop via the scanner's own logging.
- Phase 10: `npm run test` / `npm run lint` in `market_sentiment_tool/`, and manually load the app to confirm the mock chart is gone and only one War Room page is routed.

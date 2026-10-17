# Applied migrations

The authoritative record of which `market_sentiment_tool/supabase/migrations/*.sql` files have been
applied to the production Supabase project.

**Confirmed by Kevin on 2026-10-17: every migration listed below is applied.** The newest (the
watermark) is `20260428000021_journal_scores_paired_brier_validate.sql`.

## Why this file exists

A migration and the code that reads it ship in the same PR, but they are applied at different times by
different people. `tradehub/journal/store.py` is the clearest example of why that is not a formality:
it carries explicit fallbacks for migration `20260428000018` (`journal_forecasts.horizon_seconds`) and
`20260428000020` (`journal_scores.brier_on_baseline` / `n_baseline`), because PostgREST rejects the
*whole* insert when it names an unknown column. Get that order wrong and the journal silently records
nothing while every scorecard keeps its last value — nothing looks broken.

`tests/test_migrations_recorded.py` fails any PR that adds a migration file without recording it here,
so applying a migration is a deliberate, dated act by a person rather than an assumption.

## Applied, in filename order

| # | Migration |
|---|---|
| 1 | `20260223183727_init_trading_schema.sql` |
| 2 | `20260223183729_6cd04bce-991f-481b-8fe4-918f9bb0fc76.sql` |
| 3 | `20260223223000_enable_realtime_and_rls.sql` |
| 4 | `20260408224000_crypto_operator_plane.sql` |
| 5 | `20260415090000_signal_events_unification.sql` |
| 6 | `20260416000000_schema_consolidation.sql` |
| 7 | `20260416000001_kalshi_edges_and_macro.sql` |
| 8 | `20260416000002_pgvector_news.sql` |
| 9 | `20260416000003_predictions_ledger.sql` |
| 10 | `20260416000004_backtest_runs.sql` |
| 11 | `20260416000005_kalshi_edges_urls_energy.sql` |
| 12 | `20260416000006_backtest_log_loss.sql` |
| 13 | `20260416000007_predictions_hardening.sql` |
| 14 | `20260416000008_sports_reviews.sql` |
| 15 | `20260416000009_jobs_scorecard.sql` |
| 16 | `20260416000010_rls_portfolio_news.sql` |
| 17 | `20260416000011_war_room_tables.sql` |
| 18 | `20260428000012_kalshi_quarantine_edges.sql` |
| 19 | `20260428000013_signal_events_publication_and_rls.sql` |
| 20 | `20260428000014_prediction_journal.sql` |
| 21 | `20260428000015_journal_costs.sql` |
| 22 | `20260428000016_journal_backtests.sql` |
| 23 | `20260428000017_journal_backtests_uncertainty.sql` |
| 24 | `20260428000018_journal_forecasts_horizon.sql` |
| 25 | `20260428000019_journal_forecasts_horizon_validate.sql` |
| 26 | `20260428000020_journal_scores_paired_brier.sql` |
| 27 | `20260428000021_journal_scores_paired_brier_validate.sql` |

**Watermark: `20260428000021_journal_scores_paired_brier_validate.sql`**

## How to record a new one

1. Apply the migration to the production Supabase project (the agent does **not** apply migrations).
2. Add a row to the table above, in filename order.
3. Update the watermark line.
4. `tests/test_migrations_recorded.py` must pass before the PR merges.

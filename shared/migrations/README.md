# Superseded

These two files are no longer the source of truth for schema. They have been
folded into the CLI-tracked migration path so `kalshi_edges`, `macro_signals`,
`fpl_optimizations`, and `news_embeddings` are versioned the same way as every
other table:

- `001_add_kalshi_and_macro_tables.sql` → `market_sentiment_tool/supabase/migrations/20260416000001_kalshi_edges_and_macro.sql`
- `002_add_pgvector_news.sql` → `market_sentiment_tool/supabase/migrations/20260416000002_pgvector_news.sql`

Left in place for history rather than deleted. New schema changes should go
through `market_sentiment_tool/supabase/migrations/` via the Supabase CLI,
not this folder.

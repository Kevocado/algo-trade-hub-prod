-- Close two tables the Supabase security advisor flagged as "RLS disabled in public":
-- with RLS off, anyone holding the public anon key could insert, update or delete rows.
-- Applied to production on 2026-09-26 via the Supabase connector; recorded here so the repo
-- matches the database. Idempotent.
--
-- kalshi_portfolio: written only by the backend (service role, which bypasses RLS); the War
-- Room reads it with the anon key (src/hooks/usePortfolio.ts), so clients get read-only.
ALTER TABLE kalshi_portfolio ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "kalshi_portfolio_public_read" ON kalshi_portfolio;
CREATE POLICY "kalshi_portfolio_public_read" ON kalshi_portfolio FOR SELECT
  TO anon, authenticated USING (true);

-- news_embeddings: no client reads or writes it; service role only (no client policy).
ALTER TABLE news_embeddings ENABLE ROW LEVEL SECURITY;

-- Advisor "function_search_path_mutable": pin match_news's search path.
ALTER FUNCTION public.match_news(vector, integer) SET search_path = public, extensions;

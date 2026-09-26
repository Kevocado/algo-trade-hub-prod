-- LLM reviewer cache and call log for sports edges (rollout step 7, spec section 3.2).
-- Append-only: one row per OpenRouter call, so the daily budget count is exact.
-- Only status='ok' rows are served as cached reviews (key: sport:game:market:side:price bucket).
-- Idempotent, like the earlier migrations. Apply after 20260416000007.

CREATE TABLE IF NOT EXISTS sports_reviews (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cache_key     text NOT NULL,
  sport         text NOT NULL,
  game_id       text NOT NULL,
  market_ticker text NOT NULL,
  side          text NOT NULL CHECK (side IN ('yes', 'no')),
  price_bucket  integer NOT NULL,
  entry_price   numeric(5,4) NOT NULL,
  our_prob      numeric(5,4) NOT NULL,
  model         text,
  status        text NOT NULL CHECK (status IN ('ok', 'invalid', 'error')),
  explainable   boolean,
  drivers       jsonb NOT NULL DEFAULT '[]'::jsonb,
  red_flags     jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  user_id       uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS sports_reviews_cache_key_idx ON sports_reviews (cache_key, status);
CREATE INDEX IF NOT EXISTS sports_reviews_created_at_idx ON sports_reviews (created_at);

-- kalshi_edges gains the game start as a first-class, indexable column.
--
-- expires_at is the Kalshi close time, which for a sports market is about TWO DAYS after
-- kickoff (the recorded fixtures close 2026-09-29 for games starting 2026-09-27), so an
-- expires_at predicate cannot express "this game has started" and started games stayed on the
-- board for days. start_utc is what the scan writes and what the started-game delete filters
-- on, scoped to engine IN ('sports_nfl','sports_cfb').
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS start_utc timestamptz;
CREATE INDEX IF NOT EXISTS kalshi_edges_sports_start_idx ON kalshi_edges (engine, start_utc);

-- Backfill rows written before the column existed: the scan has always put the start in
-- raw_payload, so those rows are recoverable instead of keeping a NULL start_utc forever
-- (a NULL start_utc never matches a `<= now` predicate, i.e. a started game would be kept).
UPDATE kalshi_edges
   SET start_utc = NULLIF(raw_payload ->> 'start_utc', '')::timestamptz
 WHERE edge_type = 'SPORTS'
   AND start_utc IS NULL
   AND raw_payload ? 'start_utc'
   AND NULLIF(raw_payload ->> 'start_utc', '') ~ '^\d{4}-\d{2}-\d{2}[T ]';

-- The scan job writes with the service role (bypasses RLS); the War Room reads through the API.
ALTER TABLE sports_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sports_reviews_owner_read" ON sports_reviews;
CREATE POLICY "sports_reviews_owner_read" ON sports_reviews FOR SELECT
  USING (auth.uid() = user_id);

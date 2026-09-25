-- Predictions ledger + per-engine track record (rollout step 2 of the
-- prediction-scope redesign).
--
-- Idempotent: safe to re-run via `supabase db push` or the SQL editor,
-- following the pattern of 20260416000001_kalshi_edges_and_macro.sql.

-- Every engine output, whether or not anyone trades on it (spec section 4.4).
-- Rows start OPEN; the settlement job flips them to SETTLED (or CANCELED)
-- against the Kalshi market result.
CREATE TABLE IF NOT EXISTS predictions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  market_ticker  text NOT NULL,
  our_prob       numeric(5,4) NOT NULL CHECK (our_prob >= 0 AND our_prob <= 1),
  market_prob    numeric(5,4) CHECK (market_prob IS NULL OR (market_prob >= 0 AND market_prob <= 1)),
  engine         text NOT NULL,
  engine_version text NOT NULL DEFAULT 'v0',
  as_of          timestamptz NOT NULL,
  status         text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'SETTLED', 'CANCELED')),
  result         text CHECK (result IN ('yes', 'no')),
  brier          numeric(6,5),
  market_brier   numeric(6,5),
  raw_payload    jsonb,
  created_at     timestamptz DEFAULT now(),
  user_id        uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS predictions_engine_status_idx ON predictions (engine, status);
CREATE INDEX IF NOT EXISTS predictions_ticker_idx ON predictions (market_ticker);
ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "predictions_owner" ON predictions;
CREATE POLICY "predictions_owner" ON predictions FOR ALL
  USING (auth.uid() = user_id);

-- Per-engine rollup the Track Record UI reads (spec sections 4.5 and 6).
-- Recomputed by the settlement cron job after every pass.
CREATE TABLE IF NOT EXISTS track_record (
  engine         text PRIMARY KEY,
  engine_version text NOT NULL DEFAULT 'v0',
  n_settled      integer NOT NULL DEFAULT 0,
  brier_ours     numeric(6,5),
  brier_market   numeric(6,5),
  cal_buckets    jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_cal_dev    numeric(5,4),
  gate_status    text NOT NULL DEFAULT 'SHADOW' CHECK (gate_status IN ('SHADOW', 'PROMOTED', 'DEMOTED')),
  updated_at     timestamptz DEFAULT now(),
  user_id        uuid REFERENCES auth.users(id)
);
ALTER TABLE track_record ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "track_record_owner" ON track_record;
CREATE POLICY "track_record_owner" ON track_record FOR ALL
  USING (auth.uid() = user_id);

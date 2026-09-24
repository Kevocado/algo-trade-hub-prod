-- Migration: Schema consolidation (Phase 0 of the improvement roadmap)
--
-- 1. Give `trades.status` a real vocabulary instead of free-text VARCHAR(20),
--    and split `pnl` into realized vs unrealized so settlement (Phase 1) has
--    somewhere to write. Existing values in production are only ever
--    PENDING / OPEN / FILLED / CLOSED (verified against orchestrator.py and
--    mcp_server.py), so this constraint does not need a backfill.
ALTER TABLE trades RENAME COLUMN pnl TO realized_pnl;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC DEFAULT 0.0;

ALTER TABLE trades
ALTER COLUMN status SET DEFAULT 'PENDING';

ALTER TABLE trades
DROP CONSTRAINT IF EXISTS trades_status_check;

ALTER TABLE trades
ADD CONSTRAINT trades_status_check
CHECK (status IN ('PENDING', 'OPEN', 'FILLED', 'SETTLED', 'CLOSED', 'CANCELLED'));

-- 2. `kalshi_portfolio` and `portfolio_metrics` are written to by
--    SP500 Predictor/src/supabase_client.py (upsert_kalshi_portfolio,
--    upsert_portfolio_metrics) and read by
--    market_sentiment_tool/src/hooks/usePortfolio.ts, but had no migration
--    anywhere -- they were created ad hoc via the Supabase dashboard.
--    Columns below match those two call sites exactly.
CREATE TABLE IF NOT EXISTS kalshi_portfolio (
    id              TEXT PRIMARY KEY,
    balance         NUMERIC DEFAULT 0,
    portfolio_value NUMERIC DEFAULT 0,
    total_invested  NUMERIC DEFAULT 0,
    total_pnl       NUMERIC DEFAULT 0,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    open_positions  JSONB DEFAULT '[]'::jsonb,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_metrics (
    id          INTEGER PRIMARY KEY,
    total_value NUMERIC DEFAULT 0,
    daily_pnl   NUMERIC DEFAULT 0,
    cash_balance NUMERIC DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE kalshi_portfolio ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_metrics ENABLE ROW LEVEL SECURITY;

-- Both tables are single-row/global (id='MAIN_ACCOUNT' / id=1) and are only
-- ever written by the Python backend via the service-role key, which
-- bypasses RLS entirely -- so these need a read-only anon policy and no
-- write policy at all (unlike user_settings, there is no legitimate
-- browser-side write path here).
DROP POLICY IF EXISTS "Anon can view kalshi portfolio" ON kalshi_portfolio;
CREATE POLICY "Anon can view kalshi portfolio"
ON kalshi_portfolio FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "Anon can view portfolio metrics" ON portfolio_metrics;
CREATE POLICY "Anon can view portfolio metrics"
ON portfolio_metrics FOR SELECT TO anon USING (true);

ALTER PUBLICATION supabase_realtime ADD TABLE kalshi_portfolio;
ALTER PUBLICATION supabase_realtime ADD TABLE portfolio_metrics;

-- NOTE (intentionally not done here): user_settings currently has an
-- "Anon can update settings" policy (20260223223000_enable_realtime_and_rls.sql)
-- that is the only write path for the frontend's kill-switch toggle
-- (useSupabaseData.ts:toggleAutoTrade) -- there is no real auth session
-- wired up (Auth.tsx/AuthContext.tsx exist but are unused/unrouted).
-- Removing that policy without first building a real auth flow or a
-- server-side toggle endpoint would silently disable the kill switch.
-- Flagging for a deliberate follow-up rather than changing it here.

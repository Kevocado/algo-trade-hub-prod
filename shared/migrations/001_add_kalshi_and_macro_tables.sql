-- ============================================================
-- Migration 001: Kalshi edges, macro signals, FPL optimizations
-- Target: Supabase project wuhpbvgidnrrdndhkehl
-- ============================================================

-- Kalshi market edges (weather, macro, sports arbitrage)
CREATE TABLE IF NOT EXISTS kalshi_edges (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  market_id     text NOT NULL,
  title         text,
  edge_type     text CHECK (edge_type IN ('WEATHER', 'MACRO', 'SPORTS')),
  our_prob      numeric(5,4),
  market_prob   numeric(5,4),
  edge_pct      numeric(5,4),
  raw_payload   jsonb,
  discovered_at timestamptz DEFAULT now(),
  user_id       uuid REFERENCES auth.users(id)
);
ALTER TABLE kalshi_edges ENABLE ROW LEVEL SECURITY;
CREATE POLICY "kalshi_edges_owner" ON kalshi_edges FOR ALL
  USING (auth.uid() = user_id);

-- Macro signals from FRED + NWS
CREATE TABLE IF NOT EXISTS macro_signals (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source      text,           -- 'FRED' | 'NWS'
  series_id   text,           -- e.g. 'UNRATE', 'DGS10', 'NWS_OHX'
  value       numeric,
  signal_ts   timestamptz,
  created_at  timestamptz DEFAULT now(),
  user_id     uuid REFERENCES auth.users(id)
);
ALTER TABLE macro_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "macro_signals_owner" ON macro_signals FOR ALL
  USING (auth.uid() = user_id);

-- FPL optimizer run results
CREATE TABLE IF NOT EXISTS fpl_optimizations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy      text,
  total_cost    numeric,
  total_score   numeric,
  captain       text,
  squad_json    jsonb,
  created_at    timestamptz DEFAULT now(),
  user_id       uuid REFERENCES auth.users(id)
);
ALTER TABLE fpl_optimizations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "fpl_optimizations_owner" ON fpl_optimizations FOR ALL
  USING (auth.uid() = user_id);

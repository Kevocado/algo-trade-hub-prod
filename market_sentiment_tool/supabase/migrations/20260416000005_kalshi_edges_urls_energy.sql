-- kalshi_edges: deep links + ENERGY edge type + unique market_id (rollout step 4).
-- Idempotent. The original CHECK was declared inline on edge_type, so
-- Postgres named it kalshi_edges_edge_type_check.

ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS market_url text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS engine text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS gate_status text NOT NULL DEFAULT 'SHADOW';
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS expires_at timestamptz;

ALTER TABLE kalshi_edges DROP CONSTRAINT IF EXISTS kalshi_edges_edge_type_check;
ALTER TABLE kalshi_edges ADD CONSTRAINT kalshi_edges_edge_type_check
  CHECK (edge_type IN ('WEATHER', 'MACRO', 'SPORTS', 'CRYPTO', 'ENERGY'));
ALTER TABLE kalshi_edges DROP CONSTRAINT IF EXISTS kalshi_edges_gate_status_check;
ALTER TABLE kalshi_edges ADD CONSTRAINT kalshi_edges_gate_status_check
  CHECK (gate_status IN ('SHADOW', 'PROMOTED'));

-- upsert(on_conflict="market_id") requires a unique index on market_id.
CREATE UNIQUE INDEX IF NOT EXISTS kalshi_edges_market_id_key ON kalshi_edges (market_id);

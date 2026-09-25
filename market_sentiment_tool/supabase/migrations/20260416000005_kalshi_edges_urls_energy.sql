-- kalshi_edges: deep links + ENERGY edge type + unique market_id (rollout step 4).
-- Idempotent. The original CHECK was declared inline on edge_type, so
-- Postgres named it kalshi_edges_edge_type_check.

ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS market_url text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE kalshi_edges ADD COLUMN IF NOT EXISTS engine text;
-- Rows that exist before this migration were written by the legacy scanners
-- (background_scanner / fast_scanner). Tag them legacy_* so the scan's
-- engine-scoped stale-edge cleanup ('weather', 'gas') never deletes them.
UPDATE kalshi_edges SET engine = 'legacy_' || lower(edge_type) WHERE engine IS NULL;
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
-- The legacy scanners inserted rather than upserted, so duplicates may exist:
-- keep the newest row per market_id before creating the index.
DELETE FROM kalshi_edges a
  USING kalshi_edges b
  WHERE a.market_id = b.market_id
    AND (COALESCE(a.discovered_at, 'epoch'), a.id::text) < (COALESCE(b.discovered_at, 'epoch'), b.id::text);
CREATE UNIQUE INDEX IF NOT EXISTS kalshi_edges_market_id_key ON kalshi_edges (market_id);
CREATE INDEX IF NOT EXISTS kalshi_edges_engine_idx ON kalshi_edges (engine);

-- 20260416000011: the five tables the Trade Hub reads and writes that no migration ever created.
--
-- Found by auditing the live app on 2026-09-27: `tests/test_war_room_api_truthfulness.py` walks
-- every `supabase.table(...)` name in tradehub/ and fails if no migration creates it. It named
-- five. The live symptoms were `/api/positions` and `/api/pnl_summary` returning HTTP 500
-- (PostgREST PGRST205) and `/api/opportunities` returning an empty list, because the write path
-- in tradehub/core/supabase_client.py has been failing since the hub was deployed.
--
-- WHAT THIS CREATES (five tables, no data, no change to any existing table):
--   live_opportunities - one row per opportunity a scan proposed. Written by record_opportunities().
--   paper_signals      - one row per Quant ML paper signal. Written by insert_paper_signal().
--   trade_history      - one row per prediction, for the backtester. insert_trade_log()/get_trade_history().
--   scanner_runs       - one row per scanner run (start/complete). start_run()/complete_run()/get_wipe_date().
--   paper_trades       - the paper position ledger the /api/positions and /api/pnl_summary
--                        endpoints read. Nothing writes it, so it starts empty: this is a
--                        SUGGEST-ONLY product and an empty ledger is the honest state, not a fault.
--
-- Column sets are exactly the keys the code inserts or filters on; `select *` readers are
-- unaffected by later additions. RLS follows the existing convention: owner-only writes, and the
-- anon SELECT the War Room SPA needs is NOT granted here, because the SPA is being moved onto
-- this API rather than reading the database from the browser.

-- ── live_opportunities ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS live_opportunities (
    id             BIGSERIAL PRIMARY KEY,
    run_id         TEXT,
    engine         TEXT NOT NULL DEFAULT 'Unknown',
    asset          TEXT NOT NULL DEFAULT '',
    market_title   TEXT NOT NULL DEFAULT '',
    market_ticker  TEXT NOT NULL DEFAULT '',
    event_ticker   TEXT NOT NULL DEFAULT '',
    action         TEXT NOT NULL DEFAULT '',
    model_prob     DOUBLE PRECISION NOT NULL DEFAULT 0,
    market_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    edge           DOUBLE PRECISION NOT NULL DEFAULT 0,
    confidence     DOUBLE PRECISION NOT NULL DEFAULT 0,
    reasoning      TEXT NOT NULL DEFAULT '',
    data_source    TEXT NOT NULL DEFAULT '',
    kalshi_url     TEXT NOT NULL DEFAULT '',
    market_date    TEXT NOT NULL DEFAULT '',
    expiration     TEXT NOT NULL DEFAULT '',
    ai_approved    BOOLEAN NOT NULL DEFAULT TRUE,
    ai_reasoning   TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_live_opportunities_created_at
    ON live_opportunities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_opportunities_ticker
    ON live_opportunities(market_ticker);

-- ── paper_signals ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paper_signals (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT,
    ticker          TEXT NOT NULL DEFAULT '',
    predicted_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    direction       TEXT NOT NULL DEFAULT '',
    model_prob      DOUBLE PRECISION NOT NULL DEFAULT 0,
    kelly_bet       DOUBLE PRECISION NOT NULL DEFAULT 0,
    edge            DOUBLE PRECISION NOT NULL DEFAULT 0,
    rmse            DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_paper_signals_created_at
    ON paper_signals(created_at DESC);

-- ── trade_history ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_history (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL DEFAULT '',
    predicted_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    actual_price    DOUBLE PRECISION,
    model_rmse      DOUBLE PRECISION NOT NULL DEFAULT 0,
    best_edge       DOUBLE PRECISION NOT NULL DEFAULT 0,
    best_action     TEXT NOT NULL DEFAULT '',
    best_strike     TEXT NOT NULL DEFAULT '',
    brier_score     DOUBLE PRECISION,
    pnl_cents       DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trade_history_ticker
    ON trade_history(ticker, created_at DESC);

-- ── scanner_runs ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scanner_runs (
    id           BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    engines_run  JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_opps   INTEGER NOT NULL DEFAULT 0,
    duration_sec DOUBLE PRECISION,
    error_msg    TEXT,
    wipe_date    TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scanner_runs_run_id
    ON scanner_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_scanner_runs_created_at
    ON scanner_runs(created_at DESC);

-- ── paper_trades ─────────────────────────────────────────────────────────────
-- Read by /api/positions and /api/pnl_summary. Deliberately has no writer: the product is
-- suggest-only (spec section 6), so the ledger stays empty until a paper-trading feature earns
-- one. The shape is the legacy research file's, which is what those two endpoints already read.
CREATE TABLE IF NOT EXISTS paper_trades (
    id               BIGSERIAL PRIMARY KEY,
    engine           TEXT NOT NULL,
    ticker           TEXT,
    action           TEXT,
    side             TEXT,
    contracts        INTEGER NOT NULL DEFAULT 1,
    avg_cost_cents   REAL,
    exit_price_cents REAL,
    pnl_cents        REAL,
    edge_pct         REAL,
    model_prob       REAL,
    status           TEXT NOT NULL DEFAULT 'signal',
    ai_cleared       BOOLEAN,
    ai_reason        TEXT,
    reasoning        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status
    ON paper_trades(status);

-- ── RLS: owner-only writes, consistent with the other tables in this schema ───
ALTER TABLE live_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_signals      ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_history      ENABLE ROW LEVEL SECURITY;
ALTER TABLE scanner_runs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_trades       ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['live_opportunities', 'paper_signals', 'trade_history',
                             'scanner_runs', 'paper_trades']
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_owner_all', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR ALL TO authenticated USING (auth.uid() IS NOT NULL) '
            'WITH CHECK (auth.uid() IS NOT NULL)', t || '_owner_all', t);
    END LOOP;
END $$;

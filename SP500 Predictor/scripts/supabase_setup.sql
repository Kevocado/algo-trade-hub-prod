-- ============================================================
-- Kalshi Edge System — Supabase Schema
-- Run this in the Supabase SQL Editor (Dashboard → SQL)
-- ============================================================

-- Live scanner opportunities
CREATE TABLE IF NOT EXISTS live_opportunities (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL,
    engine          TEXT NOT NULL,
    asset           TEXT,
    market_title    TEXT,
    market_ticker   TEXT,
    event_ticker    TEXT,
    action          TEXT,
    model_prob      REAL,
    market_price    REAL,
    edge            REAL,
    confidence      REAL,
    reasoning       TEXT,
    data_source     TEXT,
    kalshi_url      TEXT,
    market_date     TEXT,
    expiration      TEXT,
    ai_approved     BOOLEAN DEFAULT TRUE,
    ai_reasoning    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Paper trading signals from Quant engine
CREATE TABLE IF NOT EXISTS paper_signals (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    predicted_price REAL,
    current_price   REAL,
    direction       TEXT,
    model_prob      REAL,
    kelly_bet       REAL,
    edge            REAL,
    rmse            REAL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Historical trade log for backtesting & PnL tracking
CREATE TABLE IF NOT EXISTS trade_history (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    predicted_price REAL,
    current_price   REAL,
    actual_price    REAL,
    model_rmse      REAL,
    best_edge       REAL,
    best_action     TEXT,
    best_strike     TEXT,
    brier_score     REAL,
    pnl_cents       REAL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Scanner run metadata
CREATE TABLE IF NOT EXISTS scanner_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT UNIQUE NOT NULL,
    status          TEXT DEFAULT 'running',
    engines_run     TEXT[],
    total_opps      INTEGER DEFAULT 0,
    duration_sec    REAL,
    error_msg       TEXT,
    wipe_date       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ============================================================
-- Phase 1-4 Extension: New tables for decoupled system
-- ============================================================

-- Unified paper trade log (the 200-trade threshold for live capital)
-- engine: "weather_maker" | "nba_props" | "f1_telemetry" | "crypto_microstructure"
CREATE TABLE IF NOT EXISTS paper_trades (
    id               BIGSERIAL PRIMARY KEY,
    engine           TEXT NOT NULL,
    ticker           TEXT,
    action           TEXT,
    side             TEXT,
    contracts        INTEGER DEFAULT 1,
    avg_cost_cents   REAL,
    exit_price_cents REAL,
    pnl_cents        REAL,
    edge_pct         REAL,
    model_prob       REAL,
    status           TEXT DEFAULT 'signal',  -- "signal"|"open"|"closed"|"aborted"
    ai_cleared       BOOLEAN,
    ai_reason        TEXT,
    reasoning        TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at        TIMESTAMPTZ
);

-- NBA player props signals
CREATE TABLE IF NOT EXISTS nba_props (
    id               BIGSERIAL PRIMARY KEY,
    player           TEXT NOT NULL,
    team             TEXT,
    stat             TEXT NOT NULL,
    line             REAL NOT NULL,
    model_prob_over  REAL,
    kalshi_ticker    TEXT,
    kalshi_yes_ask   REAL,
    edge_pct         REAL,
    action           TEXT,
    injury_flag      BOOLEAN DEFAULT FALSE,
    injury_status    TEXT,
    is_b2b           BOOLEAN DEFAULT FALSE,
    game_date        TEXT,
    detected_at      TIMESTAMPTZ DEFAULT NOW()
);

-- F1 telemetry-derived signals
CREATE TABLE IF NOT EXISTS f1_signals (
    id               BIGSERIAL PRIMARY KEY,
    driver           TEXT NOT NULL,
    team             TEXT,
    event            TEXT NOT NULL,
    session          TEXT,
    signal_type      TEXT,
    model_prob       REAL,
    kalshi_ticker    TEXT,
    kalshi_yes_ask   REAL,
    edge_pct         REAL,
    action           TEXT,
    key_metric       TEXT,
    detected_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Hourly scanner snapshots for trend analysis
CREATE TABLE IF NOT EXISTS scanner_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    snapshot_at      TIMESTAMPTZ DEFAULT NOW(),
    total_opps       INTEGER DEFAULT 0,
    high_edge_opps   INTEGER DEFAULT 0,
    engines_run      TEXT[],
    top_edge_pct     REAL,
    raw_json         JSONB
);

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_live_opps_run        ON live_opportunities(run_id);
CREATE INDEX IF NOT EXISTS idx_live_opps_engine     ON live_opportunities(engine);
CREATE INDEX IF NOT EXISTS idx_paper_signals_ticker ON paper_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_trade_history_ticker ON trade_history(ticker);
CREATE INDEX IF NOT EXISTS idx_scanner_runs_status  ON scanner_runs(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_engine  ON paper_trades(engine);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status  ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_created ON paper_trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nba_props_player     ON nba_props(player);
CREATE INDEX IF NOT EXISTS idx_nba_props_detected   ON nba_props(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_f1_signals_driver    ON f1_signals(driver);
CREATE INDEX IF NOT EXISTS idx_f1_signals_detected  ON f1_signals(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_scanner_snap_at      ON scanner_snapshots(snapshot_at DESC);

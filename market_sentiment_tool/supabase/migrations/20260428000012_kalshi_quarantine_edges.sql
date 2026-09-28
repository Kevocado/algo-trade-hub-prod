-- 20260428000012: the second sink. Quarantined Weather and Macro rows, measured and readable.
--
-- WHY THIS TABLE EXISTS. PR #38 labelled the Weather and Macro real-edge engines as stopped,
-- correctly: they read a Kalshi quote field the API no longer sends, so every market they fetched
-- looked like a 0c quote, every one was skipped, and they published nothing while appearing to run.
-- That was honest and it answered a question nobody asked. The owner's question is what those
-- engines WOULD do, and the labelling deliberately did not say: repairing them makes them produce
-- 295 rows a scan into the one table a reader trusts, from a model with no measurement, no gate
-- and no backtest, and whether to publish that is a decision that has not been made.
--
-- So the engines were repaired and their output put HERE instead. This is a measurement surface and
-- nothing else: no writer reads it to place an order, nothing settles it, it feeds no scoreboard,
-- and no pipeline consumes it. It exists so the decision can be made against real output rather
-- than against unseen code.
--
-- DELIBERATELY NOT `kalshi_edges` WITH A COLUMN. A row in `kalshi_edges` is a row something
-- downstream can act on, and a `quarantined` boolean is one refactor, one upsert rewrite or one
-- new consumer away from not being read. A separate table cannot be mistaken for a trade proposal
-- by anything that does not go looking for it.
--
-- NOTHING IS MIGRATED INTO IT. The engines have been producing nothing, so there is no backlog to
-- copy, and a table pre-filled with rows nobody scanned would be a table of numbers with no scan
-- behind them.

CREATE TABLE IF NOT EXISTS kalshi_quarantine_edges (
    -- The same key `kalshi_edges` upserts on, so a quarantined row and a published row for the
    -- same market collide loudly in review rather than quietly coexisting.
    market_id             TEXT PRIMARY KEY,
    title                 TEXT NOT NULL DEFAULT '',
    engine                TEXT,
    edge_type             TEXT,
    action                TEXT,
    market_ticker         TEXT,
    event_ticker          TEXT,

    -- Cents and percentage points, exactly as the engines produced them. NOT rescaled into 0-1 the
    -- way `kalshi_edges` stores probabilities: the two tables are read by different things, and
    -- mixing the conventions is how a 29c quote becomes a 0.29% one.
    --
    -- All three are NULLABLE and the writer sends NULL for a figure the engine did not record. A
    -- missing figure is never a number, and this is the one table where that rule is load-bearing
    -- rather than assumed: the table exists to hold figures that were really measured, so a
    -- fabricated 0 in it would be the defect this whole change exists to stop, quieter.
    price_cents           DOUBLE PRECISION,
    model_probability_pct DOUBLE PRECISION,
    edge_points           DOUBLE PRECISION,

    -- The classification, stored rather than recomputed by whoever reads this. `edge_kind` is
    -- 'opportunity' or 'units_artefact'; `independent` is false on every row that restates a
    -- forecast an earlier row already made. Without these columns the table holds 295 undifferentiated
    -- rows, which is the unreadable number the surface was built to replace.
    edge_kind             TEXT NOT NULL DEFAULT 'opportunity',
    independent           BOOLEAN NOT NULL DEFAULT TRUE,
    -- 'engine | asset | model probability'. The identity of the STATEMENT, as opposed to the market
    -- it was applied to. Two rows sharing this key are one opinion, and the independent count counts
    -- each key once.
    forecast_key          TEXT,

    reasoning             TEXT,
    kalshi_url            TEXT,

    -- The marker travels with the row, three ways, so a row read out of context -- out of SQL, out
    -- of a CSV, out of a support ticket -- cannot be read as a live edge. A quarantined number that
    -- travels alone is indistinguishable from a published one, and that is the whole failure.
    quarantined           BOOLEAN NOT NULL DEFAULT TRUE,
    marker                TEXT NOT NULL DEFAULT 'QUARANTINED',
    note                  TEXT NOT NULL DEFAULT '',

    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Read by `/api/quarantine`, which filters by engine and orders by recency.
CREATE INDEX IF NOT EXISTS idx_kalshi_quarantine_edges_engine
    ON kalshi_quarantine_edges(engine, updated_at DESC);
-- The counts the surface reports, so they are not a sequential scan of the whole table per request.
CREATE INDEX IF NOT EXISTS idx_kalshi_quarantine_edges_kind
    ON kalshi_quarantine_edges(edge_kind, independent);
-- One statement's restatements, which is how a reader finds the eleven rows that are one GDP point
-- forecast rather than eleven opinions.
CREATE INDEX IF NOT EXISTS idx_kalshi_quarantine_edges_forecast
    ON kalshi_quarantine_edges(forecast_key);

-- A row that is not marked quarantined does not belong in this table. It is the table's whole
-- meaning, and a DEFAULT of FALSE with no NOT NULL would let a partial insert produce a row that
-- reads as a live edge while sitting in the quarantine ledger.
ALTER TABLE kalshi_quarantine_edges DROP CONSTRAINT IF EXISTS kalshi_quarantine_edges_quarantined_true;
ALTER TABLE kalshi_quarantine_edges
    ADD CONSTRAINT kalshi_quarantine_edges_quarantined_true CHECK (quarantined);

-- RLS: backend-only, matching 20260416000011. The War Room SPA goes through the API with the
-- service role, which bypasses RLS, so no client policy is created and the anon key gets nothing.
ALTER TABLE kalshi_quarantine_edges ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "kalshi_quarantine_edges_owner_all" ON kalshi_quarantine_edges;

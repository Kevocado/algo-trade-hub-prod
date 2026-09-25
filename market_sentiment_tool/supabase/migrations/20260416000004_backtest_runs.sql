-- Backtest runs (rollout step 3, spec section 5a).
-- One row per reproducible backtest: engine version + config hash +
-- data-snapshot hash + date range pin down exactly what was replayed.
-- Idempotent, following 20260416000003_predictions_ledger.sql.

CREATE TABLE IF NOT EXISTS backtest_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  engine          text NOT NULL,
  engine_version  text NOT NULL,
  mode            text NOT NULL CHECK (mode IN ('taker', 'maker')),
  config          jsonb NOT NULL DEFAULT '{}'::jsonb,
  config_hash     text NOT NULL,
  data_hash       text NOT NULL,
  date_from       timestamptz NOT NULL,
  date_to         timestamptz NOT NULL,
  n_decisions     integer NOT NULL,
  n_fills         integer NOT NULL,
  n_settled       integer NOT NULL,
  pnl_after_fees  numeric(12,4) NOT NULL,
  max_drawdown    numeric(12,4) NOT NULL,
  turnover        numeric(12,4) NOT NULL,
  brier_ours      numeric(6,5),
  brier_market    numeric(6,5),
  cal_buckets     jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_cal_dev     numeric(5,4),
  gate_status     text NOT NULL CHECK (gate_status IN ('SHADOW', 'PROMOTED')),
  gate_reasons    jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at      timestamptz DEFAULT now(),
  user_id         uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS backtest_runs_engine_idx ON backtest_runs (engine, created_at DESC);
ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "backtest_runs_owner" ON backtest_runs;
CREATE POLICY "backtest_runs_owner" ON backtest_runs FOR ALL
  USING (auth.uid() = user_id);

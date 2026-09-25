-- Add the spec-required log-loss metric without changing existing backtest rows.
-- Nullable so runs recorded before this migration remain readable.
ALTER TABLE backtest_runs
  ADD COLUMN IF NOT EXISTS log_loss numeric(12,8);

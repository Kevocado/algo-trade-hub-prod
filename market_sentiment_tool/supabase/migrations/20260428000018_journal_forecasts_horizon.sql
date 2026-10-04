-- journal_forecasts.horizon: spec §3 step 1 names it in the row shape
--   `(forecaster, target, horizon, probability, frozen_at, source_hash)`
-- and it was never added. Without it a frozen row cannot say how far ahead it was made, so
-- calibration cannot be read per-horizon and a 5-minute-ahead CPI call is indistinguishable from a
-- one-month-ahead housing call.
--
-- Seconds from the freeze to the target's cutoff, computed by the runner from the calendar row it
-- already has. NULL is allowed and expected for rows frozen before this migration: an absent horizon
-- is an honest gap, and backfilling it would invent a freeze time that was never recorded.
ALTER TABLE journal_forecasts
  ADD COLUMN IF NOT EXISTS horizon_seconds integer
  CHECK (horizon_seconds IS NULL OR horizon_seconds >= 0);

COMMENT ON COLUMN journal_forecasts.horizon_seconds IS
  'Seconds from frozen_at to the target''s cutoff. NULL for rows frozen before this migration; '
  'not backfilled, because the freeze time it would need was never stored.';

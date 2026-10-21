-- journal_scores.gap / gap_se: the paired Brier gap vs baseline (model Brier minus baseline Brier,
-- negative = better) and its standard error, computed per-contract from squared-error differences.
--
-- NULL is allowed and expected for rows scored before this migration, and they are NOT backfilled:
-- the per-contract squared-error differences a row's gap/SE was computed from were never stored,
-- so any backfilled value would be a number nobody measured. `market_skill()` and the journal
-- skill chart skip a NULL here rather than reading it as 0.0.
--
-- Additive and idempotent: `IF NOT EXISTS` means re-applying is a no-op. Each ALTER TABLE takes
-- only ROW SHARE (or less) on an existing table, so it does not block the hourly journal's reads
-- or writes while it adds the column.
ALTER TABLE journal_scores
  ADD COLUMN IF NOT EXISTS gap double precision;

ALTER TABLE journal_scores
  ADD COLUMN IF NOT EXISTS gap_se double precision;

COMMENT ON COLUMN journal_scores.gap IS
  'Paired Brier gap vs baseline on the same contracts: model Brier minus baseline Brier. '
  'Negative = better than baseline. NULL for rows scored before 20260428000022, and not backfilled '
  '-- the per-contract squared-error differences were never stored.';

COMMENT ON COLUMN journal_scores.gap_se IS
  'Standard error of the paired Brier gap, computed from per-contract squared-error differences. '
  'NULL for rows scored before 20260428000022, and not backfilled.';
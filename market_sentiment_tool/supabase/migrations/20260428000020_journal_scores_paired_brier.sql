-- journal_scores.brier_on_baseline / n_baseline: the other half of the fraction `bss` was computed from.
--
-- `brier` is a mean over EVERY settled target. `brier_baseline` is a mean over only the targets that HAVE
-- a baseline. `bss` is `1 - ours_b / brier_base`, where `ours_b` is the MODEL's Brier over those same
-- baseline-matched targets -- and `ours_b` was computed, used, and thrown away. So the scorecard could
-- not say what it had been graded against, and `market_skill()` had to pair `brier` against
-- `brier_baseline`: an all-targets numerator, a matched-subset denominator, all-targets weights.
--
-- That is three different denominators in one ratio, and it inverted the headline's SIGN. A forecaster
-- that beat the market on the 100 targets the market is graded on, and had 300 further settled targets
-- with no market at all, pooled as `1 - 0.61/0.04 = -14.25` while its own `bss` was `+0.75`.
--
-- NULL is allowed and expected for rows scored before this migration, and they are NOT backfilled: the
-- matched subset a row's `bss` was computed from was never stored, so any backfilled value would be a
-- number nobody measured. `market_skill()` skips a NULL here rather than reading it as 0.0, so the hero
-- drops to absent instead of publishing a fabricated 1.00.
--
-- CodeRabbit, on #110: the CHECKs are named NOT VALID constraints rather than inline, and are validated
-- in the follow-up migration 20260428000021. `journal_scores` predates this migration and is NOT empty
-- in production, so an inline CHECK made Postgres scan every existing row while holding ACCESS
-- EXCLUSIVE -- blocking the hourly journal's reads AND writes for the length of the scan. NOT VALID
-- takes a brief lock to record the constraint and skips the scan; the VALIDATE in the follow-up takes
-- only SHARE UPDATE EXCLUSIVE, which does not block reads or writes.
ALTER TABLE journal_scores
  ADD COLUMN IF NOT EXISTS brier_on_baseline numeric(8,6);

ALTER TABLE journal_scores
  ADD COLUMN IF NOT EXISTS n_baseline integer;

-- A Brier score is a squared error, so it cannot be negative, and a count cannot be either.
ALTER TABLE journal_scores
  DROP CONSTRAINT IF EXISTS journal_scores_brier_on_baseline_nonneg;

ALTER TABLE journal_scores
  ADD CONSTRAINT journal_scores_brier_on_baseline_nonneg
  CHECK (brier_on_baseline IS NULL OR brier_on_baseline >= 0) NOT VALID;

ALTER TABLE journal_scores
  DROP CONSTRAINT IF EXISTS journal_scores_n_baseline_nonneg;

ALTER TABLE journal_scores
  ADD CONSTRAINT journal_scores_n_baseline_nonneg
  CHECK (n_baseline IS NULL OR n_baseline >= 0) NOT VALID;

-- The matched subset cannot be larger than the settled set it is a subset of. This is the invariant the
-- hero got wrong: `brier_baseline` is a mean over `n_baseline` targets, so a count that exceeded
-- `n_settled` would be a count of contracts the card does not have.
ALTER TABLE journal_scores
  DROP CONSTRAINT IF EXISTS journal_scores_n_baseline_within_settled;

ALTER TABLE journal_scores
  ADD CONSTRAINT journal_scores_n_baseline_within_settled
  CHECK (n_baseline IS NULL OR n_baseline <= n_settled) NOT VALID;

COMMENT ON COLUMN journal_scores.brier_on_baseline IS
  'The model''s Brier over exactly the targets brier_baseline covers. This is the numerator bss was '
  'computed from; brier is a different mean, over every settled target. NULL for rows scored before '
  '20260428000020, and not backfilled -- the subset was never stored.';

COMMENT ON COLUMN journal_scores.n_baseline IS
  'Settled targets that have a baseline, i.e. the denominator behind brier_baseline and the weight '
  'market_skill() pools by. Never n_settled. NULL for rows scored before 20260428000020.';
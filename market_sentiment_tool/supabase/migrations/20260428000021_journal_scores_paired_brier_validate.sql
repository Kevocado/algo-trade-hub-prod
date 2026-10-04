-- Validate the constraints 20260428000020 added NOT VALID. Split deliberately, for the reason that
-- migration gives: it took a brief lock to add the columns and record the constraints; VALIDATE
-- CONSTRAINT takes only SHARE UPDATE EXCLUSIVE, so it scans every existing row WITHOUT blocking the
-- hourly journal's reads or writes.
--
-- Nothing rewrites or backfills: rows scored before the paired columns existed keep NULL in both, and
-- NULL passes every CHECK here. This only confirms that no row which DOES carry a paired Brier or a
-- matched count is impossible -- negative, negative-counted, or counted above the card's settled set.
ALTER TABLE journal_scores
  VALIDATE CONSTRAINT journal_scores_brier_on_baseline_nonneg;

ALTER TABLE journal_scores
  VALIDATE CONSTRAINT journal_scores_n_baseline_nonneg;

ALTER TABLE journal_scores
  VALIDATE CONSTRAINT journal_scores_n_baseline_within_settled;
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
--
-- MEASURED (2026-10-04, throwaway postgres:16-alpine populated with 400 journal_scores rows, 200 of
-- them market-graded, 97 distinct brier values): this migration SCANS every existing row -- all 400,
-- including those whose paired columns are NULL -- and finds zero violations. It does not skip them:
-- NULL passes the CHECK, so a pre-00020 row is examined and legitimately passes.
--
-- The consequence is about what the pass PROVES, not about how many rows it reads. 00020 adds
-- `n_baseline`/`brier_on_baseline` as NULL and nothing backfills them, so immediately after 00020 the
-- scan can only ever confirm that no row carrying a paired value violates the constraint -- and there
-- are none yet. It is a clean result over a table with nothing in the columns to check.
--
-- Not a reason to skip it, but a reason not to expect it to mean anything immediately: apply 00020
-- first, let one journal run write paired values, then apply this. A negative control confirmed it is
-- load-bearing rather than vacuous -- with the constraint absent, a row carrying n_baseline=99 against
-- n_settled=1 was inserted and this migration rejected it. Note also that a NOT VALID constraint still
-- ENFORCES on new rows, so from 00020 onward the invariant is protected whether or not this has run.

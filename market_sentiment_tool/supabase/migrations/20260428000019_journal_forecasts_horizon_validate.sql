-- Validate the constraint 20260428000018 added NOT VALID. Split deliberately: that migration took a
-- brief lock to add the column and record the constraint; VALIDATE CONSTRAINT takes only SHARE UPDATE
-- EXCLUSIVE, so it scans every existing row WITHOUT blocking the hourly journal's reads or writes.
--
-- Nothing rewrites or backfills: rows frozen before the horizon column existed keep a NULL horizon,
-- and NULL passes the constraint. This only confirms that no row which DOES carry a horizon is
-- negative.
ALTER TABLE journal_forecasts
  VALIDATE CONSTRAINT journal_forecasts_horizon_nonneg;

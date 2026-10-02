-- Plan 16: walk-forward replays of the daily-direction models, stored apart from the journal.
--
-- A replay is context, never evidence: it has no path into journal_forecasts, journal_scores or any gate.
-- One row per replay run, so the page can show how the answer moves. Written by the service role only
-- (tradehub.scripts.backtest_daily); clients read through /api/journal/backtests.

CREATE TABLE IF NOT EXISTS journal_backtests (
  id                 bigserial PRIMARY KEY,
  forecaster         text        NOT NULL,
  forecaster_version text        NOT NULL,
  date_from          date        NOT NULL,
  date_to            date        NOT NULL,
  n                  integer     NOT NULL CHECK (n > 0),
  brier              numeric     NOT NULL,
  brier_baseline     numeric     NOT NULL,
  bss                numeric,
  by_year            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS journal_backtests_latest ON journal_backtests (forecaster, forecaster_version, created_at DESC);

ALTER TABLE journal_backtests ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON journal_backtests FROM anon, authenticated;
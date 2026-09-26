-- Jobs Scorecard (rollout step 8, spec section 3.4).
-- One row per (series, reference_month): our nowcast, the Kalshi-implied
-- ladder one hour before the release and at the last pre-release quote,
-- the first print (what Kalshi settles on), the 2nd/3rd monthly estimates,
-- the first annual benchmark, the latest value, and the scores.
-- Payroll values are in thousands of jobs; unemployment values in percent.
--
-- Written only by the service-role builder
-- (python -m tradehub.scripts.build_jobs_scorecard); the War Room reads it
-- through GET /api/jobs-scorecard. Clients can at most read their own rows,
-- like the step-2b predictions/track_record policies.
-- Numbered 000009: 000007 is step 2b, 000008 is step 7b.
-- Idempotent.

CREATE TABLE IF NOT EXISTS jobs_scorecard (
  series               text NOT NULL CHECK (series IN ('payrolls', 'unemployment')),
  reference_month      date NOT NULL,
  kalshi_event         text,
  release_date         date,
  kalshi_close_ts      timestamptz,
  nowcast_mu           numeric(12,4),
  nowcast_sigma        numeric(12,4),
  engine_version       text,
  nowcast_features     jsonb NOT NULL DEFAULT '{}'::jsonb,
  kalshi_ladder_1h     jsonb NOT NULL DEFAULT '[]'::jsonb,
  kalshi_ladder_close  jsonb NOT NULL DEFAULT '[]'::jsonb,
  kalshi_mean_1h       numeric(12,4),
  kalshi_median_1h     numeric(12,4),
  kalshi_mean_close    numeric(12,4),
  first_print          numeric(12,4),
  first_print_vintage  date,
  rev2                 numeric(12,4),
  rev2_vintage         date,
  rev3                 numeric(12,4),
  rev3_vintage         date,
  benchmark            numeric(12,4),
  benchmark_vintage    date,
  latest               numeric(12,4),
  latest_vintage       date,
  n_strikes            integer NOT NULL DEFAULT 0,
  nowcast_abs_err      numeric(12,4),
  kalshi_abs_err       numeric(12,4),
  nowcast_brier        numeric(8,6),
  kalshi_brier         numeric(8,6),
  nowcast_crps         numeric(12,4),
  kalshi_crps          numeric(12,4),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  user_id              uuid REFERENCES auth.users(id),
  PRIMARY KEY (series, reference_month)
);

ALTER TABLE jobs_scorecard ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "jobs_scorecard_owner_read" ON jobs_scorecard;
CREATE POLICY "jobs_scorecard_owner_read" ON jobs_scorecard FOR SELECT
  USING (auth.uid() = user_id);

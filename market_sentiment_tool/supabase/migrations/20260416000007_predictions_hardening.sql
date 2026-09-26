-- Rollout step 2b: harden the predictions ledger and track record.
--
-- * settlement_payload / settled_at: settlement no longer overwrites the
--   engine's raw_payload (its inputs), and the settle time is auditable.
-- * A SETTLED row must carry its result.
-- * track_record is keyed per (engine, engine_version): a new model version
--   earns its own record instead of inheriting its predecessor's promotion.
-- * Clients get read-only access. All writes come from the service-role
--   jobs (which bypass RLS); the War Room reads through the API.
--
-- Idempotent, like the earlier migrations.

ALTER TABLE predictions ADD COLUMN IF NOT EXISTS settlement_payload jsonb;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS settled_at timestamptz;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'predictions_settled_has_result') THEN
    ALTER TABLE predictions
      ADD CONSTRAINT predictions_settled_has_result CHECK (status <> 'SETTLED' OR result IS NOT NULL);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS predictions_engine_version_status_idx
  ON predictions (engine, engine_version, status);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.conname = 'track_record_pkey'
    GROUP BY c.conname HAVING count(*) = 1
  ) THEN
    ALTER TABLE track_record DROP CONSTRAINT track_record_pkey;
    ALTER TABLE track_record ADD CONSTRAINT track_record_pkey PRIMARY KEY (engine, engine_version);
  END IF;
END $$;

DROP POLICY IF EXISTS "predictions_owner" ON predictions;
DROP POLICY IF EXISTS "predictions_owner_read" ON predictions;
CREATE POLICY "predictions_owner_read" ON predictions FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "track_record_owner" ON track_record;
DROP POLICY IF EXISTS "track_record_owner_read" ON track_record;
CREATE POLICY "track_record_owner_read" ON track_record FOR SELECT
  USING (auth.uid() = user_id);

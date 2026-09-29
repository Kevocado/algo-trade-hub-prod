-- 20260428000014: the prediction journal (v2 spec §3-§4).
--
-- Four tables:
--   journal_calendars   one row per target: its family, cadence and freeze cutoff. Immutable.
--   journal_forecasts   one frozen forecast per (forecaster, version, target). Immutable, except
--                       that `rebuilt` may flip false -> true (a row found invalid is kept and shown,
--                       never counted).
--   journal_settlements one realised outcome per target. Immutable. Only after the cutoff.
--   journal_scores      the per-(forecaster, version) scorecard. Derived data: recomputed and
--                       upserted by the score job, so it is the one table that is updatable.
--
-- ENFORCEMENT IS BY TRIGGER, NOT RLS. The scan/settle/journal jobs write as the service role, and the
-- service role bypasses RLS, so an RLS insert policy could never refuse a late write. Row triggers
-- fire for every role, including the service role:
--   * BEFORE INSERT on journal_forecasts: `frozen_at := now()` (a client value is ignored),
--     `rebuilt := false`, and the insert is refused when the target has no calendar row or
--     `now() >= cutoff_at`.
--   * BEFORE UPDATE/DELETE on the three ledger tables: refused (except the rebuilt flip above).
--   * BEFORE TRUNCATE (statement trigger): refused. TRUNCATE skips row triggers, so without this a
--     service-role TRUNCATE would empty the audit trail silently.
-- Clients (anon, authenticated) get no write privilege and no RLS policy: the War Room reads
-- through the API (service role).
--
-- Idempotent: CREATE ... IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS.

CREATE TABLE IF NOT EXISTS journal_calendars (
  target           text PRIMARY KEY,
  family           text NOT NULL,
  cadence          text NOT NULL CHECK (cadence IN ('daily', 'monthly', 'meeting')),
  cutoff_at        timestamptz NOT NULL,
  market_linked    boolean NOT NULL DEFAULT false,
  climatology_prob numeric(6,5) CHECK (climatology_prob IS NULL OR (climatology_prob > 0 AND climatology_prob < 1)),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journal_calendars_family_cutoff_idx ON journal_calendars (family, cutoff_at);

CREATE TABLE IF NOT EXISTS journal_forecasts (
  id                 bigserial PRIMARY KEY,
  forecaster         text NOT NULL,
  forecaster_version text NOT NULL,
  target             text NOT NULL REFERENCES journal_calendars (target),
  probability        numeric(6,5) NOT NULL CHECK (probability >= 0 AND probability <= 1),
  market_prob        numeric(6,5) CHECK (market_prob IS NULL OR (market_prob >= 0 AND market_prob <= 1)),
  source_hash        text NOT NULL,
  payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
  rebuilt            boolean NOT NULL DEFAULT false,
  frozen_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (forecaster, forecaster_version, target)
);
CREATE INDEX IF NOT EXISTS journal_forecasts_forecaster_idx ON journal_forecasts (forecaster, forecaster_version);

CREATE TABLE IF NOT EXISTS journal_settlements (
  target         text PRIMARY KEY REFERENCES journal_calendars (target),
  outcome        smallint NOT NULL CHECK (outcome IN (0, 1)),
  realized_value numeric,
  source         text NOT NULL,
  settled_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journal_scores (
  forecaster         text NOT NULL,
  forecaster_version text NOT NULL,
  cadence            text NOT NULL,
  baseline           text NOT NULL,
  n_targets          integer NOT NULL DEFAULT 0,
  n_settled          integer NOT NULL DEFAULT 0,
  brier              numeric(8,6),
  brier_baseline     numeric(8,6),
  bss                numeric(10,6),
  reliability        jsonb NOT NULL DEFAULT '[]'::jsonb,
  murphy             jsonb NOT NULL DEFAULT '{}'::jsonb,
  calibration_ready  boolean NOT NULL DEFAULT false,
  gate_status        text NOT NULL DEFAULT 'SHADOW' CHECK (gate_status IN ('SHADOW', 'PROMOTED')),
  gate_reasons       jsonb NOT NULL DEFAULT '[]'::jsonb,
  computed_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (forecaster, forecaster_version)
);

-- ── guards ──────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION journal_calendar_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.cutoff_at <= now() THEN
      RAISE EXCEPTION 'journal: calendar cutoff % for % is not in the future', NEW.cutoff_at, NEW.target
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.created_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'journal: journal_calendars rows are immutable (%)', TG_OP USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_forecast_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  cutoff timestamptz;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT c.cutoff_at INTO cutoff FROM journal_calendars c WHERE c.target = NEW.target;
    IF cutoff IS NULL THEN
      RAISE EXCEPTION 'journal: no calendar row for target %', NEW.target USING ERRCODE = 'foreign_key_violation';
    END IF;
    NEW.frozen_at := now();
    NEW.rebuilt := false;
    IF NEW.frozen_at >= cutoff THEN
      RAISE EXCEPTION 'journal: freeze for % refused, cutoff % has passed', NEW.target, cutoff
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    IF NEW.rebuilt AND NOT OLD.rebuilt AND (to_jsonb(NEW) - 'rebuilt') = (to_jsonb(OLD) - 'rebuilt') THEN
      RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'journal: journal_forecasts rows are immutable (%; only rebuilt false->true is allowed)', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_settlement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  cutoff timestamptz;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT c.cutoff_at INTO cutoff FROM journal_calendars c WHERE c.target = NEW.target;
    IF cutoff IS NULL OR now() < cutoff THEN
      RAISE EXCEPTION 'journal: settlement for % refused before its cutoff %', NEW.target, cutoff
        USING ERRCODE = 'check_violation';
    END IF;
    NEW.settled_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'journal: journal_settlements rows are immutable (%)', TG_OP USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE OR REPLACE FUNCTION journal_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'journal: TRUNCATE of % is refused (audit trail)', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

DROP TRIGGER IF EXISTS journal_calendars_guard ON journal_calendars;
CREATE TRIGGER journal_calendars_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_calendars
  FOR EACH ROW EXECUTE FUNCTION journal_calendar_guard();
DROP TRIGGER IF EXISTS journal_forecasts_guard ON journal_forecasts;
CREATE TRIGGER journal_forecasts_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_forecasts
  FOR EACH ROW EXECUTE FUNCTION journal_forecast_guard();
DROP TRIGGER IF EXISTS journal_settlements_guard ON journal_settlements;
CREATE TRIGGER journal_settlements_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_settlements
  FOR EACH ROW EXECUTE FUNCTION journal_settlement_guard();

DROP TRIGGER IF EXISTS journal_calendars_no_truncate ON journal_calendars;
CREATE TRIGGER journal_calendars_no_truncate BEFORE TRUNCATE ON journal_calendars
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();
DROP TRIGGER IF EXISTS journal_forecasts_no_truncate ON journal_forecasts;
CREATE TRIGGER journal_forecasts_no_truncate BEFORE TRUNCATE ON journal_forecasts
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();
DROP TRIGGER IF EXISTS journal_settlements_no_truncate ON journal_settlements;
CREATE TRIGGER journal_settlements_no_truncate BEFORE TRUNCATE ON journal_settlements
  FOR EACH STATEMENT EXECUTE FUNCTION journal_no_truncate();

-- ── client access: none ─────────────────────────────────────────────────────
ALTER TABLE journal_calendars   ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_forecasts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_settlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_scores      ENABLE ROW LEVEL SECURITY;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON journal_calendars, journal_forecasts, journal_settlements, journal_scores
  FROM anon, authenticated;

-- 20260428000013: finish what 20260415090000 could not, because it died at line 51.
--
-- WHAT HAPPENED. `20260415090000_signal_events_unification.sql` was applied to production on
-- 2026-09-28 through the Supabase SQL editor and failed:
--
--     ERROR:  42P01: relation "crypto_signal_events" does not exist
--     CONTEXT:  SQL statement "ALTER PUBLICATION supabase_realtime DROP TABLE crypto_signal_events"
--
-- The `EXCEPTION` guard on that statement caught `undefined_object` (42704, undefined
-- function/operator) and `invalid_parameter_value` (22023). 42P01 is `undefined_table`, a
-- different condition, so the guard did not match and the error escaped it. The condition has
-- been fixed in the original file; this migration is what actually completes the work.
--
-- WHY A FOLLOW-UP AND NOT A RE-RUN. The SQL editor sends statements one at a time and each one
-- commits on its own, so the file was applied up to the failure and no further. Everything before
-- line 48 is in the database; the DO block at 48-56 raised; nothing from line 58 onward ever ran.
-- The rename at line 1 committed, which is exactly why the error names the old relation: the
-- publication stores relation OIDs, so renaming the table moved its publication membership to the
-- new name, and by the time the DROP ran there was no `crypto_signal_events` left to remove.
--
-- ASSUMED ALREADY APPLIED -- read this before running it. Exactly one thing:
--
--     public.signal_events exists as a TABLE.
--
-- That is provable from the failure rather than assumed. Either line 1 renamed `crypto_signal_events`
-- into that name, or line 3 created it, and both are above the point the script died. The check
-- below fails loudly and says so if the assumption is wrong for some other reason. Nothing else is
-- assumed: every statement here is independently re-runnable, so it does not matter whether a
-- previous attempt of THIS file partially applied, and it does not matter which of the two
-- statements above produced the table.
--
-- IDEMPOTENT, and safe from either starting state. Publication membership is decided by looking at
-- `pg_publication_tables` before touching the publication, rather than by catching the error after
-- the fact, so there is no error code to get wrong here. The rest is `IF [NOT] EXISTS` and
-- `CREATE OR REPLACE`. Running this file twice is a no-op the second time, and running it on a
-- database where the rename never happened is also correct: the old name is still a member and
-- still gets dropped.
--
-- NOT a reset. This file does not drop, truncate or recreate `signal_events`. That table holds the
-- production signal ledger -- the crypto worker, the non-crypto domains and the shadow scorer all
-- write to it through the service role -- and the whole point of the original migration was to
-- preserve it across the rename.

-- ── Precondition ──────────────────────────────────────────────────────────────────────────────
-- Deliberately a hard failure. If this table is absent, the rename never happened and applying
-- this file would create policies and a view against nothing, which is worse than stopping.
DO $$
BEGIN
    IF to_regclass('signal_events') IS NULL THEN
        RAISE EXCEPTION
            'public.signal_events does not exist. This migration continues 20260415090000 from the '
            'line it failed on and assumes lines 1-46 of that file are already applied. Apply '
            '20260415090000_signal_events_unification.sql first, then re-run this one.';
    END IF;
END $$;

-- ── Realtime publication ──────────────────────────────────────────────────────────────────────
-- The membership the rename already moved: publications store relation OIDs, so `signal_events`
-- is normally already a member by the time this runs and the first block does nothing. The drop is
-- kept because the case it covers is real -- a database where the rename did not happen has
-- `crypto_signal_events` in the publication and `signal_events` alongside it -- and skipping it
-- would leave that database with two live realtime tables for one ledger.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = current_schema()
          AND tablename = 'crypto_signal_events'
    ) THEN
        BEGIN
            ALTER PUBLICATION supabase_realtime DROP TABLE crypto_signal_events;
        EXCEPTION
            -- 42P01: the relation is not there (renamed, or this file has already been run).
            WHEN undefined_table THEN NULL;
            -- 42704: the relation exists but is not a member of the publication. PostgreSQL
            -- reports this as undefined_object, not as object_not_in_prerequisite_state.
            WHEN undefined_object THEN NULL;
            WHEN invalid_parameter_value THEN NULL;
        END;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = current_schema()
          AND tablename = 'signal_events'
    ) THEN
        BEGIN
            ALTER PUBLICATION supabase_realtime ADD TABLE signal_events;
        EXCEPTION
            -- 42710: already a member, which is what the IF above was checking for and what a
            -- concurrent writer could beat us to between the two statements.
            WHEN duplicate_object THEN NULL;
            -- 42704: the PUBLICATION is missing, not the table. This name is correct here and
            -- must not be "corrected" to undefined_table.
            WHEN undefined_object THEN NULL;
        END;
    END IF;
END $$;

-- ── Row level security ────────────────────────────────────────────────────────────────────────
ALTER TABLE signal_events ENABLE ROW LEVEL SECURITY;

-- The two policies 20260408224000 created on this table under its old name. A rename carries
-- policies with it (they are attached to the table, not named after it), and the DROP/CREATE pairs
-- below only match the new names, so on this database all four would otherwise sit on one table:
-- two correct, two describing a table that no longer exists. Not a hole -- both old policies grant
-- exactly what the new ones grant -- but a table whose security posture is written twice and can
-- only be read one way.
DROP POLICY IF EXISTS "Users can view their own crypto signal events" ON signal_events;
DROP POLICY IF EXISTS "Anon can view crypto signal events" ON signal_events;

DROP POLICY IF EXISTS "Users can view their own signal events" ON signal_events;
CREATE POLICY "Users can view their own signal events"
ON signal_events FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);

DROP POLICY IF EXISTS "Anon can view signal events" ON signal_events;
CREATE POLICY "Anon can view signal events"
ON signal_events FOR SELECT TO anon USING (true);

-- ── The compatibility view and its triggers ───────────────────────────────────────────────────
-- Nothing in this repository reads or writes `crypto_signal_events`: every writer uses
-- `signal_events` (market_sentiment_tool/backend/signal_events.py), and the only other mention is
-- the table->migration map in tradehub/api/main.py that names a file in an error message. This view
-- is kept because the rename is the kind of change that has readers outside the repo, not because
-- anything here needs it. `CREATE OR REPLACE` so a re-run cannot fail on an existing view.
CREATE OR REPLACE VIEW crypto_signal_events
WITH (security_invoker = true)
AS
SELECT
    id,
    created_at,
    user_id,
    asset,
    source_market_ticker,
    resolved_ticker,
    desired_side,
    status,
    skip_reason,
    execution_status,
    alert_kind,
    alert_sent,
    dedupe_key,
    model_probability_yes,
    signal_price_dollars,
    spot_price_dollars,
    kalshi_price_dollars,
    edge,
    strike_price,
    event_ticker,
    event_close_time,
    payload
FROM signal_events
WHERE domain = 'crypto';

CREATE OR REPLACE FUNCTION public.crypto_signal_events_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.signal_events (
        id,
        domain,
        created_at,
        user_id,
        asset,
        source_market_ticker,
        resolved_ticker,
        desired_side,
        status,
        skip_reason,
        execution_status,
        alert_kind,
        alert_sent,
        dedupe_key,
        model_probability_yes,
        signal_price_dollars,
        spot_price_dollars,
        kalshi_price_dollars,
        edge,
        strike_price,
        event_ticker,
        event_close_time,
        payload
    )
    VALUES (
        COALESCE(NEW.id, uuid_generate_v4()),
        'crypto',
        COALESCE(NEW.created_at, NOW()),
        NEW.user_id,
        NEW.asset,
        NEW.source_market_ticker,
        NEW.resolved_ticker,
        NEW.desired_side,
        NEW.status,
        NEW.skip_reason,
        NEW.execution_status,
        NEW.alert_kind,
        COALESCE(NEW.alert_sent, FALSE),
        NEW.dedupe_key,
        NEW.model_probability_yes,
        NEW.signal_price_dollars,
        NEW.spot_price_dollars,
        NEW.kalshi_price_dollars,
        NEW.edge,
        NEW.strike_price,
        NEW.event_ticker,
        NEW.event_close_time,
        COALESCE(NEW.payload, '{}'::jsonb)
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.crypto_signal_events_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE public.signal_events
    SET
        created_at = NEW.created_at,
        user_id = NEW.user_id,
        asset = NEW.asset,
        source_market_ticker = NEW.source_market_ticker,
        resolved_ticker = NEW.resolved_ticker,
        desired_side = NEW.desired_side,
        status = NEW.status,
        skip_reason = NEW.skip_reason,
        execution_status = NEW.execution_status,
        alert_kind = NEW.alert_kind,
        alert_sent = NEW.alert_sent,
        dedupe_key = NEW.dedupe_key,
        model_probability_yes = NEW.model_probability_yes,
        signal_price_dollars = NEW.signal_price_dollars,
        spot_price_dollars = NEW.spot_price_dollars,
        kalshi_price_dollars = NEW.kalshi_price_dollars,
        edge = NEW.edge,
        strike_price = NEW.strike_price,
        event_ticker = NEW.event_ticker,
        event_close_time = NEW.event_close_time,
        payload = COALESCE(NEW.payload, '{}'::jsonb)
    WHERE id = OLD.id
      AND domain = 'crypto';
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.crypto_signal_events_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.signal_events
    WHERE id = OLD.id
      AND domain = 'crypto';
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS crypto_signal_events_insert_trigger ON crypto_signal_events;
CREATE TRIGGER crypto_signal_events_insert_trigger
INSTEAD OF INSERT ON crypto_signal_events
FOR EACH ROW
EXECUTE FUNCTION public.crypto_signal_events_insert();

DROP TRIGGER IF EXISTS crypto_signal_events_update_trigger ON crypto_signal_events;
CREATE TRIGGER crypto_signal_events_update_trigger
INSTEAD OF UPDATE ON crypto_signal_events
FOR EACH ROW
EXECUTE FUNCTION public.crypto_signal_events_update();

DROP TRIGGER IF EXISTS crypto_signal_events_delete_trigger ON crypto_signal_events;
CREATE TRIGGER crypto_signal_events_delete_trigger
INSTEAD OF DELETE ON crypto_signal_events
FOR EACH ROW
EXECUTE FUNCTION public.crypto_signal_events_delete();

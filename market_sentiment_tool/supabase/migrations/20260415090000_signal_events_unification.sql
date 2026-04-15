ALTER TABLE IF EXISTS crypto_signal_events RENAME TO signal_events;

CREATE TABLE IF NOT EXISTS signal_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID REFERENCES auth.users(id),
    asset TEXT NOT NULL,
    source_market_ticker TEXT,
    resolved_ticker TEXT,
    desired_side TEXT,
    status TEXT NOT NULL,
    skip_reason TEXT,
    execution_status TEXT,
    alert_kind TEXT,
    alert_sent BOOLEAN DEFAULT FALSE,
    dedupe_key TEXT,
    model_probability_yes NUMERIC,
    signal_price_dollars NUMERIC,
    spot_price_dollars NUMERIC,
    kalshi_price_dollars NUMERIC,
    edge NUMERIC,
    strike_price NUMERIC,
    event_ticker TEXT,
    event_close_time TIMESTAMPTZ,
    payload JSONB DEFAULT '{}'::jsonb
);

ALTER TABLE signal_events
ADD COLUMN IF NOT EXISTS domain TEXT;

UPDATE signal_events
SET domain = 'crypto'
WHERE domain IS NULL;

ALTER TABLE signal_events
ALTER COLUMN domain SET DEFAULT 'crypto';

ALTER TABLE signal_events
ALTER COLUMN domain SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signal_events_created_at
ON signal_events(domain, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_dedupe
ON signal_events(domain, dedupe_key, alert_kind, created_at DESC);

DO $$
BEGIN
    BEGIN
        ALTER PUBLICATION supabase_realtime DROP TABLE crypto_signal_events;
    EXCEPTION
        WHEN undefined_object THEN NULL;
        WHEN invalid_parameter_value THEN NULL;
    END;
END $$;

DO $$
BEGIN
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE signal_events;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
        WHEN undefined_object THEN NULL;
    END;
END $$;

ALTER TABLE signal_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own signal events" ON signal_events;
CREATE POLICY "Users can view their own signal events"
ON signal_events FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);

DROP POLICY IF EXISTS "Anon can view signal events" ON signal_events;
CREATE POLICY "Anon can view signal events"
ON signal_events FOR SELECT TO anon USING (true);

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

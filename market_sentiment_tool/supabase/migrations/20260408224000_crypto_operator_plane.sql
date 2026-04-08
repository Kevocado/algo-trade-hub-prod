ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS crypto_auto_trade_enabled BOOLEAN;

UPDATE user_settings
SET crypto_auto_trade_enabled = COALESCE(crypto_auto_trade_enabled, auto_trade_enabled)
WHERE crypto_auto_trade_enabled IS NULL;

ALTER TABLE user_settings
ALTER COLUMN crypto_auto_trade_enabled SET DEFAULT TRUE;

ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS crypto_trading_disabled_reason TEXT;

ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS crypto_trading_disabled_at TIMESTAMPTZ;

ALTER TABLE trades
ALTER COLUMN symbol TYPE TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS engine TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS market_ticker TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS contract_side TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS external_order_id TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS error_code TEXT;

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS crypto_signal_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

CREATE INDEX IF NOT EXISTS idx_crypto_signal_events_created_at
ON crypto_signal_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crypto_signal_events_dedupe
ON crypto_signal_events(dedupe_key, alert_kind, created_at DESC);

ALTER PUBLICATION supabase_realtime ADD TABLE crypto_signal_events;

ALTER TABLE crypto_signal_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own crypto signal events" ON crypto_signal_events;
CREATE POLICY "Users can view their own crypto signal events"
ON crypto_signal_events FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);

DROP POLICY IF EXISTS "Anon can view crypto signal events" ON crypto_signal_events;
CREATE POLICY "Anon can view crypto signal events"
ON crypto_signal_events FOR SELECT TO anon USING (true);

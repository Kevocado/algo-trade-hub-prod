-- Table: trades
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(4) CHECK (side IN ('BUY', 'SELL')),
    qty NUMERIC NOT NULL,
    execution_price NUMERIC,
    status VARCHAR(20) DEFAULT 'PENDING',
    pnl NUMERIC DEFAULT 0.0,
    agent_confidence NUMERIC CHECK (agent_confidence >= 0 AND agent_confidence <= 1)
);

-- Table: agent_logs
CREATE TABLE agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    module VARCHAR(50) NOT NULL,
    log_level VARCHAR(10) DEFAULT 'INFO',
    message TEXT NOT NULL,
    reasoning_context JSONB
);

-- Table: portfolio_state
CREATE TABLE portfolio_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    total_equity NUMERIC NOT NULL,
    available_cash NUMERIC NOT NULL,
    open_positions JSONB NOT NULL
);

-- Table: user_settings
CREATE TABLE user_settings (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id),
    auto_trade_enabled BOOLEAN DEFAULT FALSE,
    max_daily_drawdown NUMERIC DEFAULT 0.05,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

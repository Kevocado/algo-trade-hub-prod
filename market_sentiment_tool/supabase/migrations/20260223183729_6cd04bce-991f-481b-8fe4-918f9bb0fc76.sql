
-- 1. Add user_id columns to tables missing them
ALTER TABLE portfolio_state ADD COLUMN user_id UUID REFERENCES auth.users(id);
ALTER TABLE trades ADD COLUMN user_id UUID REFERENCES auth.users(id);
ALTER TABLE agent_logs ADD COLUMN user_id UUID REFERENCES auth.users(id);

-- 2. Enable RLS on all tables
ALTER TABLE portfolio_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- 3. Drop overly permissive public read policies
DROP POLICY IF EXISTS "Allow public read access" ON portfolio_state;
DROP POLICY IF EXISTS "Allow public read access" ON trades;
DROP POLICY IF EXISTS "Allow public read access" ON agent_logs;

-- 4. Create proper user-scoped policies for portfolio_state
CREATE POLICY "Users read own portfolio"
  ON portfolio_state FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users insert own portfolio"
  ON portfolio_state FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- 5. Create proper user-scoped policies for trades
CREATE POLICY "Users read own trades"
  ON trades FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users insert own trades"
  ON trades FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- 6. Create proper user-scoped policies for agent_logs
CREATE POLICY "Users read own logs"
  ON agent_logs FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users insert own logs"
  ON agent_logs FOR INSERT
  WITH CHECK (auth.uid() = user_id);

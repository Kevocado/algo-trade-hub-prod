-- Migration: Enable Realtime and wipe orphaned backend data
-- Fixes the missing frontend data issue caused by RLS drops and inactive WebSockets

-- 1. Enable Realtime Publication
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        CREATE PUBLICATION supabase_realtime;
    END IF;
END $$;

ALTER PUBLICATION supabase_realtime ADD TABLE agent_logs;
ALTER PUBLICATION supabase_realtime ADD TABLE portfolio_state;
ALTER PUBLICATION supabase_realtime ADD TABLE trades;

-- 2. Wipe old backend data that was inserted without a user_id
DELETE FROM agent_logs WHERE user_id IS NULL;
DELETE FROM portfolio_state WHERE user_id IS NULL;
DELETE FROM trades WHERE user_id IS NULL;

-- 3. Enforce RLS
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- 4. Re-create Select Policies
DROP POLICY IF EXISTS "Users can view their own agent logs" ON agent_logs;
CREATE POLICY "Users can view their own agent logs" 
ON agent_logs FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);
DROP POLICY IF EXISTS "Anon can view agent logs" ON agent_logs;
CREATE POLICY "Anon can view agent logs" ON agent_logs FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "Users can view their own portfolio state" ON portfolio_state;
CREATE POLICY "Users can view their own portfolio state" 
ON portfolio_state FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);
DROP POLICY IF EXISTS "Anon can view portfolio state" ON portfolio_state;
CREATE POLICY "Anon can view portfolio state" ON portfolio_state FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "Users can view their own trades" ON trades;
CREATE POLICY "Users can view their own trades" 
ON trades FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);
DROP POLICY IF EXISTS "Anon can view trades" ON trades;
CREATE POLICY "Anon can view trades" ON trades FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "Users can view their own settings" ON user_settings;
CREATE POLICY "Users can view their own settings" 
ON user_settings FOR SELECT TO authenticated USING (auth.uid() = user_id::uuid);
DROP POLICY IF EXISTS "Anon can view settings" ON user_settings;
CREATE POLICY "Anon can view settings" ON user_settings FOR SELECT TO anon USING (true);

-- 5. User Settings Update Policy (Required for Kill Switch UI)
DROP POLICY IF EXISTS "Users can update their own settings" ON user_settings;
CREATE POLICY "Users can update their own settings" 
ON user_settings FOR UPDATE TO authenticated USING (auth.uid() = user_id::uuid);

DROP POLICY IF EXISTS "Anon can update settings" ON user_settings;
CREATE POLICY "Anon can update settings" ON user_settings FOR UPDATE TO anon USING (true);

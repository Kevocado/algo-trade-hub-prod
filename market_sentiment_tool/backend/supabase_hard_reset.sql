-- ==========================================
-- SUPABASE HARD-RESET & REALTIME FIX
-- ==========================================
-- Copy and paste this entire script into your Supabase SQL Editor and click "Run".
-- This will:
-- 1. Enable Realtime for your live dashboard components.
-- 2. Wipe old trial data that is missing a user_id (causing UI ghosting).
-- 3. Enforce Row Level Security (RLS) policies so you can see your data.

-- ------------------------------------------
-- 1. ENABLE REALTIME
-- ------------------------------------------
-- First, ensure the supabase_realtime publication exists.
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        CREATE PUBLICATION supabase_realtime;
    END IF;
END $$;

-- Add our core tables to the realtime publication so the React frontend can "listen" to them.
ALTER PUBLICATION supabase_realtime ADD TABLE agent_logs;
ALTER PUBLICATION supabase_realtime ADD TABLE portfolio_state;
ALTER PUBLICATION supabase_realtime ADD TABLE trades;

-- ------------------------------------------
-- 2. CLEANUP OLD / ORPHANED DATA
-- ------------------------------------------
-- Delete any rows that were inserted during trial runs before we hooked up the user_id.
-- These rows are invisible to the frontend anyway due to RLS.
DELETE FROM agent_logs WHERE user_id IS NULL;
DELETE FROM portfolio_state WHERE user_id IS NULL;
DELETE FROM trades WHERE user_id IS NULL;

-- ------------------------------------------
-- 3. ENFORCE ROW LEVEL SECURITY (RLS)
-- ------------------------------------------
-- Ensure RLS is enabled on all tables.
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- Create policies so the logged-in user can read their own data.
-- (Using DROP POLICY IF EXISTS to avoid errors if you run this multiple times)

-- agent_logs
DROP POLICY IF EXISTS "Users can view their own agent logs" ON agent_logs;
CREATE POLICY "Users can view their own agent logs" 
ON agent_logs FOR SELECT 
TO authenticated 
USING (auth.uid() = user_id::uuid);

-- portfolio_state
DROP POLICY IF EXISTS "Users can view their own portfolio state" ON portfolio_state;
CREATE POLICY "Users can view their own portfolio state" 
ON portfolio_state FOR SELECT 
TO authenticated 
USING (auth.uid() = user_id::uuid);

-- trades
DROP POLICY IF EXISTS "Users can view their own trades" ON trades;
CREATE POLICY "Users can view their own trades" 
ON trades FOR SELECT 
TO authenticated 
USING (auth.uid() = user_id::uuid);

-- user_settings
DROP POLICY IF EXISTS "Users can view their own settings" ON user_settings;
CREATE POLICY "Users can view their own settings" 
ON user_settings FOR SELECT 
TO authenticated 
USING (auth.uid() = user_id::uuid);

DROP POLICY IF EXISTS "Users can update their own settings" ON user_settings;
CREATE POLICY "Users can update their own settings" 
ON user_settings FOR UPDATE 
TO authenticated 
USING (auth.uid() = user_id::uuid);

-- Done! Your database is now secure, cleansed, and streaming live.

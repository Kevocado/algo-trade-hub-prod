-- 20260428000015: net-of-costs summary on the journal scorecard (v2 spec §10, §12).
--
-- journal_scores.costs holds, for market-linked forecasters, {n_quoted, n_traded, gross_pnl_cents,
-- fees_cents, net_pnl_cents}: the simulated one-contract taker P&L of every settled forecast after
-- Kalshi's fee and the half-spread. Empty ({}) for forecasters graded against climatology.
-- Apply BEFORE deploying the code that upserts the column. Idempotent.

ALTER TABLE journal_scores ADD COLUMN IF NOT EXISTS costs jsonb NOT NULL DEFAULT '{}'::jsonb;
NOTIFY pgrst, 'reload schema';

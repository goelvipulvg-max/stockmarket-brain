-- Batch D Session 2 -- money-seam schema changes (audit Exec #2, reco #3).
-- OWNER RUNS MANUALLY in Supabase Dashboard > SQL Editor. The agent never
-- touches the DB. Run BEFORE resuming the system, together with the v2
-- release_capital_atomic in sql/p0-1_atomic_capital_rpc.sql.

-- ============================================================
-- 1) Seam (a): allow the 'VOID' terminal status (deploy-failed trades).
--    Verified 2026-07-05 by owner: live CHECK allows only
--    OPEN / TARGET_HIT / SL_HIT / EXPIRED -- VOID must be added.
--
--    !! IMPORTANT: constraint ka naam pehle confirm karo (query niche).
--    Agar naam 'paper_trades_status_check' se different hai to DONO jagah
--    wahi naam use karo -- warna DROP IF EXISTS silently no-op hoga aur
--    ADD ek DUPLICATE constraint bana dega (purana VOID ko phir bhi
--    block karega).
--
--    SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid = 'paper_trades'::regclass AND contype = 'c';
-- ============================================================
BEGIN;
ALTER TABLE paper_trades DROP CONSTRAINT IF EXISTS paper_trades_status_check;
ALTER TABLE paper_trades ADD CONSTRAINT paper_trades_status_check
    CHECK (status IN ('OPEN', 'TARGET_HIT', 'SL_HIT', 'EXPIRED', 'VOID'));
COMMIT;

-- ============================================================
-- 2) Seam (c): retry marker for failed capital releases.
--    Updater sets it true when release_capital fails after a close;
--    _retry_failed_releases() clears it on a successful (or already-done)
--    release. Code degrades gracefully while this column is absent.
-- ============================================================
ALTER TABLE paper_trades
  ADD COLUMN IF NOT EXISTS capital_release_failed BOOLEAN NOT NULL DEFAULT false;

-- ============================================================
-- 3) Post-apply verification (run all three; expected results in comments)
-- ============================================================
-- 3a) Constraint now includes VOID:
-- SELECT pg_get_constraintdef(oid) FROM pg_constraint
-- WHERE conname = 'paper_trades_status_check';
--   => CHECK (status IN ('OPEN','TARGET_HIT','SL_HIT','EXPIRED','VOID'))

-- 3b) Column exists with default false:
-- SELECT column_name, data_type, column_default FROM information_schema.columns
-- WHERE table_name = 'paper_trades' AND column_name = 'capital_release_failed';

-- 3c) Phantom check -- 0 rows expected; koi bhi row = OPEN trade jiska
--     DEPLOY ledger row nahi hai (deploy kabhi landa hi nahi):
-- SELECT pt.id, pt.ticker, pt.status, pt.position_size_rs
-- FROM paper_trades pt
-- WHERE pt.status = 'OPEN' AND pt.quantity IS NOT NULL
--   AND NOT EXISTS (SELECT 1 FROM capital_ledger cl
--                   WHERE cl.paper_trade_id = pt.id AND cl.txn_type = 'DEPLOY');

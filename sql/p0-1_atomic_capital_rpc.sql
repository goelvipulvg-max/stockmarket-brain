-- P0-1: Atomic capital ledger operations (applied 2026-07-04 by owner via
-- Supabase Dashboard > SQL Editor).
--
-- Both functions lock the live (latest-by-id) portfolio row FOR UPDATE, so
-- concurrent deploy/release calls serialize inside Postgres -- no lost
-- updates from the old Python read-modify-write. All arithmetic is NUMERIC
-- with ROUND(x, 2) => no float drift (also fixes P3-11-iii).
--
-- Callers: utils/capital_ledger.py deploy_capital() / release_capital()
-- via supabase.rpc(). Return contract: JSONB {success, error?, cash_after,
-- deployed_after, realized_after?, equity_after}.

CREATE OR REPLACE FUNCTION deploy_capital_atomic(
    p_paper_trade_id BIGINT,
    p_amount_rs NUMERIC
) RETURNS JSONB
LANGUAGE plpgsql AS $$
DECLARE
    v_pf portfolio%ROWTYPE;
    v_new_cash NUMERIC;
    v_new_deployed NUMERIC;
BEGIN
    SELECT * INTO v_pf FROM portfolio ORDER BY id DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false,
            'error', 'Portfolio not initialized (no rows)');
    END IF;

    IF p_amount_rs > v_pf.cash_available THEN
        RETURN jsonb_build_object('success', false,
            'error', format('Insufficient cash: need Rs.%s, have Rs.%s',
                            to_char(p_amount_rs, 'FM999,999,999,990.00'),
                            to_char(v_pf.cash_available, 'FM999,999,999,990.00')));
    END IF;

    v_new_cash     := ROUND(v_pf.cash_available - p_amount_rs, 2);
    v_new_deployed := ROUND(v_pf.capital_deployed + p_amount_rs, 2);

    INSERT INTO capital_ledger (paper_trade_id, txn_type, amount_rs, cash_after, note)
    VALUES (p_paper_trade_id, 'DEPLOY', -p_amount_rs, v_new_cash,
            'Opened trade ' || COALESCE(p_paper_trade_id::text, 'None'));

    UPDATE portfolio SET
        cash_available   = v_new_cash,
        capital_deployed = v_new_deployed,
        total_equity     = ROUND(v_new_cash + v_new_deployed, 2),  -- D4: no MTM
        open_positions   = v_pf.open_positions + 1,
        updated_at       = NOW()
    WHERE id = v_pf.id;

    RETURN jsonb_build_object('success', true,
        'cash_after', v_new_cash,
        'deployed_after', v_new_deployed,
        'equity_after', ROUND(v_new_cash + v_new_deployed, 2));
END;
$$;

CREATE OR REPLACE FUNCTION release_capital_atomic(
    p_paper_trade_id BIGINT,
    p_position_size_rs NUMERIC,
    p_pnl_rs NUMERIC
) RETURNS JSONB
LANGUAGE plpgsql AS $$
DECLARE
    v_pf portfolio%ROWTYPE;
    v_returned NUMERIC;
    v_new_cash NUMERIC;
    v_new_deployed NUMERIC;
    v_new_realized NUMERIC;
BEGIN
    SELECT * INTO v_pf FROM portfolio ORDER BY id DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false,
            'error', 'Portfolio not initialized (no rows)');
    END IF;

    v_returned     := ROUND(p_position_size_rs + p_pnl_rs, 2);
    v_new_cash     := ROUND(v_pf.cash_available + v_returned, 2);
    v_new_deployed := ROUND(v_pf.capital_deployed - p_position_size_rs, 2);
    v_new_realized := ROUND(COALESCE(v_pf.realized_pnl_rs, 0) + p_pnl_rs, 2);

    INSERT INTO capital_ledger (paper_trade_id, txn_type, amount_rs, cash_after, note)
    VALUES (p_paper_trade_id, 'PNL_REALIZED', v_returned, v_new_cash,
            'Closed trade ' || COALESCE(p_paper_trade_id::text, 'None')
            || ', P&L Rs.' || to_char(p_pnl_rs, 'FM999,999,999,990.00'));

    UPDATE portfolio SET
        cash_available   = v_new_cash,
        capital_deployed = v_new_deployed,
        total_equity     = ROUND(v_new_cash + v_new_deployed, 2),  -- D4: no MTM
        realized_pnl_rs  = v_new_realized,
        open_positions   = v_pf.open_positions - 1,
        updated_at       = NOW()
    WHERE id = v_pf.id;

    RETURN jsonb_build_object('success', true,
        'cash_after', v_new_cash,
        'deployed_after', v_new_deployed,
        'realized_after', v_new_realized,
        'equity_after', ROUND(v_new_cash + v_new_deployed, 2));
END;
$$;

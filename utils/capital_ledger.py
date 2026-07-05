"""
Virtual Capital Ledger — Phase 2, v3.1 Master Plan §5.3.
Tracks simulated Rs.10,00,000 portfolio in Supabase.
"""
from utils.supabase_client import get_client

sb = get_client()


def get_current_portfolio():
    """Return the latest portfolio row dict, initializing on first ever call."""
    rows = sb.table("portfolio").select("*").order("id", desc=True).limit(1).execute().data
    if not rows:
        return _initialize_portfolio()
    return rows[0]


def _initialize_portfolio():
    """Create the seed portfolio row — Rs.10,00,000 starting capital."""
    initial = {
        "starting_capital": 1_000_000,
        "cash_available": 1_000_000,
        "capital_deployed": 0,
        "total_equity": 1_000_000,
        "open_positions": 0,
    }
    result = sb.table("portfolio").insert(initial).execute()
    return result.data[0] if result.data else initial


def deploy_capital(paper_trade_id, amount_rs):
    """Deduct cash, write a DEPLOY ledger row. Called when a trade opens.

    P0-1: single atomic RPC — ledger insert + portfolio update happen in one
    row-locked Postgres transaction, so a concurrent release_capital can no
    longer produce a lost update. Raises ValueError on insufficient cash
    (same contract as the old Python-side guard).
    """
    result = sb.rpc("deploy_capital_atomic", {
        "p_paper_trade_id": paper_trade_id,
        "p_amount_rs": round(float(amount_rs), 2),
    }).execute()
    data = result.data
    if not data or not data.get("success"):
        raise ValueError((data or {}).get("error") or "deploy_capital_atomic failed")
    return data


def release_capital(paper_trade_id, position_size_rs, pnl_rs):
    """Return deployed capital + realised P&L to cash. Called on trade close.

    P0-1: single atomic RPC (see deploy_capital). v2 RPC (Batch D-2 seam-b)
    returns error_code on guard failures -- ALREADY_RELEASED / DEPLOY_MISSING /
    INSUFFICIENT_DEPLOYED / NO_PORTFOLIO. The code is prefixed as "[CODE] msg"
    in the raised RuntimeError so callers (updater retry) can string-match it;
    a v1 RPC without error_code degrades to the bare message.
    """
    result = sb.rpc("release_capital_atomic", {
        "p_paper_trade_id": paper_trade_id,
        "p_position_size_rs": round(float(position_size_rs), 2),
        "p_pnl_rs": round(float(pnl_rs), 2),
    }).execute()
    data = result.data
    if not data or not data.get("success"):
        code = (data or {}).get("error_code")
        msg = (data or {}).get("error") or "release_capital_atomic failed"
        raise RuntimeError(f"[{code}] {msg}" if code else msg)
    return data

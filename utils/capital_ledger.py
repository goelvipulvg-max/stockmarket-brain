"""
Virtual Capital Ledger — Phase 2, v3.1 Master Plan §5.3.
Tracks simulated Rs.10,00,000 portfolio in Supabase.
"""
from datetime import datetime
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


def _update_portfolio(**kwargs):
    """UPDATE the single current portfolio row (latest by id).

    Keyword arguments:
        cash         — sets cash_available
        deployed     — sets capital_deployed
        open_count   — sets open_positions
        realized_add — INCREMENTS realized_pnl_rs (not sets)

    total_equity = cash_available + capital_deployed (at cost, no MTM — D4).
    """
    pf = get_current_portfolio()

    new_cash = kwargs.get("cash", pf["cash_available"])
    new_deployed = kwargs.get("deployed", pf["capital_deployed"])
    new_open = kwargs.get("open_count", pf["open_positions"])
    realized_add = kwargs.get("realized_add", 0)

    new_realized = float(pf.get("realized_pnl_rs") or 0) + realized_add
    new_equity = float(new_cash) + float(new_deployed)  # D4: no MTM

    sb.table("portfolio").update({
        "cash_available": new_cash,
        "capital_deployed": new_deployed,
        "total_equity": new_equity,
        "realized_pnl_rs": new_realized,
        "open_positions": new_open,
        "updated_at": datetime.now().isoformat(),
    }).eq("id", pf["id"]).execute()


def deploy_capital(paper_trade_id, amount_rs):
    """Deduct cash, write a DEPLOY ledger row. Called when a trade opens."""
    pf = get_current_portfolio()
    if amount_rs > float(pf["cash_available"]):
        raise ValueError(
            f"Insufficient cash: need Rs.{amount_rs:,.2f}, "
            f"have Rs.{float(pf['cash_available']):,.2f}"
        )

    new_cash = float(pf["cash_available"]) - amount_rs

    sb.table("capital_ledger").insert({
        "paper_trade_id": paper_trade_id,
        "txn_type": "DEPLOY",
        "amount_rs": -amount_rs,
        "cash_after": new_cash,
        "note": f"Opened trade {paper_trade_id}",
    }).execute()

    _update_portfolio(
        cash=new_cash,
        deployed=float(pf["capital_deployed"]) + amount_rs,
        open_count=pf["open_positions"] + 1,
    )


def release_capital(paper_trade_id, position_size_rs, pnl_rs):
    """Return deployed capital + realised P&L to cash. Called on trade close."""
    pf = get_current_portfolio()
    returned = position_size_rs + pnl_rs
    new_cash = float(pf["cash_available"]) + returned

    sb.table("capital_ledger").insert({
        "paper_trade_id": paper_trade_id,
        "txn_type": "PNL_REALIZED",
        "amount_rs": returned,
        "cash_after": new_cash,
        "note": f"Closed trade {paper_trade_id}, P&L Rs.{pnl_rs:,.2f}",
    }).execute()

    _update_portfolio(
        cash=new_cash,
        deployed=float(pf["capital_deployed"]) - position_size_rs,
        open_count=pf["open_positions"] - 1,
        realized_add=pnl_rs,
    )

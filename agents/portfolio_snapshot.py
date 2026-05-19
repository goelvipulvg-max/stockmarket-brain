"""
Daily Portfolio Snapshot — Phase 2, v3.1 Master Plan §5.4 (last bullet).
INSERTs a fresh portfolio row each call — builds the equity-curve history.
Distinct from _update_portfolio() which UPDATEs the single current row (D2).

Trigger: manual / cron-job.org (D5 — cron NOT wired in Phase 2).
"""
from datetime import datetime
from utils.supabase_client import get_client
from utils.capital_ledger import get_current_portfolio

sb = get_client()


def snapshot_portfolio():
    """INSERT a new portfolio row capturing the current state."""
    pf = get_current_portfolio()

    snapshot = {
        "snapshot_date": datetime.now().date().isoformat(),
        "starting_capital": pf["starting_capital"],
        "cash_available": pf["cash_available"],
        "capital_deployed": pf["capital_deployed"],
        "total_equity": pf["total_equity"],
        "realized_pnl_rs": pf.get("realized_pnl_rs", 0),
        "unrealized_pnl_rs": pf.get("unrealized_pnl_rs", 0),
        "open_positions": pf["open_positions"],
    }

    result = sb.table("portfolio").insert(snapshot).execute()
    row = result.data[0] if result.data else snapshot
    print(f"Portfolio snapshot: id={row['id']} date={row['snapshot_date']} "
          f"equity=₹{float(row['total_equity']):,.2f} "
          f"cash=₹{float(row['cash_available']):,.2f} "
          f"deployed=₹{float(row['capital_deployed']):,.2f}")
    return row


if __name__ == "__main__":
    snapshot_portfolio()

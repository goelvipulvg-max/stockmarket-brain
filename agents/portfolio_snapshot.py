"""
Daily Portfolio Snapshot — equity-curve history for Tier-4 / backtest (P2-9).

Writes one row per trading day to the dedicated append-only `portfolio_snapshots`
table. Kept SEPARATE from the single live `portfolio` row so snapshots are never
mutated by later trades and never shadow get_current_portfolio() (which selects
the live row by max id). Idempotent per day via upsert on snapshot_date.

Trigger: .github/workflows/portfolio_snapshot.yml (daily, after market close).
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.supabase_client import get_client
from utils.capital_ledger import get_current_portfolio

IST = ZoneInfo("Asia/Kolkata")
sb = get_client()


def snapshot_portfolio():
    """Upsert today's portfolio equity snapshot into portfolio_snapshots."""
    pf = get_current_portfolio()

    snapshot = {
        "snapshot_date": datetime.now(IST).date().isoformat(),
        "starting_capital": pf["starting_capital"],
        "cash_available": pf["cash_available"],
        "capital_deployed": pf["capital_deployed"],
        "total_equity": pf["total_equity"],
        "realized_pnl_rs": pf.get("realized_pnl_rs", 0),
        "unrealized_pnl_rs": pf.get("unrealized_pnl_rs", 0),
        "open_positions": pf["open_positions"],
    }

    # P2-9: idempotent per day -- a same-day re-run overwrites that snapshot_date
    # row instead of duplicating (relies on UNIQUE(snapshot_date)).
    result = (
        sb.table("portfolio_snapshots")
        .upsert(snapshot, on_conflict="snapshot_date")
        .execute()
    )
    row = result.data[0] if result.data else snapshot
    print(f"Portfolio snapshot: id={row.get('id')} date={row['snapshot_date']} "
          f"equity=₹{float(row['total_equity']):,.2f} "
          f"cash=₹{float(row['cash_available']):,.2f} "
          f"deployed=₹{float(row['capital_deployed']):,.2f}")
    return row


if __name__ == "__main__":
    snapshot_portfolio()

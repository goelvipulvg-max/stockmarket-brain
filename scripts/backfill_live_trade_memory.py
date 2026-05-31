"""Phase 7 capture-half: ONE-TIME backfill of LIVE_TRADE rows for the 3 OPEN
TIER2F trades that predate the signal-time capture hook (ids 160/161/162).

Without this, when those trades resolve (~2026-06-01) the close-time outcome
backfill (update_trade_memory_outcome) would find no trade_memory_v2 row to
update and the first-ever live Tier-2F outcomes would be lost from learning.

Per decision (a2): sector + nifty_mood come from paper_trades.raw_signal
(context_summary), reasonings from raw_signal haiku/flash, event_type from
filings_log, and market_cap_cr is RE-FETCHED from Neon company_profiles (NOT
left NULL -- raw_signal never carried it).

IDEMPOTENT: skips any trade that already has a LIVE_TRADE row (matched on
paper_trade_id), so it is safe to re-run.

  .venv\\Scripts\\python.exe -m scripts.backfill_live_trade_memory --dry-run
  .venv\\Scripts\\python.exe -m scripts.backfill_live_trade_memory

DBs: paper_trades / filings_log / trade_memory_v2 = SUPABASE.
     company_profiles (market_cap_cr) = NEON (via utils.neon_fundamentals).
"""
import json
import argparse

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.supabase_client import get_client
from utils.neon_fundamentals import get_fundamentals
from utils.trade_memory_writer import build_live_trade_memory_row, insert_live_trade_memory

# The 3 OPEN TIER2F trades created before the signal-time capture hook existed.
TRADE_IDS = [160, 161, 162]


def _parse_raw_signal(raw):
    """raw_signal is a JSON string (or already a dict). Returns dict or {}."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return {}


def backfill_one(sb, trade_id: int, dry_run: bool) -> str:
    """Backfill a single LIVE_TRADE row for trade_id. Returns a status string."""
    # --- Idempotency: skip if a LIVE_TRADE row already exists for this trade ---
    existing = sb.table("trade_memory_v2").select("id", count="exact") \
        .eq("source_type", "LIVE_TRADE").eq("paper_trade_id", trade_id) \
        .limit(1).execute()
    if existing.count and existing.count > 0:
        return f"SKIP id={trade_id}: LIVE_TRADE row already exists (count={existing.count})"

    # --- Load the paper_trade (SUPABASE) ---
    rows = sb.table("paper_trades").select(
        "id,ticker,source,status,filing_id,raw_signal"
    ).eq("id", trade_id).execute().data
    if not rows:
        return f"SKIP id={trade_id}: paper_trade NOT FOUND"
    t = rows[0]
    ticker = t["ticker"]
    symbol_base = ticker.replace(".NS", "")

    parsed = _parse_raw_signal(t.get("raw_signal"))
    haiku_output = parsed.get("haiku")
    flash_output = parsed.get("flash")
    ctx = parsed.get("context_summary") or {}
    sector = ctx.get("sector")
    nifty_mood = ctx.get("nifty_mood")

    # --- event_type from filings_log (SUPABASE) ---
    event_type = None
    fid = t.get("filing_id")
    if fid is not None:
        frows = sb.table("filings_log").select("event_type").eq("id", fid).execute().data
        if frows:
            event_type = frows[0].get("event_type")

    # --- (a2) re-fetch market_cap_cr from Neon company_profiles ---
    market_cap_cr = None
    fundamentals = get_fundamentals(symbol_base)
    if fundamentals is not None:
        market_cap_cr = fundamentals.get("market_cap_cr")

    # --- Build the row via the shared pure builder ---
    row = build_live_trade_memory_row(
        trade_id=trade_id,
        haiku_output=haiku_output,
        flash_output=flash_output,
        sector=sector,
        market_cap_cr=market_cap_cr,
        nifty_mood=nifty_mood,
        symbol_base=symbol_base,
        event_type=event_type,
    )

    # --- Eyeball summary (so a dry-run shows exactly what WOULD be inserted) ---
    h_len = len(row["haiku_reasoning"]) if row["haiku_reasoning"] else 0
    f_len = len(row["deepseek_reasoning"]) if row["deepseek_reasoning"] else 0
    print(f"  id={trade_id} {symbol_base} ({ticker}) status={t.get('status')} src={t.get('source')}")
    print(f"     source_type={row['source_type']} outcome={row['outcome']} "
          f"pnl_pct={row['pnl_pct']} holding_days={row['holding_days']} paper_trade_id={row['paper_trade_id']}")
    print(f"     event_type={row['event_type']} sector={row['sector']} "
          f"nifty_mood={row['nifty_mood']} market_cap_cr={row['market_cap_cr']} (Neon re-fetch)")
    print(f"     haiku_reasoning len={h_len} deepseek_reasoning len={f_len}")
    print(f"     pattern_tags={row['pattern_tags']}")
    print(f"     full_context keys={list(row['full_context'].keys())}")

    new_id = insert_live_trade_memory(sb, row, dry_run=dry_run)
    if dry_run:
        return f"DRY-RUN id={trade_id}: would insert (no write)"
    return f"INSERTED id={trade_id}: trade_memory_v2 id={new_id}"


def main():
    parser = argparse.ArgumentParser(
        description="One-time backfill of LIVE_TRADE rows for OPEN pre-capture trades (Phase 7)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be inserted; no writes")
    args = parser.parse_args()

    if args.dry_run:
        print("*** DRY-RUN MODE -- no DB writes ***")
    sb = get_client()

    results = []
    for tid in TRADE_IDS:
        print(f"\n--- trade {tid} ---")
        status = backfill_one(sb, tid, dry_run=args.dry_run)
        print(f"  => {status}")
        results.append(status)

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r}")


if __name__ == "__main__":
    main()

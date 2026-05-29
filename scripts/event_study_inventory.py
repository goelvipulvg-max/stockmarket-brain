"""Event-study data inventory (READ-ONLY diagnostic).

Counts + date-range + per-event_type breakdown for the datasets that feed the
filing-edge event study, plus a survivorship pre-check. NO writes.

  event_outcomes   -> Neon   (historical seed; dividend/bonus/split/buyback only)
  nse500_watchlist -> Neon   (current membership; survivorship reference)
  filing_memory    -> Supabase (live, recent; has alpha_5d/10d/30d)

Usage: .venv/Scripts/python.exe scripts/event_study_inventory.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import query
from utils.supabase_client import get_client


def _bare(sym: str) -> str:
    return (sym or "").replace(".NS", "").replace(".ns", "").strip()


def main():
    print("=" * 64)
    print("Event-Study Data Inventory (READ-ONLY)")
    print("=" * 64)

    eo_syms = set()

    # ── event_outcomes (Neon) ──────────────────────────────────────────
    print("\n[event_outcomes -- Neon]")
    try:
        rows = query("SELECT symbol, event_type, event_date FROM event_outcomes")
        print(f"  total rows: {len(rows)}")
        if rows:
            dates = [r["event_date"] for r in rows if r["event_date"]]
            if dates:
                print(f"  date range: {min(dates)} -> {max(dates)}")
            eo_syms = {_bare(r["symbol"]) for r in rows if r["symbol"]}
            print(f"  distinct symbols: {len(eo_syms)}")
            et = Counter((r["event_type"] or "NULL") for r in rows)
            print("  per event_type:")
            for k, v in et.most_common():
                print(f"    {k:<22} {v}")
    except Exception as e:
        print(f"  [FAILED] {type(e).__name__}: {e}")

    # ── nse500_watchlist (Neon) -- survivorship pre-check ──────────────
    print("\n[nse500_watchlist -- Neon]")
    try:
        wl = query("SELECT symbol, status FROM nse500_watchlist")
        active = {_bare(r["symbol"]) for r in wl if r["status"] == "ACTIVE"}
        print(f"  total rows: {len(wl)}, ACTIVE: {len(active)}")
        if eo_syms:
            not_current = eo_syms - active
            pct = 100 * len(not_current) / max(len(eo_syms), 1)
            print(f"  event_outcomes symbols NOT in current ACTIVE watchlist: "
                  f"{len(not_current)} / {len(eo_syms)} ({pct:.1f}%)")
            print("    ^ these are events on names not currently in Nifty500 -- "
                  "survivorship-relevant cohort")
    except Exception as e:
        print(f"  [FAILED] {type(e).__name__}: {e}")

    # ── filing_memory (Supabase) ───────────────────────────────────────
    print("\n[filing_memory -- Supabase]")
    try:
        sb = get_client()
        fm = (
            sb.table("filing_memory")
            .select("event_type,filing_date,outcome_10d_status")
            .execute()
            .data
        )
        print(f"  total rows: {len(fm)}")
        filled = [r for r in fm if r.get("outcome_10d_status") == "FILLED"]
        print(f"  outcome_10d FILLED: {len(filled)}")
        fds = [r["filing_date"] for r in fm if r.get("filing_date")]
        if fds:
            print(f"  filing_date range: {min(fds)} -> {max(fds)}")
        et = Counter((r.get("event_type") or "NULL") for r in filled)
        print("  per event_type (10d FILLED):")
        for k, v in et.most_common():
            print(f"    {k:<22} {v}")
    except Exception as e:
        print(f"  [skipped] filing_memory read failed: {type(e).__name__}: {e}")

    print("\nDone (read-only; no writes).")


if __name__ == "__main__":
    main()

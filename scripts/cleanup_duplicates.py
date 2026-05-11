#!/usr/bin/env python
"""
Cleanup duplicate company_profiles rows caused by missing .NS suffix
during gap-fill. Normalizes all symbols to end in .NS.

Usage:
    .venv/Scripts/python.exe scripts/cleanup_duplicates.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection


def main():
    conn = get_neon_connection()
    cur = conn.cursor()

    # Fetch all rows
    cur.execute("SELECT symbol, company_name FROM company_profiles")
    rows = cur.fetchall()
    print(f"Total rows before cleanup: {len(rows)}")

    # Build lookup: symbol -> exists
    all_symbols = {row[0] for row in rows}

    deleted = 0
    updated = 0

    for symbol, name in rows:
        # Only process symbols WITHOUT .NS suffix
        if symbol.endswith(".NS"):
            continue

        ns_symbol = symbol + ".NS"

        if ns_symbol in all_symbols:
            # .NS version exists — delete the bare one
            cur.execute("DELETE FROM company_profiles WHERE symbol = %s", (symbol,))
            deleted += 1
            print(f"  DELETE {symbol:20s}  (.NS counterpart exists)")

        else:
            # .NS version does NOT exist — rename bare to .NS
            cur.execute(
                "UPDATE company_profiles SET symbol = %s WHERE symbol = %s",
                (ns_symbol, symbol),
            )
            updated += 1
            print(f"  UPDATE {symbol:20s} -> {ns_symbol}")

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM company_profiles")
    final_count = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\nDeleted:  {deleted}")
    print(f"Updated:  {updated}")
    print(f"Final count: {final_count}")


if __name__ == "__main__":
    main()

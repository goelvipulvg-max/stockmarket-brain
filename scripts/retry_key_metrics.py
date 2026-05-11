#!/usr/bin/env python
"""Targeted retry: re-fetch key_metrics for 7 companies with missing metrics."""

import json
import sys
import os
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection

import yfinance as yf

TARGET = [
    "COFORGE.NS", "GSPL.NS", "HSCL.NS", "JINDALSTEL.NS",
    "NMDC.NS", "WELCORP.NS", "ZYDUSLIFE.NS",
]

API_TIMEOUT = 15


def main():
    conn = get_neon_connection()
    cur = conn.cursor()

    success = []
    failed = []

    for symbol in TARGET:
        print(f"  {symbol:<20s} ", end="", flush=True)
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info or info.get("message") or info.get("error"):
                raise RuntimeError(f"yFinance returned invalid data")

            key_metrics = json.dumps({
                "market_cap": info.get("marketCap"),
                "website": info.get("website"),
                "employees": info.get("fullTimeEmployees"),
            })

            cur.execute("""
                UPDATE company_profiles
                SET key_metrics = %s::jsonb, updated_at = NOW()
                WHERE symbol = %s
            """, (key_metrics, symbol))

            print("OK")
            success.append(symbol)

        except Exception as e:
            print(f"FAIL -- {e}")
            failed.append(symbol)

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n  Success: {len(success)}/7 -- {success}")
    if failed:
        print(f"  Failed:  {len(failed)}/7 -- {failed}")
    else:
        print("  All 7 fixed.")

    # Verify
    conn2 = get_neon_connection()
    cur2 = conn2.cursor()
    placeholders = ",".join(["%s"] * len(TARGET))
    cur2.execute(
        f"SELECT symbol, key_metrics IS NOT NULL FROM company_profiles WHERE symbol IN ({placeholders}) ORDER BY symbol",
        TARGET,
    )
    print("\n  Verify:")
    for row in cur2.fetchall():
        print(f"    {row[0]}  key_metrics={'POPULATED' if row[1] else 'NULL'}")
    cur2.close()
    conn2.close()


if __name__ == "__main__":
    main()

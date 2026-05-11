#!/usr/bin/env python
"""
Fill gaps: find Nifty 500 symbols missing from Neon company_profiles.
Reads from local CSV, tries yFinance, falls back to minimal CSV-sourced insert.

Usage:
    .venv/Scripts/python.exe scripts/preloader_fill_gaps.py
"""

import csv
import os
import sys
import time
from datetime import datetime
from io import StringIO

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "ind_nifty500list.csv")

MAX_YFINANCE_RETRIES = 2
BETWEEN_CALLS_SLEEP = 1.0


def load_local_csv() -> list[dict]:
    """Read Nifty 500 CSV from local file. Returns list of {symbol, yf_symbol, company_name, industry}."""
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        content = f.read()

    lines = content.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if "Symbol" in line or "symbol" in line:
            header_idx = i
            break

    clean_csv = "\n".join(lines[header_idx:])
    df = pd.read_csv(StringIO(clean_csv))

    symbol_col = [c for c in df.columns if "Symbol" in c or "symbol" in c][0]
    name_col = [c for c in df.columns if "Company Name" in c or "Name" in c or "company" in c.lower()][0]
    industry_col = [c for c in df.columns if "Industry" in c or "industry" in c][0] if any("Industry" in c or "industry" in c for c in df.columns) else None

    companies = []
    for _, row in df.iterrows():
        sym = str(row[symbol_col]).strip()
        if not sym or sym == "nan":
            continue
        name = str(row[name_col]).strip() if pd.notna(row[name_col]) else sym
        industry = str(row[industry_col]).strip() if industry_col and pd.notna(row[industry_col]) else ""
        companies.append({
            "symbol": sym,
            "yf_symbol": f"{sym}.NS",
            "company_name": name,
            "industry": industry,
        })
    return companies


def fetch_yfinance_profile(yf_symbol: str) -> dict | None:
    """Try yFinance with retries. Returns info dict or None."""
    for attempt in range(MAX_YFINANCE_RETRIES):
        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            if info and info.get("longName"):
                return {
                    "longName": info.get("longName", ""),
                    "sector": info.get("sector") or "",
                    "industry": info.get("industry") or "",
                    "marketCap": info.get("marketCap"),
                    "website": info.get("website") or "",
                    "fullTimeEmployees": info.get("fullTimeEmployees"),
                    "longBusinessSummary": info.get("longBusinessSummary") or "",
                }
        except Exception:
            pass
        if attempt < MAX_YFINANCE_RETRIES - 1:
            time.sleep((attempt + 1) * 3)
    return None


def upsert_full(conn, symbol: str, company_name: str, data: dict):
    """Insert full yFinance profile into company_profiles."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO company_profiles (symbol, company_name, sector, industry,
            market_cap, nifty500, last_updated)
        VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry,
            market_cap = EXCLUDED.market_cap,
            nifty500 = TRUE,
            last_updated = NOW()
    """, (
        symbol,
        data.get("longName", company_name),
        data.get("sector", ""),
        data.get("industry", ""),
        data.get("marketCap") or 0,
    ))
    cur.close()


def upsert_minimal(conn, symbol: str, company_name: str, industry: str):
    """Insert minimal record from CSV — only what we have."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO company_profiles (symbol, company_name, sector, industry,
            market_cap, nifty500, last_updated)
        VALUES (%s, %s, %s, %s, 0, TRUE, NOW())
        ON CONFLICT (symbol) DO NOTHING
    """, (
        symbol,
        company_name,
        industry,
        "",
    ))
    cur.close()


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"  Preloader Gap Filler (Local CSV + Fallback)")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 1. Load local CSV
    companies = load_local_csv()
    print(f"\n  Symbols in local CSV: {len(companies)}")

    # 2. Get existing from Neon
    conn = get_neon_connection()
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM company_profiles")
    existing = {row[0] for row in cur.fetchall()}
    cur.close()
    print(f"  Symbols in company_profiles: {len(existing)}")

    # 3. Find gaps
    missing = [c for c in companies if c["symbol"] not in existing]
    print(f"  MISSING (CSV - Neon): {len(missing)}")

    if not missing:
        print("  No gaps to fill. Exiting.")
        conn.close()
        return 0

    print(f"\n  Processing {len(missing)} missing symbols...\n")

    counts = {"full": 0, "minimal": 0, "failed": 0}
    total = len(missing)

    for i, co in enumerate(missing, 1):
        sym = co["symbol"]
        yf_sym = co["yf_symbol"]
        name = co["company_name"]
        industry = co["industry"]
        remaining = total - i

        print(f"  [{i}/{total}] {sym}  ", end="", flush=True)

        # Try yFinance
        yf_data = fetch_yfinance_profile(yf_sym)

        try:
            if yf_data:
                upsert_full(conn, sym, name, yf_data)
                counts["full"] += 1
                print(f"FULL  ({name[:40]}, {yf_data.get('sector', 'N/A')})")
            else:
                # Fallback: minimal insert from CSV
                upsert_minimal(conn, sym, name, industry)
                counts["minimal"] += 1
                print(f"MINIMAL  ({name[:40]}, sector={industry or 'N/A'})")
        except Exception as e:
            counts["failed"] += 1
            # Reconnect on connection errors
            msg = str(e).lower()
            if "connection" in msg:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_neon_connection()
                try:
                    if yf_data:
                        upsert_full(conn, sym, name, yf_data)
                    else:
                        upsert_minimal(conn, sym, name, industry)
                    counts["full" if yf_data else "minimal"] += 1
                    counts["failed"] -= 1
                    print(f"RETRY OK")
                    continue
                except Exception:
                    pass
            print(f"ERROR  ({str(e)[:60]})")

        time.sleep(BETWEEN_CALLS_SLEEP)

    conn.close()

    # 4. Final count
    conn = get_neon_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM company_profiles")
    final_count = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  GAP FILL COMPLETE")
    print(f"  Full yFinance: {counts['full']}  |  Minimal CSV: {counts['minimal']}")
    print(f"  Failed: {counts['failed']}  |  Final Neon count: {final_count}/504")
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

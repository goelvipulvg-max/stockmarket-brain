import os
import time
import psycopg2
import yfinance as yf
import pandas as pd
import requests
from dotenv import load_dotenv
from io import StringIO

load_dotenv(override=True)

NEON_URL = os.getenv("NEON_CONNECTION_STRING")

def get_connection():
    return psycopg2.connect(NEON_URL)

def backup_existing():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS company_profiles_backup;")
    cur.execute("ALTER TABLE IF EXISTS company_profiles RENAME TO company_profiles_backup;")
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Backup done: company_profiles → company_profiles_backup")

def create_fresh_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            symbol TEXT PRIMARY KEY,
            company_name TEXT,
            sector TEXT,
            industry TEXT,
            market_cap BIGINT,
            nifty500 BOOLEAN DEFAULT TRUE,
            last_updated TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Fresh company_profiles table created")

def fetch_nifty500_symbols():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }
    session = requests.Session()
    # First hit NSE homepage to get cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=30)
    time.sleep(2)
    # Then fetch the CSV
    r = session.get(url, headers=headers, timeout=30)

    print(f"Status code: {r.status_code}")
    print(f"Response length: {len(r.text)}")
    print(f"First 200 chars: {r.text[:200]}")

    lines = r.text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if 'Symbol' in line or 'symbol' in line:
            header_idx = i
            break

    clean_csv = "\n".join(lines[header_idx:])
    df = pd.read_csv(StringIO(clean_csv))
    symbol_col = [c for c in df.columns if 'Symbol' in c or 'symbol' in c][0]
    symbols = df[symbol_col].dropna().tolist()
    symbols = [str(s).strip() + ".NS" for s in symbols if str(s).strip()]

    print(f"✅ Fetched {len(symbols)} symbols")
    return symbols

def upsert_company(symbol, data):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO company_profiles
            (symbol, company_name, sector, industry, market_cap, nifty500, last_updated)
        VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry,
            market_cap = EXCLUDED.market_cap,
            nifty500 = TRUE,
            last_updated = NOW();
    """, (
        symbol,
        data.get("longName", ""),
        data.get("sector", ""),
        data.get("industry", ""),
        data.get("marketCap", 0)
    ))
    conn.commit()
    cur.close()
    conn.close()

def load_all():
    symbols = fetch_nifty500_symbols()
    total = len(symbols)
    success = 0
    failed = []

    for i, symbol in enumerate(symbols, 1):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info and info.get("longName"):
                upsert_company(symbol, info)
                success += 1
                print(f"✅ {symbol} ({i}/{total})")
            else:
                failed.append(symbol)
                print(f"⚠️ No data: {symbol} ({i}/{total})")
        except Exception as e:
            failed.append(symbol)
            print(f"❌ Failed: {symbol} — {e}")
        time.sleep(0.5)

    print(f"\n🎯 Done: {success}/{total} loaded")
    if failed:
        print(f"⚠️ Failed symbols ({len(failed)}): {failed}")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM company_profiles;")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"📊 Final Neon count: {count}")

if __name__ == "__main__":
    backup_existing()
    create_fresh_table()
    load_all()

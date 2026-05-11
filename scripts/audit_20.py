import time
import requests
import threading
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv(override=True)

def get_db():
    return psycopg2.connect(os.getenv('NEON_CONNECTION_STRING'))

def audit_company(symbol, results, lock):
    clean_sym = symbol.replace('.NS','')
    result = {
        'symbol': symbol,
        'summary_status': 'UNKNOWN',
        'summary_length': 0,
        'cache_rows': 0,
        'nse_total': 0,
        'nse_6mo': 0,
        'gap': 0,
        'nse_status': 'UNKNOWN'
    }

    try:
        # DB Check
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                business_summary,
                key_metrics IS NOT NULL
            FROM company_profiles
            WHERE symbol = %s
        """, (symbol,))
        row = cur.fetchone()

        if row:
            bs, has_metrics = row
            if bs is None:
                result['summary_status'] = 'NULL'
            elif bs == '':
                result['summary_status'] = 'EMPTY'
            elif len(bs) < 100:
                result['summary_status'] = 'TOO_SHORT'
            else:
                result['summary_status'] = 'OK'
            result['summary_length'] = len(bs) if bs else 0

        cur.execute(
            "SELECT COUNT(*) FROM research_cache WHERE symbol = %s",
            (symbol,)
        )
        result['cache_rows'] = cur.fetchone()[0]
        cur.close()
        conn.close()

        # NSE Check with safe delay
        time.sleep(3)
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.nseindia.com'
        })
        session.get('https://www.nseindia.com', timeout=10)
        time.sleep(2)

        six_months_ago = datetime.now() - timedelta(days=180)
        url = f'https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={clean_sym}'
        r = session.get(url, timeout=30)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                for key in ('data', 'announcements', 'corporateAnnouncements'):
                    if key in data:
                        data = data[key]
                        break
                else:
                    data = []
            result['nse_total'] = len(data) if isinstance(data, list) else 0
            result['nse_6mo'] = sum(1 for x in data if isinstance(x, dict)
                and parse_nse_date(x.get('sort_date','') or x.get('an_dt','') or x.get('dt','') or '') >= six_months_ago.date()
            ) if isinstance(data, list) else 0
            result['gap'] = result['nse_6mo'] - result['cache_rows']
            result['nse_status'] = 'OK'
        else:
            result['nse_status'] = f'HTTP_{r.status_code}'

    except Exception as e:
        result['nse_status'] = f'ERROR: {str(e)[:50]}'

    with lock:
        results.append(result)
    print(f"Done: {symbol}")

def parse_nse_date(date_str):
    s = date_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%b %d, %Y",
        "%d %b %Y", "%B %d, %Y", "%d%m%Y%H%M%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return datetime.now().date()  # default: include if can't parse

def run_agent(companies, results, lock):
    for sym in companies:
        audit_company(sym, results, lock)
        time.sleep(3)  # safe gap between companies

# Get 20 symbols from DB
conn = get_db()
cur = conn.cursor()
cur.execute("""SELECT symbol FROM company_profiles
               WHERE business_summary IS NOT NULL
               ORDER BY symbol""")
symbols = [r[0] for r in cur.fetchall()]
cur.close()
conn.close()

# 5 agents x 4 companies
groups = [symbols[i:i+4] for i in range(0, len(symbols), 4)]

results = []
lock = threading.Lock()
threads = []

print(f"Starting 5 parallel agents for {len(symbols)} companies...")
for i, group in enumerate(groups[:5]):
    t = threading.Thread(
        target=run_agent,
        args=(group, results, lock)
    )
    t.start()
    threads.append(t)
    time.sleep(5)  # stagger agent starts

for t in threads:
    t.join()

# Print results table
print("\n" + "="*100)
print(f"{'Symbol':<15} {'Summary':<12} {'Length':>8} {'Cache':>6} {'NSE Total':>10} {'NSE 6mo':>8} {'Gap':>6} {'NSE Status'}")
print("="*100)
for r in sorted(results, key=lambda x: x['symbol']):
    print(f"{r['symbol']:<15} {r['summary_status']:<12} {r['summary_length']:>8} {r['cache_rows']:>6} {r['nse_total']:>10} {r['nse_6mo']:>8} {r['gap']:>6} {r['nse_status']}")

print("="*100)
ok = sum(1 for r in results if r['summary_status']=='OK')
print(f"\nSummary OK: {ok}/{len(results)}")
total_gap = sum(r['gap'] for r in results if r['gap'] > 0)
print(f"NSE gaps (6mo announcements we DON'T have): {total_gap} total missing")

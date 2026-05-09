import os
import sys
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv(override=True)
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

SEP = "-" * 50

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def fetch_all_trades(sb):
    rows, offset, page = [], 0, 1000
    while True:
        res = sb.table("paper_trades").select("*").order("signal_generated_at").range(offset, offset + page - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows

def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    print("Fetching paper_trades from Supabase...")
    rows = fetch_all_trades(sb)

    if not rows:
        print("No paper trades found in the table.")
        return

    total = len(rows)

    # --- 1. Total signals by direction ---
    direction_counts = defaultdict(int)
    for r in rows:
        direction_counts[r.get("direction", "UNKNOWN")] += 1

    section(f"1. TOTAL SIGNALS  (n={total})")
    for direction in ["BUY", "SELL", "HOLD"]:
        count = direction_counts.get(direction, 0)
        pct = count / total * 100
        print(f"  {direction:<6}  {count:>4}  ({pct:.1f}%)")

    # --- 2. Per-stock breakdown ---
    ticker_dir = defaultdict(lambda: defaultdict(int))
    for r in rows:
        ticker_dir[r["ticker"]][r.get("direction", "UNKNOWN")] += 1

    section("2. PER-STOCK BREAKDOWN")
    print(f"  {'Ticker':<16} {'BUY':>5} {'SELL':>5} {'Total':>6}")
    print(f"  {'-'*16} {'-'*5} {'-'*5} {'-'*6}")
    for ticker in sorted(ticker_dir):
        d = ticker_dir[ticker]
        buy = d.get("BUY", 0)
        sell = d.get("SELL", 0)
        ttl = sum(d.values())
        print(f"  {ticker:<16} {buy:>5} {sell:>5} {ttl:>6}")

    # --- 3. Confidence score distribution ---
    conf_counts = defaultdict(int)
    for r in rows:
        c = r.get("confidence")
        if c is not None:
            conf_counts[int(c)] += 1

    section("3. CONFIDENCE SCORE DISTRIBUTION")
    print(f"  {'Score':<8} {'Count':>6}  {'Bar'}")
    print(f"  {'-'*8} {'-'*6}  {'-'*20}")
    for score in range(1, 11):
        count = conf_counts.get(score, 0)
        bar = "#" * count
        print(f"  {score:<8} {count:>6}  {bar}")

    # --- 4. Date-wise signal count ---
    date_counts = defaultdict(int)
    for r in rows:
        date_counts[r.get("signal_date", "unknown")] += 1

    section("4. DATE-WISE SIGNAL COUNT")
    print(f"  {'Date':<12} {'Signals':>8}")
    print(f"  {'-'*12} {'-'*8}")
    for date in sorted(date_counts):
        print(f"  {date:<12} {date_counts[date]:>8}")

    # --- 5. Most bullish / bearish stocks ---
    buy_counts = {t: ticker_dir[t].get("BUY", 0) for t in ticker_dir}
    sell_counts = {t: ticker_dir[t].get("SELL", 0) for t in ticker_dir}

    most_bullish = max(buy_counts, key=buy_counts.get)
    most_bearish = max(sell_counts, key=sell_counts.get)

    section("5. MOST BULLISH / BEARISH")
    print(f"  Most BUY signals  ->  {most_bullish}  ({buy_counts[most_bullish]} BUYs)")
    print(f"  Most SELL signals ->  {most_bearish}  ({sell_counts[most_bearish]} SELLs)")

    # --- 6. Closed trade PnL (bonus — if any trades have been closed) ---
    closed = [r for r in rows if r.get("status") in ("TARGET_HIT", "SL_HIT", "EXPIRED") and r.get("pnl_pct") is not None]
    if closed:
        wins = [r for r in closed if r.get("status") == "TARGET_HIT"]
        losses = [r for r in closed if r.get("status") == "SL_HIT"]
        expired = [r for r in closed if r.get("status") == "EXPIRED"]
        avg_pnl = sum(r["pnl_pct"] for r in closed) / len(closed)
        win_rate = len(wins) / (len(wins) + len(losses)) * 100 if (wins or losses) else 0.0

        section("6. CLOSED TRADE SUMMARY")
        print(f"  Closed trades   : {len(closed)}")
        print(f"  TARGET_HIT (W)  : {len(wins)}")
        print(f"  SL_HIT (L)      : {len(losses)}")
        print(f"  EXPIRED         : {len(expired)}")
        print(f"  Win rate        : {win_rate:.1f}%  (excl. expired)")
        print(f"  Avg PnL%%        : {avg_pnl:+.2f}%%")
    else:
        section("6. CLOSED TRADE SUMMARY")
        print("  No closed trades yet (all OPEN or no status set)")

    print(f"\n{SEP}")
    print(f"  Done. {total} total records analysed.")
    print(SEP)

if __name__ == "__main__":
    main()

"""
StockMarket-Brain | Paper Trade Updater

Logic:
- Fetches all OPEN trades from Supabase
- Gets today's intraday HIGH and LOW from Yahoo Finance
- Closes trades on target/SL hit using day range (not just LTP -
  this captures intraday swings between 30-min check intervals)
- Swing window: trades stay OPEN for up to MAX_HOLDING_DAYS calendar days
- At 15:30 IST on day >= MAX_HOLDING_DAYS, force-closes remaining OPEN as EXPIRED at LTP

Backtest convention: zero slippage. Exit at exact target/SL on hit, LTP on expiry.
"""
import sys
from datetime import datetime, date, time as dt_time
from zoneinfo import ZoneInfo
from utils.supabase_client import get_client
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
load_dotenv(override=True)

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = dt_time(15, 30)
MAX_HOLDING_DAYS = 5  # swing window: expire only after this many calendar days

try:
    supabase = get_client()
except ValueError as e:
    print(f"FATAL: {e}")
    sys.exit(1)
_session = curl_requests.Session(impersonate="chrome124")


def get_market_data(ticker):
    """Returns dict with ltp, day_high, day_low. None if fetch failed."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com",
        }
        r = _session.get(url, headers=headers, timeout=10)
        meta = r.json()["chart"]["result"][0]["meta"]
        ltp = float(meta["regularMarketPrice"])
        return {
            "ltp": round(ltp, 2),
            "day_high": round(float(meta.get("regularMarketDayHigh", ltp)), 2),
            "day_low": round(float(meta.get("regularMarketDayLow", ltp)), 2),
        }
    except Exception as e:
        print(f"  Fetch failed for {ticker}: {type(e).__name__}: {e}")
        return None


def check_hit(direction, day_high, day_low, target, stop_loss):
    """Returns 'TARGET_HIT', 'SL_HIT', or None. Uses intraday range."""
    if direction == "BUY":
        if day_high >= target:    return "TARGET_HIT"
        if day_low <= stop_loss:  return "SL_HIT"
    else:  # SELL
        if day_low <= target:     return "TARGET_HIT"
        if day_high >= stop_loss: return "SL_HIT"
    return None


def calc_pnl_pct(direction, entry, exit_price):
    """BUY: profit when exit > entry. SELL: profit when exit < entry."""
    if direction == "BUY":
        return round(((exit_price - entry) / entry) * 100, 2)
    return round(((entry - exit_price) / entry) * 100, 2)


def main():
    now_ist = datetime.now(IST)
    is_market_close = now_ist.time() >= MARKET_CLOSE
    print(f"Run @ {now_ist.strftime('%Y-%m-%d %H:%M IST')} | Market close window: {is_market_close}")

    open_trades = supabase.table("paper_trades")\
        .select("*").eq("status", "OPEN").execute().data

    print(f"Open trades: {len(open_trades)}")
    closed = 0

    for trade in open_trades:
        # --- Holding days (calculated from signal_date; no DB column needed) ---
        signal_date = date.fromisoformat(trade["signal_date"])
        holding_days = (now_ist.date() - signal_date).days

        market = get_market_data(trade["ticker"])
        if market is None:
            print(f"  {trade['ticker']}: skip (no data)")
            continue

        entry = float(trade["entry_price"])
        target = float(trade["target_price"])
        stop_loss = float(trade["stop_loss"])

        new_status = check_hit(
            trade["direction"], market["day_high"], market["day_low"],
            target, stop_loss
        )

        # Only expire at market close once the swing window has elapsed
        if not new_status and is_market_close and holding_days >= MAX_HOLDING_DAYS:
            new_status = "EXPIRED"

        if new_status:
            # Backtest convention: exit at exact target/SL on hit, LTP on expiry
            if new_status == "TARGET_HIT":
                exit_price = target
            elif new_status == "SL_HIT":
                exit_price = stop_loss
            else:  # EXPIRED
                exit_price = market["ltp"]

            pnl = calc_pnl_pct(trade["direction"], entry, exit_price)

            supabase.table("paper_trades").update({
                "status": new_status,
                "closed_at": now_ist.isoformat(),
                "exit_price": exit_price,
                "pnl_pct": pnl,
            }).eq("id", trade["id"]).execute()

            print(f"  {trade['ticker']}: {new_status} @ {exit_price} | PnL: {pnl}%  (day {holding_days})")
            closed += 1
        else:
            days_left = max(0, MAX_HOLDING_DAYS - holding_days)
            print(f"  {trade['ticker']}: OPEN | LTP {market['ltp']} (range: {market['day_low']}-{market['day_high']}) | day {holding_days}/{MAX_HOLDING_DAYS}, {days_left} left")

    still_open = len(open_trades) - closed
    print(f"\nDone. Closed: {closed}  |  Still OPEN: {still_open}  |  Total checked: {len(open_trades)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Paper trade updater crashed - {type(e).__name__}: {e}")
        sys.exit(1)

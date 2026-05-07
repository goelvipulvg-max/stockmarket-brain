"""
StockMarket-Brain | Upstox Real-Time Trade Tracker

Replaces Yahoo Finance day_high/day_low with Upstox live market quotes.
Checks TARGET_HIT / SL_HIT on all OPEN paper trades using real-time data.

Upstox sandbox note:
  Sandbox covers 7 order-placement APIs only — market data is NOT supported.
  This script uses the live quotes API (read-only) with no orders placed.

Token refresh:
  Upstox access tokens expire every 24 hours.
  Run `python scripts/generate_token.py` to refresh UPSTOX_ACCESS_TOKEN in .env.
"""
import os
import sys
import requests
from datetime import datetime, date, time as dt_time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = dt_time(15, 30)
MAX_HOLDING_DAYS = 5

UPSTOX_ACCESS_TOKEN    = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()

# Watchlist ticker → Upstox instrument key (NSE_EQ|ISIN)
# ISINs are permanent identifiers — symbols can be renamed, ISINs do not change.
INSTRUMENT_MAP = {
    "RELIANCE.NS":   "NSE_EQ|INE002A01018",
    "TCS.NS":        "NSE_EQ|INE467B01029",
    "INFY.NS":       "NSE_EQ|INE009A01021",
    "HDFCBANK.NS":   "NSE_EQ|INE040A01034",
    "ICICIBANK.NS":  "NSE_EQ|INE090A01021",
    "SBIN.NS":       "NSE_EQ|INE062A01020",
    "BAJFINANCE.NS": "NSE_EQ|INE296A01024",
    "WIPRO.NS":      "NSE_EQ|INE075A01022",
    "ADANIENT.NS":   "NSE_EQ|INE423A01024",
    "HCLTECH.NS":    "NSE_EQ|INE860A01027",
}

UPSTOX_QUOTES_URL = "https://api.upstox.com/v2/market-quote/quotes"


def get_upstox_quotes(instrument_keys: list[str]) -> dict:
    """
    Batch-fetch quotes for all given instrument keys in one API call.
    Returns dict keyed by 'NSE_EQ:SYMBOL' (Upstox uses colon in response keys).
    Raises SystemExit with a clear message on auth failure.
    """
    headers = {
        "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    params = {"instrument_key": ",".join(instrument_keys)}
    r = requests.get(UPSTOX_QUOTES_URL, headers=headers, params=params, timeout=10)

    if r.status_code == 401:
        print("ERROR: Upstox token expired (401).")
        print("  Fix: run `python scripts/generate_token.py` to refresh UPSTOX_ACCESS_TOKEN in .env")
        sys.exit(1)

    r.raise_for_status()
    return r.json().get("data", {})


def extract_market_data(quote: dict) -> dict:
    """Pull ltp, day_high, day_low from a single Upstox quote object."""
    ltp = float(quote["last_price"])
    return {
        "ltp":      round(ltp, 2),
        "day_high": round(float(quote["ohlc"]["high"]), 2),
        "day_low":  round(float(quote["ohlc"]["low"]),  2),
    }


def check_hit(direction: str, day_high: float, day_low: float,
              target: float, stop_loss: float) -> str | None:
    """Returns 'TARGET_HIT', 'SL_HIT', or None."""
    if direction == "BUY":
        if day_high >= target:    return "TARGET_HIT"
        if day_low  <= stop_loss: return "SL_HIT"
    else:  # SELL
        if day_low  <= target:    return "TARGET_HIT"
        if day_high >= stop_loss: return "SL_HIT"
    return None


def calc_pnl_pct(direction: str, entry: float, exit_price: float) -> float:
    if direction == "BUY":
        return round(((exit_price - entry) / entry) * 100, 2)
    return round(((entry - exit_price) / entry) * 100, 2)


def main():
    if not UPSTOX_ACCESS_TOKEN:
        print("FATAL: UPSTOX_ACCESS_TOKEN not set in .env")
        print("  Fix: run `python scripts/generate_token.py`")
        sys.exit(1)

    now_ist = datetime.now(IST)
    is_market_close = now_ist.time() >= MARKET_CLOSE
    print(f"Run @ {now_ist.strftime('%Y-%m-%d %H:%M IST')} | Market close: {is_market_close}")
    print(f"Data source: Upstox live quotes (real-time LTP + day range)")

    try:
        sb = get_client()
    except ValueError as e:
        print(f"FATAL: {e}")
        sys.exit(1)
    open_trades = sb.table("paper_trades").select("*").eq("status", "OPEN").execute().data
    print(f"Open trades: {len(open_trades)}")

    if not open_trades:
        print("Nothing to do.")
        return

    # Collect unique instrument keys for all open tickers
    instrument_keys = []
    unmapped = []
    for trade in open_trades:
        key = INSTRUMENT_MAP.get(trade["ticker"])
        if key and key not in instrument_keys:
            instrument_keys.append(key)
        elif not key and trade["ticker"] not in unmapped:
            unmapped.append(trade["ticker"])

    if unmapped:
        print(f"  WARNING: No instrument key mapping for: {unmapped} — those trades will be skipped")

    # Single batched API call for all open tickers
    print(f"Fetching Upstox quotes for {len(instrument_keys)} instrument(s)...")
    quotes = get_upstox_quotes(instrument_keys)

    closed = 0
    for trade in open_trades:
        instrument_key = INSTRUMENT_MAP.get(trade["ticker"])
        if not instrument_key:
            continue

        # Upstox response keys use colon separator: "NSE_EQ:RELIANCE"
        data_key = instrument_key.replace("|", ":")
        quote = quotes.get(data_key) or quotes.get(instrument_key)

        if not quote:
            print(f"  {trade['ticker']}: no quote returned — skip")
            continue

        market = extract_market_data(quote)

        signal_date  = date.fromisoformat(trade["signal_date"])
        holding_days = (now_ist.date() - signal_date).days
        entry        = float(trade["entry_price"])
        target       = float(trade["target_price"])
        stop_loss    = float(trade["stop_loss"])

        new_status = check_hit(trade["direction"], market["day_high"], market["day_low"],
                               target, stop_loss)

        if not new_status and is_market_close and holding_days >= MAX_HOLDING_DAYS:
            new_status = "EXPIRED"

        if new_status:
            if new_status == "TARGET_HIT":
                exit_price = target
            elif new_status == "SL_HIT":
                exit_price = stop_loss
            else:
                exit_price = market["ltp"]

            pnl = calc_pnl_pct(trade["direction"], entry, exit_price)

            sb.table("paper_trades").update({
                "status":    new_status,
                "closed_at": now_ist.isoformat(),
                "exit_price": exit_price,
                "pnl_pct":   pnl,
            }).eq("id", trade["id"]).execute()

            print(f"  {trade['ticker']}: {new_status} @ {exit_price} | PnL: {pnl}%  (day {holding_days})")
            closed += 1
        else:
            days_left = max(0, MAX_HOLDING_DAYS - holding_days)
            print(f"  {trade['ticker']}: OPEN | LTP {market['ltp']}"
                  f" (range: {market['day_low']}-{market['day_high']})"
                  f" | day {holding_days}/{MAX_HOLDING_DAYS}, {days_left} left")

    still_open = len(open_trades) - closed
    print(f"\nDone. Closed: {closed}  |  Still OPEN: {still_open}  |  Total checked: {len(open_trades)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: {type(e).__name__}: {e}")
        sys.exit(1)

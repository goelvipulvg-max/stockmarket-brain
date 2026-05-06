import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import pandas as pd
import pandas_ta as ta
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(override=True)
from curl_cffi import requests as curl_requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from utils import questdb_client

# --- Session ---
_session = curl_requests.Session(impersonate="chrome124")

# --- Config ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_SWING_CHANNEL = os.getenv("TELEGRAM_SWING_CHANNEL", "").strip()
client = Anthropic(api_key=ANTHROPIC_API_KEY)
SCORE_THRESHOLD = 7

# --- Supabase config ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
supabase: Client | None = (
    create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None
)

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
    "ICICIBANK.NS", "SBIN.NS", "BAJFINANCE.NS",
    "WIPRO.NS", "ADANIENT.NS", "HCLTECH.NS"
]

# --- Step 1: Direct Yahoo Finance API ---
def get_stock_data(ticker):
    try:
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=90)).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start}&period2={end}&interval=1d"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com"
        }
        
        r = _session.get(url, headers=headers, timeout=15)
        data = r.json()
        
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        highs = result["indicators"]["quote"][0]["high"]
        lows = result["indicators"]["quote"][0]["low"]
        volumes = result["indicators"]["quote"][0]["volume"]
        
        df = pd.DataFrame({"Close": closes, "High": highs, "Low": lows, "Volume": volumes}).dropna()
        
        if len(df) < 20:
            return None
        
        close = df["Close"]
        df["RSI"] = ta.rsi(close, length=14)
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        if macd is not None:
            df["MACD"] = macd["MACD_12_26_9"]
            df["MACD_Signal"] = macd["MACDs_12_26_9"]
        df["Support"] = df["Low"].rolling(20).min()
        df["Resistance"] = df["High"].rolling(20).max()
        latest = df.iloc[-1]

        return {
            "ticker": ticker,
            "close": round(float(latest["Close"]), 2),
            "rsi": round(float(latest["RSI"]), 2) if pd.notna(latest.get("RSI")) else None,
            "macd": round(float(latest["MACD"]), 4) if "MACD" in df.columns and pd.notna(latest.get("MACD")) else None,
            "macd_signal": round(float(latest["MACD_Signal"]), 4) if "MACD_Signal" in df.columns and pd.notna(latest.get("MACD_Signal")) else None,
            "support": round(float(latest["Support"]), 2),
            "resistance": round(float(latest["Resistance"]), 2),
            "volume": int(latest["Volume"])
        }
    except Exception as e:
        print(f"  fetch failed: {e}")
        return None

# --- Step 2: Claude Signal ---
def get_signal(data):
    prompt = f"""You are a swing trade analyst for Indian NSE stocks.

Stock Data:
- Ticker: {data['ticker']}
- Close: ₹{data['close']}
- RSI(14): {data['rsi']}
- MACD: {data['macd']} | Signal: {data['macd_signal']}
- Support: ₹{data['support']}
- Resistance: ₹{data['resistance']}
- Volume: {data['volume']}

Respond ONLY in this JSON format:
{{
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": <integer 1-10>,
  "reason": "<one line in simple English>",
  "entry": <float>,
  "target": <float>,
  "stop_loss": <float>
}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
    temperature=0,
    messages=[{"role": "user", "content": prompt}]
)
    raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# --- Step 3: Telegram ---
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_SWING_CHANNEL:
        print("  Telegram config missing — skipping")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_SWING_CHANNEL, "text": message, "parse_mode": "HTML"}, timeout=10)
    r.raise_for_status()

def log_paper_trade(data, signal):
    """Insert all BUY/SELL signals into Supabase paper_trades for analysis."""
    if not supabase:
        print("  Supabase config missing - skipping paper trade log")
        return
    try:
        supabase.table("paper_trades").insert({
            "ticker": data["ticker"],
            "direction": signal["signal"],
            "confidence": signal["confidence"],
            "reason": signal["reason"],
            "entry_price": signal["entry"],
            "target_price": signal["target"],
            "stop_loss": signal["stop_loss"],
            "rsi": data["rsi"],
            "macd": data["macd"],
            "support": data["support"],
            "resistance": data["resistance"],
            "raw_signal": signal,
        }).execute()
        print(f"  -> Paper trade logged")
    except Exception as e:
        if "duplicate" in str(e).lower() or "23505" in str(e):
            print(f"  -> Already exists today, skipping")
        else:
            print(f"  -> Log failed: {type(e).__name__}: {e}")

def log_signal_questdb(data, signal):
    try:
        now_utc = datetime.now(timezone.utc)
        # QuestDB wire protocol rejects timestamptz — send naive UTC midnight
        ts = now_utc.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        signal_id = f"{data['ticker']}_{now_utc.strftime('%Y%m%d')}"
        sql = (
            "INSERT INTO signals "
            "(ts, signal_id, symbol, strategy, direction, confidence, "
            "entry_target, stop_loss, take_profit, reasoning, source, triggered, trade_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        row = (
            ts,
            signal_id,
            data["ticker"],
            "tier2-swing",
            signal["signal"],
            float(signal["confidence"]),
            signal["entry"],
            signal["stop_loss"],
            signal["target"],
            signal["reason"],
            "claude-haiku",
            False,
            "",
        )
        questdb_client.executemany(sql, [row])
        print("  -> QuestDB signal logged")
    except Exception as e:
        print(f"  -> QuestDB write failed (non-fatal): {type(e).__name__}: {e}")


def format_message(data, signal):
    emoji = "🟢" if signal["signal"] == "BUY" else "🔴" if signal["signal"] == "SELL" else "🟡"
    return f"""{emoji} <b>{data['ticker']}</b> — {signal['signal']}
💰 Close: ₹{data['close']}
📊 RSI: {data['rsi']} | MACD: {data['macd']}
🎯 Entry: ₹{signal['entry']} | Target: ₹{signal['target']} | SL: ₹{signal['stop_loss']}
🔒 Confidence: {signal['confidence']}/10
📝 {signal['reason']}"""

# --- Main ---
def main():
    print(f"Running Tier-2 Signal Agent — {len(WATCHLIST)} stocks")
    posted = 0
    for ticker in WATCHLIST:
        try:
            data = get_stock_data(ticker)
            if not data:
                print(f"{ticker}: No data — skip")
                continue
            signal = get_signal(data)
            print(f"{ticker}: {signal['signal']} | Confidence: {signal['confidence']}")
            if signal["signal"] != "HOLD":
                log_paper_trade(data, signal)
                log_signal_questdb(data, signal)

            if signal["confidence"] >= SCORE_THRESHOLD and signal["signal"] != "HOLD":
                msg = format_message(data, signal)
                send_telegram(msg)
                posted += 1
                print(f"  -> Posted [OK]")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"{ticker}: Error — {type(e).__name__}: {e}")
    print(f"\nDone. Posted: {posted} signals")

if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ FATAL: Tier-2 Signal Agent crashed — {type(e).__name__}: {e}")
        sys.exit(1)
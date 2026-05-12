"""After Hours Watcher — scans NSE filings post-market and queues gap-trade candidates."""

import json
import os
import hashlib
import urllib.request
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI
from utils.telegram_client import send_message
from utils.tradeable_score import is_tradeable, get_tradeable_score
from utils.liquidity_check import check_liquidity
from utils.market_context import get_market_context
from utils.pdf_parser import download_and_parse_nse_pdf, get_pdf_context_summary
from utils.gap_calculator import calculate_expected_gap
from utils.neon_client import get_neon_connection, query

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
TRADES_CHANNEL = os.getenv("TELEGRAM_TRADES_CHANNEL_ID")


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def is_duplicate(url: str) -> bool:
    h = url_hash(url)
    rows = query(f"SELECT id FROM after_hours_queue WHERE url_hash = '{h}'")
    return len(rows) > 0


def is_nse500_active(symbol: str) -> bool:
    """Check if symbol is in NSE 500 active watchlist (Neon)."""
    clean = symbol.replace(".NS", "").strip().upper()
    conn = psycopg2.connect(os.getenv("NEON_CONNECTION_STRING"))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM nse500_watchlist WHERE REPLACE(symbol, '.NS', '') = %s",
                (clean,)
            )
            row = cur.fetchone()
            return row is not None and row[0].upper() == 'ACTIVE'
    finally:
        conn.close()


def log_to_filings_log(data: dict):
    """Insert a classified filing into filings_log (Neon), dedup by url_hash."""
    conn = psycopg2.connect(os.getenv("NEON_CONNECTION_STRING"))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO filings_log
                    (symbol, company_name, exchange, event_type, summary, material_score,
                     trade_confidence, raw_title, source_url, url_hash, telegram_sent,
                     fo_checked, classified_at, published_at)
                VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s)
                ON CONFLICT (url_hash) DO NOTHING
            """, (
                data.get("symbol", ""),
                data.get("company_name", ""),
                data.get("exchange", "NSE"),
                data.get("event_type", "OTHER"),
                data.get("summary", ""),
                data.get("material_score", 0),
                data.get("trade_confidence", 0),
                data.get("raw_title", ""),
                data.get("source_url", ""),
                data.get("url_hash", ""),
                False,
                False,
                datetime.utcnow(),
                data.get("published_at", None),
            ))
            conn.commit()
    finally:
        conn.close()


def fetch_nse_filings():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    }
    cookie_req = urllib.request.Request("https://www.nseindia.com", headers=headers)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    try:
        opener.open(cookie_req, timeout=10)
        api_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
        api_req = urllib.request.Request(api_url, headers=headers)
        with opener.open(api_req, timeout=15) as r:
            data = json.loads(r.read())
        filings = []
        for item in data[:20]:
            filings.append({
                "title":    item.get("desc", ""),
                "company":  item.get("company", ""),
                "symbol":   item.get("symbol", ""),
                "category": item.get("attchmntType", ""),
                "pubdate":  item.get("an_dt", ""),
                "link":     f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={item.get('symbol','')}",
                "exchange": "NSE",
                "attchmntFile": item.get("attchmntFile", ""),
            })
        print(f"  Fetched {len(filings)} NSE filings")
        return filings
    except Exception as e:
        print(f"  NSE fetch error: {e}")
        return []


def classify_filing(filing):
    prompt = f"""Classify this NSE corporate filing for Indian retail investors.

Title: {filing['title']}
Company: {filing['company']}
Category: {filing['category']}

Respond ONLY in JSON (no markdown):
{{"event_type":"BOARD_MEETING|RESULTS|DIVIDEND|MERGER_ACQUISITION|INSIDER_TRADING|FUND_RAISE|MANAGEMENT_CHANGE|LEGAL|BONUS|SPLIT|BUYBACK|CONTRACT_WIN|OTHER","material_score":<1-10>,"summary":"<max 15 words>","is_material":<true if score>=6>,"trade_confidence":<0-100>}}"""

    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    return json.loads(text)


def get_prev_close(symbol: str) -> float:
    """Returns previous close price via yfinance, or None."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="2d")
        if len(hist) >= 1:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def save_to_queue(filing, clf, gap_result, prev_close):
    event_type = clf.get("event_type", "OTHER")
    tradeable_score = get_tradeable_score(event_type)
    expected_gap_pct = gap_result["expected_gap_pct"]

    entry_low = None
    entry_high = None
    target_price = None
    stop_loss = None
    if prev_close and prev_close > 0:
        entry_low  = round(prev_close * (1 + gap_result["entry_low_pct"]  / 100), 2)
        entry_high = round(prev_close * (1 + gap_result["entry_high_pct"] / 100), 2)
        target_price = round(prev_close * (1 + gap_result["target_pct"]    / 100), 2)
        stop_loss    = round(prev_close * (1 + gap_result["stop_loss_pct"] / 100), 2)

    action = "BUY" if expected_gap_pct > 0 else "SELL" if expected_gap_pct < 0 else "WATCH"

    conn = get_neon_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO after_hours_queue
                    (symbol, company_name, event_type, announcement_time,
                     tradeable_score, expected_gap_pct, recommended_action,
                     entry_price_low, entry_price_high, target_price, stop_loss,
                     confidence, telegram_sent, status, source_url, url_hash)
                VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s)
            """, (
                str(filing.get("symbol", "")),
                filing.get("company", ""),
                event_type,
                filing.get("pubdate", ""),
                tradeable_score,
                expected_gap_pct,
                action,
                entry_low,
                entry_high,
                target_price,
                stop_loss,
                gap_result["confidence"],
                False,
                "PENDING",
                filing.get("link", ""),
                url_hash(filing.get("link", "")),
            ))
    finally:
        conn.close()


def main():
    print("\n" + "="*50)
    print("  After Hours Watcher")
    print("="*50)

    filings = fetch_nse_filings()
    if not filings:
        print("No filings fetched. Exiting.")
        return

    market_mood, size_multiplier, nifty_change, vix_value = get_market_context()
    print(f"  Market: {market_mood} | NIFTY {nifty_change:+.2f}% | VIX {vix_value:.1f}")

    queued = 0
    alerted = 0

    for i, filing in enumerate(filings[:10]):
        print(f"\n[{i+1}] {filing['title'][:60]}...")
        if is_duplicate(filing.get("link", "")):
            print(f"     Already in queue — skipping")
            continue

        # Gate 1: Must be in NSE 500 active watchlist
        if not is_nse500_active(filing.get("symbol", "")):
            print(f"     SKIP: {filing['symbol']} — not in NSE500 active watchlist")
            continue

        try:
            try:
                clf = classify_filing(filing)
            except (json.JSONDecodeError, ValueError):
                print(f"     AI classification failed — skipping")
                continue

            # Log every classified filing to filings_log (Neon)
            log_to_filings_log({
                "symbol": filing.get("symbol", ""),
                "company_name": filing.get("company", ""),
                "exchange": "NSE",
                "event_type": clf.get("event_type", "OTHER"),
                "summary": clf.get("summary", ""),
                "material_score": clf.get("material_score", 0),
                "trade_confidence": clf.get("trade_confidence", 0),
                "raw_title": filing.get("title", ""),
                "source_url": filing.get("link", ""),
                "url_hash": url_hash(filing.get("link", "")),
                "published_at": filing.get("pubdate", None),
            })

            # Gate 2: Trade confidence threshold
            tc = clf.get("trade_confidence", 0)
            if tc < 70:
                print(f"     SKIP: {filing['symbol']} — trade_confidence {tc} < 70")
                continue

            event_type = clf.get("event_type", "OTHER")
            if not is_tradeable(event_type):
                ts = get_tradeable_score(event_type)
                print(f"     SKIP: {filing['symbol']} — {event_type} score {ts}/10 below threshold")
                continue

            is_liquid, daily_value = check_liquidity(filing["symbol"])
            if not is_liquid:
                print(f"     SKIP: {filing['symbol']} — Low liquidity Rs {daily_value/10000000:.1f}Cr < Rs 5Cr")
                continue

            pdf_url = filing.get("attchmntFile", "")
            pdf_data = download_and_parse_nse_pdf(pdf_url)
            pdf_summary = get_pdf_context_summary(pdf_data)
            print(f"     PDF: {pdf_summary[:100]}...")

            gap_result = calculate_expected_gap(event_type, pdf_data, market_mood)

            if abs(gap_result["expected_gap_pct"]) < 1.0:
                print(f"     SKIP: {filing['symbol']} — Gap {gap_result['expected_gap_pct']}% too small")
                continue

            prev_close = get_prev_close(filing["symbol"])
            save_to_queue(filing, clf, gap_result, prev_close)
            queued += 1
            print(f"     QUEUED: {filing['symbol']} — {event_type} | "
                  f"Gap: {gap_result['expected_gap_pct']}% | "
                  f"Confidence: {gap_result['confidence']}")

            if clf.get("is_material") and abs(gap_result["expected_gap_pct"]) >= 2.0:
                ts = get_tradeable_score(event_type)
                msg = (
                    f"\U0001f4cb <b>After Hours Filing Detected</b>\n"
                    f"\U0001f3e2 {filing['company']} ({filing['symbol']})\n"
                    f"\U0001f4ca {event_type}\n"
                    f"⭐ Score: {ts}/10\n"
                    f"\U0001f4c8 Expected Gap: {gap_result['expected_gap_pct']}%\n"
                    f"\U0001f3af Confidence: {gap_result['confidence']}"
                )
                send_message(BOT, TRADES_CHANNEL, msg)
                alerted += 1
                print(f"     Sent to Telegram!")

        except Exception as e:
            print(f"     Error: {e}")

    print(f"\n{'='*50}")
    print(f"  Done! {queued} queued, {alerted} alerted → Telegram")
    print(f"  Processed: {min(10, len(filings))} filings")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()

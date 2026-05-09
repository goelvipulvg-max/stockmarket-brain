import json, os, urllib.request, hashlib
from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI
from utils.supabase_client import get_client
from utils.telegram_client import send_message
from utils.tradeable_score import is_tradeable, get_tradeable_score
from utils.liquidity_check import check_liquidity
from utils.market_context import get_market_context
from utils.pdf_parser import download_and_parse_nse_pdf, get_pdf_context_summary

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
sb  = get_client()
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
TRADES_CHANNEL = os.getenv("TELEGRAM_TRADES_CHANNEL_ID")

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_duplicate(url: str) -> bool:
    h = url_hash(url)
    result = sb.table("filings_log").select("id").eq("url_hash", h).execute()
    return len(result.data) > 0

def fetch_nse_filings():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    }
    # First hit NSE homepage to get cookies
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
{{"event_type":"BOARD_MEETING|RESULTS|DIVIDEND|MERGER_ACQUISITION|INSIDER_TRADING|FUND_RAISE|MANAGEMENT_CHANGE|LEGAL|BONUS|SPLIT|BUYBACK|CONTRACT_WIN|OTHER","material_score":<1-10>,"summary":"<max 15 words>","is_material":<true if score>=6>}}"""

    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    return json.loads(text)

def save_to_supabase(filing, clf):
    sb.table("filings_log").insert({
        "symbol": str(filing.get("symbol","")),
        "company_name": filing.get("company",""),
        "exchange": filing.get("exchange","NSE"),
        "event_type": clf.get("event_type","OTHER"),
        "summary": clf.get("summary",""),
        "material_score": clf.get("material_score",0),
        "raw_title": filing.get("title",""),
        "source_url": filing.get("link",""),
        "url_hash": url_hash(filing.get("link", "")),
        "telegram_sent": clf.get("telegram_sent", False)
    }).execute()

def main():
    print("\n" + "="*50)
    print("  Tier-0 Filing Agent — NSE Mode")
    print("="*50)

    filings = fetch_nse_filings()
    if not filings:
        print("No filings fetched. Exiting.")
        return

    emoji_map = {
        "RESULTS":"📊","DIVIDEND":"💰","MERGER_ACQUISITION":"🤝",
        "BOARD_MEETING":"📋","FUND_RAISE":"💵","MANAGEMENT_CHANGE":"👤",
        "BONUS":"🎁","SPLIT":"✂️","BUYBACK":"🔄","CONTRACT_WIN":"🏆",
        "INSIDER_TRADING":"🔍","LEGAL":"⚖️","OTHER":"📌"
    }

    material_count = 0

    # Loop 2 — Market Context (pre-fetch once, applies to all filings)
    market_mood, size_multiplier, nifty_change, vix_value = get_market_context()
    print(f"  Market: {market_mood} | NIFTY {nifty_change:+.2f}% | VIX {vix_value:.1f} | Size: {size_multiplier}x")

    for i, filing in enumerate(filings[:10]):
        print(f"\n[{i+1}] {filing['title'][:60]}...")
        if is_duplicate(filing.get("link", "")):
            print(f"     ⏭️  Already processed — skipping")
            continue
        try:
            try:
                clf = classify_filing(filing)
            except (json.JSONDecodeError, ValueError):
                print(f"     ⚠️ AI classification failed — saving as seen to prevent retry")
                save_to_supabase(filing, {
                    "event_type": "OTHER",
                    "material_score": 0,
                    "summary": "Classification failed",
                    "is_material": False,
                })
                continue
            # Loop 5 — Tradeable Score Gate
            event_type = clf.get("event_type", "OTHER")
            if not is_tradeable(event_type):
                ts = get_tradeable_score(event_type)
                print(f"     SKIP: {filing['symbol']} — {event_type} score {ts}/10 below threshold")
                save_to_supabase(filing, clf)
                continue

            # Loop 6 — Liquidity Gate
            is_liquid, daily_value = check_liquidity(filing["symbol"])
            if not is_liquid:
                print(f"     SKIP: {filing['symbol']} — Low liquidity Rs {daily_value/10000000:.1f}Cr < Rs 5Cr")
                save_to_supabase(filing, clf)
                continue

            # Loop 2 — Market Context Gate
            if size_multiplier == 0.0:
                print(f"     SKIP: {filing['symbol']} — Market BEARISH (NIFTY down, VIX elevated), no trades today")
                save_to_supabase(filing, clf)
                continue

            # Loop 1 — PDF Parser
            pdf_url = filing.get("attchmntFile", "")
            pdf_data = download_and_parse_nse_pdf(pdf_url)
            pdf_summary = get_pdf_context_summary(pdf_data)
            if pdf_data["pdf_available"]:
                print(f"     PDF: {pdf_summary[:100]}...")
            else:
                print(f"     PDF: {pdf_summary}")

            score = clf.get("material_score", 0)
            print(f"     {clf['event_type']} | Score: {score}/10 | Material: {clf['is_material']}")
            if clf.get("is_material"):
                emoji = emoji_map.get(clf["event_type"], "📌")
                msg = (
                    f"{emoji} <b>{clf['event_type']}</b>\n"
                    f"🏢 {filing['company']} ({filing['symbol']})\n"
                    f"📝 {clf['summary']}\n"
                    f"⭐ Score: {score}/10\n"
                    f"📅 {filing['pubdate']}\n"
                    f"🔗 NSE Filing"
                )
                send_message(BOT, TRADES_CHANNEL, msg)
                clf["telegram_sent"] = True
                material_count += 1
                print(f"     ✅ Sent to Telegram!")
            save_to_supabase(filing, clf)
        except Exception as e:
            print(f"     ❌ Error: {e}")

    print(f"\n{'='*50}")
    print(f"  Done! {material_count} material filings → Telegram")
    print(f"  Processed: {min(10,len(filings))} filings")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()

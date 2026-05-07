import json, urllib.request
import anthropic
from utils.supabase_client import get_client
from utils.telegram_client import send_message

env = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

ai  = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
sb  = get_client()
BOT = env["TELEGRAM_BOT_TOKEN"]
MOVERS_CHANNEL = env["TELEGRAM_MOVERS_CHANNEL"]

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
                "exchange": "NSE"
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

    msg = ai.messages.create(
        model="claude-haiku-4-5",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().replace("```json","").replace("```","").strip()
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
    for i, filing in enumerate(filings[:10]):
        print(f"\n[{i+1}] {filing['title'][:60]}...")
        try:
            clf = classify_filing(filing)
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
                send_message(BOT, MOVERS_CHANNEL, msg)
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

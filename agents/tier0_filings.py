import json, os, urllib.request, hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI
from utils.supabase_client import get_client
from utils.telegram_client import send_message
from utils.tradeable_score import is_tradeable, get_tradeable_score
from utils.liquidity_check import check_liquidity
from utils.market_context import get_market_context
from utils.pdf_parser import download_and_parse_nse_pdf, get_pdf_context_summary
from utils.gap_calculator import calculate_expected_gap
import utils.questdb_client as questdb_client

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

def classify_filing(filing, pdf_summary=None):
    prompt = f"""Classify this NSE corporate filing for Indian retail investors.

Title: {filing['title']}
Company: {filing['company']}
Category: {filing['category']}"""

    if pdf_summary and pdf_summary != "PDF not available — using title only.":
        prompt += f"""

PARSED PDF DATA:
{pdf_summary}"""

    prompt += """

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

    for i, filing in enumerate(filings[:20]):
        print(f"\n[{i+1}] {filing['title'][:60]}...")
        if is_duplicate(filing.get("link", "")):
            print(f"     ⏭️  Already processed — skipping")
            continue
        try:
            # Loop 1 — PDF Parser (before classification so model sees PDF data)
            pdf_url = filing.get("attchmntFile", "")
            pdf_data = download_and_parse_nse_pdf(pdf_url)
            pdf_summary = get_pdf_context_summary(pdf_data)
            if pdf_data["pdf_available"]:
                print(f"     PDF: {pdf_summary[:100]}...")
            else:
                print(f"     PDF: {pdf_summary}")

            try:
                clf = classify_filing(filing, pdf_summary)
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

            # Loop 7 — Gap Calculator (after all gates pass)
            gap_data = None
            try:
                gap_data = calculate_expected_gap(event_type, pdf_data, market_mood)
                print(f"     Gap: {gap_data['expected_gap_pct']:+.2f}% | Confidence: {gap_data['confidence']}")
            except Exception as e:
                print(f"     ⚠️ Gap calc failed: {e} — continuing without trade setup")

            score = clf.get("material_score", 0)
            print(f"     {clf['event_type']} | Score: {score}/10 | Material: {clf['is_material']}")
            if clf.get("is_material"):
                emoji = emoji_map.get(clf["event_type"], "📌")
                msg = (
                    f"{emoji} <b>{clf['event_type']}</b>\n"
                    f"🏢 {filing['company']} ({filing['symbol']})\n"
                    f"📝 {clf['summary']}"
                )
                # PDF Details (Bug #5)
                pdf_lines = []
                if pdf_data.get("dividend_amount"):
                    dtype = pdf_data.get("dividend_type") or ""
                    pdf_lines.append(f"• Dividend: ₹{pdf_data['dividend_amount']}/share {dtype}")
                if pdf_data.get("quarter"):
                    pdf_lines.append(f"• Quarter: {pdf_data['quarter']}")
                if pdf_data.get("record_date"):
                    pdf_lines.append(f"• Record Date: {pdf_data['record_date']}")
                if pdf_data.get("pat"):
                    pdf_lines.append(f"• PAT: ₹{pdf_data['pat']} Cr")
                if pdf_lines:
                    msg += "\n\n📄 <b>PDF Details:</b>\n" + "\n".join(pdf_lines)
                # Trade Setup (Bug #4)
                if gap_data:
                    gap_lines = []
                    gap_lines.append(f"• Expected Gap: {gap_data['expected_gap_pct']:+.1f}%")
                    if gap_data.get('entry_low_pct') is not None and gap_data.get('entry_high_pct') is not None:
                        gap_lines.append(f"• Entry Zone: {gap_data['entry_low_pct']:+.1f}% to {gap_data['entry_high_pct']:+.1f}%")
                    if gap_data.get('target_pct') is not None:
                        gap_lines.append(f"• Target: {gap_data['target_pct']:+.1f}%")
                    if gap_data.get('stop_loss_pct') is not None:
                        gap_lines.append(f"• Stop Loss: {gap_data['stop_loss_pct']:+.1f}%")
                    target = gap_data.get('target_pct')
                    sl = gap_data.get('stop_loss_pct')
                    if target is not None and sl is not None and sl != 0 and target != 0:
                        if (target > 0 and sl < 0) or (target < 0 and sl > 0):
                            rr = abs(target / sl)
                            gap_lines.append(f"• Risk:Reward: 1:{rr:.1f}")
                    if gap_lines:
                        msg += "\n\n🎯 <b>Trade Setup:</b>\n" + "\n".join(gap_lines)
                # Score + Date + Link
                msg += (
                    f"\n\n⭐ Score: {score}/10\n"
                    f"📅 {filing['pubdate']}\n"
                    f"🔗 NSE Filing"
                )
                send_message(BOT, TRADES_CHANNEL, msg)
                clf["telegram_sent"] = True
                material_count += 1
                print(f"     ✅ Sent to Telegram!")
                # QuestDB parallel write (non-fatal)
                try:
                    sql = (
                        "INSERT INTO news_events "
                        "(ts, event_id, source, symbol, headline, url, sentiment, category, summary) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    )
                    row = (
                        datetime.now(timezone.utc),
                        url_hash(filing.get("link", "")),
                        "NSE_FILING",
                        filing.get("symbol", ""),
                        filing.get("title", ""),
                        filing.get("link", ""),
                        float(clf.get("material_score", 0)),
                        clf.get("event_type", "OTHER"),
                        clf.get("summary", ""),
                    )
                    questdb_client.executemany(sql, [row])
                    print(f"     📊 QuestDB: written")
                except Exception as e:
                    print(f"     ⚠️ QuestDB write failed: {e}")
            save_to_supabase(filing, clf)
        except Exception as e:
            print(f"     ❌ Error: {e}")

    print(f"\n{'='*50}")
    print(f"  Done! {material_count} material filings → Telegram")
    print(f"  Processed: {min(10,len(filings))} filings")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()

import json, os, time, urllib.request, hashlib
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
from utils.nse_dates import parse_nse_datetime
import utils.questdb_client as questdb_client
from utils.json_extract import extract_json

# Feature flag: switch dedup key between legacy (symbol-URL) and new
# composite (symbol|seq_id). Default false = legacy behavior preserved.
USE_NEW_DEDUP_KEY = os.getenv("USE_NEW_DEDUP_KEY", "false").lower() == "true"

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
sb  = get_client()
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
TRADES_CHANNEL = os.getenv("TELEGRAM_TRADES_CHANNEL_ID")

with open(os.path.join(os.path.dirname(__file__), "..", "prompts", "tier0_classify_v2.txt"), encoding="utf-8") as f:
    CLASSIFY_PROMPT_V2 = f.read()

VALID_EVENT_TYPES = {
    "RESULTS", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK", "MERGER_ACQUISITION",
    "ACQUISITION", "DIVESTMENT", "FUND_RAISE", "CONTRACT_WIN", "INSIDER_TRADING", "BULK_DEAL",
    "MANAGEMENT_CHANGE", "LEGAL", "CREDIT_RATING", "AUDIT_REPORT", "ALLOTMENT", "ESOP",
    "DISCLOSURE", "RATING_ACTION",
    "BOARD_MEETING", "AGM", "POSTAL_BALLOT", "INVESTOR_PRES", "ANNUAL_REPORT",
    "VOTING_RESULTS", "NEWSPAPER_PUB", "GENERAL_UPDATE", "OTHER"
}

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
            symbol = item.get("symbol", "")
            seq_id = item.get("seq_id", "")
            attch = (item.get("attchmntFile") or "").strip()

            # source_url with "-" placeholder fallback (Phase 2 Decision 2)
            if attch and attch != "-":
                source_url = attch
            else:
                source_url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"

            # Compute BOTH dedup keys for Gate B dry-run comparison
            dedup_key_new = f"{symbol}|{seq_id}"
            dedup_key_old = f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"

            # Feature flag selects active key (default false = legacy behavior)
            active_dedup_key = dedup_key_new if USE_NEW_DEDUP_KEY else dedup_key_old

            # Gate B observability: log both hashes for comparison analysis
            new_hash_short = hashlib.md5(dedup_key_new.encode()).hexdigest()[:8]
            old_hash_short = hashlib.md5(dedup_key_old.encode()).hexdigest()[:8]
            mode_tag = "NEW" if USE_NEW_DEDUP_KEY else "OLD"
            print(f"[GATE_B] sym={symbol:<14} seq={seq_id} new={new_hash_short} old={old_hash_short} mode={mode_tag}")

            filings.append({
                "title":        item.get("desc", ""),
                "company":      item.get("sm_name", ""),
                "symbol":       symbol,
                "category":     item.get("attchmntType", ""),
                "pubdate":      item.get("an_dt", ""),
                "link":         source_url,
                "dedup_key":    active_dedup_key,
                "exchange":     "NSE",
                "attchmntFile": item.get("attchmntFile", ""),
            })
        print(f"  Fetched {len(filings)} NSE filings")
        return filings
    except Exception as e:
        print(f"  NSE fetch error: {e}")
        return []

def classify_filing(filing, pdf_summary=None, max_retries=2):
    pdf_section = ""
    if pdf_summary and pdf_summary != "PDF not available — using title only.":
        pdf_section = f"\n\nPARSED PDF DATA:\n{pdf_summary}"

    prompt = CLASSIFY_PROMPT_V2.format(
        title=filing['title'],
        company=filing['company'],
        category=filing['category'],
        pdf_section=pdf_section,
    )

    for attempt in range(max_retries + 1):
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            max_tokens=400,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )
        raw_text = resp.choices[0].message.content.strip()
        if not raw_text:
            if attempt < max_retries:
                print(f"     [WARN] classify_filing attempt {attempt+1}: empty response, retrying...")
                time.sleep(2)
                continue
            raise ValueError("Empty response after retries")
        try:
            parsed = extract_json(raw_text)
            event_type = parsed.get("event_type", "OTHER")
            if event_type not in VALID_EVENT_TYPES:
                print(f"     [WARN] unknown event_type '{event_type}' coerced to OTHER")
                parsed["event_type"] = "OTHER"
            return parsed
        except (json.JSONDecodeError, ValueError) as e:
            if attempt < max_retries:
                print(f"     [WARN] classify_filing attempt {attempt+1}: JSON parse failed ({e}), retrying...")
                time.sleep(2)
                continue
            print(f"     [ERROR] classify_filing failed after {max_retries+1} attempts: {e}")
            raise

def save_to_supabase(filing, clf):
    try:
        sb.table("filings_log").insert({
            "symbol": str(filing.get("symbol","")),
            "company_name": filing.get("company",""),
            "exchange": filing.get("exchange","NSE"),
            "event_type": clf.get("event_type","OTHER"),
            "summary": clf.get("summary",""),
            "material_score": clf.get("material_score",0),
            "is_material": clf.get("is_material", False),
            "directional_bias": clf.get("directional_bias"),
            "reasoning": clf.get("reasoning"),
            "trade_confidence": clf.get("trade_confidence", 0),
            "raw_title": filing.get("title",""),
            "source_url": filing.get("link",""),
            "url_hash": url_hash(filing.get("dedup_key", "")),
            "published_at": parse_nse_datetime(filing.get("pubdate")),
            "telegram_sent": clf.get("telegram_sent", False)
        }).execute()
    except Exception as e:
        err = str(e)
        if "23505" in err or "duplicate key" in err.lower() or "url_hash" in err.lower():
            print(f"     ⏭️  Duplicate url_hash (23505) — skipping (benign race)")
            return
        raise

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
        if is_duplicate(filing.get("dedup_key", "")):
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
                    "trade_confidence": 0,
                    "directional_bias": None,
                    "reasoning": None,
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
                gap_data = calculate_expected_gap(event_type, market_mood)
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
                        url_hash(filing.get("dedup_key", "")),
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
    print(f"  Processed: {min(20,len(filings))} filings")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()

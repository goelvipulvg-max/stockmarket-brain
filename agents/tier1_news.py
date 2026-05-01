# agents/tier1_news.py
# Tier-1 News Researcher — StockMarket-Brain
# Scrapes 5 financial news sites via RSS → Haiku classify → Score 6+ → Telegram MOVERS

import os
import json
import hashlib
import feedparser
import requests
from datetime import datetime, timezone
from anthropic import Anthropic
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
import re
for k, v in os.environ.items():
    os.environ[k] = v.strip()

# ── Config ─────────────────────────────────────────────────────────────────────
SUPABASE_URL          = os.getenv("SUPABASE_URL")
SUPABASE_KEY          = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_MOVERS_CHAT  = os.getenv("TELEGRAM_MOVERS_CHANNEL")  # e.g. -100xxxxxxxxxx
SCORE_THRESHOLD       = 6

# ── Clients ────────────────────────────────────────────────────────────────────
client   = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── RSS Feeds ──────────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "ET Markets":         "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    "Moneycontrol":       "https://www.moneycontrol.com/rss/latestnews.xml",
    "LiveMint":           "https://www.livemint.com/rss/markets",
    "NDTV Profit":          "https://feeds.feedburner.com/ndtvprofit-latest",
    "Investing.com":        "https://in.investing.com/rss/news.rss",
    "Hindu BusinessLine": "https://www.thehindubusinessline.com/markets/?service=rss",
}

# ── Duplicate Filter ───────────────────────────────────────────────────────────
def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_duplicate(url: str) -> bool:
    h = url_hash(url)
    result = supabase.table("news_log").select("id").eq("url_hash", h).execute()
    return len(result.data) > 0

def log_article(source, url, title, score, category, summary):
    supabase.table("news_log").insert({
        "source":     source,
        "url":        url,
        "url_hash":   url_hash(url),
        "title":      title,
        "score":      score,
        "category":   category,
        "summary":    summary,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

# ── Haiku Classifier ───────────────────────────────────────────────────────────
CLASSIFY_PROMPT = """You are a stock market analyst. Rate this news headline's market impact.

Return ONLY valid JSON, no markdown, no extra text:
{{"score": <1-10>, "category": "<bullish|bearish|neutral>", "summary": "<max 20 words>"}}

Scoring guide:
- 8-10: Major mover (RBI rate change, index crash/rally, big earnings surprise, FII exodus)
- 6-7:  Significant (sector rally, policy update, FII activity, key company result)
- 4-5:  Moderate (minor result, sector update)
- 1-3:  Low impact (routine filing, generic news)

Headline: {headline}
Snippet: {snippet}"""

def classify(headline: str, snippet: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(
        headline=headline,
        snippet=snippet[:400] if snippet else "N/A"
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="You must respond with ONLY a valid JSON object. No preamble, no markdown, no code fences. Just raw JSON.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end+1]
    return json.loads(raw)

# ── Telegram Sender ────────────────────────────────────────────────────────────
EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}

def send_telegram(source, title, url, score, category, summary):
    emoji = EMOJI.get(category, "⚪")
    text = (
        f"{emoji} *{category.upper()}* | Score: {score}/10\n"
        f"*{title}*\n\n"
        f"_{summary}_\n\n"
        f"📰 {source}\n"
        f"🔗 [Read More]({url})"
    )
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id":                  TELEGRAM_MOVERS_CHAT,
            "text":                     text,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    if not r.ok:
        print(f"  ⚠️  Telegram error: {r.status_code} — {r.text[:100]}")

# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    print(f"\n{'='*52}")
    print(f"  Tier-1 News Researcher | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*52}")

    fetched = dupes = posted = errors = 0

    for source, feed_url in RSS_FEEDS.items():
        print(f"\n📡 {source}")
        try:
            entries = feedparser.parse(feed_url).entries[:10]
            print(f"   {len(entries)} articles fetched")
        except Exception as e:
            print(f"   ❌ Feed error: {e}")
            continue

        for entry in entries:
            url     = entry.get("link", "").strip()
            title   = entry.get("title", "").strip()
            snippet = entry.get("summary", "")

            if not url or not title:
                continue

            fetched += 1

            if is_duplicate(url):
                dupes += 1
                continue

            try:
                result   = classify(title, snippet)
                score    = int(result.get("score", 0))
                category = result.get("category", "neutral")
                summary  = result.get("summary", "")
            except Exception as e:
                print(f"   ⚠️  Classify error: {e}")
                errors += 1
                continue

            try:
                log_article(source, url, title, score, category, summary)
            except Exception as e:
                print(f"   ⚠️  Supabase error: {e}")

            if score >= SCORE_THRESHOLD:
                print(f"   ✅ [{score}/10] {category:<8} | {title[:55]}")
                try:
                    send_telegram(source, title, url, score, category, summary)
                    posted += 1
                except Exception as e:
                    print(f"   ⚠️  Telegram send error: {e}")
            else:
                print(f"   ⬇️  [{score}/10] {category:<8} | {title[:55]}")

    print(f"\n{'='*52}")
    print(f"  Fetched: {fetched} | Dupes: {dupes} | Posted: {posted} | Errors: {errors}")
    print(f"{'='*52}\n")

if __name__ == "__main__":
    run()


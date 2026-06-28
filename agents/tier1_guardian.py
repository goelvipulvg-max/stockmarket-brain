# agents/tier1_guardian.py
# Tier-1 Guardian — news/filing-based position protection layer
# Scans held positions, scores material news via DeepSeek (-10 to +10), fires EXIT/HOLD_STRONG alerts

import os, json, hashlib, re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI
from utils.supabase_client import get_client
from utils.neon_client import get_neon_connection
from utils.telegram_client import send_message
from utils.market_context import get_market_context
import utils.questdb_client as questdb_client
from psycopg2.extras import RealDictCursor

# ── Config ─────────────────────────────────────────────────────────────────────
LOOKBACK_HOURS        = 4
DEDUP_HOURS           = 4
EXIT_THRESHOLD        = -7
HOLD_STRONG_THRESHOLD = 7
MIN_SOURCES_REQUIRED  = 2
DEEPSEEK_MODEL        = "deepseek-v4-flash"
IST                   = ZoneInfo("Asia/Kolkata")

AUTO_REJECT_KEYWORDS = {
    "politics", "cricket", "weather", "gdp", "inflation", "election"
}
AUTO_ACCEPT_KEYWORDS = {
    "fraud", "raid", "fire", "accident", "arrest", "default", "scam",
    "shutdown", "resign", "loss", "explosion", "bankruptcy"
}

# Canonical NSE ticker → company name mapping for news_log title matching.
# news_log has no symbol column, so we match by company name in headline text.
# Extended over time as new positions are opened.
SYMBOL_NAME_MAP = {
    "RELIANCE":   "Reliance Industries",
    "TCS":        "Tata Consultancy",
    "HDFCBANK":   "HDFC Bank",
    "ICICIBANK":  "ICICI Bank",
    "INFY":       "Infosys",
    "SBIN":       "State Bank of India",
    "BAJFINANCE": "Bajaj Finance",
    "TATAMOTORS": "Tata Motors",
    "ITC":        "ITC",
    "LT":         "Larsen",
}

# ── Clients ────────────────────────────────────────────────────────────────────
deepseek = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
supabase = get_client()
GUARDIAN_CHANNEL = os.getenv("TELEGRAM_GUARDIAN_CHANNEL")
BOT_TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN")


def _utc_now():
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _ist_now():
    """Return current IST datetime."""
    return datetime.now(IST)


def _load_prompt():
    """Load Guardian system prompt from prompts/ directory."""
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prompts", "guardian_prompt.txt"
    )
    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


GUARDIAN_PROMPT = _load_prompt()


def _parse_ts(ts_val):
    """Parse ISO timestamp string to datetime, return None on failure."""
    if not ts_val:
        return None
    try:
        return datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _matches_symbol(symbol: str, title: str) -> bool:
    """Check if title contains canonical company name for symbol (word-boundary match)."""
    name = SYMBOL_NAME_MAP.get(symbol.upper())
    if not name:
        return False
    pattern = r'\b' + re.escape(name) + r'\b'
    return bool(re.search(pattern, title, re.IGNORECASE))


# ── Data Fetching ──────────────────────────────────────────────────────────────

def get_held_positions() -> list[str]:
    """Return unique symbols (without .NS suffix) from OPEN paper_trades."""
    try:
        trades = (
            supabase.table("paper_trades")
            .select("ticker").eq("status", "OPEN").execute().data
        )
    except Exception as e:
        print(f"  ⚠️ paper_trades fetch failed: {e}")
        return []
    symbols = []
    for t in (trades or []):
        sym = (t.get("ticker") or "").replace(".NS", "")
        if sym and sym not in symbols:
            symbols.append(sym)
    return symbols


def fetch_recent_news(symbol: str, hours: int) -> list[dict]:
    """Fetch news_log rows where title matches symbol via canonical name, within time window."""
    cutoff = _utc_now() - timedelta(hours=hours)
    try:
        rows = (
            supabase.table("news_log")
            .select("id,source,title,summary,score,category,fetched_at")
            .order("fetched_at", desc=True).limit(50).execute().data
        )
    except Exception:
        return []
    if symbol.upper() not in SYMBOL_NAME_MAP:
        return []  # no name mapping → can't match news_log by title
    filtered = []
    for r in (rows or []):
        title = r.get("title") or ""
        if not _matches_symbol(symbol, title):
            continue
        ts = _parse_ts(r.get("fetched_at"))
        if ts and ts < cutoff:
            continue
        filtered.append(r)
    return filtered


def fetch_recent_filings(symbol: str, hours: int) -> list[dict]:
    """Fetch filings_log rows for symbol within time window."""
    cutoff = _utc_now() - timedelta(hours=hours)
    try:
        rows = (
            supabase.table("filings_log")
            .select("id,symbol,event_type,summary,material_score,created_at")
            .eq("symbol", symbol.upper()).order("created_at", desc=True).limit(20)
            .execute().data
        )
    except Exception:
        return []
    filtered = []
    for r in (rows or []):
        ts = _parse_ts(r.get("created_at"))
        if ts and ts < cutoff:
            continue
        filtered.append(r)
    return filtered


# ── Keyword Filters ────────────────────────────────────────────────────────────

def apply_keyword_filters(items: list[dict]) -> list[dict]:
    """Drop items hitting AUTO_REJECT keywords, mark AUTO_ACCEPT items with boost=True."""
    result = []
    for item in items:
        text = " ".join([
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("headline", "")),
        ]).lower()
        if any(kw in text for kw in AUTO_REJECT_KEYWORDS):
            continue
        item["boost"] = any(kw in text for kw in AUTO_ACCEPT_KEYWORDS)
        result.append(item)
    return result


# ── Two-Source Gate ────────────────────────────────────────────────────────────

def two_source_gate(news: list[dict], filings: list[dict]) -> tuple:
    """Return (passes_gate, distinct_source_count)."""
    sources = set()
    for n in (news or []):
        src = n.get("source", "")
        if src:
            sources.add(src)
    if filings:
        sources.add("NSE_FILING")
    return len(sources) >= MIN_SOURCES_REQUIRED, len(sources)


# ── Company Context ────────────────────────────────────────────────────────────

def fetch_company_context(symbol: str) -> dict | None:
    """Pull business_summary and risk_factors from Neon company_profiles.

    company_profiles stores symbols WITH the .NS suffix (493/505), but held
    positions arrive .NS-stripped (get_held_positions); append .NS before the
    lookup or it always returns None (P2-11a). Mirrors neon_fundamentals.py.
    """
    try:
        conn = get_neon_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT business_summary, risk_factors FROM company_profiles WHERE symbol = %s",
                (f"{symbol.upper()}.NS",)
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return None
        risk = row.get("risk_factors")
        if isinstance(risk, (dict, list)):
            risk = json.dumps(risk, indent=2)
        return {"business_summary": row.get("business_summary") or "",
                "risk_factors": risk or ""}
    except Exception:
        return None


# ── DeepSeek Scoring ───────────────────────────────────────────────────────────

def score_via_deepseek(symbol, news, filings, company_context, market_mood) -> tuple:
    """Return (score: int -10 to +10, reasoning: str)."""
    ctx = company_context or {}
    news_text = "\n".join(
        f"- [{n.get('source','?')}] {n.get('title','')}: {n.get('summary','')}"
        + (" [HIGH-URGENCY]" if n.get("boost") else "")
        for n in (news or [])
    ) or "None"
    filings_text = "\n".join(
        f"- [{f.get('event_type','?')}] {f.get('summary','')} (score: {f.get('material_score',0)})"
        for f in (filings or [])
    ) or "None"
    boosted = [n for n in (news or []) if n.get("boost")]
    boost_note = (
        f"WARNING: {len(boosted)} item(s) matched HIGH-URGENCY keywords "
        "(fraud/raid/scam/bankruptcy etc). These MUST carry disproportionate weight."
    ) if boosted else ""
    prompt = GUARDIAN_PROMPT.format(
        symbol=symbol,
        business_summary=ctx.get("business_summary", "Not available"),
        risk_factors=ctx.get("risk_factors", "Not available"),
        market_mood=market_mood,
        news_count=len(news or []), news_text=news_text,
        filings_count=len(filings or []), filings_text=filings_text,
        boost_note=boost_note,
    )
    resp = deepseek.chat.completions.create(
        model=DEEPSEEK_MODEL, max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.choices[0].message.content.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    result = json.loads(text)
    score = max(-10, min(10, int(result.get("score", 0))))
    return score, result.get("reasoning", "No reasoning provided")


# ── Classification ─────────────────────────────────────────────────────────────

def classify_alert_type(score: int) -> str:
    """Return 'EXIT' if <= -7, 'HOLD_STRONG' if >= +7, else 'IGNORE'."""
    if score <= EXIT_THRESHOLD:
        return "EXIT"
    if score >= HOLD_STRONG_THRESHOLD:
        return "HOLD_STRONG"
    return "IGNORE"


# ── Dedup ──────────────────────────────────────────────────────────────────────

def is_duplicate_alert(symbol: str, alert_type: str, hours: int) -> bool:
    """Check tier1_guardian_alerts for same symbol + alert_type within window."""
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    try:
        conn = get_neon_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM tier1_guardian_alerts "
                "WHERE symbol = %s AND alert_type = %s AND ts >= %s::timestamptz",
                (symbol.upper(), alert_type, cutoff)
            )
            count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"     ⚠️ Dedup check failed: {e} — allowing alert")
        return False


# ── Logging ────────────────────────────────────────────────────────────────────

def log_to_neon(symbol, score, alert_type, status, headline, news_event_ids,
                reasoning, sources_count):
    """INSERT into tier1_guardian_alerts (10-column schema)."""
    try:
        conn = get_neon_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tier1_guardian_alerts "
                "(symbol, score, alert_type, status, headline, news_event_ids, reasoning, sources_count) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                (symbol.upper(), score, alert_type, status,
                 headline or "", json.dumps(news_event_ids or []),
                 reasoning or "", sources_count)
            )
        conn.close()
    except Exception as e:
        print(f"     ⚠️ Neon log failed: {e}")


def log_to_questdb(symbol, score, alert_type, headline):
    """Parallel write to news_events with source='GUARDIAN_ALERT'. Non-fatal."""
    try:
        event_id = hashlib.md5(
            f"guardian_{symbol}_{alert_type}_{_utc_now().isoformat()}".encode()
        ).hexdigest()
        row = (
            _utc_now(), event_id, "GUARDIAN_ALERT",
            symbol.upper(), headline or "", "",
            float(score), alert_type,
            f"Guardian {alert_type} for {symbol}",
        )
        questdb_client.executemany(
            "INSERT INTO news_events "
            "(ts, event_id, source, symbol, headline, url, sentiment, category, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [row]
        )
        print(f"     📊 QuestDB: written")
    except Exception as e:
        print(f"     ⚠️ QuestDB write failed: {e}")


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_guardian_telegram(symbol, score, alert_type, headline, sources_list, reasoning):
    """Send alert to GUARDIAN_CHANNEL. Returns True on success."""
    if not GUARDIAN_CHANNEL or alert_type == "IGNORE":
        return False
    emoji = "🚨" if alert_type == "EXIT" else "🛡️"
    text = (
        f"{emoji} <b>GUARDIAN ALERT — {alert_type}</b>\n"
        f"🏢 {symbol}\n"
        f"📊 Score: {score:+d}/10 (range: -10 to +10)\n"
        f"📰 Sources ({len(sources_list)}): {', '.join(sources_list)}\n"
        f"🔍 {reasoning}\n"
        f"⏰ {_ist_now().strftime('%d %b %Y, %I:%M %p IST')}"
    )
    try:
        send_message(BOT_TOKEN, GUARDIAN_CHANNEL, text)
        return True
    except Exception as e:
        print(f"     ⚠️ Telegram send failed: {e}")
        return False


# ── Per-Symbol Pipeline ────────────────────────────────────────────────────────

def process_position(symbol: str, market_mood: str) -> str | None:
    """Run full pipeline for one symbol. Returns alert_type if alert fired, else None."""
    print(f"\n🔍 [{symbol}] checking…")

    news    = fetch_recent_news(symbol, LOOKBACK_HOURS)
    filings = fetch_recent_filings(symbol, LOOKBACK_HOURS)
    print(f"     News: {len(news)}, Filings: {len(filings)}")

    if symbol.upper() not in SYMBOL_NAME_MAP:
        print(f"     ⚠️ No name mapping — news_log matching skipped, filings_log unaffected")

    news    = apply_keyword_filters(news)
    filings = apply_keyword_filters(filings)

    passes, sources_count = two_source_gate(news, filings)
    if not passes:
        print(f"     ⚠️ SKIP: {sources_count} source(s) < {MIN_SOURCES_REQUIRED}")
        return None
    print(f"     Sources: {sources_count}")

    company_ctx = fetch_company_context(symbol)

    try:
        score, reasoning = score_via_deepseek(
            symbol, news, filings, company_ctx, market_mood
        )
    except Exception as e:
        print(f"     ⚠️ DeepSeek failed: {e} — skipping")
        return None

    alert_type = classify_alert_type(score)
    print(f"     📊 Score: {score:+d} → {alert_type}")

    if alert_type == "IGNORE":
        return None

    if is_duplicate_alert(symbol, alert_type, DEDUP_HOURS):
        print(f"     ⚠️ SKIP: duplicate {alert_type} alert in last {DEDUP_HOURS}h")
        return "DUPLICATE"

    news_ids    = [n.get("id") for n in (news or []) if n.get("id")]
    filings_ids = [f.get("id") for f in (filings or []) if f.get("id")]
    all_ids     = news_ids + filings_ids

    headline = (
        (news[0].get("title") if news else None)
        or (filings[0].get("summary") if filings else None) or ""
    )

    sources_list = list(set(
        [n.get("source", "?") for n in (news or [])] + ["NSE_FILING"]
    ))

    telegram_ok = send_guardian_telegram(
        symbol, score, alert_type, headline, sources_list, reasoning
    )

    status = "SENT" if telegram_ok else "FAILED"
    log_to_neon(symbol, score, alert_type, status, headline, all_ids, reasoning, sources_count)
    log_to_questdb(symbol, score, alert_type, headline)

    print(f"     ✅ Alerted: {alert_type}")
    return alert_type


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    """Entry point — orchestrate over all held positions."""
    print("\n" + "=" * 52)
    print(f"  🛡️  Tier-1 Guardian | {_ist_now().strftime('%Y-%m-%d %H:%M IST')}")
    print("=" * 52)

    if not GUARDIAN_CHANNEL:
        print("⚠️ TELEGRAM_GUARDIAN_CHANNEL not set — Telegram alerts disabled, Neon log still active")

    try:
        market_mood, _, _, _ = get_market_context()
        print(f"  Market: {market_mood}")
    except Exception as e:
        print(f"  ⚠️ Market context failed: {e} — using NEUTRAL")
        market_mood = "NEUTRAL"

    symbols = get_held_positions()
    print(f"  Held positions: {len(symbols)} — {', '.join(symbols) if symbols else 'none'}")
    if not symbols:
        print("  No open positions. Exiting.")
        return

    alerts_fired, skipped_dupes = 0, 0
    for symbol in symbols:
        try:
            result = process_position(symbol, market_mood)
            if result == "DUPLICATE":
                skipped_dupes += 1
            elif result is not None:
                alerts_fired += 1
        except Exception as e:
            print(f"     ❌ Error processing {symbol}: {e}")

    print(f"\n{'=' * 52}")
    print(f"  ✅ Processed {len(symbols)} positions, fired {alerts_fired} alerts, "
          f"skipped {skipped_dupes} duplicates")
    print(f"{'=' * 52}\n")


if __name__ == "__main__":
    main()

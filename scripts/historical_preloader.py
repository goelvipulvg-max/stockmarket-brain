#!/usr/bin/env python
"""
Historical data preloader for StockMarket-Brain.
Downloads Nifty 500 list, fetches company profiles via yFinance,
generates AI summaries via DeepSeek, fetches NSE announcements,
computes price impact, and builds the pattern library in Neon DB.

Usage:
    .venv/Scripts/python.exe scripts/historical_preloader.py
"""

import csv
import json
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from io import StringIO

import requests
import yfinance as yf
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection

# ── Config ──────────────────────────────────────────────────────────
TEST_MODE = os.getenv("PRELOADER_TEST_MODE", "true").lower() == "true"
TEST_LIMIT = 10
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements"
TWO_YEARS_AGO = datetime.now() - timedelta(days=730)
BATCH_SLEEP = 1.0
ANNOUNCEMENT_SLEEP = 0.5
MAX_ANNOUNCEMENTS_PER_COMPANY = 50 if not TEST_MODE else 20

# ── Clients ─────────────────────────────────────────────────────────
deepseek = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=DEEPSEEK_BASE_URL,
)

_nse_session = None


def get_nse_session():
    global _nse_session
    if _nse_session is None:
        _nse_session = requests.Session()
        _nse_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com",
        })
        try:
            _nse_session.get("https://www.nseindia.com", timeout=15)
            time.sleep(0.5)
        except Exception:
            pass
    return _nse_session


# ── Step 1: Load Nifty 500 ──────────────────────────────────────────
def load_nifty500() -> list[dict]:
    """Download Nifty 500 CSV, return list of {symbol, yf_symbol, company_name}."""
    resp = requests.get(NIFTY500_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(StringIO(resp.text))
    companies = []
    for row in reader:
        sym = (row.get("Symbol") or row.get("symbol") or "").strip()
        name = (row.get("Company Name") or row.get("CompanyName") or "").strip()
        if sym and name:
            companies.append({
                "symbol": sym,
                "yf_symbol": f"{sym}.NS",
                "company_name": name,
            })
    return companies


# ── Step 2: Fetch yFinance profile ──────────────────────────────────
def fetch_yfinance_profile(yf_symbol: str) -> dict | None:
    """Return {sector, industry, longBusinessSummary, marketCap, website, fullTimeEmployees} or None."""
    try:
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info
        if not info or "longName" not in info and "shortName" not in info:
            return None
        return {
            "sector": info.get("sector") or info.get("industryDisp") or "",
            "industry": info.get("industry") or "",
            "longBusinessSummary": info.get("longBusinessSummary") or "",
            "marketCap": info.get("marketCap"),
            "website": info.get("website") or "",
            "fullTimeEmployees": info.get("fullTimeEmployees"),
        }
    except Exception:
        return None


# ── Step 3: DeepSeek profile summary ────────────────────────────────
def generate_profile_summary(company_name: str, symbol: str, profile: dict) -> str:
    """Call DeepSeek to generate a 3-sentence investment profile summary."""
    prompt = (
        f"You are a financial analyst. Given this company data for {company_name} ({symbol}), "
        f"write a 3-sentence investment profile summary covering: what the company does, "
        f"its sector position, and key financial characteristic. "
        f"Data: sector={profile['sector']}, industry={profile['industry']}, "
        f"summary={profile['longBusinessSummary'][:500]}. "
        f"Be concise and factual."
    )
    try:
        resp = deepseek.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"    DeepSeek profile summary failed: {e}")
        return "Summary unavailable"


# ── Step 4: Fetch 2-year price history ──────────────────────────────
def fetch_price_history(yf_symbol: str) -> list[dict] | None:
    """Return list of {date, open, high, low, close, volume} dicts for 2 years."""
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="2y")
        if df.empty:
            return None
        df = df.reset_index()
        rows = []
        for _, row in df.iterrows():
            dt = row["Date"]
            if hasattr(dt, "to_pydatetime"):
                dt = dt.to_pydatetime()
            rows.append({
                "date": dt,
                "close": float(row["Close"]),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "volume": int(row["Volume"]),
            })
        return rows
    except Exception:
        return None


# ── Step 5: NSE Announcements ───────────────────────────────────────
def fetch_nse_announcements(nse_symbol: str) -> list[dict]:
    """Fetch corporate announcements from NSE for the given symbol."""
    session = get_nse_session()
    params = {"index": "equities", "symbol": nse_symbol}
    for attempt in range(2):
        try:
            resp = session.get(NSE_ANNOUNCEMENTS_API, params=params, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for key in ("data", "announcements", "corporateAnnouncements"):
                        if key in data:
                            return data[key]
                    return []
                return []
            elif resp.status_code in (403, 429):
                print(f"    NSE API {resp.status_code}, waiting 10s (attempt {attempt+1})")
                time.sleep(10)
            else:
                print(f"    NSE API returned {resp.status_code}")
                return []
        except Exception as e:
            print(f"    NSE API error: {e}")
            if attempt == 0:
                time.sleep(5)
    return []


def parse_nse_date(date_str: str) -> date | None:
    """Parse various NSE date formats."""
    s = date_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",    # sort_date: 2026-05-07 14:59:20
        "%Y-%m-%d",             # ISO date
        "%d-%b-%Y %H:%M:%S",    # an_dt: 07-May-2026 14:59:20
        "%d-%b-%Y",             # 07-May-2026
        "%d-%b-%y",             # 07-May-26
        "%d/%m/%Y",             # 07/05/2026
        "%b %d, %Y",            # May 07, 2026
        "%d %b %Y",             # 07 May 2026
        "%B %d, %Y",            # May 07, 2026
        "%d%m%Y%H%M%S",        # compact dt: 07052026145920
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def classify_event_type(subject: str) -> str:
    """Classify NSE announcement into event type bucket."""
    s = subject.lower()
    if "dividend" in s or "interim dividend" in s:
        return "dividend"
    if "bonus" in s and "issue" in s:
        return "bonus"
    if "split" in s or "sub-division" in s or "face value" in s:
        return "split"
    if "buyback" in s or "buy back" in s or "buy-back" in s:
        return "buyback"
    if any(w in s for w in ("merger", "amalgamation", "scheme of arrangement", "composite scheme")):
        return "merger"
    if any(w in s for w in ("results", "quarterly", "financial results", "audited results", "unaudited results")):
        return "results"
    return "other"


def summarize_announcement(subject: str, desc: str) -> str:
    """Call DeepSeek to summarize an NSE announcement."""
    text = (desc or subject or "")[:800]
    prompt = (
        f"Summarize this NSE corporate announcement in 2 sentences: {text}. "
        f"Identify: event type, key numbers (if any), and likely market sentiment "
        f"(positive/negative/neutral)."
    )
    try:
        resp = deepseek.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Summary unavailable: {e}"


def compute_price_impact(history: list[dict], ann_date: date) -> dict | None:
    """
    Find ann_date (or next trading day) in history, compute % change
    to close 5 trading days later. Returns {price_impact_pct, days_to_impact} or None.
    """
    if not history:
        return None
    dates = sorted(history, key=lambda r: r["date"])
    idx = None
    for i, row in enumerate(dates):
        row_d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        if row_d >= ann_date:
            idx = i
            break
    if idx is None:
        return None
    future_idx = min(idx + 5, len(dates) - 1)
    if future_idx <= idx:
        return None
    start_close = dates[idx]["close"]
    end_close = dates[future_idx]["close"]
    if start_close == 0:
        return None
    pct = ((end_close - start_close) / start_close) * 100
    actual_days = (dates[future_idx]["date"] - dates[idx]["date"]).days
    if isinstance(actual_days, float):
        actual_days = int(actual_days)
    return {"price_impact_pct": round(pct, 2), "days_to_impact": actual_days}


# ── Neon INSERT helpers ─────────────────────────────────────────────
def insert_company_profile(conn, symbol: str, company_name: str, profile: dict, summary: str):
    cur = conn.cursor()
    key_metrics = json.dumps({
        "market_cap": profile.get("marketCap"),
        "website": profile.get("website"),
        "employees": profile.get("fullTimeEmployees"),
    })
    cur.execute("""
        INSERT INTO company_profiles (symbol, company_name, sector, industry,
            business_summary, key_metrics, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector = EXCLUDED.sector,
            industry = EXCLUDED.industry,
            business_summary = EXCLUDED.business_summary,
            key_metrics = EXCLUDED.key_metrics,
            updated_at = NOW()
    """, (symbol, company_name, profile["sector"], profile["industry"], summary, key_metrics))
    cur.close()


def insert_research_cache(conn, symbol: str, content_type: str, summary: str,
                          source_date: str, raw_metadata: dict | None = None):
    cur = conn.cursor()
    context = json.dumps({"source_date": source_date, "raw": raw_metadata or {}})
    cur.execute("""
        INSERT INTO research_cache (symbol, query_hash, query_text, response_text, created_at)
        VALUES (%s, %s, %s, %s, NOW())
    """, (symbol, content_type, context, summary))
    cur.close()


def insert_event_outcome(conn, symbol: str, event_type: str, event_date,
                         description: str, price_impact_pct, days_to_impact):
    cur = conn.cursor()
    ed = event_date
    if isinstance(ed, date) and not isinstance(ed, datetime):
        ed = ed
    elif hasattr(ed, "date"):
        ed = ed.date()
    desc = f"{description} | Days to impact: {days_to_impact}" if days_to_impact else description
    cur.execute("""
        INSERT INTO event_outcomes (symbol, event_type, event_date, signal_generated,
            trade_result, outcome_score, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (symbol, event_type, ed, True, desc[:500], price_impact_pct))
    cur.close()


def build_pattern_library(conn):
    """Group event_outcomes by (sector, event_type), write patterns for groups with sample_size >= 3."""
    cur = conn.cursor()

    cur.execute("""
        SELECT cp.sector, eo.event_type,
               COUNT(*) AS n,
               AVG(eo.outcome_score) AS avg_impact
        FROM event_outcomes eo
        JOIN company_profiles cp ON cp.symbol = eo.symbol
        WHERE cp.sector IS NOT NULL AND cp.sector != ''
          AND eo.outcome_score IS NOT NULL
        GROUP BY cp.sector, eo.event_type
        HAVING COUNT(*) >= 3
    """)
    rows = cur.fetchall()

    inserted = 0
    for sector, event_type, n, avg_impact in rows:
        confidence = min(n / 20.0, 1.0)
        pattern_name = f"{sector}_{event_type}"
        pattern_data = json.dumps({
            "description": f"Average {event_type} impact in {sector} sector based on {n} events",
            "avg_impact_pct": round(float(avg_impact), 2),
            "sector": sector,
        })
        cur.execute("""
            INSERT INTO pattern_library (symbol, pattern_name, pattern_data,
                success_rate, sample_size, created_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, NOW())
        """, (None, pattern_name, pattern_data, round(confidence, 2), n))
        inserted += 1

    cur.close()
    return inserted


# ── Main ────────────────────────────────────────────────────────────
def main():
    start_time = datetime.now()
    print("=" * 60)
    print("StockMarket-Brain Historical Preloader")
    print(f"Started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"TEST_MODE = {TEST_MODE}")
    print("=" * 60)

    # ── Load Nifty 500 ──
    print("\n[1/6] Loading Nifty 500 list...")
    companies = load_nifty500()
    print(f"  Loaded {len(companies)} companies")

    if TEST_MODE:
        companies = companies[:TEST_LIMIT]
        print(f"  TEST_MODE: limiting to first {len(companies)} companies")

    # ── Process companies ──
    conn = get_neon_connection()

    counts = {
        "profiles": 0,
        "research_cache": 0,
        "event_outcomes": 0,
        "patterns": 0,
    }
    failures = []

    total = len(companies)
    print(f"\n[2/6] Processing {total} companies...")

    for i, co in enumerate(companies, 1):
        sym = co["symbol"]
        yf_sym = co["yf_symbol"]
        name = co["company_name"]
        print(f"\n  Processing {i}/{total}: {name} ({sym})")

        try:
            # Step 2: yFinance profile
            profile = fetch_yfinance_profile(yf_sym)
            if profile is None:
                print(f"    Skipping: no yFinance data")
                failures.append(f"{sym}: no yFinance data")
                continue

            # Step 3: DeepSeek profile summary
            print(f"    Generating profile summary...")
            summary = generate_profile_summary(name, sym, profile)
            insert_company_profile(conn, sym, name, profile, summary)
            counts["profiles"] += 1
            time.sleep(BATCH_SLEEP)

            # Step 4: Fetch price history
            history = fetch_price_history(yf_sym)

            # Step 5: NSE announcements
            nse_announcements = fetch_nse_announcements(sym)
            if nse_announcements:
                print(f"    Found {len(nse_announcements)} NSE announcements")
                ann_processed = 0
                for ann in nse_announcements:
                    try:
                        desc = ann.get("desc") or ann.get("attchmntText") or ""
                        long_desc = ann.get("attchmntText") or ann.get("desc") or ""
                        ann_date_str = ann.get("sort_date") or ann.get("an_dt") or ann.get("dt") or ""
                        ann_date = parse_nse_date(ann_date_str)

                        if ann_date is None:
                            continue

                        # Filter to last 2 years
                        if ann_date < TWO_YEARS_AGO.date():
                            continue

                        # Limit per company
                        if ann_processed >= MAX_ANNOUNCEMENTS_PER_COMPANY:
                            break

                        event_type = classify_event_type(desc)
                        ann_summary = summarize_announcement(desc, long_desc)

                        # Store summary in research_cache
                        insert_research_cache(conn, sym, "announcement_summary",
                                              ann_summary, str(ann_date), ann)
                        counts["research_cache"] += 1

                        # Compute price impact for trigger events
                        if event_type in ("dividend", "bonus", "split", "buyback") and history:
                            impact = compute_price_impact(history, ann_date)
                            if impact:
                                insert_event_outcome(conn, sym, event_type, ann_date,
                                                     ann_summary,
                                                     impact["price_impact_pct"],
                                                     impact["days_to_impact"])
                                counts["event_outcomes"] += 1

                        ann_processed += 1
                        time.sleep(ANNOUNCEMENT_SLEEP)

                    except Exception as e:
                        print(f"    Announcement error: {e}")

                print(f"    Processed {ann_processed} announcements (2y window)")
            else:
                print(f"    No NSE announcements found")

        except Exception as e:
            print(f"    FAILED: {e}")
            traceback.print_exc()
            failures.append(f"{sym}: {e}")

        # Progress pause between companies (not after last)
        if i < total:
            time.sleep(0.5)

    # ── Step 6: Build pattern_library ──
    print(f"\n[3/6] Building pattern library...")
    pattern_count = build_pattern_library(conn)
    counts["patterns"] = pattern_count
    print(f"  Created {pattern_count} sector-level patterns")

    conn.close()

    # ── Summary ──
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"  company_profiles  : {counts['profiles']} inserted")
    print(f"  research_cache    : {counts['research_cache']} inserted")
    print(f"  event_outcomes    : {counts['event_outcomes']} inserted")
    print(f"  pattern_library   : {counts['patterns']} inserted")
    print(f"  after_hours_queue : 0 (left empty for live triggers)")
    print(f"  Elapsed           : {elapsed:.0f}s")
    if failures:
        print(f"  Failed ({len(failures)}): {failures[:10]}{'...' if len(failures) > 10 else ''}")
    else:
        print(f"  Failed            : 0")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

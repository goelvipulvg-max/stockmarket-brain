#!/usr/bin/env python
"""
Single-batch historical preloader — processes one company range.
All INSERTs are UPSERTs. 30s timeout on every external API call.
Resume check: skips companies already in company_profiles + research_cache.

Usage:
    .venv/Scripts/python.exe scripts/preloader_single_batch.py --start 0 --end 25
"""

import argparse
import csv
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta
from io import StringIO

import requests
import yfinance as yf
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection, query as neon_query

# ── Config ──────────────────────────────────────────────────────────
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements"
TWO_YEARS_AGO = datetime.now() - timedelta(days=730)
API_TIMEOUT = 30
BATCH_SLEEP = 1.0
ANNOUNCEMENT_SLEEP = 0.5
MAX_ANNOUNCEMENTS_PER_COMPANY = 190

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


def with_timeout(seconds, func, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=seconds)
        except FutureTimeout:
            return None
        except Exception:
            return None


# ── Step 1: Load Nifty 500 ──────────────────────────────────────────
def load_nifty500() -> list[dict]:
    resp = requests.get(NIFTY500_CSV_URL, timeout=API_TIMEOUT)
    resp.raise_for_status()
    reader = csv.DictReader(StringIO(resp.text))
    companies = []
    for row in reader:
        sym = (row.get("Symbol") or row.get("symbol") or "").strip()
        name = (row.get("Company Name") or row.get("CompanyName") or "").strip()
        if sym and name:
            ns_sym = sym if sym.endswith(".NS") else f"{sym}.NS"
            companies.append({
                "symbol": ns_sym,
                "yf_symbol": ns_sym,
                "company_name": name,
            })
    return companies


# ── Resume check ────────────────────────────────────────────────────
def is_company_processed(conn, symbol: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM company_profiles WHERE symbol = %s AND business_summary IS NOT NULL", (symbol,))
        has_profile = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM research_cache WHERE symbol = %s LIMIT 1", (symbol,))
        has_research = cur.fetchone() is not None
        cur.close()
        return has_profile and has_research
    except Exception:
        return False


# ── Step 2: Fetch yFinance profile ──────────────────────────────────
def fetch_yfinance_profile(yf_symbol: str) -> dict | None:
    try:
        ticker = yf.Ticker(yf_symbol)
        info = with_timeout(API_TIMEOUT, lambda: ticker.info)
        if info is None or (isinstance(info, dict) and "longName" not in info and "shortName" not in info):
            return None
        if not isinstance(info, dict):
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
    prompt = (
        f"You are a financial analyst. Given this company data for {company_name} ({symbol}), "
        f"write a 3-sentence investment profile summary covering: what the company does, "
        f"its sector position, and key financial characteristic. "
        f"Data: sector={profile['sector']}, industry={profile['industry']}, "
        f"summary={profile['longBusinessSummary'][:500]}. "
        f"Be concise and factual."
    )
    for attempt in range(2):
        try:
            resp = deepseek.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
                timeout=API_TIMEOUT,
            )
            text = resp.choices[0].message.content.strip()
            if text:
                return text
            if attempt == 0:
                print(f"    DeepSeek returned empty, retrying...")
                time.sleep(2)
        except Exception as e:
            print(f"    DeepSeek profile summary failed: {e}")
            if attempt == 1:
                break
            time.sleep(2)

    # Fallback: use truncated yFinance summary
    fallback = (profile.get("longBusinessSummary") or "").strip()
    if fallback:
        print(f"    Using yFinance fallback summary ({len(fallback)} chars)")
        return fallback[:1000]
    print(f"    No summary available")
    return "Summary unavailable"


# ── Step 4: Fetch price history ─────────────────────────────────────
def fetch_price_history(yf_symbol: str) -> list[dict] | None:
    try:
        ticker = yf.Ticker(yf_symbol)
        df = with_timeout(API_TIMEOUT, ticker.history, period="2y")
        if df is None or df.empty:
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
    session = get_nse_session()
    params = {"index": "equities", "symbol": nse_symbol}
    for attempt in range(2):
        try:
            resp = session.get(NSE_ANNOUNCEMENTS_API, params=params, timeout=API_TIMEOUT)
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
    s = date_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%d%m%Y%H%M%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def classify_event_type(subject: str) -> str:
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
            timeout=API_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Summary unavailable: {e}"


def compute_price_impact(history: list[dict], ann_date: date) -> dict | None:
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


# ── UPSERT helpers ──────────────────────────────────────────────────
def upsert_company_profile(conn, symbol: str, company_name: str, profile: dict, summary: str):
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


def upsert_research_cache(conn, symbol: str, content_type: str, summary: str,
                          source_date: str, raw_metadata: dict | None = None):
    cur = conn.cursor()
    context = json.dumps({"source_date": source_date, "raw": raw_metadata or {}})
    cur.execute("""
        INSERT INTO research_cache (symbol, query_hash, query_text, response_text, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING
    """, (symbol, content_type, context, summary))
    cur.close()


def upsert_event_outcome(conn, symbol: str, event_type: str, event_date,
                         description: str, price_impact_pct, days_to_impact):
    cur = conn.cursor()
    ed = event_date
    if isinstance(ed, datetime):
        ed = ed.date()
    desc = f"{description} | Days to impact: {days_to_impact}" if days_to_impact else description
    cur.execute("""
        INSERT INTO event_outcomes (symbol, event_type, event_date, signal_generated,
            trade_result, outcome_score, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING
    """, (symbol, event_type, ed, True, desc[:500], price_impact_pct))
    cur.close()


# ── Pattern library ─────────────────────────────────────────────────
def build_pattern_library(conn):
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
        # Delete existing then insert (no unique constraint on pattern_name)
        cur.execute("DELETE FROM pattern_library WHERE pattern_name = %s", (pattern_name,))
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
    parser = argparse.ArgumentParser(description="Preload a batch of Nifty 500 companies")
    parser.add_argument("--start", type=int, required=True, help="Start index (0-based)")
    parser.add_argument("--end", type=int, required=True, help="End index (exclusive)")
    args = parser.parse_args()

    batch_id = f"batch_{args.start}_{args.end}"
    print(f"\n{'='*60}")
    print(f"  Preloader Batch [{args.start}:{args.end}]")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    companies = load_nifty500()
    batch = companies[args.start:args.end]
    total = len(batch)
    print(f"  Batch size: {total} companies (of {len(companies)} total)")

    conn = get_neon_connection()

    counts = {"profiles": 0, "research_cache": 0, "event_outcomes": 0, "skipped": 0, "failed": 0}
    failures = []

    for i, co in enumerate(batch, 1):
        sym = co["symbol"]
        yf_sym = co["yf_symbol"]
        name = co["company_name"]
        print(f"\n  Processing {i}/{total}: {name} ({sym})")

        try:
            if is_company_processed(conn, sym):
                print(f"    SKIP: already in company_profiles + research_cache")
                counts["skipped"] += 1
                continue

            profile = fetch_yfinance_profile(yf_sym)
            if profile is None:
                print(f"    FAIL: no yFinance data")
                counts["failed"] += 1
                failures.append(f"{sym}: no yFinance data")
                continue

            print(f"    Generating profile summary...")
            summary = generate_profile_summary(name, sym, profile)
            upsert_company_profile(conn, sym, name, profile, summary)
            counts["profiles"] += 1
            time.sleep(BATCH_SLEEP)

            history = fetch_price_history(yf_sym)

            nse_symbol = sym.replace(".NS", "")  # NSE API expects bare symbol
            nse_announcements = fetch_nse_announcements(nse_symbol)
            if nse_announcements:
                print(f"    Found {len(nse_announcements)} NSE announcements")
                ann_processed = 0
                conn_errors = 0
                for ann in nse_announcements:
                    if conn_errors >= 3:
                        print(f"    Too many connection errors, skipping remaining announcements")
                        break
                    try:
                        desc = ann.get("desc") or ann.get("attchmntText") or ""
                        long_desc = ann.get("attchmntText") or ann.get("desc") or ""
                        ann_date_str = ann.get("sort_date") or ann.get("an_dt") or ann.get("dt") or ""
                        ann_date = parse_nse_date(ann_date_str)
                        if ann_date is None:
                            continue
                        if ann_date < TWO_YEARS_AGO.date():
                            continue
                        if ann_processed >= MAX_ANNOUNCEMENTS_PER_COMPANY:
                            break
                        event_type = classify_event_type(desc)
                        ann_summary = summarize_announcement(desc, long_desc)
                        upsert_research_cache(conn, sym, "announcement_summary",
                                              ann_summary, str(ann_date), ann)
                        counts["research_cache"] += 1
                        if event_type in ("dividend", "bonus", "split", "buyback") and history:
                            impact = compute_price_impact(history, ann_date)
                            if impact:
                                upsert_event_outcome(conn, sym, event_type, ann_date,
                                                     ann_summary,
                                                     impact["price_impact_pct"],
                                                     impact["days_to_impact"])
                                counts["event_outcomes"] += 1
                        ann_processed += 1
                        time.sleep(ANNOUNCEMENT_SLEEP)
                    except Exception as e:
                        msg = str(e).lower()
                        if "connection already closed" in msg or "server closed" in msg:
                            conn_errors += 1
                            print(f"    Neon connection lost, reconnecting (error {conn_errors}/3)...")
                            try:
                                conn.close()
                            except Exception:
                                pass
                            time.sleep(1)
                            conn = get_neon_connection()
                        else:
                            print(f"    Announcement error: {e}")
                print(f"    Processed {ann_processed} announcements (2y window)")
            else:
                print(f"    No NSE announcements found")

        except Exception as e:
            print(f"    FAILED: {e}")
            traceback.print_exc()
            counts["failed"] += 1
            failures.append(f"{sym}: {e}")

        if i < total:
            time.sleep(0.5)

    # Build pattern_library at end of batch
    print(f"\n  Building pattern library...")
    try:
        pattern_count = build_pattern_library(conn)
        print(f"  Created {pattern_count} sector-level patterns")
    except Exception as e:
        print(f"  Pattern library error: {e}")
        pattern_count = 0

    conn.close()

    print(f"\n{'='*60}")
    print(f"  BATCH [{args.start}:{args.end}] COMPLETE")
    print(f"  Profiles: {counts['profiles']} | Research: {counts['research_cache']}")
    print(f"  Outcomes: {counts['event_outcomes']} | Skipped: {counts['skipped']} | Failed: {counts['failed']}")
    print(f"  Patterns: {pattern_count}")
    if failures:
        print(f"  Failures ({len(failures)}): {failures[:5]}{'...' if len(failures) > 5 else ''}")
    print(f"{'='*60}\n")

    if counts["failed"] > (total * 0.5):
        sys.exit(1)


if __name__ == "__main__":
    main()

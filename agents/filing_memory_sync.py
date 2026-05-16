"""Phase 0.7 — filing_memory_sync: live sync of material filings_log rows into filing_memory.

Runs on a 10-min cron during NSE market hours. Queries filings_log for rows
classified in the last 20 minutes (material_score >= 6, event_type != OTHER),
looks up sector from Neon company_profiles, and inserts into filing_memory.
url_hash UNIQUE constraint provides idempotency on re-runs.
"""
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.supabase_client import get_client
from utils.neon_client import get_neon_connection

WINDOW_MINUTES = 20


def lookup_sector(symbol: str) -> str | None:
    """Look up a stock's sector from Neon company_profiles (symbols stored with .NS suffix)."""
    try:
        conn = get_neon_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sector FROM company_profiles WHERE symbol = %s LIMIT 1",
                (f"{symbol}.NS",)
            )
            row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        return None
    except Exception as e:
        print(f"  [WARN] sector lookup failed for {symbol}: {e}")
        return None


def sync_to_filing_memory():
    sb = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)).isoformat()

    rows = sb.table("filings_log").select("*")\
        .gte("material_score", 6)\
        .neq("event_type", "OTHER")\
        .gte("classified_at", cutoff)\
        .not_.is_("url_hash", "null")\
        .execute()

    if not rows.data:
        print("  No material filings in window.")
        return 0

    print(f"  Found {len(rows.data)} material filings in last {WINDOW_MINUTES}min")
    inserted = 0
    skipped_dup = 0

    for filing in rows.data:
        url_hash_val = filing.get("url_hash")
        if not url_hash_val:
            print(f"  [WARN] {filing.get('symbol','?')}: NULL url_hash — skipping")
            continue

        classified_at = filing.get("classified_at")
        filing_date = None
        filing_timestamp = None
        if classified_at:
            try:
                dt = datetime.fromisoformat(classified_at.replace("Z", "+00:00"))
                filing_date = dt.date().isoformat()
                filing_timestamp = dt.isoformat()
            except (ValueError, AttributeError):
                pass

        sector_val = lookup_sector(filing.get("symbol", ""))

        insert_data = {
            "url_hash": url_hash_val,
            "symbol_base": filing.get("symbol", ""),
            "company_name": filing.get("company_name"),
            "sector": sector_val,
            "event_type": filing.get("event_type", "OTHER"),
            "material_score": filing.get("material_score", 0),
            "filing_date": filing_date,
            "filing_timestamp": filing_timestamp,
            "raw_title": filing.get("raw_title"),
            "ai_summary": filing.get("summary"),
        }

        try:
            sb.table("filing_memory").insert(insert_data).execute()
            inserted += 1
            print(f"  + {filing.get('symbol','?')}: {filing.get('event_type','?')} "
                  f"score={filing.get('material_score','?')} sector={sector_val}")
        except Exception as e:
            err_str = str(e)
            if "23505" in err_str:
                skipped_dup += 1
                continue
            print(f"  [WARN] insert failed for {filing.get('symbol','?')}: {e}")

    print(f"  Done: {inserted} inserted, {skipped_dup} duplicates skipped")
    return inserted


if __name__ == "__main__":
    print("filing_memory_sync")
    sync_to_filing_memory()

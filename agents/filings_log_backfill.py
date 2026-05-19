"""Phase 4 Batch A — filings_log -> filing_memory one-time backfill.

Backfills material filings_log rows into filing_memory (§3.10 NOTE 1).
Safe to re-run — upsert on url_hash, 0 duplicates on subsequent runs.
"""

from datetime import datetime

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import get_neon_connection
from utils.supabase_client import get_client


def backfill_filings_log():
    sb = get_client()

    # Read material candidates from filings_log
    candidates = sb.table("filings_log").select("*") \
        .gte("material_score", 6) \
        .neq("event_type", "OTHER") \
        .execute()

    if not candidates.data:
        print("No material candidates found in filings_log.")
        return

    print(f"Candidates read: {len(candidates.data)}")

    # Sector lookup — one query, build dict
    conn = get_neon_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol, sector FROM company_profiles")
            sector_map = {}
            for sym, sec in cur.fetchall():
                bare = sym.replace(".NS", "")
                sector_map[bare] = sec
    finally:
        conn.close()

    insert_rows = []
    skipped_null_hash = 0

    for filing in candidates.data:
        url_hash_val = filing.get("url_hash")
        if not url_hash_val:
            skipped_null_hash += 1
            print(f"  [WARN] NULL url_hash for {filing.get('symbol','?')} "
                  f"({filing.get('event_type','?')}) — skipping")
            continue

        symbol_base = filing.get("symbol", "")
        sector = sector_map.get(symbol_base)

        # filing_timestamp from classified_at
        classified_at = filing.get("classified_at")
        filing_timestamp = None
        filing_date = None
        if classified_at:
            try:
                dt = datetime.fromisoformat(classified_at.replace("Z", "+00:00"))
                filing_timestamp = dt.isoformat()
                filing_date = dt.date().isoformat()
            except (ValueError, AttributeError):
                pass

        insert_rows.append({
            "url_hash": url_hash_val,
            "symbol_base": symbol_base,
            "company_name": filing.get("company_name"),
            "sector": sector,
            "event_type": filing.get("event_type", "OTHER"),
            "material_score": filing.get("material_score", 0),
            "filing_date": filing_date,
            "filing_timestamp": filing_timestamp,
            "raw_title": filing.get("raw_title"),
            "ai_summary": filing.get("summary"),
            "pdf_extract": None,
        })

    if not insert_rows:
        print("No rows to insert after skipping NULL url_hash.")
        print(f"  Candidates: {len(candidates.data)}")
        print(f"  Skipped NULL url_hash: {skipped_null_hash}")
        return

    # Upsert with on_conflict='url_hash' — re-run inserts 0 duplicates
    result = sb.table("filing_memory").upsert(insert_rows, on_conflict="url_hash").execute()

    print(f"\nBackfill summary:")
    print(f"  Candidates read:        {len(candidates.data)}")
    print(f"  Skipped NULL url_hash:  {skipped_null_hash}")
    print(f"  Upserted:               {len(insert_rows)}")
    print(f"  (duplicates handled by url_hash ON CONFLICT)")


if __name__ == "__main__":
    backfill_filings_log()

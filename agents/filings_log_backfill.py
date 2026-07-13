"""Phase 4 Batch A — filings_log -> filing_memory one-time backfill.

Backfills material filings_log rows into filing_memory (§3.10 NOTE 1).
Safe to re-run — upsert on url_hash, 0 duplicates on subsequent runs.
"""

from datetime import datetime

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import get_neon_connection
from utils.supabase_client import get_client

PAGE_SIZE = 1000    # PostgREST max-rows cap; each .range() window stays at/below it
INSERT_BATCH = 500


def _fetch_all_candidates(sb) -> list[dict]:
    """All material candidates, paginated in stable id order (F-1 fix).

    The old single .execute() silently capped at the PostgREST 1000-row window
    in heap order, so late rows were never swept.
    """
    rows, start = [], 0
    while True:
        page = sb.table("filings_log").select("*") \
            .gte("material_score", 6) \
            .neq("event_type", "OTHER") \
            .order("id", desc=False) \
            .range(start, start + PAGE_SIZE - 1) \
            .execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _fetch_existing_hashes(sb) -> set[str]:
    """Every url_hash already in filing_memory, paginated (also >1000 rows now)."""
    hashes, start = set(), 0
    while True:
        page = sb.table("filing_memory").select("url_hash") \
            .order("url_hash", desc=False) \
            .range(start, start + PAGE_SIZE - 1) \
            .execute().data or []
        hashes.update(r["url_hash"] for r in page if r.get("url_hash"))
        if len(page) < PAGE_SIZE:
            return hashes
        start += PAGE_SIZE


def backfill_filings_log():
    sb = get_client()

    # F-1: paginated read of material candidates + the already-synced hash set
    candidate_rows = _fetch_all_candidates(sb)
    existing_hashes = _fetch_existing_hashes(sb)

    if not candidate_rows:
        print("No material candidates found in filings_log.")
        return

    print(f"Candidates read: {len(candidate_rows)}")
    print(f"Existing filing_memory hashes: {len(existing_hashes)}")

    # Sector lookup — one query, build dict. Fail-open like filing_memory_sync:
    # a Neon outage must not kill the sweep; new rows just get sector NULL
    # (existing rows are never rewritten, so nothing gets clobbered).
    sector_map = {}
    try:
        conn = get_neon_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol, sector FROM company_profiles")
                for sym, sec in cur.fetchall():
                    bare = sym.replace(".NS", "")
                    sector_map[bare] = sec
        finally:
            conn.close()
    except Exception as e:
        print(f"  [WARN] Neon connection failed: {e} -- sector will be NULL this run")

    insert_rows = []
    skipped_null_hash = 0
    already_present = 0

    for filing in candidate_rows:
        url_hash_val = filing.get("url_hash")
        if not url_hash_val:
            skipped_null_hash += 1
            print(f"  [WARN] NULL url_hash for {filing.get('symbol','?')} "
                  f"({filing.get('event_type','?')}) — skipping")
            continue
        if url_hash_val in existing_hashes:
            already_present += 1
            continue  # never rewrite existing rows (protects sync-written sector etc.)

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
            # pdf_extract intentionally omitted: column reserved for the future
            # PDF pipeline; including it here would clobber populated values on
            # upsert re-runs.
        })

    if not insert_rows:
        print("Nothing to insert -- filing_memory already covers all candidates.")
        print(f"  Candidates: {len(candidate_rows)}")
        print(f"  Already present: {already_present}")
        print(f"  Skipped NULL url_hash: {skipped_null_hash}")
        return

    # Insert ONLY missing rows, in batches; ignore_duplicates=True renders the
    # conflict path DO NOTHING (never clobbers existing filing_memory columns).
    for i in range(0, len(insert_rows), INSERT_BATCH):
        batch = insert_rows[i:i + INSERT_BATCH]
        sb.table("filing_memory").upsert(
            batch, on_conflict="url_hash", ignore_duplicates=True
        ).execute()
        print(f"  batch {i // INSERT_BATCH + 1}: {len(batch)} rows")

    print(f"\nBackfill summary:")
    print(f"  Candidates read:        {len(candidate_rows)}")
    print(f"  Already present:        {already_present}")
    print(f"  Skipped NULL url_hash:  {skipped_null_hash}")
    print(f"  Inserted (new):         {len(insert_rows)}")


if __name__ == "__main__":
    backfill_filings_log()

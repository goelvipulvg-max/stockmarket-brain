"""Phase 4 Batch A — Memory Seeding: event_outcomes -> trade_memory_v2.

One-time idempotent seed. Safe to re-run — skips if already seeded.
"""

from decimal import Decimal

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import query, get_neon_connection
from utils.supabase_client import get_client

BATCH_SIZE = 100


def _json_safe(v):
    """Make any value JSON-serializable for JSONB insert."""
    if isinstance(v, Decimal):
        return float(v)
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def seed_memory_from_event_outcomes():
    sb = get_client()

    # Idempotency guard
    existing = sb.table("trade_memory_v2").select("id", count="exact") \
        .eq("source_type", "SEED_EVENT_OUTCOME").limit(1).execute()
    if existing.count and existing.count > 0:
        print(f"[SKIP] seeding already done ({existing.count} rows in trade_memory_v2)")
        return

    # Read all event_outcomes from Neon
    rows = query("SELECT * FROM event_outcomes")
    print(f"Read {len(rows)} rows from event_outcomes")

    # Sector lookup — one query, build dict for O(1) per-row access
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

    print(f"Sector map: {len(sector_map)} symbols loaded")

    insert_rows = []
    outcome_counts = {"TARGET_HIT": 0, "SL_HIT": 0, "EXPIRED": 0}
    sector_hits = 0
    warn_count = 0
    seen = {}
    dup_count = 0

    for row in rows:
        symbol = row["symbol"].replace(".NS", "")
        event_type = row["event_type"]
        outcome_score_raw = row["outcome_score"]
        trade_result_raw = row["trade_result"]

        # Dedup by (symbol, event_type, event_date) — keep first occurrence
        evt_date = str(row["event_date"])
        key = (symbol, event_type, evt_date)
        if key in seen:
            dup_count += 1
            prev_score = seen[key]
            if str(prev_score) != str(outcome_score_raw):
                print(f"  [WARN] duplicate {key} with differing score: "
                      f"{prev_score!r} vs {outcome_score_raw!r} — keeping first")
            continue
        seen[key] = outcome_score_raw

        # Outcome from outcome_score (text -> float, +/-3% rule per brief SC0)
        outcome = "EXPIRED"
        try:
            score = float(outcome_score_raw)
            if score > 3.0:
                outcome = "TARGET_HIT"
            elif score < -3.0:
                outcome = "SL_HIT"
        except (ValueError, TypeError):
            warn_count += 1
            print(f"  [WARN] unparseable outcome_score for {symbol}: {outcome_score_raw!r}")

        outcome_counts[outcome] += 1

        # Sector lookup
        sector = sector_map.get(symbol)
        if sector:
            sector_hits += 1
        sector_key = (sector or "unknown").replace(" ", "_").lower()

        insert_rows.append({
            "source_type": "SEED_EVENT_OUTCOME",
            "symbol_base": symbol,
            "event_type": event_type,
            "sector": sector,
            "outcome": outcome,
            "pattern_tags": [
                f"event_{event_type.lower()}",
                f"sector_{sector_key}",
                "source_seed",
            ],
            "full_context": {
                "outcome_score_raw": _json_safe(outcome_score_raw),
                "trade_result_raw": _json_safe(trade_result_raw),
                "event_date": str(row["event_date"]),
                "signal_generated": _json_safe(row["signal_generated"]),
            },
        })

    # Batch insert
    total_inserted = 0
    for i in range(0, len(insert_rows), BATCH_SIZE):
        batch = insert_rows[i:i + BATCH_SIZE]
        sb.table("trade_memory_v2").insert(batch).execute()
        total_inserted += len(batch)
        print(f"  Inserted {total_inserted}/{len(insert_rows)}...")

    print(f"\nTotal read:     {len(rows)}")
    print(f"Total inserted: {total_inserted}")
    print(f"Duplicates skipped: {dup_count}")
    print(f"Sector matched: {sector_hits}/{len(insert_rows)}")
    print(f"Unparseable:    {warn_count}")
    print(f"Outcomes: TARGET_HIT={outcome_counts['TARGET_HIT']}, "
          f"SL_HIT={outcome_counts['SL_HIT']}, EXPIRED={outcome_counts['EXPIRED']}")


def extract_initial_patterns():
    """Group seed rows by (sector, event_type) and upsert into pattern_insights."""
    sb = get_client()

    rows = sb.table("trade_memory_v2").select("*") \
        .eq("source_type", "SEED_EVENT_OUTCOME").execute()

    if not rows.data:
        print("No seed rows found — run seeding first.")
        return

    groups = {}
    for r in rows.data:
        sector = r.get("sector") or "unknown"
        sector_key = sector.replace(" ", "_").lower()
        event_type = r.get("event_type", "other").lower()
        gkey = (sector_key, event_type)
        if gkey not in groups:
            groups[gkey] = []
        groups[gkey].append(r)

    upsert_rows = []
    total_groups = len(groups)
    passed = 0
    skipped_small = 0

    for (sector_key, event_type), members in groups.items():
        n = len(members)
        if n < 5:
            skipped_small += 1
            continue

        target_hits = sum(1 for r in members if r.get("outcome") == "TARGET_HIT")
        win_rate = round(target_hits / n, 3)

        scores = []
        for r in members:
            ctx = r.get("full_context") or {}
            raw = ctx.get("outcome_score_raw")
            if raw is not None:
                try:
                    scores.append(float(raw))
                except (ValueError, TypeError):
                    pass
        avg_outcome_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        if n >= 20:
            confidence = "HIGH"
        elif n >= 10:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        pattern_key = f"{sector_key}_{event_type}"
        display_sector = sector_key.replace("_", " ").title()

        insight_text = (
            f"{event_type} events in {display_sector}: "
            f"{n} samples, {win_rate*100:.1f}% positive, "
            f"avg score {avg_outcome_score:+.2f}"
        )

        upsert_rows.append({
            "pattern_key": pattern_key,
            "sector": sector_key,
            "event_type": event_type,
            "sample_size": n,
            "win_rate": win_rate,
            "avg_outcome_score": avg_outcome_score,
            "confidence": confidence,
            "insight_text": insight_text,
            "active": True,
        })
        passed += 1

    if upsert_rows:
        # Full recompute each run — clear then insert
        sb.table("pattern_insights").delete().neq("id", 0).execute()
        sb.table("pattern_insights").insert(upsert_rows).execute()

    print(f"\nPattern extraction:")
    print(f"  Total groups:   {total_groups}")
    print(f"  Passed (n>=5):  {passed}")
    print(f"  Skipped (<5):   {skipped_small}")
    print(f"  Upserted:       {len(upsert_rows)}")


if __name__ == "__main__":
    seed_memory_from_event_outcomes()
    extract_initial_patterns()

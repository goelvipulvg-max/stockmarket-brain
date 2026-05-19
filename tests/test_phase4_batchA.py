"""
Phase 4 -- Batch A Verification Gates (V4.1, V4.1b, V4.2, V4.3).
Tests trade_memory_v2 seeding, filing_memory backfill, pattern_insights.
"""
import sys
sys.path.insert(0, "C:/dev/stockmarket-brain")
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.supabase_client import get_client
sb = get_client()

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}")
        FAIL += 1


# ============================================================
# V4.1 -- trade_memory_v2 has SEED_EVENT_OUTCOME rows
# ============================================================
print("\n-- V4.1: trade_memory_v2 seeding --")
result = sb.table("trade_memory_v2").select("id", count="exact") \
    .eq("source_type", "SEED_EVENT_OUTCOME").execute()
count = result.count if result.count else 0
check(f"SEED_EVENT_OUTCOME rows > 500 (got {count})", count > 500)

# Outcome distribution sanity
if count > 0:
    thr = sb.table("trade_memory_v2").select("id", count="exact") \
        .eq("source_type", "SEED_EVENT_OUTCOME").eq("outcome", "TARGET_HIT").execute()
    slh = sb.table("trade_memory_v2").select("id", count="exact") \
        .eq("source_type", "SEED_EVENT_OUTCOME").eq("outcome", "SL_HIT").execute()
    exp = sb.table("trade_memory_v2").select("id", count="exact") \
        .eq("source_type", "SEED_EVENT_OUTCOME").eq("outcome", "EXPIRED").execute()
    t = thr.count if thr.count else 0
    s = slh.count if slh.count else 0
    e = exp.count if exp.count else 0
    check(f"outcome buckets non-degenerate (TARGET_HIT={t}, SL_HIT={s}, EXPIRED={e})",
          t > 0 and s > 0 and e > 0)


# ============================================================
# V4.1b -- filing_memory has backfilled rows
# ============================================================
print("\n-- V4.1b: filing_memory backfill --")
fm = sb.table("filing_memory").select("id", count="exact").execute()
fm_count = fm.count if fm.count else 0
check(f"filing_memory has backfilled rows (got {fm_count})", fm_count > 0)

# Check for NULL url_hash (should be 0 -- the backfill skipped them)
null_hash = sb.table("filing_memory").select("id", count="exact") \
    .is_("url_hash", "null").execute()
nh = null_hash.count if null_hash.count else 0
check(f"filing_memory has zero NULL url_hash rows (got {nh})", nh == 0)


# ============================================================
# V4.2 -- pattern_insights has active, valid-confidence rows
# ============================================================
print("\n-- V4.2: pattern_insights --")
pi = sb.table("pattern_insights").select("id", count="exact") \
    .eq("active", True).execute()
pi_count = pi.count if pi.count else 0
check(f"pattern_insights active rows > 0 (got {pi_count})", pi_count > 0)

if pi_count > 0:
    valid = sb.table("pattern_insights").select("id", count="exact") \
        .eq("active", True).in_("confidence", ["HIGH", "MEDIUM", "LOW"]).execute()
    vc = valid.count if valid.count else 0
    check(f"all active rows have valid confidence (HIGH/MEDIUM/LOW): {vc}/{pi_count}",
          vc == pi_count)


# ============================================================
# V4.3 -- dividend patterns return at least one row
# ============================================================
print("\n-- V4.3: pattern retrieval --")
div = sb.table("pattern_insights").select("*") \
    .eq("event_type", "dividend").eq("active", True).execute()
div_count = len(div.data)
check(f"'dividend' patterns found (got {div_count})", div_count > 0)

if div_count > 0:
    sample = div.data[0]
    check("sample has pattern_key", bool(sample.get("pattern_key")))
    check("sample has win_rate >= 0", sample.get("win_rate") is not None
          and sample.get("win_rate", 0) >= 0)
    check("sample has confidence in HIGH/MEDIUM/LOW",
          sample.get("confidence") in ("HIGH", "MEDIUM", "LOW"))


# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
print(f"Phase 4 Batch A: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
if FAIL == 0:
    print("ALL GATES PASS -- Batch A checkpoint clear")
else:
    print(f"SOME GATES FAILED ({FAIL} failures)")
    sys.exit(1)
print(f"{'='*50}")

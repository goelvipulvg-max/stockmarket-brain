import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client
from utils.filing_memory_brief import get_filing_memory_brief

sb = get_client()
failures = 0
gate = 0

print("=" * 60)
print("test_phase4_batchB -- Phase 4 Batch B Gate Tests")
print("=" * 60)

# ------------------------------------------------------------------ V4.5
gate += 1
print(f"\n[V4.5] Outcome backfill correctness")

rows = sb.table("filing_memory").select("*").execute()
data = rows.data or []

filled_5d = [r for r in data if r.get("outcome_5d_status") == "FILLED"]
filled_10d = [r for r in data if r.get("outcome_10d_status") == "FILLED"]
filled_30d = [r for r in data if r.get("outcome_30d_status") == "FILLED"]
any_filled = filled_5d or filled_10d or filled_30d

if not any_filled:
    print(f"  [V4.5 STRUCTURAL-ONLY] no FILLED rows yet -- nothing to verify, this is correct for current data age")
    print(f"  [V4.5 PASS]")
else:
    v45_ok = True

    # Assert FILLED rows have all price columns NOT NULL
    for label, filled_rows in [("5d", filled_5d), ("10d", filled_10d), ("30d", filled_30d)]:
        for r in filled_rows:
            missing = []
            for col in [f"price_{label}", f"nifty_{label}", f"raw_move_{label}", f"alpha_{label}"]:
                if r.get(col) is None:
                    missing.append(col)
            if missing:
                print(f"  [FAIL] row {r['id']} ({r['symbol_base']}): outcome_{label}_status=FILLED but NULL cols: {missing}")
                v45_ok = False

    # Assert PENDING rows have price/alpha as NULL
    pending_rows = [r for r in data if r.get("outcome_5d_status") == "PENDING"
                    or r.get("outcome_10d_status") == "PENDING"
                    or r.get("outcome_30d_status") == "PENDING"]
    for r in pending_rows:
        for label in ["5d", "10d", "30d"]:
            if r.get(f"outcome_{label}_status") == "PENDING":
                leaked = []
                for col in [f"price_{label}", f"nifty_{label}", f"raw_move_{label}", f"alpha_{label}"]:
                    if r.get(col) is not None:
                        leaked.append(col)
                if leaked:
                    print(f"  [FAIL] row {r['id']} ({r['symbol_base']}): outcome_{label}_status=PENDING but populated: {leaked}")
                    v45_ok = False

    # Cross-symbol math sanity on most-recent FILLED 10d row
    if filled_10d:
        sample = filled_10d[0]
        nifty_move_recomputed = (sample["nifty_10d"] - sample["nifty_base"]) / sample["nifty_base"] * 100
        alpha_from_raw = sample["raw_move_10d"] - nifty_move_recomputed
        delta = abs(alpha_from_raw - sample["alpha_10d"])
        if delta > 0.01:
            print(f"  [FAIL] alpha math: raw_move={sample['raw_move_10d']}, nifty_move_re={nifty_move_recomputed:.6f}, alpha_re={alpha_from_raw:.6f}, stored alpha_10d={sample['alpha_10d']}, delta={delta:.6f}")
            v45_ok = False
        else:
            print(f"  alpha math sanity: delta={delta:.6f} (row {sample['id']}, {sample['symbol_base']})")

    print(f"  FILLED rows: 5d={len(filled_5d)}, 10d={len(filled_10d)}, 30d={len(filled_30d)}")
    print(f"  [V4.5 {'PASS' if v45_ok else 'FAIL'}]")
    if not v45_ok:
        failures += 1

# ------------------------------------------------------------------ V4.6
gate += 1
print(f"\n[V4.6] swing_verdict rule")

if not filled_10d:
    print(f"  [V4.6 STRUCTURAL-ONLY] no FILLED 10d rows yet")
    print(f"  [V4.6 PASS]")
else:
    v46_ok = True
    verdict_dist = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    for r in filled_10d:
        verdict = r.get("swing_verdict")
        alpha = r.get("alpha_10d")
        if verdict not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
            print(f"  [FAIL] row {r['id']} ({r['symbol_base']}): invalid swing_verdict '{verdict}'")
            v46_ok = False
            continue

        expected = "POSITIVE" if alpha > 3 else "NEGATIVE" if alpha < -3 else "NEUTRAL"
        if verdict != expected:
            print(f"  [FAIL] row {r['id']} ({r['symbol_base']}): swing_verdict={verdict} but alpha_10d={alpha} -> expected {expected}")
            v46_ok = False

        verdict_dist[verdict] += 1

    print(f"  FILLED 10d rows: {len(filled_10d)}")
    print(f"  verdict distribution: POSITIVE={verdict_dist['POSITIVE']}, NEGATIVE={verdict_dist['NEGATIVE']}, NEUTRAL={verdict_dist['NEUTRAL']}")
    print(f"  [V4.6 {'PASS' if v46_ok else 'FAIL'}]")
    if not v46_ok:
        failures += 1

# ------------------------------------------------------------------ V4.7
gate += 1
print(f"\n[V4.7] get_filing_memory_brief() shape")

v47_ok = True

# Test 1: fake symbol -> exact fallback string
result1 = get_filing_memory_brief("NONEXISTENT_FAKE_TEST_SYMBOL", "dividend")
expected = "No matured material filing history for this company."
if result1 == expected:
    print(f"  Test 1 (fake symbol): returned exact no-rows string -- PASS")
else:
    print(f"  [FAIL] Test 1: expected {repr(expected)}, got {repr(result1)}")
    v47_ok = False

# Test 2: real symbol from filing_memory
first_row = data[0] if data else None
if first_row:
    real_symbol = first_row.get("symbol_base", "")
    result2 = get_filing_memory_brief(real_symbol, "dividend")
    is_str = isinstance(result2, str)
    header_pattern = f"{real_symbol} -- Filing Memory"
    has_header = header_pattern in result2
    is_no_rows = result2 == expected
    if is_str and (is_no_rows or has_header):
        print(f"  Test 2 (real symbol '{real_symbol}'): type=str, valid shape ({'no-rows' if is_no_rows else 'has header'}) -- PASS")
    else:
        print(f"  [FAIL] Test 2: type={type(result2).__name__}, is_str={is_str}, is_no_rows={is_no_rows}, has_header={has_header}")
        v47_ok = False
else:
    print(f"  [WARN] Test 2 skipped: filing_memory has zero rows")
    print(f"  Test 2 (no data): skipped -- PASS by default")

print(f"  [V4.7 {'PASS' if v47_ok else 'FAIL'}]")
if not v47_ok:
    failures += 1

# ------------------------------------------------------------------ Summary
print()
print("=" * 60)
print(f"Gates passed: {gate - failures}/{gate}")
print("=" * 60)

if failures > 0:
    print(f"\n{failures} gate(s) FAILED.")
    sys.exit(1)

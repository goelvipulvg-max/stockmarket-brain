"""
Phase 3 — Batch B Verification Gates (V3.2, B2, B3).
Tests filing_history, tiered_target_generator, ai_consensus.determine_consensus.
"""
import sys
sys.path.insert(0, "C:/dev/stockmarket-brain")
from dotenv import load_dotenv
load_dotenv(override=True)

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
# V3.2 — filing_history: Neon research_cache read + to_brief
# ============================================================
print("\n-- V3.2: filing_history.get_filing_history('RELIANCE') --")
from utils.filing_history import get_filing_history, to_brief

try:
    history = get_filing_history("RELIANCE")
    check("RELIANCE returns non-empty list", isinstance(history, list) and len(history) > 0)

    if history:
        required_keys = {"symbol", "filing_date", "event_desc", "summary", "created_at"}
        all_keys_ok = all(required_keys.issubset(h.keys()) for h in history)
        check("every dict has all 5 keys (symbol/filing_date/event_desc/summary/created_at)",
              all_keys_ok)

        filing_dates = [h["filing_date"] for h in history]
        check("results newest-first (full list non-increasing)",
              all(filing_dates[i] >= filing_dates[i+1]
                  for i in range(len(filing_dates) - 1)))

        brief = to_brief(history)
        check("to_brief returns non-empty string", isinstance(brief, str) and len(brief) > 0)
        check("to_brief contains 'RELIANCE'", "RELIANCE" in brief)
        print(f"  Got {len(history)} filings, range {filing_dates[-1]} to {filing_dates[0]}")

    empty = get_filing_history("NOTAREALSYMBOLXYZ")
    check("unknown symbol returns []", isinstance(empty, list) and len(empty) == 0)
    check("to_brief([]) == 'No filing history available for this company.'",
          to_brief([]) == "No filing history available for this company.")

except Exception as e:
    check(f"V3.2 live Neon read succeeded (not raised {type(e).__name__}: {e})", False)


# ============================================================
# B2 smoke — tiered_target_generator: pure arithmetic
# ============================================================
print("\n-- B2 smoke: tiered_target_generator.generate_targets --")
from utils.tiered_target_generator import generate_targets

# BUY/HIGH
b = generate_targets(100, "BUY", "HIGH")
check("BUY/HIGH: 5 keys present (t1/t2/t3/t4/stop_loss)",
      set(b.keys()) == {"t1", "t2", "t3", "t4", "stop_loss"})
check("BUY/HIGH: t1 < t2 < t3 < t4", b["t1"] < b["t2"] < b["t3"] < b["t4"])
check("BUY/HIGH: all targets > 100", all(b[k] > 100 for k in ["t1", "t2", "t3", "t4"]))
check("BUY/HIGH: stop_loss < 100", b["stop_loss"] < 100)
print(f"  BUY/HIGH: t1={b['t1']} t2={b['t2']} t3={b['t3']} t4={b['t4']} sl={b['stop_loss']}")

# SELL/HIGH
s = generate_targets(100, "SELL", "HIGH")
check("SELL/HIGH: t1 > t2 > t3", s["t1"] > s["t2"] > s["t3"])
check("SELL/HIGH: all targets < 100", all(s[k] < 100 for k in ["t1", "t2", "t3", "t4"]))
check("SELL/HIGH: stop_loss > 100", s["stop_loss"] > 100)
print(f"  SELL/HIGH: t1={s['t1']} t2={s['t2']} t3={s['t3']} t4={s['t4']} sl={s['stop_loss']}")

# T4 visibility
m = generate_targets(100, "BUY", "MEDIUM")
check("BUY/MEDIUM: t4 is None", m["t4"] is None)
low = generate_targets(100, "BUY", "LOW")
check("BUY/LOW: t4 is None", low["t4"] is None)

# ValueError guards
for label, args in [
    ("entry_price=0 raises ValueError", (0, "BUY", "HIGH")),
    ("direction='HOLD' raises ValueError", (100, "HOLD", "HIGH")),
    ("conviction='MAYBE' raises ValueError", (100, "BUY", "MAYBE")),
]:
    try:
        generate_targets(*args)
        check(label, False)
    except ValueError:
        check(label, True)


# ============================================================
# B3 smoke — ai_consensus.determine_consensus (no live API)
# ============================================================
print("\n-- B3 smoke: ai_consensus.determine_consensus (5 branches + _safe_conf) --")
from utils.ai_consensus import determine_consensus

# 1. Not tradeable
haiku_nt = {"tradeable": False, "directional_bias": "BULLISH", "confidence": 80}
flash_nt = {"verdict": "CONFIRM", "agreement_score": 90, "my_directional_bias": "BULLISH", "my_confidence": 85}
d, r = determine_consensus(haiku_nt, flash_nt)
check("not tradeable -> SKIP", d == "SKIP")
check("not tradeable reason contains 'not tradeable'", "not tradeable" in r)

# 2. Verifier CHALLENGE + low agreement
haiku_c = {"tradeable": True, "directional_bias": "BULLISH", "confidence": 80}
flash_ch = {"verdict": "CHALLENGE", "agreement_score": 40, "my_directional_bias": "BULLISH", "my_confidence": 50}
d, r = determine_consensus(haiku_c, flash_ch)
check("CHALLENGE + agreement<70 -> SKIP", d == "SKIP")
check("reason contains 'challenged'", "challenged" in r.lower())

# 3. Direction mismatch
haiku_bull = {"tradeable": True, "directional_bias": "BULLISH", "confidence": 80}
flash_bear = {"verdict": "CONFIRM", "agreement_score": 80, "my_directional_bias": "BEARISH", "my_confidence": 75}
d, r = determine_consensus(haiku_bull, flash_bear)
check("direction mismatch -> SKIP", d == "SKIP")
check("reason contains 'Direction mismatch'", "Direction mismatch" in r)

# 4. Low confidence
haiku_lc = {"tradeable": True, "directional_bias": "BULLISH", "confidence": 50}
flash_lc = {"verdict": "CONFIRM", "agreement_score": 80, "my_directional_bias": "BULLISH", "my_confidence": 40}
d, r = determine_consensus(haiku_lc, flash_lc)
check("avg conf 45 < 65 -> SKIP", d == "SKIP")
check("reason contains 'Avg confidence 45.0'", "Avg confidence 45.0" in r)

# 5. Full agreement
haiku_ok = {"tradeable": True, "directional_bias": "BULLISH", "confidence": 80}
flash_ok = {"verdict": "CONFIRM", "agreement_score": 90, "my_directional_bias": "BULLISH", "my_confidence": 75}
d, r = determine_consensus(haiku_ok, flash_ok)
check("full agreement -> PROCEED", d == "PROCEED")
check("reason = 'Consensus reached'", r == "Consensus reached")

# 6. _safe_conf guard — confidence=None
haiku_null = {"tradeable": True, "directional_bias": "BULLISH", "confidence": None}
flash_norm = {"verdict": "CONFIRM", "agreement_score": 90, "my_directional_bias": "BULLISH", "my_confidence": 75}
d, r = determine_consensus(haiku_null, flash_norm)
check("confidence=None -> SKIP", d == "SKIP")
check("reason contains 'Missing or invalid confidence'", "Missing or invalid confidence" in r)


# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
print(f"Phase 3 Batch B: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
if FAIL == 0:
    print("ALL GATES PASS — Batch B checkpoint clear")
else:
    print(f"SOME GATES FAILED ({FAIL} failures)")
print(f"{'='*50}")

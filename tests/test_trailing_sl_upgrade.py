"""DB-free unit tests for the trailing-SL upgrade path (HOTFIX-6 follow-up).

Run: .venv\\Scripts\\python.exe tests\\test_trailing_sl_upgrade.py

Covers the two pure functions extracted from update_paper_trades.main():
  - _compute_t1_upgrade(entry, direction, segment)  -> T1->T2 upgrade dict
  - _compute_t2_upgrade(entry, direction)            -> T2->T3 upgrade dict (EQUITY only)

Makes NO live calls — calls the pure functions directly. Sets dummy Supabase
env vars to survive the module-level get_client() at import time (mirrors
test_close_expired.py); the client is never queried here.
"""
import os
import sys
import pathlib

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.update_paper_trades as upt

upt.DRY_RUN = True  # belt-and-suspenders — pure functions don't read it, but safe

# ── helpers ──────────────────────────────────────────────────────────
_failed = 0
_passed = 0


def check(desc, got, want):
    global _passed, _failed
    if got != want:
        _failed += 1
        print(f"  FAIL: {desc} -> got {got!r}, want {want!r}")
    else:
        _passed += 1
        print(f"  ok: {desc}")


def check_true(desc, cond):
    global _passed, _failed
    if not cond:
        _failed += 1
        print(f"  FAIL: {desc} -> condition false")
    else:
        _passed += 1
        print(f"  ok: {desc}")


# ── 1. Guard: constants haven't drifted (HOTFIX-6 locked values) ─────
print("-- 1. Constants (HOTFIX-6 locked) --")
check("EQ_T2        == 1.10", upt.EQ_T2, 1.10)
check("EQ_SL_T1     == 1.03", upt.EQ_SL_T1, 1.03)
check("EQ_SL_T2     == 1.06", upt.EQ_SL_T2, 1.06)
check("EQ_T3        == 1.15", upt.EQ_T3, 1.15)
check("FNO_T2       == 1.20", upt.FNO_T2, 1.20)
check("FNO_SL_T1    == 1.05", upt.FNO_SL_T1, 1.05)

# ── 2. _compute_t1_upgrade — BUY, EQUITY ─────────────────────────────
print("\n-- 2. _compute_t1_upgrade BUY EQUITY entry=100 --")
r = upt._compute_t1_upgrade(100.0, "BUY", "EQUITY")
check("t1_hit               == True",          r["t1_hit"], True)
check("current_target_level == 'T2'",          r["current_target_level"], "T2")
check("t2_price computed    == _dir_price(100, EQ_T2=1.10, BUY)",
      r["t2_price"], upt._dir_price(100.0, upt.EQ_T2, "BUY"))
check("t2_price literal     == 110.0",         r["t2_price"], 110.0)
check("trailing_sl computed == _dir_price(100, EQ_SL_T1=1.03, BUY)",
      r["trailing_sl"], upt._dir_price(100.0, upt.EQ_SL_T1, "BUY"))
check("trailing_sl literal  == 103.0",         r["trailing_sl"], 103.0)
check("t3_price computed   == _dir_price(100, EQ_T3=1.15, BUY)",
      r["t3_price"], upt._dir_price(100.0, upt.EQ_T3, "BUY"))
check("t3_price literal     == 115.0",         r["t3_price"], 115.0)

# ── Guard: trailing SL locks in profit after T1 hit ──
check_true("trailing_sl (103.0) > entry (100.0) — profit locked",
           r["trailing_sl"] > 100.0)

# ── 3. _compute_t1_upgrade — BUY, FNO ────────────────────────────────
print("\n-- 3. _compute_t1_upgrade BUY FNO entry=100 --")
r = upt._compute_t1_upgrade(100.0, "BUY", "FNO")
check("t1_hit               == True",          r["t1_hit"], True)
check("current_target_level == 'T2'",          r["current_target_level"], "T2")
check("t2_price computed    == _dir_price(100, FNO_T2=1.20, BUY)",
      r["t2_price"], upt._dir_price(100.0, upt.FNO_T2, "BUY"))
check("t2_price literal     == 120.0",         r["t2_price"], 120.0)
check("trailing_sl computed == _dir_price(100, FNO_SL_T1=1.05, BUY)",
      r["trailing_sl"], upt._dir_price(100.0, upt.FNO_SL_T1, "BUY"))
check("trailing_sl literal  == 105.0",         r["trailing_sl"], 105.0)

# ── Critical: FNO path must NOT have t3_price (if-not-is_fno guard) ──
check_true("'t3_price' key ABSENT in FNO dict",
           "t3_price" not in r)

# ── 4. _compute_t1_upgrade — SELL, EQUITY ─────────────────────────────
print("\n-- 4. _compute_t1_upgrade SELL EQUITY entry=100 --")
r = upt._compute_t1_upgrade(100.0, "SELL", "EQUITY")
check("t1_hit               == True",          r["t1_hit"], True)
check("current_target_level == 'T2'",          r["current_target_level"], "T2")
check("t2_price computed    == _dir_price(100, EQ_T2=1.10, SELL)",
      r["t2_price"], upt._dir_price(100.0, upt.EQ_T2, "SELL"))
check("t2_price literal     == 90.0",          r["t2_price"], 90.0)
check("trailing_sl computed == _dir_price(100, EQ_SL_T1=1.03, SELL)",
      r["trailing_sl"], upt._dir_price(100.0, upt.EQ_SL_T1, "SELL"))
check("trailing_sl literal  == 97.0",          r["trailing_sl"], 97.0)
check("t3_price computed   == _dir_price(100, EQ_T3=1.15, SELL)",
      r["t3_price"], upt._dir_price(100.0, upt.EQ_T3, "SELL"))
check("t3_price literal     == 85.0",          r["t3_price"], 85.0)

# ── Guard: SELL trailing SL locks in profit (SL below entry after move down) ──
check_true("trailing_sl (97.0) < entry (100.0) — profit locked (SELL)",
           r["trailing_sl"] < 100.0)

# ── 5. _compute_t2_upgrade — BUY ─────────────────────────────────────
print("\n-- 5. _compute_t2_upgrade BUY entry=100 --")
r = upt._compute_t2_upgrade(100.0, "BUY")
check("t2_hit               == True",          r["t2_hit"], True)
check("current_target_level == 'T3'",          r["current_target_level"], "T3")
check("trailing_sl computed == _dir_price(100, EQ_SL_T2=1.06, BUY)",
      r["trailing_sl"], upt._dir_price(100.0, upt.EQ_SL_T2, "BUY"))
check("trailing_sl literal  == 106.0",         r["trailing_sl"], 106.0)
check_true("trailing_sl (106.0) > entry (100.0) — profit locked (T2 BUY)",
           r["trailing_sl"] > 100.0)

# ── 6. _compute_t2_upgrade — SELL ────────────────────────────────────
print("\n-- 6. _compute_t2_upgrade SELL entry=100 --")
r = upt._compute_t2_upgrade(100.0, "SELL")
check("t2_hit               == True",          r["t2_hit"], True)
check("current_target_level == 'T3'",          r["current_target_level"], "T3")
check("trailing_sl computed == _dir_price(100, EQ_SL_T2=1.06, SELL)",
      r["trailing_sl"], upt._dir_price(100.0, upt.EQ_SL_T2, "SELL"))
check("trailing_sl literal  == 94.0",          r["trailing_sl"], 94.0)
check_true("trailing_sl (94.0) < entry (100.0) — profit locked (T2 SELL)",
           r["trailing_sl"] < 100.0)

# ── summary ───────────────────────────────────────────────────────────
print(f"\n{_passed + _failed} assertions: {_passed} passed, {_failed} failed")
if _failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")

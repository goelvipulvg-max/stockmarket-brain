"""DB-free unit test for compute_pnl_rs (Item 1: persist pnl_rs on close).

Run: .venv\\Scripts\\python.exe tests\\test_compute_pnl_rs.py

Pure-logic test. update_paper_trades.py builds a Supabase client at import, so
set dummy env first; the client is never used for a query here.
"""
import os
import sys
import pathlib

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agents.update_paper_trades import compute_pnl_rs


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# --- BUY-side gain: pnl_pct is already direction-adjusted upstream ---
check("win: +5% on entry 100 x qty 10 -> +50.0", compute_pnl_rs(5.0, 100, 10), 50.0)
check("loss: -3% on entry 200 x qty 5 -> -30.0", compute_pnl_rs(-3.0, 200, 5), -30.0)

# --- Real TIER2F shapes (ids 160/162 entries) ---
check("ASHOKLEY-like: +2.0% on 164.44 x 729 -> 2397.54", compute_pnl_rs(2.0, 164.44, 729), 2397.54)

# --- Break-even ---
check("flat: 0% -> 0.0", compute_pnl_rs(0.0, 100, 10), 0.0)

# --- Legacy NULL-quantity rows: pnl_rs stays None (not back-computable) ---
check("legacy no-qty: qty=None -> None", compute_pnl_rs(5.0, 100, None), None)

print("ALL TESTS PASSED")

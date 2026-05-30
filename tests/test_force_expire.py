"""DB-free unit test for the per-row max_holding_days time-stop fix.

Run: .venv\\Scripts\\python.exe tests\\test_force_expire.py

Pure-logic test of agents.update_paper_trades.should_force_expire -- makes NO DB
calls. update_paper_trades.py constructs a Supabase client at import, so we set
dummy Supabase env first (load_dotenv override wins if a real .env exists); the
client object is never used for a query here.
"""
import os
import sys
import pathlib

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agents.update_paper_trades import should_force_expire, DEFAULT_HOLDING_DAYS


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# --- Regression guard: a 10-day (MEDIUM) thesis must NOT die at calendar day 5 ---
check("MEDIUM(10) at day 5, market close -> not expired", should_force_expire(5, 10, True), False)

# --- Each per-row horizon expires exactly at its own window ---
check("SHORT(3) at day 3 -> expired", should_force_expire(3, 3, True), True)
check("MEDIUM(10) at day 10 -> expired", should_force_expire(10, 10, True), True)
check("LONG(30) at day 10 -> not expired", should_force_expire(10, 30, True), False)
check("LONG(30) at day 30 -> expired", should_force_expire(30, 30, True), True)

# --- Market-close gate respected ---
check("MEDIUM(10) at day 12 but NOT market close -> not expired", should_force_expire(12, 10, False), False)

# --- NULL / 0 / missing fall back to DEFAULT_HOLDING_DAYS (=10) ---
check("DEFAULT_HOLDING_DAYS is 10", DEFAULT_HOLDING_DAYS, 10)
check("NULL row at day 5 -> default(10), not expired", should_force_expire(5, None, True), False)
check("NULL row at day 10 -> default(10), expired", should_force_expire(10, None, True), True)
check("0 row at day 5 -> default(10), not expired", should_force_expire(5, 0, True), False)
check("0 row at day 10 -> default(10), expired", should_force_expire(10, 0, True), True)

print("ALL TESTS PASSED")

"""DB-free unit test for the fetch-fail-at-expiry path shipped in 507f6f0.

Run: .venv\\Scripts\\python.exe tests\\test_close_expired.py

Covers agents.update_paper_trades._close_expired (the shared EXPIRED-close
helper) and the fetch-fail-at-time-stop branch in main(). Makes NO live calls:
DRY_RUN is forced True (no paper_trades write, no capital release; the
trade_memory backfill is dry-run too -> returns 0 without touching the client).
update_paper_trades builds a Supabase client at import, so we set dummy env
first (mirrors test_force_expire.py); the client is never queried here.
"""
import io
import os
import sys
import pathlib
import contextlib
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.update_paper_trades as upt

upt.DRY_RUN = True  # force the no-write path for every assertion below
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 6, 13, 16, 0, tzinfo=IST)  # fixed; never datetime.now()


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# -- 1. _close_expired() direct: flat exit (exit == entry) => 0.0% pnl --
flat_trade = {
    "id": 9001, "ticker": "TEST.NS", "direction": "BUY",
    "entry_price": 100.0, "quantity": 10, "position_size_rs": 1000.0,
}
check("BUY flat exit (100==100) -> 0.0% pnl",
      upt._close_expired(flat_trade, 100.0, holding_days=5, now_ist=NOW), 0.0)
check("SELL flat exit (100==100) -> 0.0% pnl",
      upt._close_expired({**flat_trade, "direction": "SELL"}, 100.0, 5, NOW), 0.0)

# -- 2. _close_expired() direct: non-flat exit => direction-correct pnl --
check("BUY exit 110 from entry 100 -> +10.0%",
      upt._close_expired({**flat_trade, "direction": "BUY"}, 110.0, 5, NOW), 10.0)
check("BUY exit 95 from entry 100 -> -5.0%",
      upt._close_expired({**flat_trade, "direction": "BUY"}, 95.0, 5, NOW), -5.0)
check("SELL exit 90 from entry 100 -> +10.0%",
      upt._close_expired({**flat_trade, "direction": "SELL"}, 90.0, 5, NOW), 10.0)
check("SELL exit 110 from entry 100 -> -10.0%",
      upt._close_expired({**flat_trade, "direction": "SELL"}, 110.0, 5, NOW), -10.0)

# -- 3. fetch-fail-at-time-stop branch in main() closes EXPIRED at entry_price --
# Minimal, no live calls: fake the OPEN-trades read, force fetch failure, and
# make every wall-clock >= market close so the time-stop fires. DRY_RUN stays
# True, so the EXPIRED close is only PRINTED -- we assert on that.
class _FakeQuery:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def execute(self): return type("R", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, rows): self._rows = rows
    def table(self, name): return _FakeQuery(self._rows)


# day-17 BUY, SHORT horizon (max 3) -> well past its window
expire_row = {
    "id": 9002, "ticker": "GAPFAIL.NS", "direction": "BUY",
    "entry_price": 250.0, "quantity": 20, "position_size_rs": 5000.0,
    "signal_date": "2026-05-27", "max_holding_days": 3,
}
orig_gmd, orig_sb, orig_close = upt.get_market_data, upt.supabase, upt.MARKET_CLOSE
try:
    upt.get_market_data = lambda ticker: None       # force fetch failure
    upt.supabase = _FakeSupabase([expire_row])       # controlled OPEN trades
    upt.MARKET_CLOSE = dt_time(0, 0)                 # any wall-clock >= close
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        upt.main()
    out = buf.getvalue()
finally:
    upt.get_market_data, upt.supabase, upt.MARKET_CLOSE = orig_gmd, orig_sb, orig_close

check("fetch-fail branch closed EXPIRED at entry_price (250.0)",
      "EXPIRED at last-known 250.0" in out, True)
check("fetch-fail branch pnl is 0.0% (exit == entry)", "PnL: 0.0%" in out, True)
check("fetch-fail branch did NOT fire SL/target",
      ("SL_HIT" in out or "TARGET_HIT" in out), False)

print("ALL TESTS PASSED")

"""DB-free unit tests for Batch D Session 2 fidelity trio (audit Exec #3).

Run: .venv\\Scripts\\python.exe tests\\test_fidelity_trio.py
 or: .venv\\Scripts\\python.exe -m pytest tests\\test_fidelity_trio.py -v

Covers (i) first_touch + both-touched routing via main() (P1-3), (ii) the
wait-floor boundary fill, (iii) net-of-cost releases (direct close + retry)
with the cost_rs best-effort store. NO live calls: session/supabase/release
are all replaced with recording fakes; the main()-driven scenarios run in
DRY_RUN (no writes, retry-scan short-circuits).
"""
import io
import os
import contextlib
import pathlib
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.update_paper_trades as upt          # noqa: E402
from utils.trade_costs import compute_trade_costs  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 5, 16, 0, tzinfo=IST)  # fixed for direct-call tests


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# ── fakes (self-contained; mirror test_money_seam_guards) ───────────────
class _FakeQuery:
    def __init__(self, sb, table):
        self.sb = sb; self.table = table
        self.op = None; self.payload = None; self.filters = []
    def select(self, *a, **k): self.op = "select"; return self
    def update(self, payload): self.op = "update"; self.payload = payload; return self
    def eq(self, col, val): self.filters.append((col, val)); return self
    def limit(self, n): return self
    def execute(self):
        self.sb.calls.append(self)
        return type("R", (), {"data": self.sb.handler(self)})()


class _FakeSB:
    def __init__(self, handler): self.handler = handler; self.calls = []
    def table(self, name): return _FakeQuery(self, name)
    def updates(self, table=None):
        return [q for q in self.calls
                if q.op == "update" and (table is None or q.table == table)]


# ── 1. first_touch (pure) ────────────────────────────────────────────────
def test_first_touch():
    ft = upt.first_touch
    check("BUY target first", ft([(105.2, 99.0), (104.0, 94.5)], 105.0, 95.0, "BUY"), "TARGET")
    check("BUY SL first", ft([(101.0, 94.9), (105.5, 100.0)], 105.0, 95.0, "BUY"), "SL")
    check("same-bar tie -> SL (pessimistic)", ft([(105.5, 94.0)], 105.0, 95.0, "BUY"), "SL")
    check("empty bars -> SL", ft([], 105.0, 95.0, "BUY"), "SL")
    check("None bars -> SL", ft(None, 105.0, 95.0, "BUY"), "SL")
    check("neither found -> SL", ft([(100.0, 99.0)], 105.0, 95.0, "BUY"), "SL")
    check("SELL target first", ft([(101.0, 94.8), (106.0, 100.0)], 95.0, 105.0, "SELL"), "TARGET")
    check("SELL SL first", ft([(105.1, 100.0), (99.0, 94.0)], 95.0, 105.0, "SELL"), "SL")
    check("SELL same-bar tie -> SL", ft([(105.1, 94.8)], 95.0, 105.0, "SELL"), "SL")


# ── 2. _trade_cost_rs (pure wrapper) ─────────────────────────────────────
def test_trade_cost_rs():
    expected = round(compute_trade_costs(100.0, 105.0, 10)["total_cost_rs"], 2)
    check("valid trade -> rounded cost", upt._trade_cost_rs(100.0, 105.0, 10), expected)
    check("qty None -> None", upt._trade_cost_rs(100.0, 105.0, None), None)
    check("invalid exit -> None", upt._trade_cost_rs(100.0, None, 10), None)


# ── 3. main()-driven scenarios (DRY_RUN; fake market + fake OPEN scan) ──
def _run_main(rows, market):
    orig = (upt.get_market_data, upt.supabase, upt.DRY_RUN)
    try:
        upt.get_market_data = lambda ticker: dict(market)
        upt.supabase = _FakeSB(lambda q: [dict(r) for r in rows])
        upt.DRY_RUN = True
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            upt.main()
        return buf.getvalue()
    finally:
        upt.get_market_data, upt.supabase, upt.DRY_RUN = orig


def _open_row(**over):
    # signal_date pinned 2 days behind the REAL clock (main() uses
    # datetime.now): holding_days stays 2 (< max 30, never expires) and
    # is_day0 stays False no matter when the suite runs.
    base = {
        "id": 9201, "ticker": "FID.NS", "direction": "BUY", "status": "OPEN",
        "entry_price": 100.0, "stop_loss": 95.0, "target_price": 105.0,
        "quantity": 10, "position_size_rs": 1000.0, "max_holding_days": 30,
        "signal_date": (datetime.now(IST).date() - timedelta(days=2)).isoformat(),
    }
    base.update(over)
    return base


def test_both_touched_sl_first_routes_to_sl():
    out = _run_main(
        [_open_row()],
        {"ltp": 100.0, "day_high": 105.5, "day_low": 90.9, "day_open": 99.0,
         "bars": [(101.0, 94.0), (105.5, 100.0)]},
    )
    check("ambiguity detected + SL first", "1m sequence says SL first" in out, True)
    check("booked GAP-EXIT at wait_floor 91.0", "GAP-EXIT @ 91.0" in out, True)
    check("no T1 upgrade happened", "T1_HIT" in out, False)


def test_both_touched_target_first_keeps_target():
    out = _run_main(
        [_open_row()],
        {"ltp": 104.0, "day_high": 105.5, "day_low": 94.9, "day_open": 99.0,
         "bars": [(105.2, 99.0), (104.0, 94.5)]},
    )
    check("ambiguity detected + TARGET first", "1m sequence says TARGET first" in out, True)
    check("T1 upgrade proceeded", "T1_HIT" in out, True)


def test_both_touched_no_bars_pessimistic():
    out = _run_main(
        [_open_row()],
        {"ltp": 100.0, "day_high": 105.5, "day_low": 90.9, "day_open": 99.0,
         "bars": None},
    )
    check("no-bars ambiguity -> SL", "1m sequence says SL first" in out, True)


def test_wait_floor_breach_books_boundary():
    # target NOT touched; lo 90.5 <= wait_floor 91 (> mandatory 90)
    out = _run_main(
        [_open_row()],
        {"ltp": 92.0, "day_high": 96.0, "day_low": 90.5, "day_open": 95.0},
    )
    check("booked at wait_floor, not active_sl", "GAP-EXIT @ 91.0" in out, True)
    check("pnl reflects the boundary (-9.0%)", "PnL: -9.0%" in out, True)


def test_single_touch_target_unchanged():
    out = _run_main(
        [_open_row()],
        {"ltp": 104.0, "day_high": 105.5, "day_low": 99.0, "day_open": 100.0,
         "bars": [(105.5, 99.0)]},
    )
    check("no ambiguity line on single touch", "AMBIGUOUS" in out, False)
    check("T1 upgrade normal", "T1_HIT" in out, True)


# ── 4. net-of-cost: direct close path ───────────────────────────────────
TRADE = {"id": 9301, "ticker": "COST.NS", "direction": "BUY",
         "entry_price": 100.0, "quantity": 10, "position_size_rs": 1000.0}
EXP_COST = round(compute_trade_costs(100.0, 105.0, 10)["total_cost_rs"], 2)
EXP_NET = round(50.0 - EXP_COST, 2)


def _close_with(handler):
    released = []
    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital,
            upt.update_trade_memory_outcome, upt._tg_send)
    try:
        upt.DRY_RUN = False
        upt.supabase = fake
        upt.release_capital = lambda tid, size, pnl: released.append((tid, size, pnl))
        upt.update_trade_memory_outcome = lambda *a, **k: 0
        upt._tg_send = lambda *a, **k: None  # U-9 close alert: load_dotenv leaks real creds
        ret = upt._close_trade(dict(TRADE), "TARGET_HIT", 105.0, 5, NOW)
    finally:
        (upt.DRY_RUN, upt.supabase, upt.release_capital,
         upt.update_trade_memory_outcome, upt._tg_send) = orig
    return ret, fake, released


def test_close_trade_releases_net_and_stores_cost():
    def handler(q):
        return [dict(TRADE)] if (q.op == "update" and "status" in (q.payload or {})) else []

    ret, fake, released = _close_with(handler)
    check("pnl_pct returned gross (+5%)", ret, 5.0)
    close_upd = [q for q in fake.updates("paper_trades") if "status" in (q.payload or {})]
    check("row pnl_rs stays GROSS (+50)", close_upd[0].payload["pnl_rs"], 50.0)
    cost_upd = [q for q in fake.updates("paper_trades") if "cost_rs" in (q.payload or {})]
    check("cost_rs stored once", len(cost_upd), 1)
    check("cost_rs value exact", cost_upd[0].payload["cost_rs"], EXP_COST)
    check("release got NET pnl", released, [(9301, 1000.0, EXP_NET)])


def test_close_trade_cost_column_missing_still_nets():
    def handler(q):
        if q.op == "update" and "cost_rs" in (q.payload or {}):
            raise Exception('column "cost_rs" does not exist')
        return [dict(TRADE)] if (q.op == "update" and "status" in (q.payload or {})) else []

    ret, fake, released = _close_with(handler)
    check("close still returns pnl", ret, 5.0)
    check("release STILL net (cost deterministic, store optional)",
          released, [(9301, 1000.0, EXP_NET)])


# ── 5. net-of-cost: retry path ───────────────────────────────────────────
def test_retry_releases_net():
    row = {"id": 9401, "ticker": "RET.NS", "quantity": 10, "position_size_rs": 1000.0,
           "entry_price": 100.0, "exit_price": 105.0, "pnl_rs": 50.0}

    def handler(q):
        if q.table == "paper_trades" and q.op == "select":
            return [dict(row)]
        return []  # ledger pre-check: no PNL_REALIZED row

    released = []
    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital)
    try:
        upt.DRY_RUN = False
        upt.supabase = fake
        upt.release_capital = lambda tid, size, pnl: released.append((tid, size, pnl))
        upt._retry_failed_releases()
    finally:
        upt.DRY_RUN, upt.supabase, upt.release_capital = orig
    check("retry released NET (same math as direct close)",
          released, [(9401, 1000.0, EXP_NET)])
    cleared = [q for q in fake.updates("paper_trades")
               if q.payload == {"capital_release_failed": False}]
    check("flag cleared after net release", len(cleared), 1)


# ── 6. bars extraction from the 1m payload ──────────────────────────────
def test_get_market_data_extracts_bars():
    payload = {"chart": {"result": [{
        "meta": {"regularMarketPrice": 102.0, "regularMarketDayHigh": 106.0,
                 "regularMarketDayLow": 94.0, "chartPreviousClose": 100.0},
        "indicators": {"quote": [{
            "open": [100.0, None, 101.0],
            "high": [105.0, None, 106.0],
            "low": [99.0, None, 94.0],
        }]},
    }]}}

    class _FakeResp:
        def json(self): return payload

    class _FakeSession:
        def get(self, url, headers=None, timeout=None): return _FakeResp()

    orig = upt._session
    try:
        upt._session = _FakeSession()
        m = upt.get_market_data("FAKE.NS")
    finally:
        upt._session = orig
    check("ltp unchanged", m["ltp"], 102.0)
    check("day_high unchanged", m["day_high"], 106.0)
    check("day_low unchanged", m["day_low"], 94.0)
    check("day_open from first non-null open", m["day_open"], 100.0)
    check("bars filtered to non-null pairs", m["bars"], [(105.0, 99.0), (106.0, 94.0)])


if __name__ == "__main__":
    for fn in [test_first_touch, test_trade_cost_rs,
               test_both_touched_sl_first_routes_to_sl,
               test_both_touched_target_first_keeps_target,
               test_both_touched_no_bars_pessimistic,
               test_wait_floor_breach_books_boundary,
               test_single_touch_target_unchanged,
               test_close_trade_releases_net_and_stores_cost,
               test_close_trade_cost_column_missing_still_nets,
               test_retry_releases_net,
               test_get_market_data_extracts_bars]:
        print(f"\n{fn.__name__}:")
        fn()
    print("\nALL TESTS PASSED")

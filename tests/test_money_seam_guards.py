"""DB-free unit tests for Batch D Session 2 money-seam guards.

Run: .venv\\Scripts\\python.exe tests\\test_money_seam_guards.py
 or: .venv\\Scripts\\python.exe -m pytest tests\\test_money_seam_guards.py -v

Covers seam (a) _void_failed_deploy, seam (c) _close_trade release-failure
marking + _retry_failed_releases healing, and the error_code prefix in
utils.capital_ledger.release_capital. Makes NO live calls: every Supabase
client / RPC / telegram send is replaced with a recording fake before use
(the real clients built at import are never queried).
"""
import os
import pathlib
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")
os.environ.setdefault("NEON_CONNECTION_STRING", "dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("TELEGRAM_TIER3_CHANNEL", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.update_paper_trades as upt          # noqa: E402
import agents.tier2_fundamental as t2f            # noqa: E402
import utils.capital_ledger as cl                 # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 5, 16, 0, tzinfo=IST)  # fixed; never datetime.now()


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# ── Recording fakes ─────────────────────────────────────────────────────
class _FakeQuery:
    def __init__(self, sb, table):
        self.sb = sb
        self.table = table
        self.op = None
        self.payload = None
        self.filters = []

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, n):
        return self

    def execute(self):
        self.sb.calls.append(self)
        return type("R", (), {"data": self.sb.handler(self)})()


class _FakeSB:
    """handler(q) -> data list (or raise). Every executed query is recorded."""
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def table(self, name):
        return _FakeQuery(self, name)

    def updates(self, table=None):
        return [q for q in self.calls
                if q.op == "update" and (table is None or q.table == table)]


class _FakeRpcSB:
    def __init__(self, data):
        self.data = data
        self.last = None

    def rpc(self, name, params):
        self.last = (name, params)
        return type("Q", (), {"execute": lambda s: type("R", (), {"data": self.data})()})()


# ── 1. capital_ledger.release_capital error_code prefix ────────────────
def test_release_capital_error_code_prefix():
    orig_sb = cl.sb
    try:
        cl.sb = _FakeRpcSB({"success": False, "error_code": "ALREADY_RELEASED",
                            "error": "Trade 7 already has a PNL_REALIZED ledger row"})
        try:
            cl.release_capital(7, 1000.0, 50.0)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            check("error_code prefixed", str(e).startswith("[ALREADY_RELEASED] "), True)

        cl.sb = _FakeRpcSB({"success": False, "error": "boom"})  # v1 shape
        try:
            cl.release_capital(7, 1000.0, 50.0)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            check("v1 shape -> bare message", str(e), "boom")

        cl.sb = _FakeRpcSB(None)
        try:
            cl.release_capital(7, 1000.0, 50.0)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            check("None data -> fallback message", str(e), "release_capital_atomic failed")

        cl.sb = _FakeRpcSB({"success": True, "cash_after": 1.0})
        check("success returns data", cl.release_capital(7, 1000.0, 50.0)["success"], True)
    finally:
        cl.sb = orig_sb


# ── 2. seam (a): _void_failed_deploy ────────────────────────────────────
def test_void_failed_deploy_happy():
    tg_log = []
    orig_sb, orig_tg = t2f.sb, t2f._tg_send
    try:
        fake = _FakeSB(lambda q: [])
        t2f.sb = fake
        t2f._tg_send = tg_log.append
        t2f._void_failed_deploy(123, "TCS", ValueError("Insufficient cash"))
        upd = fake.updates("paper_trades")
        check("exactly one void update", len(upd), 1)
        check("status set to VOID", upd[0].payload["status"], "VOID")
        check("closed_at stamped", bool(upd[0].payload.get("closed_at")), True)
        check("filtered on id", ("id", 123) in upd[0].filters, True)
        check("guarded on status=OPEN", ("status", "OPEN") in upd[0].filters, True)
        check("tg alert sent", len(tg_log), 1)
        check("tg mentions symbol+id+VOIDED",
              "TCS" in tg_log[0] and "123" in tg_log[0] and "VOIDED" in tg_log[0], True)
    finally:
        t2f.sb, t2f._tg_send = orig_sb, orig_tg


def test_void_failed_deploy_critical_path():
    tg_log = []
    orig_sb, orig_tg = t2f.sb, t2f._tg_send

    def _boom(q):
        raise Exception("violates check constraint")

    try:
        t2f.sb = _FakeSB(_boom)
        t2f._tg_send = tg_log.append
        t2f._void_failed_deploy(124, "INFY", ValueError("network"))  # must not raise
        check("critical tg alert sent", len(tg_log), 1)
        check("tg flags PHANTOM", "PHANTOM" in tg_log[0], True)
    finally:
        t2f.sb, t2f._tg_send = orig_sb, orig_tg


# ── 3. seam (c): _close_trade marks + continues on release failure ─────
TRADE = {"id": 9101, "ticker": "SEAM.NS", "direction": "BUY",
         "entry_price": 100.0, "quantity": 10, "position_size_rs": 1000.0}


def _close_trade_with(release_fn):
    """Run _close_trade(SL_HIT @95) with fakes; returns (ret, fake_sb)."""
    def handler(q):
        return [dict(TRADE)] if (q.op == "update" and "status" in (q.payload or {})) else []

    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital,
            upt.update_trade_memory_outcome, upt._tg_send)
    try:
        upt.DRY_RUN = False
        upt.supabase = fake
        upt.release_capital = release_fn
        upt.update_trade_memory_outcome = lambda *a, **k: 0
        upt._tg_send = lambda *a, **k: None  # U-9 alerts (close + release-fail): no real send
        ret = upt._close_trade(dict(TRADE), "SL_HIT", 95.0, 5, NOW)
    finally:
        (upt.DRY_RUN, upt.supabase, upt.release_capital,
         upt.update_trade_memory_outcome, upt._tg_send) = orig
    return ret, fake


def test_close_trade_release_failure_marks_and_continues():
    def raiser(tid, size, pnl):
        raise RuntimeError("[DEPLOY_MISSING] No DEPLOY ledger row")

    ret, fake = _close_trade_with(raiser)
    check("pnl still returned (close committed)", ret, -5.0)
    flag_upd = [q for q in fake.updates("paper_trades")
                if q.payload == {"capital_release_failed": True}]
    check("release-failed flag written", len(flag_upd), 1)
    check("flag filtered on trade id", ("id", 9101) in flag_upd[0].filters, True)


def test_close_trade_release_success_writes_no_flag():
    ret, fake = _close_trade_with(lambda tid, size, pnl: {"success": True})
    check("pnl returned", ret, -5.0)
    flag_upd = [q for q in fake.updates("paper_trades")
                if "capital_release_failed" in (q.payload or {})]
    check("no flag write on success", len(flag_upd), 0)


# ── 4. seam (c): _retry_failed_releases branches ────────────────────────
def _run_retry(flagged_rows, ledger_done_ids, release_behavior):
    """release_behavior: {tid: 'ok' | RuntimeError-message-to-raise}."""
    attempts = []

    def handler(q):
        if q.table == "paper_trades" and q.op == "select":
            return [dict(r) for r in flagged_rows]
        if q.table == "capital_ledger":
            tid = dict(q.filters).get("paper_trade_id")
            return [{"id": 77}] if tid in ledger_done_ids else []
        return []

    def fake_release(tid, size, pnl):
        attempts.append(tid)
        beh = release_behavior.get(tid, "ok")
        if beh != "ok":
            raise RuntimeError(beh)
        return {"success": True}

    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital)
    try:
        upt.DRY_RUN = False
        upt.supabase = fake
        upt.release_capital = fake_release
        upt._retry_failed_releases()
    finally:
        upt.DRY_RUN, upt.supabase, upt.release_capital = orig
    cleared = [dict(q.filters)["id"] for q in fake.updates("paper_trades")
               if q.payload == {"capital_release_failed": False}]
    return attempts, cleared, fake


def _row(tid, pnl_rs=25.0, qty=10):
    return {"id": tid, "ticker": f"T{tid}.NS", "quantity": qty,
            "position_size_rs": 1000.0, "pnl_rs": pnl_rs}


def test_retry_all_branches():
    rows = [_row(1), _row(2), _row(3), _row(4), _row(5, pnl_rs=0.0), _row(6, qty=None)]
    attempts, cleared, _ = _run_retry(
        rows,
        ledger_done_ids={1},
        release_behavior={3: "[ALREADY_RELEASED] dup",
                          4: "[INSUFFICIENT_DEPLOYED] low"},
    )
    check("pre-check-done row not re-released", 1 not in attempts, True)
    check("release attempted for 2,3,4,5", attempts, [2, 3, 4, 5])
    check("qty-None row never attempted", 6 not in attempts, True)
    check("flags cleared: pre-check + ok + already-released (not 4/6)",
          sorted(cleared), [1, 2, 3, 5])
    check("pnl_rs=0.0 row still retried (is-None check, not falsy)", 5 in attempts, True)


def test_retry_scan_column_missing_degrades():
    def handler(q):
        raise Exception('column "capital_release_failed" does not exist')

    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase)
    try:
        upt.DRY_RUN = False
        upt.supabase = fake
        upt._retry_failed_releases()  # must not raise
    finally:
        upt.DRY_RUN, upt.supabase = orig
    check("column-missing: no updates attempted", len(fake.updates()), 0)


def test_retry_skipped_in_dry_run():
    fake = _FakeSB(lambda q: [_row(1)])
    orig = (upt.DRY_RUN, upt.supabase)
    try:
        upt.DRY_RUN = True
        upt.supabase = fake
        upt._retry_failed_releases()
    finally:
        upt.DRY_RUN, upt.supabase = orig
    check("dry-run: zero queries", len(fake.calls), 0)


if __name__ == "__main__":
    for fn in [test_release_capital_error_code_prefix,
               test_void_failed_deploy_happy,
               test_void_failed_deploy_critical_path,
               test_close_trade_release_failure_marks_and_continues,
               test_close_trade_release_success_writes_no_flag,
               test_retry_all_branches,
               test_retry_scan_column_missing_degrades,
               test_retry_skipped_in_dry_run]:
        print(f"\n{fn.__name__}:")
        fn()
    print("\nALL TESTS PASSED")

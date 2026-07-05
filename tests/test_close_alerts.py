"""DB-free unit tests for the U-9 updater Telegram alerts (Batch D Session 3).

Run: .venv\\Scripts\\python.exe tests\\test_close_alerts.py
 or: .venv\\Scripts\\python.exe -m pytest tests\\test_close_alerts.py -v

Covers _close_trade close alerts (content, loser-run silence, DRY_RUN skip),
the two-level _mark_release_failed alerts, the T1-upgrade alert in main(), and
the fail-open guarantee (_tg_send swallows send errors; missing env skips
cleanly inside utils.telegram_client). Makes NO live calls: supabase/release/
memory and _tg_send (or send_message) are replaced with recording fakes.

CONVENTION REMINDER: any test driving _close_trade or _mark_release_failed
with DRY_RUN=False must stub upt._tg_send -- load_dotenv(override=True) at
module import puts REAL Telegram creds into os.environ on the dev machine.
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

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 5, 16, 0, tzinfo=IST)  # fixed; never datetime.now()

TRADE = {"id": 9501, "ticker": "ALRT.NS", "direction": "BUY",
         "entry_price": 100.0, "quantity": 10, "position_size_rs": 1000.0}


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


# ── fakes (repo convention: self-contained per file) ────────────────────
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


def _winner_handler(q):
    return [dict(TRADE)] if (q.op == "update" and "status" in (q.payload or {})) else []


def _close_with(handler, release_fn=None, dry_run=False):
    """_close_trade(TARGET_HIT @105) with fakes; returns (ret, alerts, stdout)."""
    alerts = []
    fake = _FakeSB(handler)
    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital,
            upt.update_trade_memory_outcome, upt._tg_send)
    try:
        upt.DRY_RUN = dry_run
        upt.supabase = fake
        upt.release_capital = release_fn or (lambda *a: {"success": True})
        upt.update_trade_memory_outcome = lambda *a, **k: 0
        upt._tg_send = alerts.append
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = upt._close_trade(dict(TRADE), "TARGET_HIT", 105.0, 5, NOW)
    finally:
        (upt.DRY_RUN, upt.supabase, upt.release_capital,
         upt.update_trade_memory_outcome, upt._tg_send) = orig
    return ret, alerts, buf.getvalue()


# ── 1. close alert: content + exactly-once ──────────────────────────────
def test_close_alert_content():
    ret, alerts, _ = _close_with(_winner_handler)
    check("close returns pnl", ret, 5.0)
    check("exactly one alert", len(alerts), 1)
    msg = alerts[0]
    check("alert has target emoji", "\U0001F3AF" in msg, True)
    for token in ("CLOSED", "ALRT.NS", "BUY", "TARGET_HIT",
                  "@ 105.0", "PnL 5.0%", "Rs.50.00", "day 5"):
        check(f"alert has {token!r}", token in msg, True)


# ── 2. loser run (P2-7 idempotent close) stays silent ───────────────────
def test_loser_run_no_alert():
    ret, alerts, out = _close_with(lambda q: [])
    check("loser returns None", ret, None)
    check("loser sends no alert", alerts, [])
    check("loser logs already-closed", "already closed" in out, True)


# ── 3. DRY_RUN: print-only, no send ─────────────────────────────────────
def test_dry_run_no_alert():
    ret, alerts, out = _close_with(_winner_handler, dry_run=True)
    check("dry-run returns pnl", ret, 5.0)
    check("dry-run sends nothing", alerts, [])
    check("dry-run prints would-alert",
          "Would alert: CLOSED ALRT.NS TARGET_HIT" in out, True)


# ── 4. release failure: two-level alerts, close alert still last ────────
def test_release_failure_alert_two_levels():
    def raiser(*a):
        raise RuntimeError("[DEPLOY_MISSING] no deploy row")

    # variant 1: retry-flag write works -> [release-fail, close]
    ret, alerts, _ = _close_with(_winner_handler, release_fn=raiser)
    check("close still returns pnl on release failure", ret, 5.0)
    check("two alerts: release-fail + close", len(alerts), 2)
    check("first alert is release-fail", "capital release FAILED" in alerts[0], True)
    check("release-fail alert names the trade",
          "ALRT.NS" in alerts[0] and "id=9501" in alerts[0], True)
    check("close alert still sent last", "CLOSED ALRT.NS" in alerts[1], True)

    # variant 2: flag write ALSO fails -> [release-fail, CRITICAL, close]
    def handler2(q):
        if q.op == "update" and "capital_release_failed" in (q.payload or {}):
            raise Exception('column "capital_release_failed" does not exist')
        return _winner_handler(q)

    ret, alerts, _ = _close_with(handler2, release_fn=raiser)
    check("flag-fail: close still returns pnl", ret, 5.0)
    check("three alerts: release-fail + CRITICAL + close", len(alerts), 3)
    check("second alert is the CRITICAL manual-fix one",
          "CRITICAL" in alerts[1] and "manual reconciliation" in alerts[1], True)


# ── 5. fail-open: a raising send never breaks the close ─────────────────
def test_tg_send_fail_open():
    def boom(*a, **k):
        raise ConnectionError("telegram down")

    orig = (upt.DRY_RUN, upt.supabase, upt.release_capital,
            upt.update_trade_memory_outcome, upt.send_message)
    try:
        upt.DRY_RUN = False
        upt.supabase = _FakeSB(_winner_handler)
        upt.release_capital = lambda *a: {"success": True}
        upt.update_trade_memory_outcome = lambda *a, **k: 0
        upt.send_message = boom  # REAL _tg_send wraps this and must swallow
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = upt._close_trade(dict(TRADE), "SL_HIT", 95.0, 5, NOW)
    finally:
        (upt.DRY_RUN, upt.supabase, upt.release_capital,
         upt.update_trade_memory_outcome, upt.send_message) = orig
    check("send failure never breaks the close", ret, -5.0)
    check("failure logged, run continues",
          "Telegram send failed" in buf.getvalue(), True)


# ── 6. missing env: clean skip inside telegram_client, no network ───────
def test_tg_send_env_missing_skips():
    saved = {k: os.environ.pop(k, None)
             for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TIER3_CHANNEL")}
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            upt._tg_send("unit-test message, must not hit network")
        check("missing env -> config-missing skip",
              "Telegram config missing" in buf.getvalue(), True)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ── 7. T1 upgrade alert fires only with the real (non-DRY_RUN) write ────
def test_t1_upgrade_alert_on_real_write():
    row = {"id": 9601, "ticker": "UPGD.NS", "direction": "BUY", "segment": "EQUITY",
           "entry_price": 100.0, "quantity": 10, "position_size_rs": 1000.0,
           "target_price": 105.0, "stop_loss": 95.0, "max_holding_days": 30,
           "signal_date": (datetime.now(IST) - timedelta(days=2)).date().isoformat()}

    def handler(q):
        if q.op == "select" and ("capital_release_failed", True) in q.filters:
            return []           # retry scan: nothing flagged
        if q.op == "select":
            return [dict(row)]  # the OPEN-trades scan
        return [dict(row)]      # the T1 upgrade update succeeds

    alerts = []
    orig = (upt.DRY_RUN, upt.supabase, upt.get_market_data, upt._tg_send)
    try:
        upt.DRY_RUN = False
        upt.supabase = _FakeSB(handler)
        upt.get_market_data = lambda t: {"ltp": 104.0, "day_high": 105.5,
                                         "day_low": 99.0, "day_open": 100.0,
                                         "bars": [(105.5, 99.0)]}
        upt._tg_send = alerts.append
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            upt.main()
    finally:
        upt.DRY_RUN, upt.supabase, upt.get_market_data, upt._tg_send = orig
    check("exactly one upgrade alert", len(alerts), 1)
    check("upgrade alert content",
          "UPGD.NS T1 hit @ 105.0 -> T2 mode" in alerts[0], True)
    check("upgrade alert carries the new SL", "SL raised to 103.0" in alerts[0], True)
    check("no close alert on an upgrade", any("CLOSED" in m for m in alerts), False)


if __name__ == "__main__":
    for fn in [test_close_alert_content, test_loser_run_no_alert,
               test_dry_run_no_alert, test_release_failure_alert_two_levels,
               test_tg_send_fail_open, test_tg_send_env_missing_skips,
               test_t1_upgrade_alert_on_real_write]:
        print(f"\n{fn.__name__}:")
        fn()
    print("\nALL TESTS PASSED")

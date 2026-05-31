"""DB-free unit tests for agents/health_monitor.py pure helpers (Phase 8 §10.2).

Run: .venv\\Scripts\\python.exe tests\\test_health_monitor.py

Tests only no-I/O helpers: is_stalled, other_rate, is_overdue, reconcile,
ledger_deploy_total, format_health_alert. No DB. Dummy env so import needs no creds.
"""
import os
import sys
import pathlib
from datetime import date, datetime

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agents.health_monitor import (
    is_stalled, other_rate, is_overdue, reconcile, ledger_deploy_total,
    format_health_alert, is_market_open, evaluate,
    DEFAULT_HOLDING_DAYS, STALL_THRESHOLD_MIN,
    BACKLOG_THRESHOLD, OTHER_RATE_THRESHOLD_PCT,
)
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


def check_in(desc, hay, needle):
    assert needle in hay, f"FAIL: {desc} -> {needle!r} not in:\n{hay}"
    print(f"  ok: {desc}")


# --- constants are the master-plan defaults ---
check("STALL_THRESHOLD_MIN=30", STALL_THRESHOLD_MIN, 30)
check("BACKLOG_THRESHOLD=20", BACKLOG_THRESHOLD, 20)
check("OTHER_RATE_THRESHOLD_PCT=20.0", OTHER_RATE_THRESHOLD_PCT, 20.0)
check("DEFAULT_HOLDING_DAYS=10", DEFAULT_HOLDING_DAYS, 10)

# --- is_stalled ---
t0 = datetime(2026, 5, 29, 11, 0, 0)   # 11:00
t_recent = datetime(2026, 5, 29, 10, 45, 0)  # 15 min earlier
t_old = datetime(2026, 5, 29, 10, 20, 0)     # 40 min earlier
check("market closed -> never stalled", is_stalled(t_old, t0, is_market_open=False), False)
check("market open, 15min gap -> not stalled", is_stalled(t_recent, t0, is_market_open=True), False)
check("market open, 40min gap -> stalled", is_stalled(t_old, t0, is_market_open=True), True)
check("market open, no filings ever -> stalled", is_stalled(None, t0, is_market_open=True), True)
check("market closed, no filings -> not stalled", is_stalled(None, t0, is_market_open=False), False)
check("market open, exactly 30min -> not stalled (>, not >=)",
      is_stalled(datetime(2026, 5, 29, 10, 30, 0), t0, is_market_open=True), False)
# Production contract: classified_at is tz-aware UTC, now is tz-aware IST.
# aware-minus-aware must NOT raise and must respect the real offset (40 min gap).
_now_ist = datetime(2026, 5, 29, 16, 0, tzinfo=IST)          # 10:30 UTC
_latest_utc = datetime(2026, 5, 29, 9, 50, tzinfo=UTC)       # 40 min earlier (UTC)
check("aware IST now vs aware UTC latest, 40min -> stalled (no TypeError)",
      is_stalled(_latest_utc, _now_ist, is_market_open=True), True)
check("aware IST now vs aware UTC latest, 15min -> not stalled",
      is_stalled(datetime(2026, 5, 29, 10, 15, tzinfo=UTC), _now_ist, is_market_open=True), False)

# --- other_rate ---
check("empty -> None (div-0 guard)", other_rate({}), None)
check("zero total -> None", other_rate({"RESULTS": 0}), None)
check("3 of 12 OTHER -> 25%", other_rate({"OTHER": 3, "RESULTS": 9}), 25.0)
check("0 OTHER -> 0%", other_rate({"RESULTS": 10}), 0.0)
check("all OTHER -> 100%", other_rate({"OTHER": 5}), 100.0)

# --- is_overdue (per-row max_holding_days; judged vs ref_day, >= mirrors updater) ---
# ref_day is the last COMPLETED post-close trading day (caller passes report_date).
# Comparator is >= to mirror update_paper_trades.should_force_expire (holding_days
# >= max_hold): if a post-close run on ref_day should have expired it, it's overdue.
ref = date(2026, 6, 8)
check("MEDIUM(10) sig 05-28 -> held 11 >= 10 -> overdue", is_overdue(date(2026, 5, 28), 10, ref), True)
check("MEDIUM(10) sig 05-29 -> held 10 >= 10 -> overdue (>= boundary, mirrors updater)",
      is_overdue(date(2026, 5, 29), 10, ref), True)
check("MEDIUM(10) sig 05-30 -> held 9 < 10 -> not overdue", is_overdue(date(2026, 5, 30), 10, ref), False)
check("SHORT(3) sig 06-04 -> held 4 >= 3 -> overdue", is_overdue(date(2026, 6, 4), 3, ref), True)
check("SHORT(3) sig 06-05 -> held 3 >= 3 -> overdue (boundary)", is_overdue(date(2026, 6, 5), 3, ref), True)
check("SHORT(3) sig 06-06 -> held 2 < 3 -> not overdue", is_overdue(date(2026, 6, 6), 3, ref), False)
check("LONG(30) sig 05-28 -> held 11 < 30 -> not overdue", is_overdue(date(2026, 5, 28), 30, ref), False)
check("NULL max_hold -> default 10; sig 05-29 -> held 10 >= 10 -> overdue",
      is_overdue(date(2026, 5, 29), None, ref), True)
check("0 max_hold -> default 10; sig 05-30 -> held 9 < 10 -> not overdue",
      is_overdue(date(2026, 5, 30), 0, ref), False)

# --- reconcile (D4 identity; live numbers should pass) ---
ok, probs = reconcile(cash=832504.24, deployed=167495.76, total_equity=1000000.0,
                      ledger_deploy_sum=167495.76)
check("live numbers reconcile OK", ok, True)
check("live numbers no problems", probs, [])
# deploy mismatch
ok2, probs2 = reconcile(cash=832504.24, deployed=167495.76, total_equity=1000000.0,
                        ledger_deploy_sum=150000.0)
check("deploy mismatch -> not ok", ok2, False)
check_in("deploy mismatch message", " ".join(probs2), "deploy mismatch")
# equity mismatch
ok3, probs3 = reconcile(cash=800000.0, deployed=167495.76, total_equity=1000000.0,
                        ledger_deploy_sum=167495.76)
check("equity mismatch -> not ok", ok3, False)
check_in("equity mismatch message", " ".join(probs3), "equity mismatch")
# within tolerance (sub-rupee rounding)
ok4, _ = reconcile(cash=832504.24, deployed=167495.76, total_equity=1000000.5,
                   ledger_deploy_sum=167495.76, tol=1.0)
check("0.5 drift within tol -> ok", ok4, True)
# NULL coalescing doesn't crash
ok5, probs5 = reconcile(cash=None, deployed=None, total_equity=None, ledger_deploy_sum=None)
check("all-None coalesces to 0, identities hold -> ok", ok5, True)

# --- ledger_deploy_total ---
ledger = [
    {"txn_type": "DEPLOY", "amount_rs": -119876.76, "paper_trade_id": 160},
    {"txn_type": "DEPLOY", "amount_rs": -24855.0, "paper_trade_id": 161},
    {"txn_type": "DEPLOY", "amount_rs": -22764.0, "paper_trade_id": 162},
    {"txn_type": "PNL_REALIZED", "amount_rs": 5000.0, "paper_trade_id": 99},  # ignored (not DEPLOY)
    {"txn_type": "DEPLOY", "amount_rs": -9999.0, "paper_trade_id": 5},        # ignored (not open)
]
check("sum DEPLOY for open 160/161/162 = 167495.76",
      ledger_deploy_total(ledger, {160, 161, 162}), 167495.76)
check("no open ids -> 0", ledger_deploy_total(ledger, set()), 0.0)
check("NULL amount coalesced",
      ledger_deploy_total([{"txn_type": "DEPLOY", "amount_rs": None, "paper_trade_id": 1}], {1}), 0.0)

# --- format_health_alert ---
alert = format_health_alert(["Tier-0 stalled (42 min)", "backlog 25 > 20"], date(2026, 5, 29))
check_in("alert header", alert, "Health Monitor — 29-May-2026")
check_in("alert count", alert, "2 problem(s) detected:")
check_in("alert problem 1", alert, "• Tier-0 stalled (42 min)")
check_in("alert problem 2", alert, "• backlog 25 > 20")
check_in("alert footer", alert, "StockMarket-Brain Monitor")

# --- is_market_open (trading day + 9:15-15:30 IST) ---
# 2026-06-01 is Monday (trading day); 2026-05-30 is Saturday.
check("Mon 11:00 -> open", is_market_open(datetime(2026, 6, 1, 11, 0, tzinfo=IST)), True)
check("Mon 09:15 -> open (boundary)", is_market_open(datetime(2026, 6, 1, 9, 15, tzinfo=IST)), True)
check("Mon 15:30 -> open (boundary)", is_market_open(datetime(2026, 6, 1, 15, 30, tzinfo=IST)), True)
check("Mon 09:00 -> closed (pre-open)", is_market_open(datetime(2026, 6, 1, 9, 0, tzinfo=IST)), False)
check("Mon 16:00 -> closed (post-close)", is_market_open(datetime(2026, 6, 1, 16, 0, tzinfo=IST)), False)
check("Sat 11:00 -> closed (weekend)", is_market_open(datetime(2026, 5, 30, 11, 0, tzinfo=IST)), False)


def green_data(**override):
    """A live-realistic all-green data dict for evaluate(); override to perturb."""
    base = {
        "now": datetime(2026, 5, 29, 18, 0, tzinfo=IST),
        "today": date(2026, 5, 29),
        "report_date": date(2026, 5, 29),
        "is_market_open": False,            # stall check gated off
        "latest_classified": datetime(2026, 5, 29, 14, 21, tzinfo=IST),
        "backlog": 0,
        "event_counts": {"RESULTS": 10, "OTHER": 1},   # ~9% < 20%
        "portfolio": {"cash_available": 832504.24, "capital_deployed": 167495.76,
                      "total_equity": 1000000.0},
        "ledger_rows": [
            {"txn_type": "DEPLOY", "amount_rs": -119876.76, "paper_trade_id": 160},
            {"txn_type": "DEPLOY", "amount_rs": -24855.0, "paper_trade_id": 161},
            {"txn_type": "DEPLOY", "amount_rs": -22764.0, "paper_trade_id": 162},
        ],
        "open_trades": [
            {"id": 160, "ticker": "ASHOKLEY.NS", "signal_date": date(2026, 5, 28), "max_holding_days": 10},
            {"id": 161, "ticker": "GILLETTE.NS", "signal_date": date(2026, 5, 28), "max_holding_days": 3},
            {"id": 162, "ticker": "LUPIN.NS", "signal_date": date(2026, 5, 28), "max_holding_days": 10},
        ],
    }
    base.update(override)
    return base


# --- evaluate: all green -> no problems (mirrors live reality today) ---
check("green -> no problems", evaluate(green_data()), [])

# --- evaluate: each check fires exactly its own problem ---
stall = evaluate(green_data(is_market_open=True,
                            latest_classified=datetime(2026, 5, 29, 17, 0, tzinfo=IST)))
check("stall fires 1 problem", len(stall), 1)
check_in("stall message", stall[0], "Tier-0 stalled")

backlog = evaluate(green_data(backlog=25))
check("backlog fires 1", len(backlog), 1)
check_in("backlog message", backlog[0], "Tier-0F backlog: 25")

other = evaluate(green_data(event_counts={"OTHER": 5, "RESULTS": 5}))
check("OTHER rate fires 1", len(other), 1)
check_in("OTHER message", other[0], "OTHER rate 50%")

recon = evaluate(green_data(portfolio={"cash_available": 832504.24,
                                       "capital_deployed": 150000.0,
                                       "total_equity": 1000000.0}))
# deploy mismatch (150000 != ledger 167495.76) AND equity mismatch (832504.24+150000 != 1e6)
check("reconcile fires >=1", len(recon) >= 1, True)
check_in("reconcile message", " ".join(recon), "Capital reconciliation")

orphan = evaluate(green_data(ledger_rows=[
    {"txn_type": "DEPLOY", "amount_rs": -119876.76, "paper_trade_id": 160},
    {"txn_type": "DEPLOY", "amount_rs": -24855.0, "paper_trade_id": 161},
    # 162's DEPLOY missing -> orphan + deploy-sum mismatch
]))
check_in("orphan message present", " ".join(orphan), "Insert/deploy failure: OPEN trade 162")

# Check 6 judges overdue against report_date (last COMPLETED post-close trading
# day), NOT calendar today -- the updater only expires at a post-close run and the
# monitor runs ~09:00 (before the same-day 15:30 expiry). open_trades keep ids
# 160/161/162 so the ledger DEPLOY rows above keep checks 4/5 green; we isolate
# Check 6. GILLETTE id 161 signal Wed 2026-05-27, max_hold 3.
gillette_open = [
    {"id": 160, "ticker": "ASHOKLEY.NS", "signal_date": date(2026, 5, 28), "max_holding_days": 10},
    {"id": 161, "ticker": "GILLETTE.NS", "signal_date": date(2026, 5, 27), "max_holding_days": 3},
    {"id": 162, "ticker": "LUPIN.NS", "signal_date": date(2026, 5, 28), "max_holding_days": 10},
]

# Weekend false-positive SUPPRESSED: Mon 2026-06-01 09:00 run. report_date =
# last_market_day = Fri 2026-05-29; GILLETTE held_at_ref = 05-29-05-27 = 2 < 3.
# (Calendar today 06-01 would give 5 > 3 -- the OLD bug this fix removes.)
weekend = evaluate(green_data(today=date(2026, 6, 1), report_date=date(2026, 5, 29),
                              is_market_open=False, open_trades=gillette_open))
check("GILLETTE weekend false-positive suppressed -> no problems", weekend, [])

# Genuine failure: Tue 2026-06-02 09:00 and GILLETTE STILL open -> Monday's
# post-close run should have expired it. report_date = Mon 2026-06-01;
# held_at_ref = 06-01-05-27 = 5 >= 3 -> overdue (only GILLETTE; 160/162 held 4 < 10).
genuine = evaluate(green_data(today=date(2026, 6, 2), report_date=date(2026, 6, 1),
                              is_market_open=False, open_trades=gillette_open))
genuine_msgs = [p for p in genuine if p.startswith("Overdue:")]
check("genuine failure: exactly 1 overdue", len(genuine_msgs), 1)
check_in("genuine overdue names GILLETTE", genuine_msgs[0], "GILLETTE.NS")
check_in("genuine overdue names max_holding_days", genuine_msgs[0], "max_holding_days")
check_in("genuine overdue names the post-close trading day", genuine_msgs[0], "2026-06-01")

# Far-future report_date -> all 3 overdue (default fixture signals 05-28).
overdue = evaluate(green_data(report_date=date(2026, 6, 30)))
overdue_msgs = [p for p in overdue if p.startswith("Overdue:")]
check("all 3 overdue", len(overdue_msgs), 3)
check_in("overdue message", overdue_msgs[0], "max_holding_days")

print("ALL TESTS PASSED")

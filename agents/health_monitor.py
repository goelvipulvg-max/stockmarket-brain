"""StockMarket-Brain | Health Monitor (Phase 8, master plan §10.2).

Daily ~9 AM IST (cron 30 3 * * 1-5). ALERT-ON-PROBLEM ONLY: sends a Telegram
message only when >=1 check fails; silent (exit 0) when all green. (Contrast
agents/daily_summary.py §10.3, which always sends a proof-of-life digest.)

Six checks (all read SUPABASE):
  1. Tier-0 stalled         -- filings_log.classified_at gap during market hours
  2. Tier-0F backlog > N    -- unpicked material filings (windowed)
  3. OTHER rate > X%        -- filings_log.event_type classification quality
  4. Capital reconciliation -- D4 ledger<->portfolio identity (TIER2F-scoped)
  5. Insert failures        -- orphan-trade proxy (D1: OPEN TIER2F w/ no DEPLOY)
  6. Trades past max_holding_days -- per-row window (matches db4eaae)

  python -m agents.health_monitor            # run checks; send Telegram only if a problem
  python -m agents.health_monitor --dry-run  # print result, never send

Pure helpers (is_stalled, other_rate, is_overdue, reconcile, evaluate, …) are
DB-free and unit-tested in tests/test_health_monitor.py; gather_health_data is
the only DB reader. Shared helpers (last_market_day, fmt_rs) come from
utils.monitor_format -- this agent never imports agents/daily_summary.
"""
import os
import argparse
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.telegram_client import send_message
from utils.supabase_client import get_client
from utils import trading_calendar
from utils.monitor_format import last_market_day, fmt_rs

IST = ZoneInfo("Asia/Kolkata")
# NSE continuous session (used only to gate the Tier-0 stall check).
MARKET_OPEN_TIME = dt_time(9, 15)
MARKET_CLOSE_TIME = dt_time(15, 30)

# ---------------------------------------------------------------------------
# Tunable thresholds (master-plan §10.2 defaults; change here, not in logic)
# ---------------------------------------------------------------------------
STALL_THRESHOLD_MIN = 30        # Tier-0 stalled if no new filing for >30 min (market hours)
BACKLOG_THRESHOLD = 20          # alert if >20 unpicked material filings...
BACKLOG_WINDOW_HOURS = 2        # ...within the last 2h (ignore stale older backlog)
OTHER_RATE_THRESHOLD_PCT = 20.0 # alert if OTHER classification rate >20%
RECONCILE_TOLERANCE_RS = 1.0    # capital identity allowed drift (rounding)
DEFAULT_HOLDING_DAYS = 10       # fallback when a row's max_holding_days is NULL (matches db4eaae)

# Shared scoping (mirror daily_summary / tier0f_poller / update_paper_trades)
LIVE_SOURCE = "TIER2F"
OTHER_EVENT_TYPE = "OTHER"


def _num(v):
    """Coerce to float; None/garbage -> 0.0 (defensive NULL coalescing)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Pure check helpers (no I/O -- unit-tested)
# ---------------------------------------------------------------------------

def is_stalled(latest_classified, now, is_market_open,
               threshold_min: int = STALL_THRESHOLD_MIN) -> bool:
    """Tier-0 stall check. True only DURING market hours.

    - Outside market hours -> False (no weekend/holiday false alarms).
    - In market hours, no filings at all (latest None) -> True (stalled).
    - In market hours -> True if now - latest_classified > threshold_min.
    Both datetimes must share tz-awareness (caller's responsibility).
    """
    if not is_market_open:
        return False
    if latest_classified is None:
        return True
    gap_min = (now - latest_classified).total_seconds() / 60.0
    return gap_min > threshold_min


def other_rate(event_type_counts: dict):
    """OTHER classification rate as a percent, or None when no filings (div-0 guard).

    `event_type_counts` maps event_type -> count over the measurement window.
    """
    total = sum(event_type_counts.values())
    if total == 0:
        return None
    return event_type_counts.get(OTHER_EVENT_TYPE, 0) / total * 100.0


def is_overdue(signal_date: date, max_holding_days, ref_day: date) -> bool:
    """True if a post-close run on `ref_day` should already have EXPIRED this trade.

    `ref_day` is the last COMPLETED post-close trading day (caller passes
    report_date = last_market_day(today)) -- NOT calendar today. The updater only
    force-expires at a >=15:30 IST run (update_paper_trades.should_force_expire:
    is_market_close AND holding_days >= max_hold) and this monitor runs ~09:00,
    before the same-day expiry. Judging vs calendar today therefore flags trades a
    full trading day early -- and over a weekend/holiday it false-alarms on trades
    that no run has yet had the chance to expire.

    Comparator is >= to MIRROR should_force_expire exactly (held >= max_hold), so a
    still-OPEN trade here means a completed post-close run genuinely failed to
    expire it. max_holding_days NULL/0/missing -> DEFAULT_HOLDING_DAYS (matches the
    updater's fallback). Calendar-day delta, matching holding_days upstream.
    """
    max_hold = max_holding_days or DEFAULT_HOLDING_DAYS
    return (ref_day - signal_date).days >= max_hold


def reconcile(cash, deployed, total_equity, ledger_deploy_sum,
              tol: float = RECONCILE_TOLERANCE_RS):
    """D4 capital reconciliation. Returns (ok: bool, problems: list[str]).

    Enforces the two identities that hold live (TIER2F-scoped; legacy NULLs
    coalesced to 0 via _num):
      (1) Sum of |ledger DEPLOY (open)| == portfolio.capital_deployed
      (2) cash_available + capital_deployed == total_equity   (no MTM, D4)
    """
    cash = _num(cash)
    deployed = _num(deployed)
    te = _num(total_equity)
    lds = _num(ledger_deploy_sum)
    problems = []
    if abs(lds - deployed) > tol:
        problems.append(
            f"deploy mismatch: Σ|ledger DEPLOY| {fmt_rs(lds)} != capital_deployed {fmt_rs(deployed)}"
        )
    if abs((cash + deployed) - te) > tol:
        problems.append(
            f"equity mismatch: cash {fmt_rs(cash)} + deployed {fmt_rs(deployed)} != total_equity {fmt_rs(te)}"
        )
    return (len(problems) == 0, problems)


def ledger_deploy_total(ledger_rows, open_trade_ids) -> float:
    """Σ|amount_rs| of DEPLOY ledger rows whose paper_trade_id is an OPEN trade.

    Pure aggregation over already-fetched rows (NULL amounts coalesced to 0).
    `open_trade_ids` is the set of currently-OPEN TIER2F paper_trade ids.
    """
    ids = set(open_trade_ids)
    total = 0.0
    for r in ledger_rows:
        if r.get("txn_type") == "DEPLOY" and r.get("paper_trade_id") in ids:
            total += abs(_num(r.get("amount_rs")))
    return round(total, 2)


def format_health_alert(problems: list, report_date: date = None) -> str:
    """Build the alert-on-problem Telegram text. Caller sends only if problems.

    `problems` is a list of one-line problem strings from the checks.
    """
    stamp = report_date.strftime("%d-%b-%Y") if report_date else ""
    head = f"🚨 <b>Health Monitor — {stamp}</b>" if stamp else "🚨 <b>Health Monitor</b>"
    lines = [head, "", f"<b>{len(problems)} problem(s) detected:</b>"]
    for p in problems:
        lines.append(f"  • {p}")
    lines.append("")
    lines.append("🧠 StockMarket-Brain Monitor")
    return "\n".join(lines)


def is_market_open(now_ist: datetime) -> bool:
    """True if `now_ist` is within NSE continuous hours on a trading day.

    Deterministic (trading calendar + clock); no DB. Gates the stall check so
    it never fires on weekends/holidays or before-open/after-close.
    """
    if not trading_calendar.is_trading_day(now_ist.date()):
        return False
    return MARKET_OPEN_TIME <= now_ist.time() <= MARKET_CLOSE_TIME


def _stall_gap_min(latest_classified, now) -> int:
    """Whole minutes since the last classified filing (0 if unknown)."""
    if latest_classified is None:
        return 0
    return int((now - latest_classified).total_seconds() / 60)


# ---------------------------------------------------------------------------
# evaluate() -- pure orchestration of the 6 checks (no I/O; unit-tested).
# Takes a plain data dict (from gather_health_data) and returns problem strings.
# ---------------------------------------------------------------------------

def evaluate(data: dict) -> list:
    """Run all 6 checks over an already-fetched data dict. Returns problems[]."""
    problems = []

    # 1. Tier-0 stalled (market-hours-gated)
    if is_stalled(data["latest_classified"], data["now"], data["is_market_open"]):
        gap = _stall_gap_min(data["latest_classified"], data["now"])
        detail = f"{gap} min" if data["latest_classified"] else "no filings today"
        problems.append(f"Tier-0 stalled: {detail} since last filing (>{STALL_THRESHOLD_MIN} min, market hours)")

    # 2. Tier-0F backlog (windowed)
    if data["backlog"] > BACKLOG_THRESHOLD:
        problems.append(
            f"Tier-0F backlog: {data['backlog']} unpicked material filings "
            f"in last {BACKLOG_WINDOW_HOURS}h (>{BACKLOG_THRESHOLD})"
        )

    # 3. OTHER classification rate (last market day)
    rate = other_rate(data["event_counts"])
    if rate is not None and rate > OTHER_RATE_THRESHOLD_PCT:
        problems.append(
            f"OTHER rate {rate:.0f}% on {data['report_date'].isoformat()} "
            f"(>{OTHER_RATE_THRESHOLD_PCT:.0f}%)"
        )

    # 4. Capital reconciliation (D4 identity, TIER2F-scoped)
    pf = data["portfolio"]
    open_ids = {t["id"] for t in data["open_trades"]}
    deploy_sum = ledger_deploy_total(data["ledger_rows"], open_ids)
    ok, recon_probs = reconcile(
        pf.get("cash_available"), pf.get("capital_deployed"),
        pf.get("total_equity"), deploy_sum,
    )
    for p in recon_probs:
        problems.append(f"Capital reconciliation: {p}")

    # 5. Insert/deploy failures -- orphan-trade proxy (D1)
    deployed_ids = {
        r.get("paper_trade_id") for r in data["ledger_rows"]
        if r.get("txn_type") == "DEPLOY"
    }
    for t in data["open_trades"]:
        if t["id"] not in deployed_ids:
            problems.append(
                f"Insert/deploy failure: OPEN trade {t['id']} ({t.get('ticker')}) "
                f"has no capital_ledger DEPLOY row"
            )

    # 6. Trades past max_holding_days (per-row, db4eaae). Judged vs report_date =
    # the last COMPLETED post-close trading day, NOT calendar today: the updater
    # only expires at a >=15:30 IST run and this monitor runs ~09:00. This
    # suppresses weekend/holiday false-positives (no run has had the chance to
    # expire) while still catching a genuine missed expiry on a completed run.
    ref_day = data["report_date"]
    for t in data["open_trades"]:
        if is_overdue(t["signal_date"], t.get("max_holding_days"), ref_day):
            held = (ref_day - t["signal_date"]).days
            cap = t.get("max_holding_days") or DEFAULT_HOLDING_DAYS
            problems.append(
                f"Overdue: {t.get('ticker')} (trade {t['id']}) held {held}d "
                f">= max_holding_days {cap} as of post-close {ref_day.isoformat()}"
            )

    return problems


# ---------------------------------------------------------------------------
# gather_health_data() -- the only DB reader (SUPABASE, read-only).
# ---------------------------------------------------------------------------

def _parse_ts(s):
    """Parse a Supabase timestamptz string to a tz-aware datetime, or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def gather_health_data(sb, now_ist: datetime) -> dict:
    """Fetch everything the 6 checks need from SUPABASE (read-only).

    TIMEZONE: filings_log.classified_at is stored tz-AWARE UTC (DB default
    NOW(); verified live e.g. '2026-05-29T14:21:42+00:00'). `now_ist` is tz-aware
    IST. All classified_at comparisons stay tz-aware so Postgres converts the
    backlog cutoff correctly AND is_stalled's (now - latest_classified) is a
    valid aware-minus-aware subtraction. Do NOT strip tz -- a naive cutoff vs a
    timestamptz column breaks the 2h window, and naive-minus-aware raises.
    """
    today = now_ist.date()
    report_date = last_market_day(today)
    rd_lo = report_date.isoformat()
    rd_hi = (report_date + timedelta(days=1)).isoformat()
    backlog_cutoff = (now_ist - timedelta(hours=BACKLOG_WINDOW_HOURS)).isoformat()

    # 1. Latest classified_at (Tier-0 liveness)
    latest_rows = sb.table("filings_log").select("classified_at") \
        .order("classified_at", desc=True).limit(1).execute().data
    latest_classified = _parse_ts(latest_rows[0]["classified_at"]) if latest_rows else None

    # 2. Backlog: unpicked material filings within the window (mirror tier0f_poller)
    backlog = sb.table("filings_log").select("id", count="exact") \
        .eq("is_material", True).gte("material_score", 6) \
        .eq("picked_by_tier0f", False).gte("classified_at", backlog_cutoff) \
        .limit(1).execute().count or 0

    # 3. Event-type counts over the last market day (for OTHER rate)
    et_rows = sb.table("filings_log").select("event_type") \
        .gte("classified_at", rd_lo).lt("classified_at", rd_hi).execute().data
    event_counts = {}
    for r in et_rows:
        et = r.get("event_type")
        event_counts[et] = event_counts.get(et, 0) + 1

    # 4. Portfolio latest row
    pf_rows = sb.table("portfolio").select("*").order("id", desc=True).limit(1).execute().data
    portfolio = pf_rows[0] if pf_rows else {}

    # 4/5. Capital ledger rows (DEPLOY linkage for reconcile + orphan proxy)
    ledger_rows = sb.table("capital_ledger") \
        .select("paper_trade_id,txn_type,amount_rs").execute().data

    # 5/6. OPEN TIER2F trades (orphan proxy + overdue)
    open_raw = sb.table("paper_trades") \
        .select("id,ticker,signal_date,max_holding_days") \
        .eq("source", LIVE_SOURCE).eq("status", "OPEN").execute().data
    open_trades = []
    for t in open_raw:
        sd = t.get("signal_date")
        open_trades.append({
            "id": t["id"],
            "ticker": t.get("ticker"),
            "signal_date": date.fromisoformat(sd) if sd else today,
            "max_holding_days": t.get("max_holding_days"),
        })

    return {
        "now": now_ist,
        "today": today,
        "report_date": report_date,
        "is_market_open": is_market_open(now_ist),
        "latest_classified": latest_classified,
        "backlog": backlog,
        "event_counts": event_counts,
        "portfolio": portfolio,
        "ledger_rows": ledger_rows,
        "open_trades": open_trades,
    }


def run(dry_run: bool = False) -> list:
    """Gather -> evaluate -> alert ONLY if problems. Returns the problems list."""
    sb = get_client()
    now_ist = datetime.now(IST)
    data = gather_health_data(sb, now_ist)
    problems = evaluate(data)

    if not problems:
        print(f"[health] all green ({now_ist.strftime('%Y-%m-%d %H:%M IST')}) -- no alert sent")
        return problems

    text = format_health_alert(problems, data["report_date"])
    print(text)
    if dry_run:
        print("\n[DRY-RUN] not sent.")
        return problems
    send_message(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_TIER3_CHANNEL"),
        text=text,
        parse_mode="HTML",
    )
    print("\n[sent]")
    return problems


def main():
    parser = argparse.ArgumentParser(description="StockMarket-Brain health monitor (§10.2)")
    parser.add_argument("--dry-run", action="store_true", help="print result, never send")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

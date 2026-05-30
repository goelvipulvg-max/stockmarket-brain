"""StockMarket-Brain | Daily Summary (Phase 8, master plan §10.3).

Morning digest sent ~8 AM IST (cron 30 2 * * 1-5). ALWAYS sends (proof-of-life
that the monitoring layer is alive), unlike health_monitor which is silent when
green.

  python -m agents.daily_summary            # build + send
  python -m agents.daily_summary --dry-run  # print only, no Telegram send

Reads SUPABASE only (filings_log, paper_trades, portfolio, paper_trades_queue).
Reuses utils.expectancy.compute_expectancy (TIER2F-scoped) for the win-rate line.
Pure helpers (last_market_day, fmt_rs, format_winrate_line, format_summary) are
DB-free and unit-tested in tests/test_daily_summary.py.
"""

import os
import sys
import argparse
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv(override=True)

# Local-console safety: Windows' default cp1252 stdout crashes on the digest's
# emoji when printed (UnicodeEncodeError). Reconfigure stdout to UTF-8 so local
# --dry-run works without PYTHONUTF8. Guarded -- never raises if stdout is absent
# or lacks reconfigure (e.g. redirected/captured streams). Does NOT affect the
# Telegram payload: send_message json-encodes UTF-8 itself (telegram_client.py:20).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError, OSError):
    pass

from utils.telegram_client import send_message
from utils.supabase_client import get_client
from utils.expectancy import compute_expectancy
from utils import trading_calendar

# Mirrors tier0f_poller.py tradeable gate + tier4_memory_manager resolved set.
SIGNAL_CONF_FLOOR = 60
LIVE_SOURCE = "TIER2F"
RESOLVED_STATUSES = ["TARGET_HIT", "SL_HIT", "EXPIRED"]
# compute_expectancy reads exactly these fields (verified expectancy.py:43/104-105/126/147-148/160).
EXPECTANCY_COLS = "pnl_pct,entry_price,exit_price,stop_loss,quantity"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O -- unit-tested)
# ---------------------------------------------------------------------------

def last_market_day(today: date) -> date:
    """Most recent NSE trading day strictly before `today`.

    The 8 AM digest reports the previous session: Tue->Mon, Mon->Fri (skips the
    weekend), and skips NSE holidays. Walks back day-by-day (bounded).
    """
    d = today - timedelta(days=1)
    for _ in range(10):  # generous bound: covers any weekend+holiday cluster
        if trading_calendar.is_trading_day(d):
            return d
        d = d - timedelta(days=1)
    return d  # fallback: 10 consecutive non-trading days is implausible


def fmt_rs(v) -> str:
    """Indian-style plain rupee formatting, e.g. 1000000 -> 'Rs.10,00,000'.

    None / non-numeric -> 'N/A'. Rounds to whole rupees.
    """
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "N/A"
    neg = n < 0
    s = str(int(abs(round(n))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-Rs." if neg else "Rs.") + s


def format_winrate_line(exp: dict) -> str:
    """One-line win-rate/expectancy summary from a compute_expectancy() dict.

    Graceful at n=0 (no resolved TIER2F trades yet); flags small samples.
    """
    n = exp.get("n", 0)
    if not n:
        return "Win rate: n/a (no resolved TIER2F trades yet)"
    wr = exp.get("win_rate")
    wr_s = f"{wr * 100:.0f}%" if wr is not None else "N/A"
    exp_pct = exp.get("expectancy_pct")
    exp_s = f"{exp_pct:+.2f}%/trade" if exp_pct is not None else "N/A"
    line = (f"Win rate: {wr_s} ({exp.get('n_win', 0)}W/{exp.get('n_loss', 0)}L "
            f"of {n}) | Expectancy: {exp_s}")
    if exp.get("preliminary"):
        line += " (!) preliminary"
    return line


def format_summary(data: dict) -> str:
    """Render the §10.3 digest text from a plain data dict (no I/O).

    Keys: report_date (date), filings, signals, trades, queue (int);
    cash, deployed, equity, realized (num); open_positions (int);
    winrate_line (str).
    """
    d = data["report_date"]
    return "\n".join([
        f"📊 <b>Daily Summary — {d.strftime('%d-%b-%Y')}</b>",
        "",
        f"<b>Last session ({d.strftime('%a %d-%b')}):</b>",
        f"  Filings classified: {data['filings']}",
        f"  Tradeable signals (mat. &amp; conf≥{SIGNAL_CONF_FLOOR}): {data['signals']}",
        f"  New TIER2F trades: {data['trades']}",
        "",
        "<b>Today:</b>",
        f"  Queue: {data['queue']}",
        "",
        "<b>Portfolio:</b>",
        f"  Equity: {fmt_rs(data['equity'])}  "
        f"(cash {fmt_rs(data['cash'])} + deployed {fmt_rs(data['deployed'])})",
        f"  Open positions: {data['open_positions']}",
        f"  Realized P&amp;L: {fmt_rs(data['realized'])}",
        f"  {data['winrate_line']}",
        "",
        "🧠 StockMarket-Brain Monitor",
    ])


# ---------------------------------------------------------------------------
# DB reader (thin wrapper -- exercised via --dry-run)
# ---------------------------------------------------------------------------

def gather_summary_data(sb, today: date) -> dict:
    """Collect all §10.3 numbers from SUPABASE (read-only)."""
    report_date = last_market_day(today)
    day_lo = report_date.isoformat()
    day_hi = (report_date + timedelta(days=1)).isoformat()

    filings = sb.table("filings_log").select("id", count="exact") \
        .gte("classified_at", day_lo).lt("classified_at", day_hi) \
        .limit(1).execute().count or 0

    signals = sb.table("filings_log").select("id", count="exact") \
        .eq("is_material", True).gte("trade_confidence", SIGNAL_CONF_FLOOR) \
        .gte("classified_at", day_lo).lt("classified_at", day_hi) \
        .limit(1).execute().count or 0

    trades = sb.table("paper_trades").select("id", count="exact") \
        .eq("source", LIVE_SOURCE).eq("signal_date", report_date.isoformat()) \
        .limit(1).execute().count or 0

    # Queue: total row count (enum-agnostic -- no producer yet; 'QUEUED' is doc-only).
    queue = sb.table("paper_trades_queue").select("id", count="exact") \
        .limit(1).execute().count or 0

    pf_rows = sb.table("portfolio").select("*").order("id", desc=True).limit(1).execute().data
    pf = pf_rows[0] if pf_rows else {}

    resolved_rows = sb.table("paper_trades").select(EXPECTANCY_COLS + ",status") \
        .eq("source", LIVE_SOURCE).in_("status", RESOLVED_STATUSES).execute().data
    resolved = [r for r in resolved_rows if r.get("pnl_pct") is not None]
    exp = compute_expectancy(resolved)

    return {
        "report_date": report_date,
        "filings": filings,
        "signals": signals,
        "trades": trades,
        "queue": queue,
        "cash": pf.get("cash_available"),
        "deployed": pf.get("capital_deployed"),
        "equity": pf.get("total_equity"),
        "realized": pf.get("realized_pnl_rs"),
        "open_positions": pf.get("open_positions"),
        "winrate_line": format_winrate_line(exp),
    }


def run(dry_run: bool = False) -> str:
    """Build the digest and (unless dry-run) ALWAYS send it -- proof-of-life."""
    sb = get_client()
    data = gather_summary_data(sb, trading_calendar.today())
    text = format_summary(data)
    print(text)
    if dry_run:
        print("\n[DRY-RUN] not sent.")
        return text
    send_message(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_TIER3_CHANNEL"),
        text=text,
        parse_mode="HTML",
    )
    print("\n[sent]")
    return text


def main():
    parser = argparse.ArgumentParser(description="StockMarket-Brain daily summary (§10.3)")
    parser.add_argument("--dry-run", action="store_true", help="print only, no Telegram send")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

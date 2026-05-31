"""Shared pure helpers for the Phase 8 monitoring agents (master plan §10).

Imported by BOTH agents/daily_summary.py (§10.3) and agents/health_monitor.py
(§10.2). The two agents import from here and never from each other. No network
I/O — `last_market_day` uses only the deterministic NSE trading calendar.
"""
from datetime import date, timedelta

from utils import trading_calendar


def last_market_day(today: date) -> date:
    """Most recent NSE trading day strictly before `today`.

    Tue->Mon, Mon->Fri (skips the weekend), and skips NSE holidays. Walks back
    day-by-day, bounded (10 consecutive non-trading days is implausible).
    """
    d = today - timedelta(days=1)
    for _ in range(10):
        if trading_calendar.is_trading_day(d):
            return d
        d = d - timedelta(days=1)
    return d


def fmt_rs(v) -> str:
    """Indian-style plain rupee formatting, e.g. 1000000 -> 'Rs.10,00,000'.

    None / non-numeric -> 'N/A'. Rounds to whole rupees. Negative -> '-Rs.…'.
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

"""
NSE Trading-Day Calendar — Phase 3, v3.1 Master Plan §6 (Batch A1).
Weekend + NSE-holiday aware. Gate V3.4.

Uses pandas-market-calendars get_calendar('NSE'). NSE/BSE/XNSE are aliases
for one BSEExchangeCalendar — cal.name returns 'BSE' but the holiday list is
correct for NSE (verified: 246 trading days 2026, Republic Day / Holi /
Independence Day / Gandhi Jayanti all marked holiday). Do NOT switch to
'XBSE' — that is the Bulgarian exchange.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

IST = ZoneInfo("Asia/Kolkata")

# History floor for the cached schedule. B1 survivorship backfill resolves
# 2024-25 historical filing/exit dates, which the old current-year-only start
# silently mis-classified as non-trading days (P2-5). Bump if backfill predates.
_HISTORY_START_YEAR = 2024

_calendar = mcal.get_calendar("NSE")
_schedule: pd.DataFrame | None = None
_schedule_end_year: int | None = None


def _ensure_schedule():
    """Pre-compute schedule from _HISTORY_START_YEAR through end of next
    calendar year, cached. The wide start covers historical backfill (2024+,
    P2-5) as well as the forward horizon; queries for any single date are
    unaffected by the extra years in the index."""
    global _schedule, _schedule_end_year
    this_year = datetime.now(IST).year
    needed = this_year + 1  # cover current + next year
    if _schedule is not None and _schedule_end_year == needed:
        return
    _schedule = _calendar.schedule(
        start_date=date(_HISTORY_START_YEAR, 1, 1),
        end_date=date(needed + 1, 1, 1),
    )
    _schedule_end_year = needed


def is_trading_day(d: date) -> bool:
    """Return True if `d` is an NSE trading day (open)."""
    _ensure_schedule()
    ts = pd.Timestamp(d)
    return ts in _schedule.index


def today() -> date:
    """Return today's date in IST."""
    return datetime.now(IST).date()


def next_trading_day(d: date) -> date:
    """Return the next NSE trading day strictly after `d` (excludes `d`)."""
    _ensure_schedule()
    ts = pd.Timestamp(d) + pd.Timedelta(days=1)
    future = _schedule[_schedule.index >= ts]
    if len(future) == 0:
        raise ValueError(f"No trading days found after {d} in schedule")
    return future.index[0].date()


def add_trading_days(d: date, n: int) -> date:
    """Return `d` plus `n` NSE trading days, strictly forward (d excluded).

    n = 0  → `d` itself if trading day, else the next trading day after `d`.
    n = 1  → first trading day strictly after `d` (same as next_trading_day).
    n = 5  → fifth trading day strictly after `d`.
    n < 0  → ValueError.

    Filing Friday 2026-01-09 + 5 → Mon 2026-01-16 (9th excluded; 12,13,14,15,16).
    """
    if n < 0:
        raise ValueError("n must be >= 0")

    _ensure_schedule()
    ts = pd.Timestamp(d)

    if n == 0:
        # Clamp to a trading day: d itself if open, else the next open
        future = _schedule[_schedule.index >= ts]
    else:
        # Strictly after d — d is excluded from the count
        future = _schedule[_schedule.index > ts]

    if len(future) == 0:
        raise ValueError(f"No trading days found from {d} in schedule")

    idx = max(n - 1, 0) if n > 0 else 0
    idx = min(idx, len(future) - 1)
    return future.index[idx].date()

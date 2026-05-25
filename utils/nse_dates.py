"""NSE date parsing utilities for stockmarket-brain.

Parses NSE announcement timestamps (an_dt) into timezone-aware
datetime objects suitable for Postgres TIMESTAMPTZ columns.

NSE an_dt format: "07-May-2026 14:59:20" (IST naive wall-clock)
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

IST = ZoneInfo("Asia/Kolkata")

NSE_DATETIME_FORMATS = [
    "%d-%b-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d-%b-%Y",
    "%Y-%m-%d",
]


def parse_nse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse NSE an_dt string to IST timezone-aware datetime.

    Args:
        date_str: Raw NSE timestamp string (e.g. "07-May-2026 14:59:20")
                  May be None, empty, or malformed - returns None safely.

    Returns:
        Timezone-aware datetime in IST, or None if parse fails.
        Safe to pass directly to supabase-py for TIMESTAMPTZ columns.

    Examples:
        >>> parse_nse_datetime("07-May-2026 14:59:20")
        datetime(2026, 5, 7, 14, 59, 20, tzinfo=ZoneInfo('Asia/Kolkata'))

        >>> parse_nse_datetime("")
        None

        >>> parse_nse_datetime(None)
        None
    """
    if not date_str:
        return None

    s = date_str.strip()
    if not s:
        return None

    for fmt in NSE_DATETIME_FORMATS:
        try:
            naive_dt = datetime.strptime(s, fmt)
            return naive_dt.replace(tzinfo=IST)
        except ValueError:
            continue

    return None

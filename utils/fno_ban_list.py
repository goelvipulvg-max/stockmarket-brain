"""
NSE F&O Ban List — Phase 3, v3.1 Master Plan §6 (Batch A4).
2-hour cached fetch from NSE archives. Gate V3.3.

Source: https://archives.nseindia.com/content/fo/fo_secban.csv
FAIL-OPEN: any error (network, parse, timeout) returns empty / not-banned.
Never blocks a trade because the ban list was unreachable.
"""
import csv
import io
import time
from datetime import datetime, timedelta

from curl_cffi import requests as curl_requests

_BAN_LIST_URL = "https://archives.nseindia.com/content/fo/fo_secban.csv"
_CACHE_TTL_HOURS = 2

_cache: set | None = None
_cache_time: datetime | None = None
_session = curl_requests.Session(impersonate="chrome124")


def _fetch_ban_list() -> set:
    """Fetch and parse the ban list CSV. Returns a set of uppercase symbols.

    NSE format (no standard header):
      Line 0: "Securities in Ban For Trade Date DD-MON-YYYY:"
      Line 1+: INDEX,SYMBOL
    """
    r = _session.get(_BAN_LIST_URL, timeout=15)
    r.raise_for_status()

    reader = csv.reader(io.StringIO(r.text))
    rows = [row for row in reader if row]  # skip empty
    if not rows:
        return set()

    banned = set()
    for row in rows:
        if len(row) < 2:
            continue
        # Skip title/header rows (non-numeric first column)
        maybe_symbol = (row[1] or "").strip().upper()
        if not maybe_symbol or maybe_symbol in ("SYMBOL", "SECURITIES IN BAN"):
            continue
        banned.add(maybe_symbol)

    return banned


def _ensure_cache():
    """Refresh the ban-list cache if stale or uninitialised."""
    global _cache, _cache_time
    now = datetime.now()
    if _cache is not None and _cache_time is not None:
        if now - _cache_time < timedelta(hours=_CACHE_TTL_HOURS):
            return  # cache is fresh
    # Fetch — fail-open: any error → empty set, never raise
    try:
        _cache = _fetch_ban_list()
        _cache_time = now
    except Exception:
        _cache = set()
        _cache_time = now


def get_ban_list() -> list:
    """Return list of currently banned F&O symbols. Empty list on failure."""
    _ensure_cache()
    return sorted(_cache)


def is_in_ban(symbol: str) -> bool:
    """Return True if `symbol` is in the current F&O ban list.

    Fails open — returns False on any fetch/parse error.
    """
    _ensure_cache()
    return symbol.upper().strip() in _cache

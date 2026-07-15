#!/usr/bin/env python
"""
sync_nse500.py — Weekly Sunday sync.

Fetches live NSE 500 list from NSE CSV, diffs against nse500_watchlist
in Neon DB, and backfills 2 years of NSE corporate filings for
NEW and REACTIVATED companies using the same pipeline as
historical_preloader.py.

Reuses these functions verbatim from historical_preloader.py:
  get_nse_session, fetch_nse_announcements, classify_event_type,
  summarize_announcement, insert_research_cache, insert_event_outcome,
  compute_price_impact, parse_nse_date

Usage:
    .venv/Scripts/python.exe scripts/sync_nse500.py
    .venv/Scripts/python.exe scripts/sync_nse500.py --dry-run
"""

import csv
import os
import sys
import time
import traceback
import importlib.util
from datetime import date, datetime, timedelta
from io import StringIO

import pandas as pd
import psycopg2
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Load historical_preloader functions via importlib ──────────────────
_HP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical_preloader.py")
_spec = importlib.util.spec_from_file_location("historical_preloader", _HP_PATH)
_hp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hp)

get_nse_session         = _hp.get_nse_session
fetch_nse_announcements = _hp.fetch_nse_announcements
classify_event_type     = _hp.classify_event_type
summarize_announcement  = _hp.summarize_announcement
insert_research_cache   = _hp.insert_research_cache
insert_event_outcome    = _hp.insert_event_outcome
compute_price_impact    = _hp.compute_price_impact
parse_nse_date          = _hp.parse_nse_date

# ── Config ─────────────────────────────────────────────────────────────
DRY_RUN = "--dry-run" in sys.argv
LIMIT = None
for arg in sys.argv:
    if arg.startswith("--limit="):
        LIMIT = int(arg.split("=", 1)[1])
NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NSE_CSV_TIMEOUT = 30
TWO_YEARS_AGO = datetime.now() - timedelta(days=730)
MAX_ANNOUNCEMENTS_PER_COMPANY = 190
ANNOUNCEMENT_SLEEP = 0.5
BATCH_SLEEP = 1.0


# ═══════════════════════════════════════════════════════════════════════
# STEP 1 — Fetch live NSE 500
# ═══════════════════════════════════════════════════════════════════════

def fetch_live_nifty500():
    """Download NSE Nifty 500 CSV, return set of bare symbols (no .NS)."""
    print("[1/6] Fetching live Nifty 500 list...")
    try:
        resp = requests.get(NIFTY500_CSV_URL, timeout=NSE_CSV_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"  FATAL: Could not fetch Nifty 500 CSV: {e}")
        sys.exit(1)

    reader = csv.DictReader(StringIO(resp.text))
    symbols = set()
    for row in reader:
        sym = (row.get("Symbol") or row.get("symbol") or "").strip()
        if sym:
            sym = sym.replace(".NS", "").replace(".ns", "")
            symbols.add(sym)

    if not symbols:
        print("  FATAL: Nifty 500 CSV was empty — aborting")
        sys.exit(1)

    print(f"  Got {len(symbols)} live symbols from NSE")
    return symbols


# ═══════════════════════════════════════════════════════════════════════
# STEP 2 — Fetch current DB state
# ═══════════════════════════════════════════════════════════════════════

def fetch_watchlist(conn):
    """Return dict {symbol: status} from nse500_watchlist. Strips .NS for comparison."""
    cur = conn.cursor()
    cur.execute("SELECT symbol, status FROM nse500_watchlist")
    rows = cur.fetchall()
    cur.close()

    wl = {}
    for sym, st in rows:
        bare = sym.replace(".NS", "").replace(".ns", "")
        wl[bare] = st
    print(f"[2/6] Current watchlist: {len(wl)} symbols in DB")
    return wl


# ═══════════════════════════════════════════════════════════════════════
# STEP 5 — Backfill a single company
# ═══════════════════════════════════════════════════════════════════════

def backfill_company(conn, symbol):
    """
    Run full backfill pipeline for ONE company.
    Returns (research_rows, outcome_rows, error_count).
    """
    research_rows = 0
    outcome_rows = 0
    errors = 0

    # 1. Fetch yFinance price history for event_outcomes
    history = []
    try:
        hist_df = yf.download(f"{symbol}.NS", period="2y", interval="1d",
                              progress=False, auto_adjust=True)
        if not hist_df.empty:
            if isinstance(hist_df.columns, pd.MultiIndex):
                hist_df.columns = hist_df.columns.get_level_values(0)
            hist_df = hist_df.reset_index()
            for _, row in hist_df.iterrows():
                dt = row["Date"]
                if hasattr(dt, "to_pydatetime"):
                    dt = dt.to_pydatetime()
                history.append({
                    "date": dt,
                    "close": float(row["Close"]),
                })
    except Exception as e:
        print(f"    yFinance history fetch failed: {e}")

    # 2. Fetch NSE announcements
    announcements = fetch_nse_announcements(symbol)
    if not announcements:
        print(f"    No NSE announcements found")
        return 0, 0, 0

    print(f"    Found {len(announcements)} NSE announcements — "
          f"processing (max {MAX_ANNOUNCEMENTS_PER_COMPANY})...")

    ann_processed = 0
    for ann in announcements:
        try:
            # Parse date
            ann_date_str = (ann.get("sort_date") or ann.get("an_dt")
                            or ann.get("dt") or "")
            ann_date = parse_nse_date(ann_date_str)
            if ann_date is None:
                continue

            # 2-year filter
            if ann_date < TWO_YEARS_AGO.date():
                continue

            # Per-company cap
            if ann_processed >= MAX_ANNOUNCEMENTS_PER_COMPANY:
                break

            desc = ann.get("desc") or ann.get("attchmntText") or ""
            long_desc = ann.get("attchmntText") or ann.get("desc") or ""

            # ── DEDUP CHECK (not in historical_preloader) ──
            if not DRY_RUN:
                cur = conn.cursor()
                cur.execute(
                    """SELECT COUNT(*) FROM research_cache
                       WHERE symbol = %s
                         AND query_text::jsonb->>'source_date' = %s""",
                    (symbol, str(ann_date)))
                if cur.fetchone()[0] > 0:
                    cur.close()
                    continue
                cur.close()

            # Classify & summarize
            event_type = classify_event_type(desc)
            if DRY_RUN:
                summary = "[DRY-RUN] summary skipped"
            else:
                summary = summarize_announcement(desc, long_desc)
                time.sleep(ANNOUNCEMENT_SLEEP)

            # Store in research_cache
            if not DRY_RUN:
                insert_research_cache(conn, symbol, "announcement_summary",
                                      summary, str(ann_date), ann)
            research_rows += 1

            # Trigger events → event_outcomes
            if event_type in ("dividend", "bonus", "split", "buyback") and history:
                impact = compute_price_impact(history, ann_date)
                if impact and not DRY_RUN:
                    insert_event_outcome(conn, symbol, event_type, ann_date,
                                         summary,
                                         impact["price_impact_pct"],
                                         impact["days_to_impact"])
                    outcome_rows += 1
                elif impact:
                    outcome_rows += 1  # count even in dry-run

            ann_processed += 1

        except Exception as e:
            errors += 1
            print(f"    Error on announcement: {e}")

    print(f"    Processed {ann_processed} | research_cache +{research_rows} | "
          f"event_outcomes +{outcome_rows} | errors {errors}")
    return research_rows, outcome_rows, errors


# ═══════════════════════════════════════════════════════════════════════
# ACTION HELPERS — DB writes (all respect DRY_RUN)
# ═══════════════════════════════════════════════════════════════════════

def _db_symbol(symbol):
    """Neon watchlist/profiles rows store .NS-suffixed symbols; the sync
    diffs bare symbols. Convert at the write seam (B1-a: bare writes were
    no-ops against .NS rows -- GSPL stayed ACTIVE across 6 sync runs)."""
    return symbol if symbol.endswith(".NS") else f"{symbol}.NS"


def insert_new_watchlist(conn, symbol):
    if DRY_RUN:
        print(f"    [DRY-RUN] INSERT nse500_watchlist: {symbol}")
        return
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO nse500_watchlist (symbol, status, added_date)
           VALUES (%s, 'ACTIVE', %s)
           ON CONFLICT (symbol) DO UPDATE
           SET status = 'ACTIVE', added_date = %s""",
        (_db_symbol(symbol), date.today(), date.today()))
    cur.close()


def ensure_company_profile(conn, symbol):
    """INSERT a minimal company_profiles row if not present."""
    if DRY_RUN:
        print(f"    [DRY-RUN] UPSERT company_profiles: {symbol}")
        return
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO company_profiles (symbol, company_name, nifty500, created_at, updated_at)
           VALUES (%s, %s, TRUE, NOW(), NOW())
           ON CONFLICT (symbol) DO UPDATE
           SET nifty500 = TRUE, updated_at = NOW()""",
        (_db_symbol(symbol), symbol))
    cur.close()


def mark_inactive(conn, symbol):
    if DRY_RUN:
        print(f"    [DRY-RUN] MARK INACTIVE: {symbol}")
        return
    cur = conn.cursor()
    cur.execute(
        """UPDATE nse500_watchlist
           SET status = 'INACTIVE', removed_date = %s
           WHERE symbol = %s""",
        (date.today(), _db_symbol(symbol)))
    cur.close()
    cur = conn.cursor()
    cur.execute(
        """UPDATE company_profiles
           SET nifty500 = FALSE, updated_at = NOW()
           WHERE symbol = %s""",
        (_db_symbol(symbol),))
    cur.close()


def mark_active(conn, symbol):
    if DRY_RUN:
        print(f"    [DRY-RUN] MARK ACTIVE: {symbol}")
        return
    cur = conn.cursor()
    cur.execute(
        """UPDATE nse500_watchlist
           SET status = 'ACTIVE', removed_date = NULL
           WHERE symbol = %s""",
        (_db_symbol(symbol),))
    cur.close()
    cur = conn.cursor()
    cur.execute(
        """UPDATE company_profiles
           SET nifty500 = TRUE, updated_at = NOW()
           WHERE symbol = %s""",
        (_db_symbol(symbol),))
    cur.close()


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    start_time = datetime.now()
    if DRY_RUN:
        print("*** DRY-RUN MODE — no DB writes ***")
    print("=" * 60)
    print("  NSE 500 Weekly Sync")
    print(f"  Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Connect to Neon ──
    neon_url = os.getenv("NEON_CONNECTION_STRING", "").strip()
    if not neon_url:
        print("FATAL: NEON_CONNECTION_STRING missing from .env")
        sys.exit(1)
    conn = psycopg2.connect(neon_url)
    conn.autocommit = True

    # ── STEP 1 ──
    live_set = fetch_live_nifty500()

    # ── STEP 2 ──
    db_wl = fetch_watchlist(conn)
    db_set = set(db_wl.keys())

    # ── STEP 3 ── Diff ──
    print("[3/6] Computing diff...")
    new_symbols     = live_set - db_set
    removed_symbols = {s for s, st in db_wl.items()
                       if s not in live_set and st == "ACTIVE"}
    reactivated     = {s for s, st in db_wl.items()
                       if s in live_set and st != "ACTIVE"}
    unchanged       = live_set & {s for s, st in db_wl.items()
                                  if st == "ACTIVE"}

    print(f"  New:         {len(new_symbols)}")
    print(f"  Removed:     {len(removed_symbols)}")
    print(f"  Reactivated: {len(reactivated)}")
    print(f"  Unchanged:   {len(unchanged)}")

    # ── STEP 4 — Handle each case ──
    print("[4/6] Applying changes...")

    total_research = 0
    total_outcomes = 0
    total_errors = 0
    backfill_count = 0

    # A) NEW symbols
    new_list = sorted(new_symbols)
    if LIMIT and len(new_list) > LIMIT:
        print(f"  --limit={LIMIT}: processing first {LIMIT} of {len(new_list)} new symbols")
        new_list = new_list[:LIMIT]
    for i, sym in enumerate(new_list, 1):
        print(f"\n  NEW [{i}/{len(new_list)}]: {sym}")
        try:
            insert_new_watchlist(conn, sym)
            ensure_company_profile(conn, sym)
            r, o, e = backfill_company(conn, sym)
            total_research += r
            total_outcomes += o
            total_errors += e
            backfill_count += 1
            conn.commit()
        except Exception as ex:
            print(f"    FAILED: {ex}")
            traceback.print_exc()
            total_errors += 1
        if i < len(new_list):
            time.sleep(BATCH_SLEEP)

    # B) REMOVED symbols
    for sym in sorted(removed_symbols):
        print(f"\n  REMOVED: {sym}")
        try:
            mark_inactive(conn, sym)
        except Exception as ex:
            print(f"    FAILED: {ex}")
            total_errors += 1

    # C) REACTIVATED symbols
    rea_list = sorted(reactivated)
    if LIMIT and len(rea_list) > LIMIT:
        print(f"  --limit={LIMIT}: processing first {LIMIT} of {len(rea_list)} reactivated symbols")
        rea_list = rea_list[:LIMIT]
    for i, sym in enumerate(rea_list, 1):
        print(f"\n  REACTIVATED [{i}/{len(rea_list)}]: {sym}")
        try:
            mark_active(conn, sym)
            ensure_company_profile(conn, sym)
            r, o, e = backfill_company(conn, sym)
            total_research += r
            total_outcomes += o
            total_errors += e
            backfill_count += 1
            conn.commit()
        except Exception as ex:
            print(f"    FAILED: {ex}")
            traceback.print_exc()
            total_errors += 1
        if i < len(rea_list):
            time.sleep(BATCH_SLEEP)

    # D) UNCHANGED — skip
    if unchanged:
        print(f"\n  UNCHANGED: {len(unchanged)} symbols — skipped")

    # ── STEP 7 — Summary ──
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"  NSE 500 Sync Complete")
    print(f"{'=' * 60}")
    print(f"  New:          {len(new_symbols)} symbols (backfilled)")
    print(f"  Removed:      {len(removed_symbols)} symbols (marked INACTIVE)")
    print(f"  Reactivated:  {len(reactivated)} symbols (backfilled)")
    print(f"  Unchanged:    {len(unchanged)} symbols (skipped)")
    print(f"  Companies backfilled: {backfill_count}")
    print(f"  research_cache rows:  {total_research}")
    print(f"  event_outcomes rows:  {total_outcomes}")
    print(f"  Errors:       {total_errors}")
    print(f"  Elapsed:      {elapsed:.0f}s")
    if DRY_RUN:
        print(f"  Mode:         DRY-RUN (no writes)")
    print(f"{'=' * 60}")

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        print(f"\nFATAL: sync_nse500 crashed - {type(e).__name__}: {e}")
        sys.exit(1)

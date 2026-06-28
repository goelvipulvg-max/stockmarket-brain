import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.supabase_client import get_client
from utils.trading_calendar import today, next_trading_day, add_trading_days

IST = ZoneInfo("Asia/Kolkata")

# P2-2: a FAILED outcome window older than this many days is treated as a
# permanent data-desert (delisted / no Yahoo data) and marked ABANDONED, so it
# stops being retried on every run. Below this age, FAILED windows are retried
# (most failures are transient yfinance flakes and resolve once data appears).
ABANDON_AFTER_DAYS = 90


def _now_iso():
    return datetime.now(IST).isoformat()


def _date_str(d):
    """Return YYYY-MM-DD for a date or Timestamp."""
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        return d
    return str(d)


def _split_factor(splits, base_date, measure_date):
    """B6: cumulative split ratio for ex-dates strictly inside (base_date, measure_date].

    With auto_adjust=False the raw base price is pre-split and a post-split window
    close is on a different share basis; dividing the base by this factor expresses
    it in post-split terms so raw_move reflects true price-return. Dividends ignored
    by design (price-return, splits-only). Returns 1.0 when no in-window split.
    """
    F = 1.0
    if splits is not None and len(splits):
        for ts, ratio in splits.items():
            if base_date < ts.date() <= measure_date:
                F *= float(ratio)
    return F


def backfill_base_prices():
    """Pass 1: fill filing_memory.base_price and nifty_base for rows where base_price IS NULL.

    Idempotent -- WHERE base_price IS NULL filter skips already-priced rows on re-run.
    """
    sb = get_client()
    print("=" * 60)
    print(f"Pass 1 -- Base Price Backfill -- {_now_iso()}")
    print("=" * 60)

    # 1. Read PENDING base-price rows
    resp = (
        sb.table("filing_memory")
        .select("id,symbol_base,filing_date")
        .is_("base_price", "null")
        .execute()
    )
    rows = resp.data or []
    print(f"Rows with base_price IS NULL: {len(rows)}")

    if not rows:
        print("[SKIP] No rows need base price backfill.")
        return

    # 2. Compute today + target base_date per row
    today_date = today()

    def _filing_date(row):
        fd = row["filing_date"]
        if isinstance(fd, str):
            return date.fromisoformat(fd)
        if hasattr(fd, "date"):
            return fd.date()
        return fd

    prepared = []
    pending_future = 0
    for r in rows:
        fd = _filing_date(r)
        base_date = next_trading_day(fd)
        if base_date > today_date:
            pending_future += 1
            continue
        prepared.append({
            "id": r["id"],
            "symbol_base": r["symbol_base"],
            "filing_date": fd,
            "base_date": base_date,
        })
    print(f"Pending future (base_date > today): {pending_future}")
    print(f"Rows ready for pricing: {len(prepared)}")

    if not prepared:
        print("[SKIP] No rows have a base_date <= today.")
        return

    # 3. Group by symbol_base
    by_symbol = defaultdict(list)
    for p in prepared:
        by_symbol[p["symbol_base"]].append(p)
    print(f"Unique symbols: {len(by_symbol)}")

    # 4. Compute overall NIFTY date range
    all_base_dates = [p["base_date"] for p in prepared]
    overall_min = min(all_base_dates)
    overall_max = max(all_base_dates)

    # 5. Fetch NIFTY ONCE
    try:
        nifty_df = yf.Ticker("^NSEI").history(
            start=overall_min,
            end=overall_max + timedelta(days=1),
            auto_adjust=False,  # B6: index has no actions; raw for determinism
        )
        nifty_dict = {
            _date_str(idx): {"Open": float(row["Open"]), "Close": float(row["Close"])}
            for idx, row in nifty_df.iterrows()
        }
        print(f"NIFTY fetched: {len(nifty_dict)} trading days ({overall_min} to {overall_max})")
    except Exception as e:
        print(f"[FATAL] NIFTY fetch failed: {type(e).__name__}: {e}")
        return

    # 6. Per-symbol fetch + per-row pricing
    updated = 0
    lookup_failed = 0
    fetch_failed = 0

    for symbol, group in by_symbol.items():
        sym_min = min(p["base_date"] for p in group)
        sym_max = max(p["base_date"] for p in group)
        sym_before = updated

        # One yfinance call per symbol
        try:
            df = yf.Ticker(symbol + ".NS").history(
                start=sym_min,
                end=sym_max + timedelta(days=1),
                auto_adjust=False,  # B6: raw as-of base price (point-in-time)
            )
        except Exception as e:
            print(f"[WARN] yf fetch failed: {symbol}: {type(e).__name__}: {e}")
            fetch_failed += len(group)
            continue

        if df.empty:
            print(f"[WARN] yf returned empty DataFrame: {symbol} -- marking {len(group)} as fetch_failed")
            fetch_failed += len(group)
            continue

        stock_dict = {
            _date_str(idx): {"Open": float(row["Open"]), "Close": float(row["Close"])}
            for idx, row in df.iterrows()
        }

        # Per-row lookup
        for p in group:
            bd_str = _date_str(p["base_date"])
            s_entry = stock_dict.get(bd_str)
            n_entry = nifty_dict.get(bd_str)

            if s_entry is None or n_entry is None:
                lookup_failed += 1
                continue

            r_base = s_entry["Open"]
            n_base = n_entry["Open"]

            try:
                sb.table("filing_memory").update({
                    "base_price": r_base,
                    "nifty_base": n_base,
                    "updated_at": _now_iso(),
                }).eq("id", p["id"]).execute()
                updated += 1
            except Exception as e:
                print(f"[WARN] Supabase update failed for id={p['id']}: {type(e).__name__}: {e}")
                lookup_failed += 1

        sym_updated = updated - sym_before
        print(f"  {symbol}: {sym_updated}/{len(group)} updated")

    # 7. Summary
    print()
    print("=" * 60)
    print("Pass 1 Summary")
    print("=" * 60)
    print(f"  Rows read (base_price NULL):     {len(rows)}")
    print(f"  Pending future (skipped):        {pending_future}")
    print(f"  Rows updated successfully:       {updated}")
    print(f"  Lookup failed (missing date):    {lookup_failed}")
    print(f"  Fetch failed (bad symbol):       {fetch_failed}")
    print(f"  Total accounted:                 {pending_future + updated + lookup_failed + fetch_failed}")
    print()


def backfill_outcome_windows():
    """Pass 2: fill matured outcome windows (5d/10d/30d) and compute swing_verdict.

    Idempotent -- WHERE status='PENDING' filter skips already-filled windows on re-run.
    """
    sb = get_client()
    print("=" * 60)
    print(f"Pass 2 -- Outcome Window Backfill -- {_now_iso()}")
    print("=" * 60)

    WINDOWS = (5, 10, 30)

    # 1. Read rows with base_price populated + any PENDING/FAILED outcomes
    #    P2-2: FAILED included so transiently-failed windows get retried.
    resp = (
        sb.table("filing_memory")
        .select("id,symbol_base,filing_date,base_price,nifty_base,"
                "outcome_5d_status,outcome_10d_status,outcome_30d_status")
        .not_.is_("base_price", "null")
        .or_("outcome_5d_status.eq.PENDING,outcome_5d_status.eq.FAILED,"
             "outcome_10d_status.eq.PENDING,outcome_10d_status.eq.FAILED,"
             "outcome_30d_status.eq.PENDING,outcome_30d_status.eq.FAILED")
        .execute()
    )
    rows = resp.data or []
    print(f"Rows with base_price set + any PENDING/FAILED window: {len(rows)}")

    if not rows:
        print("[SKIP] No rows with PENDING outcome windows.")
        return

    # 2. Determine ripe windows per row
    today_date = today()

    def _filing_date(row):
        fd = row["filing_date"]
        if isinstance(fd, str):
            return date.fromisoformat(fd)
        if hasattr(fd, "date"):
            return fd.date()
        return fd

    # ripe_entries: one per (row, window) that is PENDING/FAILED and mature.
    # P2-2: FAILED windows are retried; a FAILED window whose target is older
    # than ABANDON_AFTER_DAYS is a permanent data-desert -> marked ABANDONED so
    # it stops being retried on every run.
    ripe_entries = []
    skipped = {5: 0, 10: 0, 30: 0}
    abandoned = {5: 0, 10: 0, 30: 0}
    abandon_updates = defaultdict(dict)  # row_id -> {status_col: "ABANDONED"}

    for r in rows:
        fd = _filing_date(r)
        base_date = next_trading_day(fd)  # B6: needed for in-window split factor
        bp = r["base_price"]
        nb = r["nifty_base"]
        if bp is None or nb is None:
            continue  # shouldn't happen given the WHERE clause, but defensive

        for N in WINDOWS:
            status_col = f"outcome_{N}d_status"
            st = r.get(status_col)
            if st not in ("PENDING", "FAILED"):
                continue
            target_date = add_trading_days(fd, N)
            if target_date >= today_date:
                skipped[N] += 1
                continue
            # P2-2: permanently-stuck FAILED window -> terminal ABANDONED
            if st == "FAILED" and (today_date - target_date).days > ABANDON_AFTER_DAYS:
                abandon_updates[r["id"]][status_col] = "ABANDONED"
                abandoned[N] += 1
                continue
            ripe_entries.append({
                "row_id": r["id"],
                "symbol_base": r["symbol_base"],
                "base_price": bp,
                "nifty_base": nb,
                "window": N,
                "base_date": base_date,
                "target_date": target_date,
            })

    # P2-2: persist ABANDONED marks now -- independent of the ripe / early-return
    # path below, so stale deserts are retired even when nothing is ripe.
    abandoned_rows = 0
    if abandon_updates:
        for row_id, updates in abandon_updates.items():
            updates["updated_at"] = _now_iso()
            try:
                sb.table("filing_memory").update(updates).eq("id", row_id).execute()
                abandoned_rows += 1
            except Exception as e:
                print(f"[WARN] ABANDONED update failed for id={row_id}: {type(e).__name__}: {e}")
        print(f"Abandoned (FAILED older than {ABANDON_AFTER_DAYS}d): "
              f"5d={abandoned[5]}, 10d={abandoned[10]}, 30d={abandoned[30]} "
              f"across {abandoned_rows} rows")

    total_ripe = len(ripe_entries)
    print(f"Ripe windows: {total_ripe}")
    for N in WINDOWS:
        print(f"  {N}d: {sum(1 for e in ripe_entries if e['window'] == N)} ripe, {skipped[N]} skipped-immature")

    if not ripe_entries:
        print("[SKIP] No windows have matured yet.")
        return

    # 3. Group ripe entries by symbol_base
    by_symbol = defaultdict(list)
    for e in ripe_entries:
        by_symbol[e["symbol_base"]].append(e)
    print(f"Unique symbols: {len(by_symbol)}")

    # 4. Compute overall NIFTY date range
    all_target_dates = [e["target_date"] for e in ripe_entries]
    overall_min = min(all_target_dates)
    overall_max = max(all_target_dates)

    # 5. Fetch NIFTY ONCE
    try:
        nifty_df = yf.Ticker("^NSEI").history(
            start=overall_min,
            end=overall_max + timedelta(days=1),
            auto_adjust=False,  # B6: index has no actions; raw for determinism
        )
        nifty_dict = {
            _date_str(idx): {"Open": float(row["Open"]), "Close": float(row["Close"])}
            for idx, row in nifty_df.iterrows()
        }
        print(f"NIFTY fetched: {len(nifty_dict)} trading days ({overall_min} to {overall_max})")
    except Exception as e:
        print(f"[FATAL] NIFTY fetch failed: {type(e).__name__}: {e}")
        return

    # 6. Per-symbol fetch + per-row lookup
    # row_updates: keyed by row_id, accumulates per-window update fields
    row_updates = defaultdict(dict)
    filled = {5: 0, 10: 0, 30: 0}
    failed = {5: 0, 10: 0, 30: 0}
    fetch_failed_count = 0
    lookup_failed_count = 0

    for symbol, entries in by_symbol.items():
        sym_min = min(e["target_date"] for e in entries)
        sym_max = max(e["target_date"] for e in entries)
        filled_before = sum(filled.values())

        try:
            tk = yf.Ticker(symbol + ".NS")
            df = tk.history(
                start=sym_min,
                end=sym_max + timedelta(days=1),
                auto_adjust=False,  # B6: raw close; in-window splits handled below
            )
            splits = tk.splits  # B6: ex-date -> ratio, for in-window split adjustment
        except Exception as e:
            print(f"[WARN] yf fetch failed: {symbol}: {type(e).__name__}: {e}")
            for entry in entries:
                N = entry["window"]
                row_updates[entry["row_id"]][f"outcome_{N}d_status"] = "FAILED"
                failed[N] += 1
            fetch_failed_count += len(entries)
            continue

        if df.empty:
            print(f"[WARN] yf returned empty DataFrame: {symbol} -- marking {len(entries)} windows as FAILED")
            for entry in entries:
                N = entry["window"]
                row_updates[entry["row_id"]][f"outcome_{N}d_status"] = "FAILED"
                failed[N] += 1
            fetch_failed_count += len(entries)
            continue

        stock_dict = {
            _date_str(idx): {"Open": float(row["Open"]), "Close": float(row["Close"])}
            for idx, row in df.iterrows()
        }

        for entry in entries:
            N = entry["window"]
            td_str = _date_str(entry["target_date"])
            s_entry = stock_dict.get(td_str)
            n_entry = nifty_dict.get(td_str)

            if s_entry is None or n_entry is None:
                row_updates[entry["row_id"]][f"outcome_{N}d_status"] = "FAILED"
                failed[N] += 1
                lookup_failed_count += 1
                continue

            stock_close = s_entry["Close"]
            nifty_close = n_entry["Close"]
            bp = entry["base_price"]
            nb = entry["nifty_base"]

            # B6: express raw pre-split base in post-split terms for in-window splits
            F = _split_factor(splits, entry["base_date"], entry["target_date"])
            adj_base = bp / F

            raw_move = round((stock_close - adj_base) / adj_base * 100, 2)
            nifty_move = round((nifty_close - nb) / nb * 100, 2)
            alpha = round(raw_move - nifty_move, 2)

            row_updates[entry["row_id"]].update({
                f"price_{N}d": round(stock_close, 2),
                f"nifty_{N}d": round(nifty_close, 2),
                f"raw_move_{N}d": raw_move,
                f"alpha_{N}d": alpha,
                f"outcome_{N}d_status": "FILLED",
            })
            filled[N] += 1

        sym_filled = sum(filled.values()) - filled_before
        print(f"  {symbol}: {sym_filled}/{len(entries)} windows filled")

    # 7. Compute swing_verdict for rows whose 10d was FILLED THIS RUN
    verdict_dist = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    for row_id, updates in row_updates.items():
        if updates.get("outcome_10d_status") == "FILLED":
            a = updates.get("alpha_10d", 0) or 0
            verdict = "POSITIVE" if a > 3 else "NEGATIVE" if a < -3 else "NEUTRAL"
            updates["swing_verdict"] = verdict
            verdict_dist[verdict] += 1

    # 8. Update Supabase per row
    rows_updated = 0
    for row_id, updates in row_updates.items():
        updates["updated_at"] = _now_iso()
        try:
            sb.table("filing_memory").update(updates).eq("id", row_id).execute()
            rows_updated += 1
        except Exception as e:
            print(f"[WARN] Supabase update failed for id={row_id}: {type(e).__name__}: {e}")

    # 9. Summary
    print()
    print("=" * 60)
    print("Pass 2 Summary")
    print("=" * 60)
    print(f"  Rows read (base_price set + PENDING/FAILED):  {len(rows)}")
    print(f"  Rows updated:                                  {rows_updated}")
    print(f"  Rows abandoned (stale FAILED):                 {abandoned_rows}")
    for N in WINDOWS:
        print(f"  {N}d: FILLED={filled[N]}, FAILED={failed[N]}, "
              f"ABANDONED={abandoned[N]}, skipped-immature={skipped[N]}")
    print(f"  Fetch failed (symbol-level):             {fetch_failed_count}")
    print(f"  Lookup failed (date-level):              {lookup_failed_count}")
    print(f"  swing_verdict (this run):               POSITIVE={verdict_dist['POSITIVE']}, NEGATIVE={verdict_dist['NEGATIVE']}, NEUTRAL={verdict_dist['NEUTRAL']}")
    print()


if __name__ == "__main__":
    try:
        backfill_base_prices()
        backfill_outcome_windows()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: backfill crashed -- {type(e).__name__}: {e}")
        sys.exit(1)


"""B6 one-off recompute of matured filing_memory rows under the point-in-time
alpha rule (auto_adjust=False + in-window split adjustment).

Mirrors agents/filing_memory_backfill.py Pass 2 math EXACTLY (reuses _split_factor).
Recomputes price_Nd / raw_move_Nd / alpha_Nd for every FILLED window of every matured
row, plus swing_verdict (10d), and compares to stored values.

  REPORT-ONLY by default -- SELECT + yfinance reads + snapshot file, NO DB writes.
  --apply           -- additionally UPDATE rows whose values changed.

Scope: rows with outcome_10d_status='FILLED' (the matured set). base_price / nifty_base
are LEFT AS-IS (already raw). Reversible: a snapshot of the affected columns is written
to tmp_b6_snapshot_<YYYY-MM-DD>.json before any write.

Usage:
  .venv\\Scripts\\python.exe scripts\\b6_recompute_matured.py            # report-only
  .venv\\Scripts\\python.exe scripts\\b6_recompute_matured.py --apply    # write changes
"""
import os
import sys
import json
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.supabase_client import get_client
from utils.trading_calendar import next_trading_day, add_trading_days
from agents.filing_memory_backfill import _split_factor, _date_str

IST = ZoneInfo("Asia/Kolkata")
WINDOWS = (5, 10, 30)


def _filing_date(v):
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    if hasattr(v, "date"):
        return v.date()
    return v


def _verdict(alpha):
    a = alpha or 0
    return "POSITIVE" if a > 3 else "NEGATIVE" if a < -3 else "NEUTRAL"


def main(apply_changes):
    sb = get_client()
    mode = "APPLY (writes enabled)" if apply_changes else "REPORT-ONLY (no DB writes)"
    print("=" * 70)
    print(f"B6 recompute -- {mode} -- {datetime.now(IST).isoformat()}")
    print("=" * 70)

    sel = ("id,symbol_base,filing_date,base_price,nifty_base,swing_verdict,"
           + ",".join(f"price_{N}d,nifty_{N}d,raw_move_{N}d,alpha_{N}d,outcome_{N}d_status"
                      for N in WINDOWS))
    rows = (sb.table("filing_memory").select(sel)
            .eq("outcome_10d_status", "FILLED").execute()).data or []
    print(f"Matured rows (outcome_10d_status=FILLED): {len(rows)}")
    if not rows:
        print("[SKIP] nothing to recompute.")
        return

    # Build the list of FILLED (row, window) jobs
    jobs = []
    for r in rows:
        fd = _filing_date(r["filing_date"])
        base_date = next_trading_day(fd)
        for N in WINDOWS:
            if r.get(f"outcome_{N}d_status") != "FILLED":
                continue
            jobs.append({
                "row": r, "N": N, "base_date": base_date,
                "target_date": add_trading_days(fd, N),
            })
    print(f"FILLED windows to recompute: {len(jobs)}")

    # Snapshot affected columns BEFORE anything (reversibility)
    snap = {}
    for r in rows:
        snap[r["id"]] = {k: r.get(k) for k in (
            ["swing_verdict"] + [f"{p}_{N}d" for N in WINDOWS
                                 for p in ("price", "nifty", "raw_move", "alpha")])}
    snap_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             f"tmp_b6_snapshot_{datetime.now(IST).date()}.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, default=str)
    print(f"Snapshot written: {snap_path}")

    # NIFTY fetch once (auto_adjust=False)
    all_targets = [j["target_date"] for j in jobs]
    nifty_df = yf.Ticker("^NSEI").history(
        start=min(all_targets), end=max(all_targets) + timedelta(days=1),
        auto_adjust=False)
    nifty_close = {_date_str(i): float(row["Close"]) for i, row in nifty_df.iterrows()}

    # Group jobs by symbol
    by_symbol = defaultdict(list)
    for j in jobs:
        by_symbol[j["row"]["symbol_base"]].append(j)

    row_updates = defaultdict(dict)
    diffs = []          # changed (row, field) tuples
    unchanged = 0
    fetch_fail = 0

    for symbol, sjobs in sorted(by_symbol.items()):
        tmin = min(j["target_date"] for j in sjobs)
        tmax = max(j["target_date"] for j in sjobs)
        try:
            tk = yf.Ticker(symbol + ".NS")
            df = tk.history(start=tmin, end=tmax + timedelta(days=1), auto_adjust=False)
            splits = tk.splits
        except Exception as e:
            print(f"[WARN] fetch failed {symbol}: {type(e).__name__}: {e}")
            fetch_fail += len(sjobs)
            continue
        sclose = {_date_str(i): float(row["Close"]) for i, row in df.iterrows()}

        for j in sjobs:
            r, N = j["row"], j["N"]
            td = _date_str(j["target_date"])
            sc, nc = sclose.get(td), nifty_close.get(td)
            if sc is None or nc is None:
                print(f"[WARN] missing bar {symbol} id={r['id']} {N}d @ {td}")
                fetch_fail += 1
                continue
            F = _split_factor(splits, j["base_date"], j["target_date"])
            adj_base = r["base_price"] / F
            raw_move = round((sc - adj_base) / adj_base * 100, 2)
            nifty_move = round((nc - r["nifty_base"]) / r["nifty_base"] * 100, 2)
            alpha = round(raw_move - nifty_move, 2)
            new = {f"price_{N}d": round(sc, 2), f"nifty_{N}d": round(nc, 2),
                   f"raw_move_{N}d": raw_move, f"alpha_{N}d": alpha}
            for k, v in new.items():
                old = r.get(k)
                if old != v:
                    diffs.append((r["id"], symbol, k, old, v))
                    row_updates[r["id"]][k] = v
                else:
                    unchanged += 1

    # swing_verdict recompute from new (or stored) alpha_10d
    for r in rows:
        if r.get("outcome_10d_status") != "FILLED":
            continue
        a10 = row_updates.get(r["id"], {}).get("alpha_10d", r.get("alpha_10d"))
        nv = _verdict(a10)
        if nv != r.get("swing_verdict"):
            diffs.append((r["id"], r["symbol_base"], "swing_verdict", r.get("swing_verdict"), nv))
            row_updates[r["id"]]["swing_verdict"] = nv

    print()
    print("=" * 70)
    print(f"Fields unchanged: {unchanged} | changed: {len(diffs)} | fetch-fail: {fetch_fail}")
    for rid, sym, field, old, new in diffs:
        print(f"  CHANGE id={rid} {sym} {field}: {old} -> {new}")
    print("=" * 70)

    if not apply_changes:
        print("REPORT-ONLY: no DB writes performed. Re-run with --apply to write.")
        return
    if not row_updates:
        print("APPLY: 0 rows changed -- nothing to write.")
        return
    n = 0
    for rid, upd in row_updates.items():
        upd["updated_at"] = datetime.now(IST).isoformat()
        sb.table("filing_memory").update(upd).eq("id", rid).execute()
        n += 1
    print(f"APPLY: updated {n} rows.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes to DB")
    main(ap.parse_args().apply)

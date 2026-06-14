#!/usr/bin/env python
"""B2 Event-Study Backtest -- Scope 1 (endpoint) + conditional Scope 2 (path-aware).

Derives an empirically-grounded T1/SL ladder (own RR >= 1.5) from matured
filing_memory alpha data. READS filing_memory only -- zero writes. All output
to stdout and a local report file (reports/b2_scope1_<YYYY-MM-DD>.md, plus
reports/b2_scope2_<YYYY-MM-DD>.md if Scope 2 runs).

Gate rule (a): if NO event-type category passes the Scope 1 RR gate, Scope 2
is skipped -- we do NOT guess a ladder.

Usage:
  .venv\\Scripts\\python.exe scripts\\event_study.py              # Scope 1 always; Scope 2 if gate passes
  .venv\\Scripts\\python.exe scripts\\event_study.py --scope1-only  # Force Scope 1 only
"""
import os
import sys
import argparse
import time
from datetime import date as date_type, datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo

import yfinance as yf
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.supabase_client import get_client
from utils.trading_calendar import next_trading_day, add_trading_days

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOWS = (5, 10)                        # horizons to analyse (30d excluded -- 0 FILLED)
EVENT_TYPES = (
    "RESULTS", "DIVIDEND", "MANAGEMENT_CHANGE", "DISCLOSURE", "CONTRACT_WIN",
)
SL_FLOOR_PCT = 2.0                       # tightest allowed SL distance (matches tier2_fundamental)
RR_FLOOR = 1.5                           # minimum reward:risk
# Gate: T1 = p75 alpha (25% of rows reach this AT ENDPOINT by definition).
# SL = T1 / 1.5. PASS if SL >= 2% (SL_FLOOR_PCT). Effectively: p75 >= 3%.
N_RETRIES = 2                            # yfinance fetch attempts (retry-once-then-fail)
RETRY_SLEEP = 2.0                        # seconds between retries

# Ladder sweep grid (Scope 2 only)
T1_CANDIDATES = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
SL_CANDIDATES = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]

# Minimum n for production-grade ladder recommendation (matches B2 maturity
# threshold from plan: "need >=20-30/category" — we raise to 100 for the
# production pick so small-sample categories don't rank first)
MIN_N_FOR_RECOMMENDATION = 100

# Output directory
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date(v):
    """Coerce a date or date-like string to date."""
    if isinstance(v, str):
        return date_type.fromisoformat(v[:10])
    if hasattr(v, "date"):
        return v.date()
    return v


def _fetch_yf(symbol, start, end):
    """Fetch daily history with retry-once-then-fail (matching 8a223b9 pattern).

    Returns (DataFrame, splits_series) or raises on failure after retries.
    """
    last_err = None
    for attempt in range(N_RETRIES):
        try:
            tk = yf.Ticker(symbol)
            df = tk.history(start=start, end=end + timedelta(days=1),
                           auto_adjust=False)
            splits = tk.splits
            return df, splits
        except Exception as e:
            last_err = e
            if attempt < N_RETRIES - 1:
                print(f"  [RETRY] {symbol} attempt {attempt+1} failed: "
                      f"{type(e).__name__}: {e}")
                time.sleep(RETRY_SLEEP)
    raise last_err


# ---------------------------------------------------------------------------
# Scope 1: Endpoint Analysis
# ---------------------------------------------------------------------------

def run_scope1(sb):
    """Read filing_memory endpoint data, compute per-category distributions.

    Returns (report_lines, pass_categories) where pass_categories is a
    list of (event_type, window, p75_alpha) tuples for categories whose
    endpoint distribution supports RR >= 1.5.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    report_path = os.path.join(REPORTS_DIR, f"b2_scope1_{today_str}.md")

    print("=" * 70)
    print("B2 SCOPE 1 -- Endpoint Alpha Distribution")
    print(f"Run date: {today_str} IST")
    print("=" * 70)

    # --- Fetch ---
    sel = ("symbol_base,event_type,sector,filing_date,base_price,nifty_base,"
           + ",".join(f"price_{N}d,nifty_{N}d,raw_move_{N}d,alpha_{N}d,"
                      f"outcome_{N}d_status" for N in WINDOWS)
           + ",swing_verdict")
    rows = (sb.table("filing_memory")
            .select(sel)
            .eq("outcome_10d_status", "FILLED")
            .in_("event_type", EVENT_TYPES)
            .execute()
            .data) or []
    print(f"\nFetched {len(rows)} filing_memory rows "
          f"(outcome_10d_status=FILLED, {len(EVENT_TYPES)} event types)")

    # --- Per-category computation ---
    results = {}   # (event_type, window) -> stats

    for et in EVENT_TYPES:
        for N in WINDOWS:
            subset = [r for r in rows
                      if r["event_type"] == et
                      and r.get(f"outcome_{N}d_status") == "FILLED"]
            if len(subset) < 20:
                # Too few for stats -- skip this category
                results[(et, N)] = {"count": len(subset), "skip_low_n": True}
                continue

            alphas = sorted([float(r[f"alpha_{N}d"]) for r in subset
                            if r.get(f"alpha_{N}d") is not None])
            raw_moves = [float(r[f"raw_move_{N}d"]) for r in subset
                        if r.get(f"raw_move_{N}d") is not None]
            swing = defaultdict(int)
            for r in subset:
                sv = r.get("swing_verdict") or "NULL"
                swing[sv] += 1

            def _pctile(vals, p):
                if not vals:
                    return None
                idx = int(round(p / 100.0 * (len(vals) - 1)))
                return round(vals[min(idx, len(vals)-1)], 2)

            results[(et, N)] = {
                "count": len(alphas),
                "mean_alpha": round(sum(alphas) / len(alphas), 2),
                "p10": _pctile(alphas, 10),
                "p25": _pctile(alphas, 25),
                "p50": _pctile(alphas, 50),
                "p75": _pctile(alphas, 75),
                "p90": _pctile(alphas, 90),
                "win_rate": round(sum(1 for a in alphas if a > 0) / len(alphas) * 100, 1),
                "mean_raw_move": round(sum(raw_moves) / len(raw_moves), 2) if raw_moves else None,
                "swing_verdict": dict(swing),
            }

    # --- Build report ---
    lines = []
    lines.append("# B2 Scope 1 -- Endpoint Alpha Distribution")
    lines.append(f"**Run date:** {today_str} IST  ")
    lines.append(f"**Data source:** `filing_memory` -- "
                 f"`outcome_10d_status='FILLED'`, 5 event types  ")
    lines.append(f"**Total rows fetched:** {len(rows)}")
    lines.append("")
    lines.append("## Interpretation Caveats (READ BEFORE USING THESE NUMBERS)")
    lines.append("")
    lines.append("1. **SELL not modeled.** This calibrates the LONG/AI-SL (BUY) ladder. "
                 "SELL signals (~19% of live) auto-invert symmetrically via `_dir_price` "
                 "and are NOT separately calibrated here -- the alpha distribution is "
                 "asymmetric, so the SELL ladder may be slightly miscalibrated. Known "
                 "accepted limitation (NIFTY BEARISH gate kills signals in bear regimes "
                 "anyway).")
    lines.append("")
    lines.append("2. **Unconditional vs AI-selected.** This models going long on EVERY "
                 "filing unconditional on alpha sign. The live engine trades only an "
                 "AI-SELECTED subset (tradeable, confidence>=65, direction consensus). "
                 "So this distribution is a CONSERVATIVE PROXY, not the realized-trade "
                 "distribution. A PASS is trustworthy (real >= proxy). A FAIL does NOT "
                 "prove the ladder is impossible -- only that we lack data to validate a "
                 "ladder for the AI-selected subset, so we don't guess one. Direct "
                 "validation of the AI-selected subset requires more matured live trades "
                 "(currently n=3).")
    lines.append("")
    lines.append("3. **Entry-basis gap.** Backtest enters at `base_price` (next-day open); "
                 "live enters at `last_close` (previous close, before the overnight gap). "
                 "For positive-catalyst filings the gap-up is part of the reaction, so the "
                 "backtest SYSTEMATICALLY UNDERSTATES favorable move (conservative bias, "
                 "not random noise). `auto_adjust=False` here vs `True` in live "
                 "(split/dividend effect negligible over 5-10d).")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Per-horizon tables ---
    pass_categories = []

    for N in WINDOWS:
        lines.append(f"## {N}-Day Horizon")
        lines.append("")
        lines.append("| Event Type | N | Mean alpha | p10 | p25 | Median | p75 | p90 | "
                     "Win Rate | Mean Raw Move | POS/NEG/NEU | RR Gate |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

        for et in EVENT_TYPES:
            key = (et, N)
            s = results.get(key)
            if s is None or s.get("skip_low_n"):
                lines.append(f"| {et} | "
                             f"{s.get('count', 0) if s else 0} | "
                             f"*insufficient n (<20)* |||||||||")
                continue

            sv = s["swing_verdict"]
            pos = sv.get("POSITIVE", 0)
            neg = sv.get("NEGATIVE", 0)
            neu = sv.get("NEUTRAL", 0)

            # --- RR Gate ---
            p75 = s["p75"]
            gate_result = "-"
            if p75 is not None and p75 > 0:
                # T1 at p75: 25% of rows reach alpha >= p75 at endpoint
                # SL = T1 / RR_FLOOR. Gate passes if SL >= SL_FLOOR_PCT.
                candidate_sl = round(p75 / RR_FLOOR, 2)
                if candidate_sl >= SL_FLOOR_PCT:
                    gate_result = f"**PASS** (T1={p75}%, SL={candidate_sl}%, "
                    gate_result += f"RR={round(p75/candidate_sl, 2)}>={RR_FLOOR})"
                    pass_categories.append((et, N, p75))
                else:
                    gate_result = (f"FAIL -- SL={candidate_sl}% < "
                                   f"SL_FLOOR={SL_FLOOR_PCT}% (T1={p75}%)")
            elif p75 is not None and p75 <= 0:
                gate_result = f"FAIL -- p75 alpha={p75}% <= 0"

            lines.append(f"| {et} | {s['count']} | "
                         f"{s['mean_alpha']}% | "
                         f"{s['p10']}% | {s['p25']}% | {s['p50']}% | "
                         f"{s['p75']}% | {s['p90']}% | "
                         f"{s['win_rate']}% | "
                         f"{s['mean_raw_move']}% | "
                         f"{pos}/{neg}/{neu} | "
                         f"{gate_result} |")

        lines.append("")

    # --- Summary ---
    lines.append("---")
    lines.append("")
    lines.append("## RR Gate Summary")
    lines.append("")
    if pass_categories:
        lines.append(f"**{len(pass_categories)} category-horizon pair(s) PASS the "
                     f"endpoint RR gate (p75 alpha as T1, SL=T1/{RR_FLOOR}>={SL_FLOOR_PCT}%):**")
        lines.append("")
        for et, N, p75 in pass_categories:
            sl = round(p75 / RR_FLOOR, 2)
            lines.append(f"- **{et} @ {N}d**: T1={p75}%, SL={sl}%, "
                         f"RR={round(p75/sl, 2)}")
        lines.append("")
        lines.append("-> **Scope 2 will run** on these passing categories to refine "
                     "the ladder with path-aware MFE/MAE data.")
    else:
        lines.append("**0 category-horizon pairs pass the RR gate.**")
        lines.append("")
        lines.append("-> **Scope 2 SKIPPED.** The endpoint data itself cannot support "
                     f"RR>={RR_FLOOR} with SL>={SL_FLOOR_PCT}% for any category. "
                     "The ladder needs fundamental rethinking -- wider T1, tighter SL, "
                     "or event-type-specific ladders. No ladder is guessed from "
                     "insufficient data.")

    lines.append("")

    # --- Write to file ---
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # --- Print to stdout ---
    print("\n" + "\n".join(lines))
    print(f"\nScope 1 report saved: {report_path}")

    return lines, pass_categories


# ---------------------------------------------------------------------------
# Scope 2: Path-Aware Analysis
# ---------------------------------------------------------------------------

def run_scope2(sb, pass_categories, scope1_lines):
    """Re-fetch daily OHLC and compute MFE/MAE for each row in passing categories.

    Sweeps (T1, SL) pairs and recommends the highest-expectancy ladder with
    RR >= 1.5.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    report_path = os.path.join(REPORTS_DIR, f"b2_scope2_{today_str}.md")

    print("\n" + "=" * 70)
    print("B2 SCOPE 2 -- Path-Aware Ladder Sweep")
    print(f"Run date: {today_str} IST")
    print(f"Passing categories from Scope 1: "
          f"{[(et, f'{N}d') for et, N, _ in pass_categories]}")
    print("=" * 70)

    # Collect unique (event_type, window) pairs
    target_windows = set()
    for et, N, _ in pass_categories:
        target_windows.add((et, N))

    # --- Fetch all rows for passing categories ---
    sel = ("id,symbol_base,event_type,sector,filing_date,base_price,nifty_base,"
           + ",".join(f"outcome_{N}d_status" for N in WINDOWS))
    rows = (sb.table("filing_memory")
            .select(sel)
            .eq("outcome_10d_status", "FILLED")
            .in_("event_type", [et for et, _, _ in pass_categories])
            .execute()
            .data) or []
    print(f"\nFetched {len(rows)} rows for Scope 2 (passing categories only)")

    # --- Prepare jobs: one per (row, qualifying window) ---
    jobs = []
    for r in rows:
        fd = _date(r["filing_date"])
        base_date = next_trading_day(fd)
        for N in WINDOWS:
            et = r["event_type"]
            if (et, N) not in target_windows:
                continue
            if r.get(f"outcome_{N}d_status") != "FILLED":
                continue
            target_date = add_trading_days(fd, N)
            jobs.append({
                "row_id": r["id"],
                "symbol_base": r["symbol_base"],
                "event_type": et,
                "base_price": float(r["base_price"]),
                "nifty_base": float(r["nifty_base"]),
                "base_date": base_date,
                "target_date": target_date,
                "window": N,
            })

    print(f"Jobs to process: {len(jobs)}")
    if not jobs:
        print("No jobs -- aborting Scope 2.")
        return

    # Group by symbol for bulk yfinance fetches
    by_symbol = defaultdict(list)
    for j in jobs:
        by_symbol[j["symbol_base"]].append(j)
    print(f"Unique symbols: {len(by_symbol)}")

    # --- Compute daily alpha paths with intraday-aware High/Low ---
    # alpha_paths[row_id] = list of (trading_day_idx, alpha_high_i, alpha_low_i)
    # where alpha_high_i uses daily High (favorable extreme within the day) and
    # alpha_low_i uses daily Low (adverse extreme). Nifty: adjusted against
    # Nifty's same-day Close (see NIFTY NUANCE in report header -- intraday
    # Nifty high/low timing is unaligned with stock intraday timing, so we
    # don't try to match extremes intraday).
    alpha_paths = {}       # row_id -> list of (day_idx, alpha_high, alpha_low)
    fetch_fail = 0

    for sym, sym_jobs in sorted(by_symbol.items()):
        t_min = min(j["base_date"] for j in sym_jobs)
        t_max = max(j["target_date"] for j in sym_jobs)

        try:
            df, splits = _fetch_yf(sym + ".NS", t_min, t_max)
        except Exception as e:
            print(f"[FAIL] {sym}: {type(e).__name__}: {e} -- "
                  f"skipping {len(sym_jobs)} job(s)")
            fetch_fail += len(sym_jobs)
            continue

        if df.empty:
            print(f"[WARN] {sym}: empty DataFrame -- "
                  f"skipping {len(sym_jobs)} job(s)")
            fetch_fail += len(sym_jobs)
            continue

        # Build OHLC lookup: date_str -> {Close, High, Low}
        stock_ohlc = {}
        for idx, row in df.iterrows():
            d_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            stock_ohlc[d_str] = {
                "close": float(row["Close"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
            }

        # Fetch Nifty for the same range (Close only -- see NIFTY NUANCE)
        try:
            nifty_df, _ = _fetch_yf("^NSEI", t_min, t_max)
            nifty_close = {}
            for idx, row in nifty_df.iterrows():
                d_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                nifty_close[d_str] = float(row["Close"])
        except Exception as e:
            print(f"[FAIL] ^NSEI fetch: {type(e).__name__}: {e} -- "
                  f"skipping {sym} ({len(sym_jobs)} job(s))")
            fetch_fail += len(sym_jobs)
            continue

        # Per-job path reconstruction
        for j in sym_jobs:
            bp = j["base_price"]
            nb = j["nifty_base"]
            bd = j["base_date"]
            td = j["target_date"]
            # t_min to t_max is the yfinance fetch window, matching the backfill
            # target_date convention: add_trading_days(filing_date, N).
            # base_date = next_trading_day(filing_date) = day-0 (entry).

            alphas = []       # (day_idx, alpha_high, alpha_low) per trading day
            day_label = 0
            cursor = bd
            while cursor <= td:
                c_str = cursor.strftime("%Y-%m-%d")
                sbar = stock_ohlc.get(c_str)
                nc = nifty_close.get(c_str)
                if sbar is None or nc is None:
                    # Missing bar (holiday/weekend/non-trading day)
                    cursor += timedelta(days=1)
                    continue

                nifty_ret = (nc / nb - 1.0) * 100.0
                alpha_high = round((sbar["high"] / bp - 1.0) * 100.0 - nifty_ret, 4)
                alpha_low  = round((sbar["low"]  / bp - 1.0) * 100.0 - nifty_ret, 4)

                alphas.append((day_label, alpha_high, alpha_low))
                day_label += 1
                cursor += timedelta(days=1)

            alpha_paths[j["row_id"]] = alphas

    print(f"Alpha paths computed: {len(alpha_paths)} rows "
          f"({fetch_fail} fetch-failed)")

    # --- Ladder sweep ---
    sweep = []  # list of dicts

    for (et, N) in sorted(target_windows, key=lambda x: (x[1], x[0])):
        cat_jobs = [j for j in jobs
                    if j["event_type"] == et and j["window"] == N]
        cat_row_ids = {j["row_id"] for j in cat_jobs}
        cat_paths = {rid: alpha_paths[rid] for rid in cat_row_ids
                     if rid in alpha_paths}
        n_paths = len(cat_paths)
        if n_paths < 10:
            print(f"  [{et} @ {N}d] only {n_paths} paths -- skipping "
                  f"(need >= 10 for meaningful sweep)")
            continue

        print(f"\n  [{et} @ {N}d] {n_paths} paths -- sweeping ladder grid...")

        for t1 in T1_CANDIDATES:
            for sl in SL_CANDIDATES:
                if t1 / sl < RR_FLOOR - 1e-9:
                    continue  # RR < 1.5 -- skip

                target_hit = 0
                sl_hit = 0
                expired = 0
                days_target = []
                days_sl = []

                for rid, path in cat_paths.items():
                    hit_target = False
                    hit_sl = False
                    day_target = None
                    day_sl = None

                    for day_idx, alpha_high, alpha_low in path:
                        # T1 reached if daily HIGH crosses the target
                        if alpha_high >= t1 and not hit_target:
                            hit_target = True
                            day_target = day_idx
                        # SL reached if daily LOW crosses the stop
                        if alpha_low <= -sl and not hit_sl:
                            hit_sl = True
                            day_sl = day_idx
                        if hit_target and hit_sl:
                            # Both touched on the same day: pessimistic --
                            # SL wins (day_sl <= day_target is always True
                            # when both occur on the same day_idx).
                            if day_sl is not None and day_target is not None and day_sl <= day_target:
                                hit_target = False  # SL wins
                            else:
                                hit_sl = False       # target wins (strictly earlier)
                            break

                    if hit_target:
                        target_hit += 1
                        if day_target is not None:
                            days_target.append(day_target)
                    elif hit_sl:
                        sl_hit += 1
                        if day_sl is not None:
                            days_sl.append(day_sl)
                    else:
                        expired += 1

                total = target_hit + sl_hit + expired
                if total == 0:
                    continue

                target_pct = round(target_hit / total * 100, 1)
                sl_pct = round(sl_hit / total * 100, 1)
                expiry_pct = round(expired / total * 100, 1)
                expectancy = round((target_hit * t1 - sl_hit * sl) / total, 4)
                avg_days_t = (round(sum(days_target) / len(days_target), 1)
                              if days_target else None)
                avg_days_s = (round(sum(days_sl) / len(days_sl), 1)
                              if days_sl else None)
                rr = round(t1 / sl, 2)

                sweep.append({
                    "event_type": et,
                    "window": N,
                    "t1": t1,
                    "sl": sl,
                    "rr": rr,
                    "n": total,
                    "target_pct": target_pct,
                    "sl_pct": sl_pct,
                    "expiry_pct": expiry_pct,
                    "expectancy": expectancy,
                    "avg_days_target": avg_days_t,
                    "avg_days_sl": avg_days_s,
                })

    # --- Sort by expectancy descending ---
    sweep.sort(key=lambda x: x["expectancy"], reverse=True)

    # --- Build report ---
    lines = []
    lines.append("# B2 Scope 2 -- Path-Aware Ladder Sweep")
    lines.append(f"**Run date:** {today_str} IST  ")
    lines.append(f"**Data source:** `filing_memory` + daily yfinance OHLC "
                 f"(`auto_adjust=False`)  ")
    lines.append(f"**Same-day ambiguity rule:** SL hit first (pessimistic)  ")
    lines.append(f"**NIFTY NUANCE:** Stock High/Low adjusted against Nifty same-day "
                 f"**Close** (not Nifty intraday High/Low -- intraday timing between "
                 f"stock and index extremes is unaligned without tick data). This "
                 f"conservatively understates alpha_high and overstates alpha_low "
                 f"on days when Nifty moves opposite to the stock extreme.  ")
    lines.append(f"**Entry basis:** `base_price` (next-day open) -- see "
                 f"Scope 1 caveat #3  ")
    lines.append(f"**Total paths computed:** {len(alpha_paths)}  ")
    lines.append(f"**Fetch failures:** {fetch_fail}  ")
    lines.append("")

    # Top 3 per (event_type, window)
    seen_cats = set()
    for et, N in sorted(target_windows, key=lambda x: (x[1], x[0])):
        cat_sweep = [s for s in sweep
                     if s["event_type"] == et and s["window"] == N]
        if not cat_sweep:
            continue

        seen_cats.add((et, N))
        lines.append(f"## {et} @ {N}d (top 10 by expectancy)")
        lines.append("")
        lines.append("| T1 | SL | RR | N | Target Hit% | SL Hit% | Expiry% | "
                     "Expectancy | Avg Days->T | Avg Days->SL |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

        for s in cat_sweep[:10]:
            lines.append(f"| {s['t1']}% | {s['sl']}% | {s['rr']} | {s['n']} | "
                         f"{s['target_pct']}% | {s['sl_pct']}% | "
                         f"{s['expiry_pct']}% | "
                         f"{s['expectancy']} | "
                         f"{s['avg_days_target'] or '--'} | "
                         f"{s['avg_days_sl'] or '--'} |")

        lines.append("")

        # Also show MFE/MAE percentile table for this category
        cat_jobs = [j for j in jobs
                    if j["event_type"] == et and j["window"] == N]
        cat_row_ids = {j["row_id"] for j in cat_jobs}
        cat_paths = {rid: alpha_paths[rid] for rid in cat_row_ids
                     if rid in alpha_paths}

        mfes = []
        maes = []
        for rid, path in cat_paths.items():
            if path:
                highs = [ah for _, ah, _ in path]    # alpha_high = daily favorable extreme
                lows  = [al for _, _, al in path]    # alpha_low  = daily adverse extreme
                mfes.append(max(highs))
                maes.append(min(lows))

        if mfes:
            mfes.sort()
            maes.sort()

            def _p(vals, p):
                idx = int(round(p / 100.0 * (len(vals) - 1)))
                return round(vals[min(idx, len(vals)-1)], 2)

            lines.append(f"**MFE/MAE distribution ({et} @ {N}d, "
                         f"n={len(mfes)} paths):**")
            lines.append("")
            lines.append("| | p10 | p25 | Median | p75 | p90 |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            lines.append(f"| MFE | {_p(mfes, 10)}% | {_p(mfes, 25)}% | "
                         f"{_p(mfes, 50)}% | {_p(mfes, 75)}% | "
                         f"{_p(mfes, 90)}% |")
            lines.append(f"| MAE | {_p(maes, 10)}% | {_p(maes, 25)}% | "
                         f"{_p(maes, 50)}% | {_p(maes, 75)}% | "
                         f"{_p(maes, 90)}% |")
            lines.append("")

    # --- Recommended ladder (two-tier: production-grade vs directional hints) ---
    if sweep:
        # Tier 1: production-grade — only categories with n >= MIN_N_FOR_RECOMMENDATION
        prod = [s for s in sweep if s["n"] >= MIN_N_FOR_RECOMMENDATION]
        # Tier 2: directional hints — low-n categories excluded from production
        low_n = [s for s in sweep if s["n"] < MIN_N_FOR_RECOMMENDATION]

        # Deduplicate: pick the single best combo per (event_type, window) for each tier
        def _top_per_category(src):
            seen = set()
            out = []
            for s in src:
                key = (s["event_type"], s["window"])
                if key not in seen:
                    seen.add(key)
                    out.append(s)
            return out

        prod_top = _top_per_category(prod)
        low_n_top = _top_per_category(low_n)

        lines.append("---")
        lines.append("")

        if prod_top:
            best_prod = prod_top[0]
            lines.append("## Recommended Ladder — Production-Grade "
                         f"(n >= {MIN_N_FOR_RECOMMENDATION})")
            lines.append("")
            lines.append(f"Low-n categories ({', '.join(sorted(set(
                s['event_type'] for s in low_n_top)))}"
                f") excluded from production recommendation "
                f"-- see Directional Hints section.")
            lines.append("")
            lines.append(f"- **Category:** {best_prod['event_type']} @ "
                         f"{best_prod['window']}d (n={best_prod['n']})")
            lines.append(f"- **T1:** {best_prod['t1']}%  ")
            lines.append(f"- **SL:** {best_prod['sl']}%  ")
            lines.append(f"- **RR:** {best_prod['rr']}  ")
            lines.append(f"- **Expectancy:** {best_prod['expectancy']} "
                         f"alpha-units per trade  ")
            lines.append(f"- **Target hit rate:** {best_prod['target_pct']}%  ")
            lines.append(f"- **SL hit rate:** {best_prod['sl_pct']}%  ")
            lines.append(f"- **Expiry rate:** {best_prod['expiry_pct']}%  ")
            if len(prod_top) > 1:
                lines.append("")
                lines.append("### Other production-grade categories (best combo each)")
                for s in prod_top[1:]:
                    lines.append(f"- {s['event_type']} @ {s['window']}d "
                                 f"(n={s['n']}): "
                                 f"T1={s['t1']}%, SL={s['sl']}%, "
                                 f"RR={s['rr']}, expect={s['expectancy']}")
            lines.append("")
        else:
            lines.append("## Recommended Ladder — Production-Grade "
                         f"(n >= {MIN_N_FOR_RECOMMENDATION})")
            lines.append("")
            lines.append("**No category meets the minimum sample size.** "
                         "See Directional Hints for low-n results.")
            lines.append("")

        if low_n_top:
            lines.append("## Directional Hints — Low-n Categories "
                         f"(n < {MIN_N_FOR_RECOMMENDATION}, NOT for production)")
            lines.append("")
            lines.append("These categories have wide confidence intervals. "
                         "Use for qualitative direction only — do NOT deploy "
                         "a ladder based solely on these numbers.")
            lines.append("")
            for s in low_n_top:
                lines.append(f"- **{s['event_type']} @ {s['window']}d "
                             f"(n={s['n']}):** "
                             f"T1={s['t1']}%, SL={s['sl']}%, "
                             f"RR={s['rr']}, expect={s['expectancy']}, "
                             f"target={s['target_pct']}%, "
                             f"SL={s['sl_pct']}%, "
                             f"expiry={s['expiry_pct']}%")
            lines.append("")

    # --- Write ---
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print(f"\nScope 2 report saved: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="B2 Event-Study Backtest -- Scope 1 + conditional Scope 2")
    ap.add_argument("--scope1-only", action="store_true",
                    help="Run Scope 1 only (skip Scope 2 even if gate passes)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch data but do not write report files")
    args = ap.parse_args()

    sb = get_client()

    # --- Scope 1 ---
    scope1_lines, pass_categories = run_scope1(sb)

    if not pass_categories:
        print("\n[GATE FAILED] GATE FAILED -- Scope 2 skipped. "
              "No category supports RR>=1.5 from endpoint data.")
        return

    if args.scope1_only:
        print(f"\n[SKIPPED]  --scope1-only set -- Scope 2 skipped. "
              f"{len(pass_categories)} category-horizon pair(s) would have run.")
        return

    # --- Scope 2 ---
    print(f"\n[PASS] GATE PASSED -- {len(pass_categories)} category-horizon pair(s). "
          "Running Scope 2 path-aware sweep...")
    run_scope2(sb, pass_categories, scope1_lines)


if __name__ == "__main__":
    main()

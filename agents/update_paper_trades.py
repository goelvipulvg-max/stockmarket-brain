"""
StockMarket-Brain | Paper Trade Updater

Logic:
- Fetches all OPEN trades from Supabase
- Gets today's intraday OPEN, HIGH and LOW from Yahoo Finance
- Multi-level trailing stop-loss: T1 → T2 → T3 (equity) / T1 → T2 exit (FNO)
- Gap-down protection (BUY): WAIT zone + mandatory exit floor
- Gap-up protection (SELL): WAIT zone + mandatory exit ceiling
- Gap-up trailing SL adjustment (BUY equity, T2+)
- Idempotency guards: t1_hit / t2_hit prevent duplicate upgrades
- DRY-RUN mode: --dry-run flag skips all DB writes
- Swing window: trades stay OPEN for up to their per-row max_holding_days calendar
  days (horizon-based: SHORT=3 / MEDIUM=10 / LONG=30; set at signal time by Tier-2F).
  Falls back to DEFAULT_HOLDING_DAYS when a row's max_holding_days is NULL/0/missing.
- At 15:30 IST on day >= that trade's max_holding_days, force-closes it as EXPIRED at LTP

Backtest convention: zero slippage. Exit at exact target/SL on hit, LTP on expiry.
"""
import sys
from datetime import datetime, date, time as dt_time
from zoneinfo import ZoneInfo
from utils.supabase_client import get_client
from utils.capital_ledger import release_capital
from utils.trade_memory_writer import update_trade_memory_outcome
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
load_dotenv(override=True)

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = dt_time(15, 30)
DEFAULT_HOLDING_DAYS = 10  # fallback only when a row's max_holding_days is NULL/0/missing (matches schema DEFAULT 10)
DRY_RUN = "--dry-run" in sys.argv

# ── Trailing stop-loss parameters (all multipliers on entry_price) ──
EQ_SL_INITIAL  = 0.95
EQ_T1          = 1.05
EQ_SL_T1       = 1.03    # HOTFIX-6: 50% of new T1 (6%) — was 50% of old T1 (3%)
EQ_T2          = 1.10
EQ_SL_T2       = 1.06    # HOTFIX-6: = new T1 (6%) — was = old T1 (3%)
EQ_T3          = 1.15
FNO_SL_INITIAL = 0.90
FNO_T1         = 1.10
FNO_SL_T1      = 1.05
FNO_T2         = 1.20
GAP_MANDATORY_EXIT     = 0.90   # BUY hard floor (entry * 0.90)
GAP_MANDATORY_CEILING  = 1.10   # SELL hard ceiling (entry * 1.10)
GAP_WAIT_PCT           = 0.04   # 4% of entry around SL = WAIT zone
GAP_UP_OPEN_THRESHOLD  = 1.03   # day_open > entry * 1.03
GAP_UP_TRAIL_FACTOR    = 0.98   # new trailing_sl = day_open * 0.98


def _dir_price(entry, mult, direction):
    """Price at BUY multiplier `mult` of entry. SELL inverts: entry * (2 - mult)."""
    if direction == "BUY":
        return round(entry * mult, 2)
    return round(entry * (2 - mult), 2)


def should_force_expire(holding_days, row_max_holding_days, is_market_close,
                        default_days=DEFAULT_HOLDING_DAYS):
    """Time-stop decision for an OPEN trade (pure; no I/O).

    Honors the trade's per-row max_holding_days (horizon window SHORT=3 /
    MEDIUM=10 / LONG=30). Falls back to default_days when the row value is
    NULL / 0 / missing. Calendar-day based, matching holding_days upstream.
    """
    max_hold = row_max_holding_days or default_days
    return is_market_close and holding_days >= max_hold


try:
    supabase = get_client()
except ValueError as e:
    print(f"FATAL: {e}")
    sys.exit(1)
_session = curl_requests.Session(impersonate="chrome124")


def get_market_data(ticker):
    """Returns dict with ltp, day_high, day_low, day_open. None if fetch failed."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com",
        }
        r = _session.get(url, headers=headers, timeout=10)
        result = r.json()["chart"]["result"][0]
        meta = result["meta"]
        ltp = float(meta["regularMarketPrice"])
        day_open = ltp
        try:
            quotes = result.get("indicators", {}).get("quote", [])
            if quotes and quotes[0].get("open"):
                opens = [o for o in quotes[0]["open"] if o is not None]
                if opens:
                    day_open = float(opens[0])
        except Exception:
            day_open = float(meta.get("chartPreviousClose", ltp))
        return {
            "ltp": round(ltp, 2),
            "day_high": round(float(meta.get("regularMarketDayHigh", ltp)), 2),
            "day_low": round(float(meta.get("regularMarketDayLow", ltp)), 2),
            "day_open": round(day_open, 2),
        }
    except Exception as e:
        print(f"  Fetch failed for {ticker}: {type(e).__name__}: {e}")
        return None


def calc_pnl_pct(direction, entry, exit_price):
    """BUY: profit when exit > entry. SELL: profit when exit < entry."""
    if direction == "BUY":
        return round(((exit_price - entry) / entry) * 100, 2)
    return round(((entry - exit_price) / entry) * 100, 2)


def compute_pnl_rs(pnl_pct, entry, qty):
    """Rupee P&L from a direction-adjusted pnl_pct (pnl_pct already encodes BUY/SELL).

    Returns None when qty is missing -- legacy source='TIER2' rows have no quantity
    and their rupee P&L is not back-computable, so pnl_rs stays NULL for them.
    """
    if qty is None:
        return None
    return round((pnl_pct / 100.0) * entry * qty, 2)


def _close_expired(trade, exit_price, holding_days, now_ist):
    """Force-close an OPEN trade as EXPIRED at exit_price.

    Single source of truth for the expiry close: DB status update + capital
    release + trade-memory outcome (all DRY_RUN-aware). Used by both the normal
    time-stop path (exit at LTP) and the fetch-fail-at-time-stop path
    (HOTFIX-1 / Q11=a: exit at entry_price -- the last-known price, since the
    row carries no mark-to-market). Returns pnl_pct.
    """
    direction = trade.get("direction", "BUY")
    entry = float(trade["entry_price"])
    pnl = calc_pnl_pct(direction, entry, exit_price)
    qty = trade.get("quantity")
    pnl_rs = compute_pnl_rs(pnl, entry, qty)
    update_data = {
        "status": "EXPIRED",
        "closed_at": now_ist.isoformat(),
        "exit_price": exit_price,
        "pnl_pct": pnl,
        "pnl_rs": pnl_rs,
    }
    if DRY_RUN:
        print(f"  [DRY-RUN] Would update: {update_data}")
    else:
        supabase.table("paper_trades").update(update_data)\
            .eq("id", trade["id"]).execute()
    # Phase 2: release capital on close (D3: skip NULL-quantity trades)
    if not DRY_RUN:
        if qty is not None:
            release_capital(trade["id"], float(trade["position_size_rs"]), pnl_rs)
        else:
            print(f"  {trade['ticker']}: pre-Phase-2 trade (no quantity), skipping ledger")
    # Phase 7 §9.2: backfill outcome onto the LIVE_TRADE row (SUPABASE, non-fatal)
    update_trade_memory_outcome(supabase, trade["id"], "EXPIRED", pnl, holding_days, dry_run=DRY_RUN)
    return pnl


def main():
    now_ist = datetime.now(IST)
    is_market_close = now_ist.time() >= MARKET_CLOSE
    if DRY_RUN:
        print("*** DRY-RUN MODE — no DB writes ***")
    print(f"Run @ {now_ist.strftime('%Y-%m-%d %H:%M IST')} | Market close window: {is_market_close}")

    open_trades = supabase.table("paper_trades")\
        .select("*").eq("status", "OPEN").execute().data

    print(f"Open trades: {len(open_trades)}")
    closed = 0
    upgraded = 0

    for trade in open_trades:
        ticker = trade["ticker"]
        signal_date = date.fromisoformat(trade["signal_date"])
        holding_days = (now_ist.date() - signal_date).days
        max_hold = trade.get("max_holding_days") or DEFAULT_HOLDING_DAYS  # per-row horizon

        # ── HOTFIX-1 (P1-2): decide the time-stop BEFORE any skip/continue, so a
        # fetch failure or a gap-WAIT hold can never swallow an expiry. ──
        must_expire = should_force_expire(holding_days, trade.get("max_holding_days"), is_market_close)

        market = get_market_data(ticker)
        if market is None:
            if must_expire:
                # Q11=a: no live quote on the trade's last day. Close EXPIRED at
                # entry_price (the last-known price -- the row has no mark-to-
                # market) => 0% P&L. Route straight to the shared expiry close;
                # do NOT run hit detection on a fabricated quote (that would
                # mis-fire SL_HIT for BUY winners whose trailing SL > entry).
                exit_price = round(float(trade["entry_price"]), 2)
                pnl = _close_expired(trade, exit_price, holding_days, now_ist)
                closed += 1
                print(f"  {ticker}: fetch failed at time-stop -- EXPIRED at last-known "
                      f"{exit_price} | PnL: {pnl}%  (day {holding_days})")
            else:
                print(f"  {ticker}: skip (no data)")
            continue

        direction = trade.get("direction", "BUY")
        entry = float(trade["entry_price"])

        segment = trade.get("segment") or "EQUITY"
        current_level = trade.get("current_target_level") or "T1"
        t1_hit = bool(trade.get("t1_hit", False))
        t2_hit = bool(trade.get("t2_hit", False))
        t2_price = float(trade["t2_price"]) if trade.get("t2_price") else None
        t3_price = float(trade["t3_price"]) if trade.get("t3_price") else None
        trailing_sl_val = float(trade["trailing_sl"]) if trade.get("trailing_sl") else None
        original_target = float(trade["target_price"])
        original_sl = float(trade["stop_loss"])

        # ── Active target & stop-loss by current level ──
        if current_level == "T3":
            active_target = t3_price or _dir_price(entry, EQ_T3, direction)
            active_sl = trailing_sl_val or original_sl
        elif current_level == "T2":
            active_target = t2_price or _dir_price(
                entry, (FNO_T2 if segment == "FNO" else EQ_T2), direction)
            active_sl = trailing_sl_val or original_sl
        else:
            active_target = original_target
            active_sl = original_sl

        # ── Gap-Up trailing SL (BUY, equity, T2+) ──
        if direction == "BUY" and segment == "EQUITY" and t2_hit:
            if market["day_open"] > entry * GAP_UP_OPEN_THRESHOLD:
                new_trail = round(market["day_open"] * GAP_UP_TRAIL_FACTOR, 2)
                if new_trail > active_sl:
                    active_sl = new_trail
                    update_data = {"trailing_sl": new_trail}
                    if DRY_RUN:
                        print(f"  [DRY-RUN] Would update: {update_data}")
                    else:
                        supabase.table("paper_trades").update(update_data)\
                            .eq("id", trade["id"]).execute()
                    print(f"  {ticker}: GAP-UP | open={market['day_open']} | "
                          f"trailing_sl → {new_trail}")

        # ── HOTFIX-2 (P0-2): day-0 look-ahead guard ──
        # get_market_data returns the FULL day's high/low (range=1d). On the
        # entry day those span price action BEFORE the intraday entry
        # (signal_generated_at) => look-ahead. Detect day-0 from
        # signal_generated_at, compared in IST (fallback: signal_date when the
        # timestamp is NULL/unparseable), and use LTP-only hit checks that day
        # (Q7=a). hi/lo == the true day range on day-1+ (no behaviour change).
        sig_at = trade.get("signal_generated_at")
        entry_day = signal_date
        if sig_at:
            try:
                entry_day = datetime.fromisoformat(
                    str(sig_at).replace("Z", "+00:00")).astimezone(IST).date()
            except (ValueError, TypeError):
                entry_day = signal_date
        is_day0 = (entry_day == now_ist.date())
        hi = market["ltp"] if is_day0 else market["day_high"]
        lo = market["ltp"] if is_day0 else market["day_low"]
        if is_day0:
            print(f"  {ticker}: day-0 (entry {entry_day} IST) -- LTP-only hit checks (no look-ahead)")

        # ── Hit detection ──
        new_status = None
        gap_exit_price = None

        # Target hit (checked first — both directions)
        if direction == "BUY" and hi >= active_target:
            new_status = "TARGET_HIT"
        elif direction == "SELL" and lo <= active_target:
            new_status = "TARGET_HIT"

        # SL check with gap protection (HOTFIX-2: hi/lo are LTP-only on day-0)
        if not new_status:
            if direction == "BUY" and lo <= active_sl:
                mandatory_floor = round(entry * GAP_MANDATORY_EXIT, 2)
                wait_floor = round(active_sl - (entry * GAP_WAIT_PCT), 2)
                if lo <= mandatory_floor:
                    new_status = "SL_HIT"
                    gap_exit_price = mandatory_floor
                elif lo > wait_floor and not must_expire:
                    # HOTFIX-1: hold in the soft WAIT zone ONLY if not at the
                    # time-stop; if expiring today fall through to the expiry
                    # close below (don't let WAIT swallow the time-stop).
                    print(f"  {ticker}: GAP-DOWN WAIT | day_low={lo} "
                          f"in WAIT zone [{wait_floor}–{active_sl}] | holding")
                    continue
                elif lo <= wait_floor:
                    new_status = "SL_HIT"

            elif direction == "SELL" and hi >= active_sl:
                mandatory_ceiling = round(entry * GAP_MANDATORY_CEILING, 2)
                wait_ceiling = round(active_sl + (entry * GAP_WAIT_PCT), 2)
                if hi >= mandatory_ceiling:
                    new_status = "SL_HIT"
                    gap_exit_price = mandatory_ceiling
                elif hi < wait_ceiling and not must_expire:
                    print(f"  {ticker}: GAP-UP WAIT (SELL) | day_high={hi} "
                          f"in WAIT zone [{active_sl}–{wait_ceiling}] | holding")
                    continue
                elif hi >= wait_ceiling:
                    new_status = "SL_HIT"

        # ── Expiry (time-stop) — decision hoisted to must_expire above (HOTFIX-1) ──
        if not new_status and must_expire:
            new_status = "EXPIRED"

        # ── Act on result ──
        if new_status == "TARGET_HIT":
            if current_level == "T1":
                if t1_hit:
                    print(f"  {ticker}: T1 already processed (idempotent), skipping")
                    continue
                is_fno = (segment == "FNO")
                t2_p = _dir_price(entry, (FNO_T2 if is_fno else EQ_T2), direction)
                new_sl = _dir_price(entry, (FNO_SL_T1 if is_fno else EQ_SL_T1), direction)
                update_data = {
                    "t1_hit": True,
                    "current_target_level": "T2",
                    "t2_price": t2_p,
                    "trailing_sl": new_sl,
                }
                if not is_fno:
                    update_data["t3_price"] = _dir_price(entry, EQ_T3, direction)
                if DRY_RUN:
                    print(f"  [DRY-RUN] Would update: {update_data}")
                else:
                    supabase.table("paper_trades").update(update_data)\
                        .eq("id", trade["id"]).execute()
                upgraded += 1
                print(f"  {ticker}: T1_HIT @ {active_target} → T2 "
                      f"(new SL={new_sl}, T2={t2_p})  (day {holding_days})")

            elif current_level == "T2":
                if segment == "FNO":
                    exit_price = active_target
                    pnl = calc_pnl_pct(direction, entry, exit_price)
                    qty = trade.get("quantity")
                    pnl_rs = compute_pnl_rs(pnl, entry, qty)
                    update_data = {
                        "status": "TARGET_HIT",
                        "closed_at": now_ist.isoformat(),
                        "exit_price": exit_price,
                        "pnl_pct": pnl,
                        "pnl_rs": pnl_rs,
                        "t2_hit": True,
                    }
                    if DRY_RUN:
                        print(f"  [DRY-RUN] Would update: {update_data}")
                    else:
                        supabase.table("paper_trades").update(update_data)\
                            .eq("id", trade["id"]).execute()
                    closed += 1
                    # Phase 2: release capital on close (D3: skip NULL-quantity trades)
                    if not DRY_RUN:
                        if qty is not None:
                            release_capital(trade["id"], float(trade["position_size_rs"]), pnl_rs)
                        else:
                            print(f"  {ticker}: pre-Phase-2 trade (no quantity), skipping ledger")
                    # Phase 7 §9.2: backfill outcome onto the LIVE_TRADE row (SUPABASE, non-fatal)
                    update_trade_memory_outcome(supabase, trade["id"], new_status, pnl, holding_days, dry_run=DRY_RUN)
                    print(f"  {ticker}: T2_HIT (FNO) @ {exit_price} | PnL: {pnl}% | "
                          f"CLOSED  (day {holding_days})")
                else:
                    if t2_hit:
                        print(f"  {ticker}: T2 already processed (idempotent), skipping")
                        continue
                    trail_sl = _dir_price(entry, EQ_SL_T2, direction)
                    update_data = {
                        "t2_hit": True,
                        "current_target_level": "T3",
                        "trailing_sl": trail_sl,
                    }
                    if DRY_RUN:
                        print(f"  [DRY-RUN] Would update: {update_data}")
                    else:
                        supabase.table("paper_trades").update(update_data)\
                            .eq("id", trade["id"]).execute()
                    upgraded += 1
                    print(f"  {ticker}: T2_HIT @ {active_target} → T3 "
                          f"(new SL={trail_sl})  (day {holding_days})")

            else:  # T3 — final exit (equity only)
                exit_price = active_target
                pnl = calc_pnl_pct(direction, entry, exit_price)
                qty = trade.get("quantity")
                pnl_rs = compute_pnl_rs(pnl, entry, qty)
                update_data = {
                    "status": "TARGET_HIT",
                    "closed_at": now_ist.isoformat(),
                    "exit_price": exit_price,
                    "pnl_pct": pnl,
                    "pnl_rs": pnl_rs,
                }
                if DRY_RUN:
                    print(f"  [DRY-RUN] Would update: {update_data}")
                else:
                    supabase.table("paper_trades").update(update_data)\
                        .eq("id", trade["id"]).execute()
                closed += 1
                # Phase 2: release capital on close (D3: skip NULL-quantity trades)
                if not DRY_RUN:
                    if qty is not None:
                        release_capital(trade["id"], float(trade["position_size_rs"]), pnl_rs)
                    else:
                        print(f"  {ticker}: pre-Phase-2 trade (no quantity), skipping ledger")
                # Phase 7 §9.2: backfill outcome onto the LIVE_TRADE row (SUPABASE, non-fatal)
                update_trade_memory_outcome(supabase, trade["id"], new_status, pnl, holding_days, dry_run=DRY_RUN)
                print(f"  {ticker}: T3_HIT @ {exit_price} | PnL: {pnl}% | "
                      f"CLOSED  (day {holding_days})")

        elif new_status == "SL_HIT":
            exit_price = gap_exit_price or active_sl
            pnl = calc_pnl_pct(direction, entry, exit_price)
            qty = trade.get("quantity")
            pnl_rs = compute_pnl_rs(pnl, entry, qty)
            label = "GAP-EXIT" if gap_exit_price else "SL_HIT"
            update_data = {
                "status": "SL_HIT",
                "closed_at": now_ist.isoformat(),
                "exit_price": exit_price,
                "pnl_pct": pnl,
                "pnl_rs": pnl_rs,
                "trailing_sl": active_sl,
            }
            if DRY_RUN:
                print(f"  [DRY-RUN] Would update: {update_data}")
            else:
                supabase.table("paper_trades").update(update_data)\
                    .eq("id", trade["id"]).execute()
            closed += 1
            # Phase 2: release capital on close (D3: skip NULL-quantity trades)
            if not DRY_RUN:
                if qty is not None:
                    release_capital(trade["id"], float(trade["position_size_rs"]), pnl_rs)
                else:
                    print(f"  {ticker}: pre-Phase-2 trade (no quantity), skipping ledger")
            # Phase 7 §9.2: backfill outcome onto the LIVE_TRADE row (SUPABASE, non-fatal)
            update_trade_memory_outcome(supabase, trade["id"], new_status, pnl, holding_days, dry_run=DRY_RUN)
            print(f"  {ticker}: {label} @ {exit_price} | PnL: {pnl}%  (day {holding_days})")

        elif new_status == "EXPIRED":
            exit_price = market["ltp"]
            pnl = _close_expired(trade, exit_price, holding_days, now_ist)
            closed += 1
            print(f"  {ticker}: EXPIRED @ {exit_price} | PnL: {pnl}%  (day {holding_days})")

        else:
            days_left = max(0, max_hold - holding_days)
            level_info = f"T={active_target} SL={active_sl}"
            print(f"  {ticker}: OPEN [{current_level}] | LTP {market['ltp']} "
                  f"(range: {market['day_low']}-{market['day_high']}) | "
                  f"{level_info} | day {holding_days}/{max_hold}, "
                  f"{days_left} left")

    still_open = len(open_trades) - closed
    print(f"\nDone. Closed: {closed} | Upgraded: {upgraded} | "
          f"Still OPEN: {still_open} | Total checked: {len(open_trades)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Paper trade updater crashed - {type(e).__name__}: {e}")
        sys.exit(1)

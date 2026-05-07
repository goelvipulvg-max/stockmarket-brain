import os
import sys
import datetime
import warnings

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(override=True)

import yfinance as yf
import vectorbt as vbt
from supabase import create_client

# --- Constants (mirrors backtest_sma.py exactly) ---
TICKERS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "BAJFINANCE.NS", "WIPRO.NS", "ADANIENT.NS", "HCLTECH.NS",
]
START_DATE = "2022-01-01"
END_DATE = datetime.date.today().isoformat()
INIT_CASH = 250_000
SIZE_PER_TICKER = 25_000
FEES = 0.001
SMA_FAST = 50
SMA_SLOW = 200

SEP = "=" * 66
INNER = "-" * 66


# --- SMA helpers (copied verbatim from backtest_sma.py) ---

def fetch_prices(tickers, start, end):
    data = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    close = data["Close"]
    bad = close.columns[close.isna().all()].tolist()
    for t in bad:
        print(f"  [WARN] {t}: no data returned, skipping")
    return close.drop(columns=bad)


def compute_signals(close):
    sma_fast = close.rolling(SMA_FAST).mean()
    sma_slow = close.rolling(SMA_SLOW).mean()
    entries = (sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1))
    exits = (sma_fast < sma_slow) & (sma_fast.shift(1) >= sma_slow.shift(1))
    return entries.fillna(False), exits.fillna(False)


def run_backtest(close, entries, exits):
    return vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=exits,
        init_cash=INIT_CASH,
        size=SIZE_PER_TICKER,
        size_type="value",
        fees=FEES,
        freq="D",
    )


def _get_scalar(val):
    if hasattr(val, "item"):
        return float(val.item())
    return float(val)


# --- Supabase helper (copied verbatim from backtest_analysis.py) ---

def fetch_all_trades(sb):
    rows, offset, page = [], 0, 1000
    while True:
        res = sb.table("paper_trades").select("*").order("signal_generated_at").range(offset, offset + page - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


# --- Section printers ---

def print_sma_section(pf, tickers):
    total_returns = pf.total_return() * 100
    ann_returns = pf.annualized_return() * 100
    sharpes = pf.sharpe_ratio()
    max_dds = pf.max_drawdown() * 100
    trade_counts = pf.trades.count()

    print(f"\n{SEP}")
    print(f"  STRATEGY 1: SMA {SMA_FAST}/{SMA_SLOW} Baseline")
    print(f"  Period : {START_DATE} -> {END_DATE}")
    print(f"  Tickers: {len(tickers)}  |  Rs {SIZE_PER_TICKER:,}/ticker  |  {FEES*100:.1f}% fees")
    print(SEP)
    print(f"  {'Ticker':<16} {'Total Ret':>10} {'CAGR':>8} {'Sharpe':>8} {'Max DD':>10} {'# Trades':>10}")
    print(f"  {INNER}")

    for ticker in tickers:
        try:
            tr = _get_scalar(total_returns[ticker])
            ar = _get_scalar(ann_returns[ticker])
            sh = _get_scalar(sharpes[ticker])
            md = _get_scalar(max_dds[ticker])
            tc = int(trade_counts[ticker])
            print(f"  {ticker:<16} {tr:>+9.1f}% {ar:>+7.1f}% {sh:>8.2f} {md:>+9.1f}% {tc:>10}")
        except (KeyError, TypeError):
            print(f"  {ticker:<16} {'N/A':>10} {'N/A':>8} {'N/A':>8} {'N/A':>10} {'N/A':>10}")

    print(f"  {INNER}")
    tr = _get_scalar(total_returns.mean())
    ar = _get_scalar(ann_returns.mean())
    sh = _get_scalar(sharpes.mean())
    md = _get_scalar(max_dds.mean())
    tc = int(trade_counts.sum())
    print(f"  {'PORTFOLIO':<16} {tr:>+9.1f}% {ar:>+7.1f}% {sh:>8.2f} {md:>+9.1f}% {tc:>10}")
    print(SEP)


def print_ai_section(rows):
    dates = sorted(r["signal_date"] for r in rows if r.get("signal_date"))
    period_start = dates[0] if dates else "?"
    period_end = dates[-1] if dates else "?"
    try:
        maturity = (
            datetime.date.fromisoformat(period_end) - datetime.date.fromisoformat(period_start)
        ).days + 1
        maturity_str = f"{maturity} day{'s' if maturity != 1 else ''}"
    except (ValueError, TypeError):
        maturity_str = "?"

    open_trades = [r for r in rows if not r.get("status") or r.get("status") == "OPEN"]
    closed = [r for r in rows if r.get("status") in ("TARGET_HIT", "SL_HIT", "EXPIRED") and r.get("pnl_pct") is not None]
    wins = [r for r in closed if r.get("status") == "TARGET_HIT"]
    losses = [r for r in closed if r.get("status") == "SL_HIT"]
    expired = [r for r in closed if r.get("status") == "EXPIRED"]

    win_rate = f"{len(wins) / (len(wins) + len(losses)) * 100:.1f}%" if (wins or losses) else "N/A"
    avg_pnl = f"{sum(r['pnl_pct'] for r in closed) / len(closed):+.2f}%" if closed else "N/A"
    conf_vals = [r["confidence"] for r in rows if r.get("confidence") is not None]
    avg_conf = f"{sum(conf_vals) / len(conf_vals):.1f}" if conf_vals else "N/A"

    print(f"\n{SEP}")
    print(f"  STRATEGY 2: Tier-2 AI Signals  (Supabase paper_trades)")
    print(f"  Period : {period_start} -> {period_end}  ({maturity_str})")
    print(f"  NOTE   : CAGR / Sharpe not computed -- insufficient data maturity")
    print(SEP)
    print(f"  {'Metric':<36} {'Value':>10}")
    print(f"  {INNER}")
    print(f"  {'Total signals':<36} {len(rows):>10}")
    print(f"  {'Open trades':<36} {len(open_trades):>10}")
    print(f"  {'Closed trades':<36} {len(closed):>10}")
    print(f"  {'  TARGET_HIT (wins)':<36} {len(wins):>10}")
    print(f"  {'  SL_HIT (losses)':<36} {len(losses):>10}")
    print(f"  {'  EXPIRED (no meaningful PnL)':<36} {len(expired):>10}")
    print(f"  {'Win rate  (excl. expired)':<36} {win_rate:>10}")
    print(f"  {'Avg PnL % (closed w/ PnL)':<36} {avg_pnl:>10}")
    print(f"  {'Avg confidence score':<36} {avg_conf:>10}")
    print(f"  {'Data maturity':<36} {maturity_str:>10}")
    print(SEP)


# --- Main ---

def main():
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    print(f"Fetching 3Y price data for {len(TICKERS)} tickers...")
    try:
        close = fetch_prices(TICKERS, START_DATE, END_DATE)
    except Exception as e:
        print(f"[ERROR] Failed to fetch price data: {e}")
        sys.exit(1)

    active_tickers = close.columns.tolist()
    print(f"Computing SMA {SMA_FAST}/{SMA_SLOW} signals and running backtest...")
    entries, exits = compute_signals(close)
    pf = run_backtest(close, entries, exits)
    print_sma_section(pf, active_tickers)

    print(f"\nFetching AI signals from Supabase...")
    try:
        sb = create_client(supabase_url, supabase_key)
        rows = fetch_all_trades(sb)
    except Exception as e:
        print(f"[ERROR] Failed to fetch paper trades: {e}")
        sys.exit(1)

    if not rows:
        print("No paper trades found — skipping Section 2.")
        return

    print_ai_section(rows)
    print()


if __name__ == "__main__":
    main()

import os
import sys
import datetime
import warnings

warnings.filterwarnings("ignore")

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import vectorbt as vbt

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
REPORTS_DIR = "reports"


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


def _get_scalar(series_or_float):
    val = series_or_float
    if hasattr(val, "item"):
        return float(val.item())
    return float(val)


def print_summary(pf, tickers):
    total_returns = pf.total_return() * 100
    ann_returns = pf.annualized_return() * 100
    sharpes = pf.sharpe_ratio()
    max_dds = pf.max_drawdown() * 100
    trade_counts = pf.trades.count()

    SEP = "-" * 68
    print(f"\nBacktest: SMA {SMA_FAST}/{SMA_SLOW} | {START_DATE} to {END_DATE} | {len(tickers)} tickers\n")
    print(f"  {'Ticker':<16} {'Total Ret':>10} {'CAGR':>8} {'Sharpe':>8} {'Max DD':>10} {'# Trades':>10}")
    print(f"  {SEP}")

    for ticker in tickers:
        try:
            tr = _get_scalar(total_returns[ticker])
            ar = _get_scalar(ann_returns[ticker])
            sh = _get_scalar(sharpes[ticker])
            md = _get_scalar(max_dds[ticker])
            tc = int(trade_counts[ticker])
        except (KeyError, TypeError):
            continue
        print(f"  {ticker:<16} {tr:>+9.1f}% {ar:>+7.1f}% {sh:>8.2f} {md:>+9.1f}% {tc:>10}")

    print(f"  {SEP}")
    tr = _get_scalar(total_returns.mean())
    ar = _get_scalar(ann_returns.mean())
    sh = _get_scalar(sharpes.mean())
    md = _get_scalar(max_dds.mean())
    tc = int(trade_counts.sum())
    print(f"  {'PORTFOLIO':<16} {tr:>+9.1f}% {ar:>+7.1f}% {sh:>8.2f} {md:>+9.1f}% {tc:>10}")


def save_report(pf, close):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = f"{REPORTS_DIR}/backtest_sma_{datetime.date.today().strftime('%Y%m%d')}.html"

    value = pf.value()
    cum_ret = (value / value.iloc[0] - 1) * 100
    drawdown = pf.drawdown() * 100

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Cumulative Return (%)", "Drawdown (%)"),
        row_heights=[0.65, 0.35],
        vertical_spacing=0.08,
    )
    for ticker in cum_ret.columns:
        fig.add_trace(go.Scatter(x=cum_ret.index, y=cum_ret[ticker], name=ticker, mode="lines"), row=1, col=1)
    for ticker in drawdown.columns:
        fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown[ticker], name=ticker, mode="lines", showlegend=False), row=2, col=1)

    fig.update_layout(
        title=f"SMA {SMA_FAST}/{SMA_SLOW} Backtest | {START_DATE} → {END_DATE} | Rs 25k/ticker | 0.1% fees",
        hovermode="x unified",
        height=700,
    )
    fig.write_html(path)
    return path


def main():
    print(f"Fetching 3Y price data for {len(TICKERS)} tickers...")
    try:
        close = fetch_prices(TICKERS, START_DATE, END_DATE)
    except Exception as e:
        print(f"[ERROR] Failed to fetch price data: {e}")
        sys.exit(1)

    active_tickers = close.columns.tolist()
    print(f"Computing SMA {SMA_FAST}/{SMA_SLOW} signals...")
    entries, exits = compute_signals(close)

    print("Running backtest...")
    pf = run_backtest(close, entries, exits)

    print_summary(pf, active_tickers)

    print("\nSaving HTML report...")
    path = save_report(pf, close)
    print(f"Report saved: {path}")


if __name__ == "__main__":
    main()

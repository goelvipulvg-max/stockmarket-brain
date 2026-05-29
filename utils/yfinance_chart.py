"""
Yahoo Finance Chart Snapshot — Phase 3, v3.1 Master Plan §6 (Batch A2).
2-year daily chart → RSI, MACD, support/resistance, trend. Gate V3.1.

RSI/MACD formulas match tier2_signals.py exactly (pandas_ta, same params).
Trend is SMA-based: last_close vs SMA_50 vs SMA_200.
Adjusted close used throughout — split/bonus safe.
"""
import pandas as pd
import pandas_ta as ta
import yfinance as yf


def get_chart_snapshot(ticker: str) -> dict:
    """Return technical snapshot for `ticker` (e.g. RELIANCE.NS).

    Raises RuntimeError on fetch failure — never returns silent zeros.
    """
    stock = yf.Ticker(ticker)
    df = stock.history(period="2y", auto_adjust=True)

    if df.empty or len(df) < 20:
        raise RuntimeError(
            f"yFinance returned insufficient data for {ticker} "
            f"({len(df)} rows, need >= 20)"
        )

    close = df["Close"]
    last_close = float(close.iloc[-1])

    # RSI-14
    rsi_series = ta.rsi(close, length=14)
    rsi_14 = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else None

    # MACD 12/26/9 (exact tier2_signals formula)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is not None:
        macd_line = float(macd_df["MACD_12_26_9"].iloc[-1])
        macd_signal = float(macd_df["MACDs_12_26_9"].iloc[-1])
        macd_hist = float(macd_df["MACDh_12_26_9"].iloc[-1])
    else:
        macd_line = macd_signal = macd_hist = None

    # Support / resistance (20-day rolling, same as tier2_signals)
    support = float(df["Low"].rolling(20).min().iloc[-1])
    resistance = float(df["High"].rolling(20).max().iloc[-1])

    # SMA-50 and SMA-200
    sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

    # Volume (latest + raw series) -- reliability-gap #3. Defensive: any problem
    # degrades to None / [] rather than raising, so an index like ^NSEI (which may
    # lack or zero-fill Volume) never breaks the snapshot or the NIFTY-mood gate.
    try:
        volume_series = [float(x) for x in df["Volume"].values]
        latest_vol = volume_series[-1] if volume_series else None
        if latest_vol is not None and latest_vol != latest_vol:  # NaN
            latest_vol = None
    except Exception:
        latest_vol = None
        volume_series = []

    # Trend — SMA-based, explicit INSUFFICIENT_DATA when SMAs unavailable
    if sma_50 is None or sma_200 is None or pd.isna(sma_50) or pd.isna(sma_200):
        trend = "INSUFFICIENT_DATA"
    elif last_close > sma_50 > sma_200:
        trend = "UPTREND"
    elif last_close < sma_50 < sma_200:
        trend = "DOWNTREND"
    else:
        trend = "SIDEWAYS"

    return {
        "ticker": ticker,
        "last_close": last_close,
        "rsi_14": rsi_14,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "volume": latest_vol,
        "volume_series": volume_series,
        "close_series": [float(x) for x in close.values],
    }

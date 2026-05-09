"""Loop 6 — Liquidity Gate: filters stocks by 5-day average daily traded value."""

import os
from dotenv import load_dotenv
load_dotenv(override=True)

MIN_DAILY_VALUE_INR = 50_000_000  # Rs 5 Crore


def check_liquidity(symbol: str) -> tuple:
    """
    Returns (is_liquid, avg_daily_value_inr).
    Checks last 5 days average daily traded value via yFinance.
    """
    import yfinance as yf

    if not symbol:
        return False, 0.0

    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="5d")
        if hist.empty:
            return False, 0.0
        avg_volume = hist["Volume"].mean()
        avg_price = hist["Close"].mean()
        avg_daily_value = avg_volume * avg_price
        return avg_daily_value >= MIN_DAILY_VALUE_INR, float(avg_daily_value)
    except Exception as e:
        print(f"     ⚠️  Liquidity check failed for {symbol}: {e}")
        return False, 0.0

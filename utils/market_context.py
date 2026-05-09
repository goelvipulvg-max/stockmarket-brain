"""Loop 2 — Market Context: NIFTY trend + India VIX gate before any trade."""

import yfinance as yf
from dotenv import load_dotenv
load_dotenv(override=True)


def get_market_context() -> tuple:
    """
    Returns (market_mood, position_size_multiplier, nifty_change_pct, vix_value).
    market_mood: BULLISH / NEUTRAL / CAUTIOUS / BEARISH
    multiplier: 1.0 / 0.75 / 0.50 / 0.0
    """
    try:
        # NIFTY 50
        nifty = yf.Ticker("^NSEI")
        nifty_hist = nifty.history(period="2d")
        if len(nifty_hist) >= 2:
            prev_close = nifty_hist["Close"].iloc[-2]
            curr_close = nifty_hist["Close"].iloc[-1]
            nifty_change_pct = ((curr_close - prev_close) / prev_close) * 100
        else:
            nifty_change_pct = 0.0

        # India VIX
        vix = yf.Ticker("^INDIAVIX")
        vix_hist = vix.history(period="1d")
        vix_value = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 15.0

    except Exception as e:
        print(f"     ⚠️  Market context fetch failed: {e}")
        return "NEUTRAL", 1.0, 0.0, 15.0

    # Decision matrix
    if nifty_change_pct < -2.5:
        return "BEARISH", 0.0, nifty_change_pct, vix_value
    elif nifty_change_pct < -1.5 and vix_value > 20:
        return "BEARISH", 0.0, nifty_change_pct, vix_value
    elif nifty_change_pct < -0.5 or vix_value > 20:
        return "CAUTIOUS", 0.50, nifty_change_pct, vix_value
    elif nifty_change_pct < 0:
        return "NEUTRAL", 0.75, nifty_change_pct, vix_value
    else:
        return "BULLISH", 1.0, nifty_change_pct, vix_value


def format_market_context_log(mood: str, multiplier: float,
                               nifty_change: float, vix: float) -> str:
    return (f"Market: {mood} | NIFTY {nifty_change:+.2f}% | "
            f"VIX {vix:.1f} | Size multiplier: {multiplier}x")

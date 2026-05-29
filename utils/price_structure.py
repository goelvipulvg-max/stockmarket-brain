"""Stock-level price-structure metrics (pure computation, no I/O).

Derives trend-template signals from chart snapshots already fetched by
utils.yfinance_chart.get_chart_snapshot:
  - position vs SMA-50 / SMA-200
  - distance from the 52-week high
  - relative strength vs NIFTY over a lookback window

compute_price_structure() never raises and never hits the network -- any
missing or too-short input yields a None metric. validate_price_structure()
turns the metrics into a deterministic skip verdict for the (currently
DORMANT) USE_PRICE_STRUCTURE_GATE in tier2_fundamental. Reliability-gap #1.

Insufficient-data policy: a None metric => that gate check is "no-opinion =
pass". The gate NEVER skips on missing data.
"""
from typing import Optional

# --- validate_price_structure thresholds (DORMANT; tune after the B2 backtest) ---
MIN_ABOVE_SMA50 = True            # require last_close > SMA-50
MAX_PCT_FROM_52WK_HIGH = -25.0    # require within 25% of the 52-week high
MIN_RS_VS_NIFTY = 0.0             # require relative strength vs NIFTY >= 0

# --- compute_price_structure lookbacks (trading days) ---
RS_LOOKBACK = 63     # ~3 months
HIGH_LOOKBACK = 252  # ~1 year


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _return_pct(series, lookback) -> Optional[float]:
    """Percent return over the last `lookback` closes; None if series too short."""
    if not series or len(series) < lookback + 1:
        return None
    past = _safe_float(series[-(lookback + 1)])
    last = _safe_float(series[-1])
    if past is None or last is None or past == 0:
        return None
    return (last - past) / past * 100.0


def compute_price_structure(chart, nifty_chart=None,
                            rs_lookback=RS_LOOKBACK,
                            high_lookback=HIGH_LOOKBACK) -> dict:
    """Derive price-structure metrics from chart snapshots.

    `chart` is a get_chart_snapshot() dict (needs last_close, sma_50, sma_200,
    close_series). `nifty_chart` is the NIFTY snapshot (needs close_series) for
    relative strength; pass None when unavailable -> rs_vs_nifty_63d is None.

    Returns a dict with pct_vs_sma50, pct_vs_sma200, above_sma50, above_sma200,
    high_52wk, pct_from_52wk_high, stock_return_63d, nifty_return_63d,
    rs_vs_nifty_63d, rs_lookback, high_lookback. Never raises.
    """
    result = {
        "pct_vs_sma50": None,
        "pct_vs_sma200": None,
        "above_sma50": None,
        "above_sma200": None,
        "high_52wk": None,
        "pct_from_52wk_high": None,
        "stock_return_63d": None,
        "nifty_return_63d": None,
        "rs_vs_nifty_63d": None,
        "rs_lookback": rs_lookback,
        "high_lookback": high_lookback,
    }
    if not isinstance(chart, dict):
        return result

    last_close = _safe_float(chart.get("last_close"))
    sma_50 = _safe_float(chart.get("sma_50"))
    sma_200 = _safe_float(chart.get("sma_200"))

    if last_close is not None and sma_50 not in (None, 0):
        result["pct_vs_sma50"] = (last_close - sma_50) / sma_50 * 100.0
        result["above_sma50"] = last_close > sma_50
    if last_close is not None and sma_200 not in (None, 0):
        result["pct_vs_sma200"] = (last_close - sma_200) / sma_200 * 100.0
        result["above_sma200"] = last_close > sma_200

    series = chart.get("close_series")
    if series and last_close is not None:
        window = [v for v in (_safe_float(x) for x in series[-high_lookback:])
                  if v is not None]
        if window:
            high = max(window)
            result["high_52wk"] = high
            if high != 0:
                result["pct_from_52wk_high"] = (last_close - high) / high * 100.0

    stock_ret = _return_pct(series, rs_lookback)
    result["stock_return_63d"] = stock_ret
    if isinstance(nifty_chart, dict):
        nifty_ret = _return_pct(nifty_chart.get("close_series"), rs_lookback)
        result["nifty_return_63d"] = nifty_ret
        if stock_ret is not None and nifty_ret is not None:
            result["rs_vs_nifty_63d"] = stock_ret - nifty_ret

    return result


def validate_price_structure(structure) -> dict:
    """Deterministic gate verdict from compute_price_structure() output.

    DORMANT: only consulted when USE_PRICE_STRUCTURE_GATE=true in
    tier2_fundamental. A None metric => that check passes (no-opinion).
    `passes` is True iff every available check passes.

    Returns {passes, checks: {above_sma50, near_52wk_high, rs_positive}, reasons}.
    """
    checks = {"above_sma50": True, "near_52wk_high": True, "rs_positive": True}
    reasons = []

    if MIN_ABOVE_SMA50 and structure.get("above_sma50") is False:
        checks["above_sma50"] = False
        reasons.append("below_sma50")

    pfh = structure.get("pct_from_52wk_high")
    if pfh is not None and pfh < MAX_PCT_FROM_52WK_HIGH:
        checks["near_52wk_high"] = False
        reasons.append("far_from_52wk_high")

    rs = structure.get("rs_vs_nifty_63d")
    if rs is not None and rs < MIN_RS_VS_NIFTY:
        checks["rs_positive"] = False
        reasons.append("negative_relative_strength")

    return {"passes": all(checks.values()), "checks": checks, "reasons": reasons}

"""Gap Calculator — estimates expected opening gap from historical pattern data."""

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import get_neon_connection

DEFAULT_GAPS = {
    "RESULTS":              3.5,
    "DIVIDEND":             2.0,
    "BONUS":                4.0,
    "SPLIT":                3.0,
    "BUYBACK":              3.5,
    "MERGER_ACQUISITION":   5.0,
    "ACQUISITION":          3.0,
    "DIVESTMENT":           2.0,
    "INSIDER_TRADING":      3.0,
    "BULK_DEAL":            2.5,
    "FUND_RAISE":           2.5,
    "MANAGEMENT_CHANGE":    2.0,
    "CONTRACT_WIN":          3.0,
    "CREDIT_RATING":        1.5,
    "RATING_ACTION":        1.5,
    "BOARD_MEETING":        1.5,
    "LEGAL":               -2.0,
    "OTHER":                1.0,
}

MOOD_MULTIPLIERS = {
    "BULLISH":  1.2,
    "NEUTRAL":  1.0,
    "CAUTIOUS": 0.7,
    "BEARISH":  0.7,
}


def _get_historical_gap(event_type: str) -> tuple:
    """Returns (avg_gap_pct, sample_size) from pattern_library in Neon."""
    try:
        conn = get_neon_connection()
        with conn.cursor() as cur:
            # LIKE suffix match across all sectors
            cur.execute("""
                SELECT (pattern_data->>'avg_impact_pct')::numeric AS avg_gap,
                       sample_size
                FROM pattern_library
                WHERE pattern_name LIKE %s
                ORDER BY sample_size DESC
                LIMIT 1
            """, (f"%_{event_type.lower()}",))
            row = cur.fetchone()
        conn.close()
        if row and row[1] and row[1] > 0:
            gap = float(row[0]) if row[0] else None
            samples = int(row[1])
            return gap, samples
        return None, 0
    except Exception:
        return None, 0


def _determine_confidence(sample_size: int) -> str:
    if sample_size >= 10:
        return "HIGH"
    elif sample_size >= 3:
        return "MEDIUM"
    return "LOW"


def _calculate_levels(gap_pct: float) -> dict:
    """Derives entry range, target, and stop-loss from expected gap %."""
    direction = 1 if gap_pct >= 0 else -1

    return {
        "entry_low_pct":  round(gap_pct * 0.6, 2),
        "entry_high_pct": round(gap_pct * 1.0, 2),
        "target_pct":     round(gap_pct + direction * 2.0, 2),
        "stop_loss_pct":  round(-abs(gap_pct) * 1.0, 2),
    }


def calculate_expected_gap(event_type: str, market_mood: str) -> dict:
    """
    Returns:
        expected_gap_pct  — float (% change expected at next open)
        confidence        — HIGH / MEDIUM / LOW
        entry_low_pct     — conservative entry level (% from prev close)
        entry_high_pct    — aggressive entry level (% from prev close)
        target_pct        — profit target (% from prev close)
        stop_loss_pct     — stop loss (% from prev close)
    """
    hist_gap, sample_size = _get_historical_gap(event_type)
    confidence = _determine_confidence(sample_size)

    if hist_gap is not None and sample_size > 0:
        base_gap = hist_gap
    else:
        base_gap = DEFAULT_GAPS.get(event_type, DEFAULT_GAPS["OTHER"])
        confidence = "LOW"

    multiplier = MOOD_MULTIPLIERS.get(market_mood, 1.0)
    expected_gap_pct = round(base_gap * multiplier, 2)

    levels = _calculate_levels(expected_gap_pct)

    return {
        "expected_gap_pct": expected_gap_pct,
        "confidence":       confidence,
        "entry_low_pct":    levels["entry_low_pct"],
        "entry_high_pct":   levels["entry_high_pct"],
        "target_pct":       levels["target_pct"],
        "stop_loss_pct":    levels["stop_loss_pct"],
    }


if __name__ == "__main__":
    result = calculate_expected_gap("RESULTS", "NEUTRAL")
    for k, v in result.items():
        print(f"  {k}: {v}")

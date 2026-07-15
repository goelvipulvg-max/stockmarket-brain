"""
Neon Fundamentals Lookup — Phase 3, v3.1 Master Plan §6 (Batch A3).
company_profiles lookup from Neon. Gate V3 (smoke check).

Reuses get_neon_connection() from utils/neon_client.py.
Appends .NS before query (exact gap_calculator.py pattern).
risk_factors / moat_analysis skipped — 100% NULL (v3.1 §1.3).
"""
from utils.neon_client import get_neon_connection


def get_fundamentals(symbol: str) -> dict | None:
    """Return {sector, market_cap_cr, business_summary} or None if not found.

    Appends .NS to `symbol` before querying company_profiles.
    A bare symbol without .NS returns None — do not skip the suffix.
    Only current index members pass: rows with nifty500 = FALSE (index
    leavers, e.g. GSPL) return None (B1-a).
    """
    conn = get_neon_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sector, market_cap, business_summary "
                "FROM company_profiles WHERE symbol = %s AND nifty500 IS TRUE LIMIT 1",
                (f"{symbol}.NS",),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    sector, market_cap, business_summary = row

    return {
        "sector": sector,
        # market_cap is stored in rupees; / 1 crore (1,00,00,000) gives crores.
        # Verified: RELIANCE ~Rs.19.4 lakh Cr.
        "market_cap_cr": round(market_cap / 10_000_000, 2) if market_cap else None,
        "business_summary": business_summary,
    }

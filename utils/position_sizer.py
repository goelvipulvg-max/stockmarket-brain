"""
Position Sizer — Phase 2, v3.1 Master Plan §5.2.
Risk-based position sizing formula. Math only — no DB, no network.
"""
from typing import Tuple


def calculate_position_size(
    total_equity: float,
    cash_available: float,
    entry_price: float,
    stop_loss_price: float,
) -> Tuple[int, float]:
    """Risk-based position sizing. Returns (quantity, position_size_rs) or (0, 0).

    Constraints (values reflect the constants below; see SIZING RATIONALE below):
      - Risk RISK_PCT (0.125%) of total equity per trade
      - Never exceed MAX_TRADE_PCT (2.5%) of equity in a single trade
        (notional cap binds when stop < 5%; ties with risk cap at 5%; see SIZING RATIONALE below)
      - Always keep >= MIN_CASH_BUFFER (20%) cash buffer

    SIZING RATIONALE (resolved 2026-05-29; supersedes prior TODO):
    Constants are INTENTIONAL -- set deliberately in commit 66a1c00
    ("tighten caps to user-intended 2.5% per trade"), not stale defaults.
      - MAX_TRADE_PCT 2.5% x Rs 10L = Rs 25,000 = the system-wide standard
        position unit (matches Tier-3's flat Rs 25k/pick in
        tier3_position_manager.py).
      - RISK_PCT 0.125% is the per-trade risk ceiling. At a fixed 5% stop both
        caps tie at Rs 25k; RISK_PCT becomes the BINDING governor whenever the
        stop exceeds 5% (e.g. AI-SL 8% stop -> notional Rs 15,625 < Rs 25k,
        risk pinned at Rs 1,250). It is therefore NOT vestigial under variable
        AI-SL stops.
      - The earlier "~16 parallel positions" figure was an unverified guess: no
        max-positions cap exists in code; the only governor is MIN_CASH_BUFFER
        20% (~32-position ceiling). A portfolio-heat / max-concurrent cap is a
        SEPARATE open gap, not a wrong-constant issue.
    """
    RISK_PCT = 0.00125
    MAX_TRADE_PCT = 0.025
    MIN_CASH_BUFFER = 0.20

    risk_amount = total_equity * RISK_PCT
    risk_per_share = abs(entry_price - stop_loss_price)
    if risk_per_share <= 0:
        return (0, 0)

    # Quantity from risk
    qty_by_risk = int(risk_amount / risk_per_share)

    # Cap by max trade size
    max_position = total_equity * MAX_TRADE_PCT
    qty_by_cap = int(max_position / entry_price)

    qty = min(qty_by_risk, qty_by_cap)
    position_size = qty * entry_price

    # Respect cash buffer
    deployable = cash_available - (total_equity * MIN_CASH_BUFFER)
    if position_size > deployable:
        qty = int(deployable / entry_price)
        position_size = qty * entry_price

    if qty <= 0:
        return (0, 0)
    return (qty, round(position_size, 2))

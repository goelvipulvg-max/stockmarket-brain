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

    Constraints (all non-negotiable):
      - Risk 2% of total equity per trade
      - Never exceed 12% of equity in a single trade
      - Always keep >=20% cash buffer
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

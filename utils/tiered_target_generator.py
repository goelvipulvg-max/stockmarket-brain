"""Tiered target generator — computes price levels from entry, direction, conviction."""


def _dir_price(entry, mult, direction):
    """Price at BUY multiplier `mult` of entry. SELL inverts: entry * (2 - mult)."""
    if direction == "BUY":
        return round(entry * mult, 2)
    return round(entry * (2 - mult), 2)


def generate_targets(entry_price, direction, conviction):
    """Return {t1, t2, t3, t4, stop_loss} — all rounded to 2 decimals.

    T1=3%, T2=5%, T3=10%, T4=20% (T4 only when conviction='HIGH').
    Stop-loss: fixed 5%.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if direction not in ("BUY", "SELL"):
        raise ValueError("direction must be 'BUY' or 'SELL'")
    if conviction not in ("HIGH", "MEDIUM", "LOW"):
        raise ValueError("conviction must be 'HIGH', 'MEDIUM', or 'LOW'")

    return {
        "t1":        _dir_price(entry_price, 1.03, direction),
        "t2":        _dir_price(entry_price, 1.05, direction),
        "t3":        _dir_price(entry_price, 1.10, direction),
        "t4":        _dir_price(entry_price, 1.20, direction) if conviction == "HIGH" else None,
        "stop_loss": _dir_price(entry_price, 0.95, direction),
    }



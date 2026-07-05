"""Tiered target generator — computes price levels from entry, direction, conviction."""

# Canonical ladder geometry (percent distances from entry). enforce_live_rr_floor
# (utils/reward_risk.py) checks T1_PCT against the final SL, so a future edit here
# is re-tested against RR_FLOOR instead of silently breaking it (audit T2F-1).
T1_PCT = 6.0   # B2-validated (HOTFIX-6)
T2_PCT = 8.0   # minimal bump above T1; not B2-validated
T3_PCT = 10.0  # untouched — B2 did not study
T4_PCT = 20.0  # untouched; HIGH conviction only
SL_PCT = 4.0   # B2-validated (HOTFIX-6)


def _dir_price(entry, mult, direction):
    """Price at BUY multiplier `mult` of entry. SELL inverts: entry * (2 - mult)."""
    if direction == "BUY":
        return round(entry * mult, 2)
    return round(entry * (2 - mult), 2)


def generate_targets(entry_price, direction, conviction):
    """Return {t1, t2, t3, t4, stop_loss} — all rounded to 2 decimals.

    HOTFIX-6 (B2-validated): T1=6%, SL=4% → RR=1.5 = RR_FLOOR.
    Previous ladder T1=3%/SL=5% (RR=0.6) was empirically wrong per
    event_study.py Scope 2 sweep on RESULTS @ 5d (n=400).

    T2=8% (minimal bump to stay above T1; not B2-validated).
    T3=10%, T4=20% UNTOUCHED — B2 studied only T1/SL.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if direction not in ("BUY", "SELL"):
        raise ValueError("direction must be 'BUY' or 'SELL'")
    if conviction not in ("HIGH", "MEDIUM", "LOW"):
        raise ValueError("conviction must be 'HIGH', 'MEDIUM', or 'LOW'")

    return {
        "t1":        _dir_price(entry_price, 1 + T1_PCT / 100, direction),
        "t2":        _dir_price(entry_price, 1 + T2_PCT / 100, direction),
        "t3":        _dir_price(entry_price, 1 + T3_PCT / 100, direction),   # untouched — B2 did not study
        "t4":        _dir_price(entry_price, 1 + T4_PCT / 100, direction) if conviction == "HIGH" else None,  # untouched
        "stop_loss": _dir_price(entry_price, 1 - SL_PCT / 100, direction),
    }



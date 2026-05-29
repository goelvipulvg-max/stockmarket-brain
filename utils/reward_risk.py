"""Reward:risk floor check (pure computation, no I/O).

Canonical home of RR_FLOOR (the minimum reward:risk ratio a signal must clear).
passes_rr_floor() is direction-aware (BUY and SELL) and fail-closed: any missing,
non-numeric, non-positive, wrong-side, or zero-risk input returns passed=False with
a reason code rather than raising. Shared by both Tier-2 paths so the floor lives
in one place. Reliability-gap #5 caveat (a).

reward:risk math (after per-direction side validation):
  risk   = |entry - stop_loss|
  reward = |target - entry|
  rr     = reward / risk
A signal passes only when rr >= rr_floor (rr == rr_floor is inclusive, matching
validate_ai_signal in tier2_fundamental.py).
"""
from typing import Optional

RR_FLOOR = 1.5  # minimum reward:risk ratio


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def passes_rr_floor(entry, stop_loss, target, direction, rr_floor=RR_FLOOR) -> dict:
    """Verdict on whether (entry, stop_loss, target, direction) clears rr_floor.

    Returns dict: passed (bool), rr (float|None), reason (str|None), direction,
    risk (float|None), reward (float|None). Never raises.

    reason codes (passed=False): missing_input, non_numeric, invalid_price,
    invalid_direction, zero_risk, sl_wrong_side, target_wrong_side, rr_below_floor.
    """
    result = {
        "passed": False,
        "rr": None,
        "reason": None,
        "direction": direction,
        "risk": None,
        "reward": None,
    }

    if entry is None or stop_loss is None or target is None:
        result["reason"] = "missing_input"
        return result

    e = _safe_float(entry)
    s = _safe_float(stop_loss)
    t = _safe_float(target)
    if e is None or s is None or t is None:
        result["reason"] = "non_numeric"
        return result

    if e <= 0 or s <= 0 or t <= 0:
        result["reason"] = "invalid_price"
        return result

    d = str(direction).upper() if direction is not None else ""
    if d not in ("BUY", "SELL"):
        result["reason"] = "invalid_direction"
        return result

    risk = abs(e - s)
    reward = abs(t - e)
    result["risk"] = risk
    result["reward"] = reward

    if risk == 0:
        result["reason"] = "zero_risk"
        return result

    # Per-direction side validation (strict): BUY needs sl<entry<target;
    # SELL needs target<entry<sl.
    if d == "BUY":
        if not s < e:
            result["reason"] = "sl_wrong_side"
            return result
        if not t > e:
            result["reason"] = "target_wrong_side"
            return result
    else:  # SELL
        if not s > e:
            result["reason"] = "sl_wrong_side"
            return result
        if not t < e:
            result["reason"] = "target_wrong_side"
            return result

    rr = reward / risk
    result["rr"] = round(rr, 4)
    if rr < rr_floor:
        result["reason"] = "rr_below_floor"
        return result

    result["passed"] = True
    return result

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


def enforce_live_rr_floor(t1_pct, ai_sl_pct, ladder_sl_pct, rr_floor=RR_FLOOR) -> dict:
    """Percent-space RR floor enforcement for the LIVE exit geometry (audit T2F-1).

    validate_ai_signal checks RR against the AI's shadow target, but the live
    trade exits its first leg at the ladder T1 while the SL may be AI-widened
    -- so the traded (t1_pct, final_sl_pct) pair must be re-checked here.

    Percent space, not prices: the ladder sits exactly at the floor (6/4 = 1.5),
    so 2-decimal price rounding makes a strict price-space check ill-conditioned
    (a perfectly intended ladder can read rr ~1.4976 from paisa rounding).

    Decision (fail-closed; rr == rr_floor is inclusive, matching passes_rr_floor):
      - valid ai_sl_pct with t1_pct/ai_sl_pct >= rr_floor  -> use "ai"
      - else t1_pct/ladder_sl_pct >= rr_floor              -> use "ladder"
      - else                                               -> use "skip"

    ai_sl_pct=None means no AI SL in play (pure ladder guard).

    Returns dict: use ("ai"|"ladder"|"skip"), rr_ai, rr_ladder, rr_floor, reason.
    reason codes: invalid_ladder_inputs, invalid_ai_sl_pct, ai_rr_below_floor,
    ladder_rr_below_floor; None when the AI SL is kept or a clean ladder pass.
    """
    result = {
        "use": "skip",
        "rr_ai": None,
        "rr_ladder": None,
        "rr_floor": rr_floor,
        "reason": None,
    }

    t1 = _safe_float(t1_pct)
    ladder = _safe_float(ladder_sl_pct)
    if t1 is None or ladder is None or t1 <= 0 or ladder <= 0:
        result["reason"] = "invalid_ladder_inputs"
        return result

    result["rr_ladder"] = round(t1 / ladder, 4)

    ai = _safe_float(ai_sl_pct)
    if ai is not None and ai > 0:
        result["rr_ai"] = round(t1 / ai, 4)
        if t1 / ai >= rr_floor:
            result["use"] = "ai"
            return result

    if t1 / ladder >= rr_floor:
        result["use"] = "ladder"
        if result["rr_ai"] is not None:
            result["reason"] = "ai_rr_below_floor"
        elif ai_sl_pct is not None:
            result["reason"] = "invalid_ai_sl_pct"
        return result

    result["reason"] = "ladder_rr_below_floor"
    return result

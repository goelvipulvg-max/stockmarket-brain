"""Unit tests for enforce_live_rr_floor (audit T2F-1) -- no DB / no I/O.

Proves the audit's concrete failure is caught: an AI-blended SL that passed
validate_ai_signal against the AI *shadow* target (14%/8% = 1.75) still
breaks the floor against the LIVE ladder T1 (6%/8% = 0.75) and must revert
to the ladder SL.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.reward_risk import enforce_live_rr_floor, RR_FLOOR
from utils.tiered_target_generator import generate_targets, T1_PCT, SL_PCT


def test_audit_case_ai_sl_8pct_reverts_to_ladder():
    v = enforce_live_rr_floor(6.0, 8.0, 4.0)   # live rr 6/8 = 0.75
    assert v["use"] == "ladder"
    assert v["reason"] == "ai_rr_below_floor"
    assert v["rr_ai"] == 0.75
    assert v["rr_ladder"] == 1.5
    print("test_audit_case_ai_sl_8pct_reverts_to_ladder OK")


def test_tight_ai_sl_kept():
    v = enforce_live_rr_floor(6.0, 3.0, 4.0)   # rr 2.0 >= floor
    assert v["use"] == "ai"
    assert v["reason"] is None
    assert v["rr_ai"] == 2.0
    print("test_tight_ai_sl_kept OK")


def test_boundary_ai_sl_4pct_inclusive_pass():
    v = enforce_live_rr_floor(6.0, 4.0, 4.0)   # rr == floor -> inclusive pass
    assert v["use"] == "ai"
    assert v["rr_ai"] == RR_FLOOR
    print("test_boundary_ai_sl_4pct_inclusive_pass OK")


def test_just_above_4pct_reverts():
    v = enforce_live_rr_floor(6.0, 4.01, 4.0)  # tighten-only consequence
    assert v["use"] == "ladder"
    assert v["reason"] == "ai_rr_below_floor"
    print("test_just_above_4pct_reverts OK")


def test_no_ai_sl_ladder_guard_passes_today():
    v = enforce_live_rr_floor(T1_PCT, None, SL_PCT)   # today's real geometry
    assert v["use"] == "ladder"
    assert v["reason"] is None
    assert v["rr_ladder"] >= RR_FLOOR
    print("test_no_ai_sl_ladder_guard_passes_today OK")


def test_broken_ladder_skips():
    v = enforce_live_rr_floor(5.0, None, 4.0)  # future drift: rr 1.25
    assert v["use"] == "skip"
    assert v["reason"] == "ladder_rr_below_floor"
    print("test_broken_ladder_skips OK")


def test_broken_ladder_with_bad_ai_still_skips():
    v = enforce_live_rr_floor(5.0, 8.0, 4.0)
    assert v["use"] == "skip"
    assert v["reason"] == "ladder_rr_below_floor"
    print("test_broken_ladder_with_bad_ai_still_skips OK")


def test_garbage_ai_sl_falls_back_to_ladder():
    v = enforce_live_rr_floor(6.0, "abc", 4.0)
    assert v["use"] == "ladder" and v["reason"] == "invalid_ai_sl_pct"
    v2 = enforce_live_rr_floor(6.0, -2.0, 4.0)
    assert v2["use"] == "ladder" and v2["reason"] == "invalid_ai_sl_pct"
    print("test_garbage_ai_sl_falls_back_to_ladder OK")


def test_garbage_ladder_inputs_fail_closed():
    assert enforce_live_rr_floor(None, 3.0, 4.0)["use"] == "skip"
    assert enforce_live_rr_floor(6.0, 3.0, None)["use"] == "skip"
    v = enforce_live_rr_floor(6.0, 3.0, 0)
    assert v["use"] == "skip" and v["reason"] == "invalid_ladder_inputs"
    print("test_garbage_ladder_inputs_fail_closed OK")


def test_constants_match_generated_ladder_geometry():
    # T1_PCT/SL_PCT must describe the prices generate_targets actually emits,
    # otherwise the pct-space floor check drifts from the traded ladder.
    entry = 100.0
    t = generate_targets(entry_price=entry, direction="BUY", conviction="MEDIUM")
    assert t["t1"] == round(entry * (1 + T1_PCT / 100), 2)
    assert t["stop_loss"] == round(entry * (1 - SL_PCT / 100), 2)
    assert T1_PCT / SL_PCT >= RR_FLOOR
    print("test_constants_match_generated_ladder_geometry OK")


if __name__ == "__main__":
    test_audit_case_ai_sl_8pct_reverts_to_ladder()
    test_tight_ai_sl_kept()
    test_boundary_ai_sl_4pct_inclusive_pass()
    test_just_above_4pct_reverts()
    test_no_ai_sl_ladder_guard_passes_today()
    test_broken_ladder_skips()
    test_broken_ladder_with_bad_ai_still_skips()
    test_garbage_ai_sl_falls_back_to_ladder()
    test_garbage_ladder_inputs_fail_closed()
    test_constants_match_generated_ladder_geometry()
    print("ALL TESTS PASSED")

"""Unit tests for utils.reward_risk (no DB / no I/O)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.reward_risk import passes_rr_floor, RR_FLOOR


def _approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def test_rr_floor_constant():
    assert RR_FLOOR == 1.5
    print("test_rr_floor_constant OK")


def test_buy_pass():
    v = passes_rr_floor(100.0, 95.0, 110.0, "BUY")   # risk 5, reward 10, rr 2.0
    assert v["passed"] is True
    assert _approx(v["rr"], 2.0)
    assert v["reason"] is None
    print("test_buy_pass OK")


def test_buy_fail_rr():
    v = passes_rr_floor(100.0, 90.0, 105.0, "BUY")   # risk 10, reward 5, rr 0.5
    assert v["passed"] is False
    assert v["reason"] == "rr_below_floor"
    assert _approx(v["rr"], 0.5)
    print("test_buy_fail_rr OK")


def test_sell_pass():
    v = passes_rr_floor(100.0, 105.0, 90.0, "SELL")  # risk 5, reward 10, rr 2.0
    assert v["passed"] is True
    assert _approx(v["rr"], 2.0)
    print("test_sell_pass OK")


def test_sell_fail_rr():
    v = passes_rr_floor(100.0, 110.0, 95.0, "SELL")  # risk 10, reward 5, rr 0.5
    assert v["passed"] is False
    assert v["reason"] == "rr_below_floor"
    print("test_sell_fail_rr OK")


def test_boundary_rr_inclusive():
    v = passes_rr_floor(100.0, 96.0, 106.0, "BUY")   # risk 4, reward 6, rr 1.5
    assert _approx(v["rr"], 1.5)
    assert v["passed"] is True                        # rr == floor is inclusive
    print("test_boundary_rr_inclusive OK")


def test_sl_wrong_side():
    v = passes_rr_floor(100.0, 105.0, 110.0, "BUY")  # BUY but SL above entry
    assert v["passed"] is False
    assert v["reason"] == "sl_wrong_side"
    print("test_sl_wrong_side OK")


def test_target_wrong_side():
    v = passes_rr_floor(100.0, 95.0, 95.0, "BUY")    # BUY but target not above entry
    assert v["passed"] is False
    assert v["reason"] == "target_wrong_side"
    print("test_target_wrong_side OK")


def test_zero_risk():
    v = passes_rr_floor(100.0, 100.0, 110.0, "BUY")  # SL == entry -> risk 0
    assert v["passed"] is False
    assert v["reason"] == "zero_risk"
    print("test_zero_risk OK")


def test_invalid_price():
    v = passes_rr_floor(0.0, 95.0, 110.0, "BUY")     # entry <= 0
    assert v["passed"] is False
    assert v["reason"] == "invalid_price"
    print("test_invalid_price OK")


def test_missing_input():
    v = passes_rr_floor(None, 95.0, 110.0, "BUY")
    assert v["passed"] is False
    assert v["reason"] == "missing_input"
    print("test_missing_input OK")


def test_non_numeric():
    v = passes_rr_floor("abc", 95.0, 110.0, "BUY")
    assert v["passed"] is False
    assert v["reason"] == "non_numeric"
    print("test_non_numeric OK")


def test_invalid_direction():
    v = passes_rr_floor(100.0, 95.0, 110.0, "HOLD")
    assert v["passed"] is False
    assert v["reason"] == "invalid_direction"
    print("test_invalid_direction OK")


def test_custom_floor():
    v = passes_rr_floor(100.0, 95.0, 109.0, "BUY", rr_floor=2.0)  # rr 1.8 < 2.0
    assert v["passed"] is False and v["reason"] == "rr_below_floor"
    v2 = passes_rr_floor(100.0, 95.0, 109.0, "BUY")              # default 1.5; 1.8 >= 1.5
    assert v2["passed"] is True
    print("test_custom_floor OK")


if __name__ == "__main__":
    test_rr_floor_constant()
    test_buy_pass()
    test_buy_fail_rr()
    test_sell_pass()
    test_sell_fail_rr()
    test_boundary_rr_inclusive()
    test_sl_wrong_side()
    test_target_wrong_side()
    test_zero_risk()
    test_invalid_price()
    test_missing_input()
    test_non_numeric()
    test_invalid_direction()
    test_custom_floor()
    print("ALL TESTS PASSED")

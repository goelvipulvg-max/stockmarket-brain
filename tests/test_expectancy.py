"""Unit tests for utils.expectancy.compute_expectancy (no DB / no I/O)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.expectancy import compute_expectancy, MIN_EXPECTANCY_N


def _approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def test_basic_expectancy():
    trades = [
        {"pnl_pct": 10.0, "entry_price": 100.0, "stop_loss": 95.0, "quantity": 10, "status": "TARGET_HIT"},
        {"pnl_pct": 20.0, "entry_price": 100.0, "stop_loss": 90.0, "quantity": 10, "status": "TARGET_HIT"},
        {"pnl_pct": -5.0, "entry_price": 100.0, "stop_loss": 95.0, "quantity": 10, "status": "SL_HIT"},
    ]
    exp = compute_expectancy(trades)
    assert exp["n"] == 3
    assert exp["n_win"] == 2 and exp["n_loss"] == 1 and exp["n_be"] == 0
    assert _approx(exp["win_rate"], 2 / 3)
    assert _approx(exp["avg_win_pct"], 15.0)
    assert _approx(exp["avg_loss_pct"], 5.0)
    assert _approx(exp["payoff_ratio"], 3.0)
    # (2/3 * 15) - (1/3 * 5) = 10 - 1.6667 = 8.3333
    assert _approx(exp["expectancy_pct"], 8.3333)
    # Rs: wins +100,+200 -> avg 150; loss -50 -> avg 50; (2/3*150)-(1/3*50)=83.33
    assert _approx(exp["expectancy_rs"], 83.3333)
    assert exp["rs_coverage"] == 3
    # R: risks 5%,10%,5% -> R = 2, 2, -1 -> mean = 1.0
    assert _approx(exp["expectancy_in_r"], 1.0)
    assert exp["r_coverage"] == 3
    assert exp["preliminary"] is True  # n < MIN_EXPECTANCY_N
    print("test_basic_expectancy OK")


def test_empty():
    exp = compute_expectancy([])
    assert exp["n"] == 0
    assert exp["expectancy_pct"] is None
    assert exp["expectancy_in_r"] is None
    print("test_empty OK")


def test_all_wins_no_losses():
    trades = [{"pnl_pct": 5.0}, {"pnl_pct": 8.0}]
    exp = compute_expectancy(trades)
    assert exp["n_loss"] == 0
    assert exp["payoff_ratio"] is None          # no losses -> payoff undefined
    assert _approx(exp["expectancy_pct"], 6.5)  # win_rate 1.0 * avg_win 6.5
    assert exp["expectancy_in_r"] is None        # no SL data
    assert exp["expectancy_rs"] is None          # no entry/qty data
    print("test_all_wins_no_losses OK")


def test_expired_counted_by_pnl_sign():
    # EXPIRED trades must be classified by pnl_pct sign, not status
    trades = [
        {"pnl_pct": 3.0, "status": "EXPIRED"},
        {"pnl_pct": -2.0, "status": "EXPIRED"},
    ]
    exp = compute_expectancy(trades)
    assert exp["n_win"] == 1 and exp["n_loss"] == 1
    assert _approx(exp["expectancy_pct"], 0.5)  # (0.5*3) - (0.5*2) = 0.5
    print("test_expired_counted_by_pnl_sign OK")


if __name__ == "__main__":
    test_basic_expectancy()
    test_empty()
    test_all_wins_no_losses()
    test_expired_counted_by_pnl_sign()
    print("ALL TESTS PASSED")

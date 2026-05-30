"""Unit tests for utils.expectancy.compute_expectancy (no DB / no I/O)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.expectancy import compute_expectancy, MIN_EXPECTANCY_N
from utils.trade_costs import compute_trade_costs


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


def test_net_expectancy():
    # Single fully-priced BUY winner. compute_trade_costs(100,110,100):
    #   total_cost_rs=59.600746, total_cost_pct=0.59600746%
    trades = [
        {"pnl_pct": 10.0, "entry_price": 100.0, "exit_price": 110.0,
         "stop_loss": 95.0, "quantity": 100, "direction": "BUY", "status": "TARGET_HIT"},
    ]
    exp = compute_expectancy(trades)
    # gross keys UNCHANGED
    assert _approx(exp["expectancy_pct"], 10.0)
    assert _approx(exp["expectancy_rs"], 1000.0)
    assert _approx(exp["expectancy_in_r"], 2.0)         # R = 10 / 5
    # net keys
    assert exp["cost_coverage"] == 1 and exp["r_net_coverage"] == 1
    assert _approx(exp["avg_cost_pct"], 0.59601)
    assert _approx(exp["avg_cost_rs"], 59.6007)
    assert _approx(exp["expectancy_pct_gross_cov"], 10.0)
    assert _approx(exp["expectancy_pct_net"], 9.40399)
    assert _approx(exp["expectancy_rs_net"], 940.3993)
    assert _approx(exp["expectancy_in_r_net"], 1.88080)
    # identity: gross-on-covered minus avg cost == net (exact on full coverage)
    assert _approx(exp["expectancy_pct_gross_cov"] - exp["avg_cost_pct"], exp["expectancy_pct_net"])
    # net is a strict drag for a winner
    assert exp["expectancy_pct_net"] < exp["expectancy_pct"]
    # cross-check directly against trade_costs (ties the two modules)
    tc = compute_trade_costs(100.0, 110.0, 100)
    assert _approx(exp["avg_cost_pct"], tc["total_cost_pct"])
    assert _approx(exp["expectancy_pct_net"], 10.0 - tc["total_cost_pct"])
    print("test_net_expectancy OK")


def test_net_expectancy_short():
    # SELL winner. Cost is DIRECTION-AGNOSTIC: compute_trade_costs(100,90,100):
    #   total_cost_rs=55.528294, total_cost_pct=0.55528294%. SL sits ABOVE entry (short).
    trades = [
        {"pnl_pct": 10.0, "entry_price": 100.0, "exit_price": 90.0,
         "stop_loss": 110.0, "quantity": 100, "direction": "SELL", "status": "TARGET_HIT"},
    ]
    exp = compute_expectancy(trades)
    assert exp["cost_coverage"] == 1 and exp["r_net_coverage"] == 1
    assert _approx(exp["avg_cost_pct"], 0.55528)
    assert _approx(exp["expectancy_pct_net"], 9.44472)
    assert _approx(exp["expectancy_in_r_net"], 0.94447)   # (10 - 0.55528) / 10
    tc = compute_trade_costs(100.0, 90.0, 100)
    assert _approx(exp["avg_cost_pct"], tc["total_cost_pct"])
    print("test_net_expectancy_short OK")


def test_net_expectancy_coverage():
    # Mixed: row 1 fully priced (in covered set C), row 2 lacks exit_price (excluded from net).
    trades = [
        {"pnl_pct": 10.0, "entry_price": 100.0, "exit_price": 110.0, "stop_loss": 95.0, "quantity": 100},
        {"pnl_pct": 4.0,  "entry_price": 100.0,                      "stop_loss": 95.0, "quantity": 100},
    ]
    exp = compute_expectancy(trades)
    assert exp["cost_coverage"] == 1                        # only the priced row
    assert _approx(exp["expectancy_pct"], 7.0)              # gross headline over BOTH (10, 4)
    assert _approx(exp["expectancy_pct_gross_cov"], 10.0)   # gross over the covered row only
    assert _approx(exp["expectancy_pct_net"], 9.40399)      # net over covered row only
    # zero-coverage: rows with pnl but no prices -> net None, no crash, never zeroed
    none_cov = compute_expectancy([{"pnl_pct": 5.0}, {"pnl_pct": -2.0}])
    assert none_cov["cost_coverage"] == 0
    assert none_cov["expectancy_pct_net"] is None
    assert none_cov["avg_cost_pct"] is None
    assert none_cov["r_net_coverage"] == 0
    print("test_net_expectancy_coverage OK")


if __name__ == "__main__":
    test_basic_expectancy()
    test_empty()
    test_all_wins_no_losses()
    test_expired_counted_by_pnl_sign()
    test_net_expectancy()
    test_net_expectancy_short()
    test_net_expectancy_coverage()
    print("ALL TESTS PASSED")

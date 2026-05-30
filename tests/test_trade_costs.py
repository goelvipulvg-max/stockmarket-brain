"""DB-free unit tests for utils.trade_costs.

Run: .venv\\Scripts\\python.exe tests\\test_trade_costs.py   (NOT pytest)
Plain asserts; prints ALL TESTS PASSED on success.

Worked examples computed at SLIPPAGE_PCT = 0.0010 (0.10%/side). Statutory rates
per the constants in utils/trade_costs.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.trade_costs import (
    compute_trade_costs,
    cost_pct_of_turnover,
    REFERENCE_POSITION_RS,
    SLIPPAGE_PCT,
)

TOL = 0.01


def approx(a, b, tol=TOL):
    return a is not None and b is not None and abs(a - b) <= tol


# Guard: these expected numbers assume 0.10%/side. If the constant is changed,
# the worked examples below must be recomputed -- fail loudly rather than silently.
assert SLIPPAGE_PCT == 0.0010, f"expected numbers assume SLIPPAGE_PCT=0.0010, got {SLIPPAGE_PCT}"

# --- Example 1: WINNING trade, entry 2500 -> exit 2625, qty 10 (buy Rs 25,000) ---
r1 = compute_trade_costs(2500, 2625, 10)
assert r1["valid"] is True
assert approx(r1["buy_turnover"], 25000.0)
assert approx(r1["sell_turnover"], 26250.0)
# itemised (auditable)
assert approx(r1["stt"], 51.25)        # 0.001 * (25000+26250)
assert approx(r1["exchange"], 1.5221)  # 0.0000297 * 51250
assert approx(r1["sebi"], 0.05125)     # 0.000001 * 51250
assert approx(r1["stamp"], 3.75)       # 0.00015 * 25000 (buy only)
assert approx(r1["brokerage"], 0.0)
assert approx(r1["gst"], 0.2832)       # 0.18 * (0 + 1.5221 + 0.05125)
assert approx(r1["dp"], 15.34)
assert approx(r1["slippage"], 51.25)   # 0.0010 * 51250
assert approx(r1["total_cost_rs"], 123.4466)
assert approx(r1["total_cost_pct"], 0.4938)
print(f"ex1 WIN  total_cost_rs={r1['total_cost_rs']:.4f} pct={r1['total_cost_pct']:.4f}")

# --- Example 2: LOSING trade, entry 1000 -> exit 950, qty 25 (buy Rs 25,000) ---
r2 = compute_trade_costs(1000, 950, 25)
assert r2["valid"] is True
assert approx(r2["buy_turnover"], 25000.0)
assert approx(r2["sell_turnover"], 23750.0)
assert approx(r2["total_cost_rs"], 118.356)
assert approx(r2["total_cost_pct"], 0.4734)
print(f"ex2 LOSS total_cost_rs={r2['total_cost_rs']:.4f} pct={r2['total_cost_pct']:.4f}")

# --- Example 3: FLAT cross-check, entry == exit == 2500, qty 10 ---
r3 = compute_trade_costs(2500, 2500, 10)
assert r3["valid"] is True
assert approx(r3["total_cost_rs"], 120.9013)
assert approx(r3["total_cost_pct"], 0.4836)

p3 = cost_pct_of_turnover(notional_rs=25000)
assert approx(p3["cost_pct"], 0.4836)
# The two APIs are EQUAL only on a flat trade (entry == exit); on non-flat trades
# they diverge by the sell-side turnover delta, by design.
assert approx(p3["cost_pct"], r3["total_cost_pct"])
# And on the winning trade the exact per-trade cost % is strictly higher than the
# sell==buy approximation -- the documented approximation direction.
assert r1["total_cost_pct"] > p3["cost_pct"]

p3_nodp = cost_pct_of_turnover(notional_rs=25000, include_dp=False)
assert approx(p3_nodp["cost_pct"], 0.42225)
assert p3_nodp["dp_included"] is False
print(f"ex3 FLAT total_cost_pct={r3['total_cost_pct']:.4f} | "
      f"pct_api={p3['cost_pct']:.4f} (equal on flat) | no_dp={p3_nodp['cost_pct']:.5f}")

# DP dilutes at larger size: 100k notional cost% < 25k notional cost%
p_big = cost_pct_of_turnover(notional_rs=100000)
assert p_big["cost_pct"] < p3["cost_pct"]
assert approx(p_big["cost_pct"], 0.43759)

# Default notional uses the named constant.
p_default = cost_pct_of_turnover()
assert approx(p_default["cost_pct"], cost_pct_of_turnover(notional_rs=REFERENCE_POSITION_RS)["cost_pct"])

# --- Example 4: INVALID input -> valid=False, no numbers, never raises ---
bad_none = compute_trade_costs(None, 100, 10)
assert bad_none["valid"] is False and bad_none["total_cost_rs"] is None
bad_zero_qty = compute_trade_costs(2500, 2625, 0)
assert bad_zero_qty["valid"] is False and bad_zero_qty["total_cost_rs"] is None
bad_neg = compute_trade_costs(2500, -10, 5)
assert bad_neg["valid"] is False and bad_neg["total_cost_rs"] is None
bad_str = compute_trade_costs("abc", 2625, 10)
assert bad_str["valid"] is False and bad_str["total_cost_rs"] is None
bad_pct = cost_pct_of_turnover(notional_rs=0)
assert bad_pct["cost_pct"] is None and bad_pct["components"]["valid"] is False
print("ex4 INVALID inputs all returned valid=False (no raise)")

# --- Broker override sanity: a paid broker raises cost (and is GST-ed) ---
r_paid = compute_trade_costs(2500, 2625, 10, brokerage_pct=0.0003)
assert r_paid["total_cost_rs"] > r1["total_cost_rs"]
assert approx(r_paid["brokerage"], 0.0003 * 51250)

print("ALL TESTS PASSED")

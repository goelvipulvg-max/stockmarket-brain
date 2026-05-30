"""Portfolio expectancy metrics (pure computation, no I/O).

Computes win-rate, payoff ratio, and expectancy (%, Rs, and R-multiple) from a
list of resolved paper_trades rows. The only caller is tier4_memory_manager;
scripts/backtest_analysis.py does its own inline pnl math and does not use this.

Win/loss is classified by pnl_pct SIGN (not status) so EXPIRED trades that
closed +/- are counted correctly. The status-based win-rate breakdown lives
separately in tier4_memory_manager.compute_stats().
"""
from statistics import mean
from typing import Optional

from utils.trade_costs import compute_trade_costs

# Below this many resolved trades, expectancy is shown but flagged preliminary.
# (A ~55% win-rate at n=20 still carries roughly a +/-20-30% confidence band.)
MIN_EXPECTANCY_N = 20


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_expectancy(trades: list) -> dict:
    """Compute portfolio expectancy from resolved trade rows.

    Each trade dict needs `pnl_pct` (required); `entry_price`, `stop_loss`,
    `quantity` are used when present for the Rs and R-multiple variants.

    Returns a dict with: n, n_win, n_loss, n_be, win_rate, loss_rate,
    avg_win_pct, avg_loss_pct, payoff_ratio, expectancy_pct, expectancy_rs,
    rs_coverage, expectancy_in_r, r_coverage, preliminary. Ratio fields are
    None when undefined (e.g. no losses yet, or no SL data).
    """
    rows = []
    for t in trades:
        p = _safe_float(t.get("pnl_pct"))
        if p is not None:
            rows.append((t, p))

    n = len(rows)
    result = {
        "n": n,
        "n_win": 0,
        "n_loss": 0,
        "n_be": 0,
        "win_rate": None,
        "loss_rate": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "payoff_ratio": None,
        "expectancy_pct": None,
        "expectancy_rs": None,
        "rs_coverage": 0,
        "expectancy_in_r": None,
        "r_coverage": 0,
        # --- net-of-cost (gap #7 + B4): additive; gross keys above stay unchanged ---
        "expectancy_pct_net": None,
        "expectancy_rs_net": None,
        "avg_cost_pct": None,
        "avg_cost_rs": None,
        "expectancy_pct_gross_cov": None,  # gross over the SAME covered set, for honest net-vs-gross
        "cost_coverage": 0,
        "expectancy_in_r_net": None,
        "r_net_coverage": 0,
        "preliminary": n < MIN_EXPECTANCY_N,
    }
    if n == 0:
        return result

    wins_pct = [p for _, p in rows if p > 0]
    losses_pct = [p for _, p in rows if p < 0]
    result["n_win"] = len(wins_pct)
    result["n_loss"] = len(losses_pct)
    result["n_be"] = sum(1 for _, p in rows if p == 0)

    base = len(wins_pct) + len(losses_pct)  # exclude break-even from rates
    if base > 0:
        result["win_rate"] = len(wins_pct) / base
        result["loss_rate"] = len(losses_pct) / base

    if wins_pct:
        result["avg_win_pct"] = mean(wins_pct)
    if losses_pct:
        result["avg_loss_pct"] = mean([abs(p) for p in losses_pct])

    if result["avg_win_pct"] is not None and result["avg_loss_pct"] not in (None, 0):
        result["payoff_ratio"] = result["avg_win_pct"] / result["avg_loss_pct"]

    if base > 0:
        win_term = (result["win_rate"] or 0.0) * (result["avg_win_pct"] or 0.0)
        loss_term = (result["loss_rate"] or 0.0) * (result["avg_loss_pct"] or 0.0)
        result["expectancy_pct"] = win_term - loss_term

    # --- Rs expectancy: recompute pnl_rs = pnl_pct/100 * entry * qty (not stored on the row) ---
    win_rs, loss_rs = [], []
    for t, p in rows:
        entry = _safe_float(t.get("entry_price"))
        qty = _safe_float(t.get("quantity"))
        if entry is None or qty is None:
            continue
        pnl_rs = (p / 100.0) * entry * qty
        if p > 0:
            win_rs.append(pnl_rs)
        elif p < 0:
            loss_rs.append(abs(pnl_rs))
    rs_base = len(win_rs) + len(loss_rs)
    result["rs_coverage"] = rs_base
    if rs_base > 0:
        wr = len(win_rs) / rs_base
        lr = len(loss_rs) / rs_base
        awr = mean(win_rs) if win_rs else 0.0
        alr = mean(loss_rs) if loss_rs else 0.0
        result["expectancy_rs"] = wr * awr - lr * alr

    # --- R-multiple expectancy: R = pnl_pct / risk_pct, risk_pct = |entry-sl|/entry*100 ---
    r_values = []
    for t, p in rows:
        entry = _safe_float(t.get("entry_price"))
        sl = _safe_float(t.get("stop_loss"))
        if entry is None or sl is None or entry == 0:
            continue
        risk_pct = abs(entry - sl) / entry * 100.0
        if risk_pct == 0:
            continue
        r_values.append(p / risk_pct)
    result["r_coverage"] = len(r_values)
    if r_values:
        result["expectancy_in_r"] = mean(r_values)

    # --- Net-of-cost expectancy: subtract exact per-trade DELIVERY round-trip cost ---
    # Cost is computed DIRECTION-AGNOSTICALLY: compute_trade_costs is statutory-symmetric
    # (STT/exchange/SEBI/slippage on both legs) and its total_cost_pct uses the entry*qty
    # base, which matches calc_pnl_pct's entry-normalization for BUY and SELL alike (the
    # buy-only stamp leg is modelled on entry notional -> sub-rupee skew on shorts).
    # Rows whose entry/exit/qty are missing/invalid are EXCLUDED -- never assigned cost 0.
    net_pct, net_rs, cost_pct_list, cost_rs_list, gross_pct_cov = [], [], [], [], []
    r_net_values = []
    for t, p in rows:
        entry = _safe_float(t.get("entry_price"))
        exit_price = _safe_float(t.get("exit_price"))
        qty = _safe_float(t.get("quantity"))
        tc = compute_trade_costs(entry, exit_price, qty)
        if not tc["valid"]:
            continue
        cost_pct = tc["total_cost_pct"]
        cost_rs = tc["total_cost_rs"]
        cost_pct_list.append(cost_pct)
        cost_rs_list.append(cost_rs)
        gross_pct_cov.append(p)
        net_pct.append(p - cost_pct)
        net_rs.append((p / 100.0) * entry * qty - cost_rs)
        # net R: cost reduces the numerator; risk denominator stays gross/pre-cost
        sl = _safe_float(t.get("stop_loss"))
        if sl is not None:
            risk_pct = abs(entry - sl) / entry * 100.0
            if risk_pct != 0:
                r_net_values.append((p - cost_pct) / risk_pct)

    result["cost_coverage"] = len(net_pct)
    if net_pct:
        result["expectancy_pct_net"] = mean(net_pct)
        result["expectancy_rs_net"] = mean(net_rs)
        result["avg_cost_pct"] = mean(cost_pct_list)
        result["avg_cost_rs"] = mean(cost_rs_list)
        result["expectancy_pct_gross_cov"] = mean(gross_pct_cov)
    result["r_net_coverage"] = len(r_net_values)
    if r_net_values:
        result["expectancy_in_r_net"] = mean(r_net_values)

    return result

"""Indian equity DELIVERY round-trip transaction-cost model (pure, no I/O).

Models the real round-trip cost of a CNC/delivery equity trade on NSE so that
expectancy (utils.expectancy, reliability-gap #7) can later be reported
net-of-cost instead of on gross pnl_pct. NOT yet wired into expectancy -- this
is the cost primitive only; the wiring is a separate step.

Two APIs:
  - compute_trade_costs(entry, exit, qty)  -> exact per-trade Rs cost (uses the
    real buy AND sell turnover), with every line item for auditability.
  - cost_pct_of_turnover(notional_rs)      -> round-trip cost as a % of buy-side
    notional, approximating sell == buy, for the case where only pnl_pct (no Rs)
    is available and a single cost-% must be subtracted from gross pnl_pct.

All rates are NAMED CONSTANTS below (2026 basis in each comment) so they are easy
to audit/update. Statutory rates are fixed; SLIPPAGE_PCT is the one ASSUMPTION.

Like the sibling utils (expectancy, price_structure, reward_risk, volume_structure)
this module is pure, DB-free, import-free of any DB/network code, and NEVER raises:
bad input yields a dict with None line items and valid=False.
"""
from typing import Optional

# --- Statutory / exchange rates (Indian equity DELIVERY, 2026 basis) ---
STT_DELIVERY_PCT  = 0.001      # 0.1% Securities Transaction Tax on BOTH buy & sell turnover (equity delivery; 2026 unchanged)
EXCHANGE_TXN_PCT  = 0.0000297  # 0.00297% NSE cash exchange txn charge, BOTH sides (~Rs 2.97 per lakh per side)
SEBI_TURNOVER_PCT = 0.000001   # 0.0001% SEBI turnover fee (Rs 10 per crore), BOTH sides
STAMP_DUTY_PCT    = 0.00015    # 0.015% stamp duty, BUY side ONLY
GST_PCT           = 0.18       # 18% GST on (brokerage + exchange + sebi) ONLY -- never on STT, stamp, DP, or slippage

# --- Broker-dependent (defaults = Zerodha delivery; overridable per call) ---
BROKERAGE_PCT     = 0.0        # Zerodha delivery brokerage = free; keep overridable for other brokers
BROKERAGE_FLAT_RS = 0.0        # optional flat per-order brokerage; overridable
DP_CHARGE_RS      = 15.34      # flat per SELL (per scrip): Rs 3.5 CDSL + Rs 9.5 broker + 18% GST on the slab. GST ALREADY INCLUDED here -> NOT GST-ed again in the gst term.

# --- The ONE non-statutory assumption ---
SLIPPAGE_PCT      = 0.0010     # 0.10% per side (round-trip 0.20%) -- ASSUMPTION, not a statutory rate. Conservative for the NSE-500 universe (mid/small-caps trade thinner; post-filing spreads widen). Calibrate against actual fills later. TUNABLE via the slippage_pct param.

# --- Reference size for the %-only variant's flat DP term ---
REFERENCE_POSITION_RS = 25000  # = MAX_TRADE_PCT 2.5% x Rs 10L capital (current basis) = the system's standard position unit. Named (not derived) to keep this util pure/import-free: position_sizer.MAX_TRADE_PCT is function-local and capital_ledger touches the DB at import. Revisit if MAX_TRADE_PCT is hoisted to module scope.


def _safe_float(v) -> Optional[float]:
    """Coerce to float; reject None / non-numeric / NaN."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def compute_trade_costs(entry_price, exit_price, quantity,
                        brokerage_pct=BROKERAGE_PCT,
                        brokerage_flat_rs=BROKERAGE_FLAT_RS,
                        slippage_pct=SLIPPAGE_PCT,
                        dp_charge_rs=DP_CHARGE_RS) -> dict:
    """Exact per-trade DELIVERY round-trip cost in Rs, itemised.

    Uses the real buy AND sell turnover (so a winning trade's larger sell leg is
    reflected). Returns a dict with every line item plus total_cost_rs and
    total_cost_pct (= total_cost_rs / buy_turnover * 100, i.e. % of capital
    deployed). Never raises: any None / non-numeric / non-positive entry, exit, or
    qty yields all line items None and valid=False.

    Keys: valid, buy_turnover, sell_turnover, turnover, stt, exchange, sebi,
    stamp, brokerage, gst, dp, slippage, total_cost_rs, total_cost_pct.
    Raw floats (unrounded); callers round for display.
    """
    result = {
        "valid": False,
        "buy_turnover": None,
        "sell_turnover": None,
        "turnover": None,
        "stt": None,
        "exchange": None,
        "sebi": None,
        "stamp": None,
        "brokerage": None,
        "gst": None,
        "dp": None,
        "slippage": None,
        "total_cost_rs": None,
        "total_cost_pct": None,
    }

    e = _safe_float(entry_price)
    x = _safe_float(exit_price)
    q = _safe_float(quantity)
    bp = _safe_float(brokerage_pct)
    bf = _safe_float(brokerage_flat_rs)
    sp = _safe_float(slippage_pct)
    dp_rs = _safe_float(dp_charge_rs)
    if None in (e, x, q, bp, bf, sp, dp_rs):
        return result
    if e <= 0 or x <= 0 or q <= 0:
        return result

    buy_turnover = e * q
    sell_turnover = x * q
    turnover = buy_turnover + sell_turnover

    stt = STT_DELIVERY_PCT * turnover
    exchange = EXCHANGE_TXN_PCT * turnover
    sebi = SEBI_TURNOVER_PCT * turnover
    stamp = STAMP_DUTY_PCT * buy_turnover          # buy side only
    brokerage = bp * turnover + 2 * bf
    gst = GST_PCT * (brokerage + exchange + sebi)  # NOT on STT / stamp / DP / slippage
    dp = dp_rs                                      # sell side only, flat (GST already inside)
    slippage = sp * turnover

    total = stt + exchange + sebi + stamp + brokerage + gst + dp + slippage

    result.update({
        "valid": True,
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "turnover": turnover,
        "stt": stt,
        "exchange": exchange,
        "sebi": sebi,
        "stamp": stamp,
        "brokerage": brokerage,
        "gst": gst,
        "dp": dp,
        "slippage": slippage,
        "total_cost_rs": total,
        "total_cost_pct": total / buy_turnover * 100.0,
    })
    return result


def cost_pct_of_turnover(notional_rs=REFERENCE_POSITION_RS,
                         brokerage_pct=BROKERAGE_PCT,
                         brokerage_flat_rs=BROKERAGE_FLAT_RS,
                         slippage_pct=SLIPPAGE_PCT,
                         include_dp=True,
                         dp_charge_rs=DP_CHARGE_RS) -> dict:
    """Round-trip cost as a % of buy-side notional, approximating sell == buy.

    For the expectancy path that only has gross pnl_pct (no Rs): the returned
    cost_pct is a single constant to subtract from gross pnl_pct. The flat DP
    charge does not scale, so it is folded in as dp_charge_rs/notional_rs*100
    when include_dp=True (set include_dp=False for the pure-scalable %).

    APPROXIMATION: this assumes sell == buy turnover. On a trade with a GAIN the
    true per-trade cost % is slightly HIGHER (the real sell leg is larger) -- use
    compute_trade_costs() for the exact per-trade Rs cost. The two APIs are EQUAL
    only on a flat trade (entry == exit).

    Returns: cost_pct, dp_included, notional_rs, approximation, components{...}.
    Never raises; bad input -> cost_pct None, valid=False under components.
    """
    approximation = ("Approximates sell==buy; for a trade with a gain the true "
                     "per-trade cost % is slightly higher -- use "
                     "compute_trade_costs() for exact per-trade Rs cost.")
    result = {
        "cost_pct": None,
        "dp_included": bool(include_dp),
        "notional_rs": None,
        "approximation": approximation,
        "components": {"valid": False},
    }

    n = _safe_float(notional_rs)
    bp = _safe_float(brokerage_pct)
    bf = _safe_float(brokerage_flat_rs)
    sp = _safe_float(slippage_pct)
    dp_rs = _safe_float(dp_charge_rs)
    if None in (n, bp, bf, sp, dp_rs) or n <= 0:
        return result

    buy_turnover = n
    sell_turnover = n          # approximation: sell == buy
    turnover = buy_turnover + sell_turnover

    stt = STT_DELIVERY_PCT * turnover
    exchange = EXCHANGE_TXN_PCT * turnover
    sebi = SEBI_TURNOVER_PCT * turnover
    stamp = STAMP_DUTY_PCT * buy_turnover
    brokerage = bp * turnover + 2 * bf
    gst = GST_PCT * (brokerage + exchange + sebi)
    dp = dp_rs if include_dp else 0.0
    slippage = sp * turnover

    total = stt + exchange + sebi + stamp + brokerage + gst + dp + slippage

    result["notional_rs"] = n
    result["cost_pct"] = total / n * 100.0
    result["components"] = {
        "valid": True,
        "stt": stt,
        "exchange": exchange,
        "sebi": sebi,
        "stamp": stamp,
        "brokerage": brokerage,
        "gst": gst,
        "dp": dp,
        "slippage": slippage,
        "total_cost_rs": total,
    }
    return result

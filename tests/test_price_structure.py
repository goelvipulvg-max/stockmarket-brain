"""Unit tests for utils.price_structure (no DB / no I/O)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.price_structure import (
    compute_price_structure,
    validate_price_structure,
)


def _approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def test_uptrend_passes_all():
    up_series = [100.0, 100.0, 112.0, 100.0] + [102.0] * 62 + [110.0]  # len 67
    nifty_series = [1000.0] * 66 + [1040.0]                            # len 67, +4%
    chart = {"last_close": 110.0, "sma_50": 100.0, "sma_200": 90.0,
             "close_series": up_series}
    nifty_chart = {"close_series": nifty_series}

    s = compute_price_structure(chart, nifty_chart)
    assert s["above_sma50"] is True and s["above_sma200"] is True
    assert _approx(s["pct_vs_sma50"], 10.0)
    assert _approx(s["pct_vs_sma200"], 22.2222)
    assert _approx(s["high_52wk"], 112.0)
    assert _approx(s["pct_from_52wk_high"], -1.7857)   # (110-112)/112*100
    assert _approx(s["stock_return_63d"], 10.0)
    assert _approx(s["nifty_return_63d"], 4.0)
    assert _approx(s["rs_vs_nifty_63d"], 6.0)

    v = validate_price_structure(s)
    assert v["passes"] is True
    assert v["reasons"] == []
    print("test_uptrend_passes_all OK")


def test_downtrend_fails_all():
    down_series = [120.0, 120.0, 120.0] + [100.0] * 62 + [80.0]  # len 66, -33.3%
    nifty_series = [1000.0] * 65 + [1020.0]                      # len 66, +2%
    chart = {"last_close": 80.0, "sma_50": 100.0, "sma_200": 110.0,
             "close_series": down_series}
    nifty_chart = {"close_series": nifty_series}

    s = compute_price_structure(chart, nifty_chart)
    assert s["above_sma50"] is False
    assert _approx(s["pct_from_52wk_high"], -33.3333)
    assert _approx(s["rs_vs_nifty_63d"], -35.3333)

    v = validate_price_structure(s)
    assert v["passes"] is False
    assert v["checks"] == {"above_sma50": False, "near_52wk_high": False,
                           "rs_positive": False}
    assert set(v["reasons"]) == {"below_sma50", "far_from_52wk_high",
                                 "negative_relative_strength"}
    print("test_downtrend_fails_all OK")


def test_near_52wk_high_boundary():
    # exactly -25.0 passes (inclusive); just beyond fails
    s_pass = {"above_sma50": True, "pct_from_52wk_high": -25.0,
              "rs_vs_nifty_63d": 1.0}
    assert validate_price_structure(s_pass)["passes"] is True
    s_fail = {"above_sma50": True, "pct_from_52wk_high": -25.01,
              "rs_vs_nifty_63d": 1.0}
    v = validate_price_structure(s_fail)
    assert v["passes"] is False
    assert v["checks"]["near_52wk_high"] is False
    assert "far_from_52wk_high" in v["reasons"]
    print("test_near_52wk_high_boundary OK")


def test_rs_sign_boundary():
    s_pass = {"above_sma50": True, "pct_from_52wk_high": -5.0,
              "rs_vs_nifty_63d": 0.0}          # exactly 0 passes
    assert validate_price_structure(s_pass)["passes"] is True
    s_fail = {"above_sma50": True, "pct_from_52wk_high": -5.0,
              "rs_vs_nifty_63d": -0.01}
    v = validate_price_structure(s_fail)
    assert v["passes"] is False
    assert v["checks"]["rs_positive"] is False
    print("test_rs_sign_boundary OK")


def test_short_series_returns_none():
    chart = {"last_close": 50.0, "sma_50": 48.0, "sma_200": 45.0,
             "close_series": [50.0] * 30}      # < 64 -> no 63d return
    s = compute_price_structure(chart, None)
    assert _approx(s["pct_vs_sma50"], 4.1667)
    assert s["above_sma50"] is True
    assert s["stock_return_63d"] is None
    assert s["rs_vs_nifty_63d"] is None
    print("test_short_series_returns_none OK")


def test_nifty_none_rs_none():
    up_series = [100.0] * 66 + [110.0]          # len 67
    chart = {"last_close": 110.0, "sma_50": 100.0, "sma_200": 90.0,
             "close_series": up_series}
    s = compute_price_structure(chart, None)    # no NIFTY chart
    assert _approx(s["stock_return_63d"], 10.0)
    assert s["nifty_return_63d"] is None
    assert s["rs_vs_nifty_63d"] is None
    print("test_nifty_none_rs_none OK")


def test_none_metrics_no_opinion_pass():
    s = {"above_sma50": None, "pct_from_52wk_high": None,
         "rs_vs_nifty_63d": None}
    v = validate_price_structure(s)
    assert v["passes"] is True
    assert v["checks"] == {"above_sma50": True, "near_52wk_high": True,
                           "rs_positive": True}
    assert v["reasons"] == []
    print("test_none_metrics_no_opinion_pass OK")


def test_non_dict_chart_no_raise():
    s = compute_price_structure(None, None)     # must not raise
    assert s["pct_vs_sma50"] is None
    assert s["rs_vs_nifty_63d"] is None
    print("test_non_dict_chart_no_raise OK")


if __name__ == "__main__":
    test_uptrend_passes_all()
    test_downtrend_fails_all()
    test_near_52wk_high_boundary()
    test_rs_sign_boundary()
    test_short_series_returns_none()
    test_nifty_none_rs_none()
    test_none_metrics_no_opinion_pass()
    test_non_dict_chart_no_raise()
    print("ALL TESTS PASSED")

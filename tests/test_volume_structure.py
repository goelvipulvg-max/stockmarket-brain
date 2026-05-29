"""Unit tests for utils.volume_structure (no DB / no I/O)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.volume_structure import (
    compute_volume_structure,
    validate_volume_structure,
)


def _approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def test_high_volume_passes():
    chart = {"volume": 250.0, "volume_series": [100.0] * 20}  # avg 100, ratio 2.5
    s = compute_volume_structure(chart)
    assert _approx(s["avg_volume_20d"], 100.0)
    assert _approx(s["vol_vs_avg_ratio"], 2.5)
    assert s["volume_spike"] is True                          # 2.5 >= 1.5
    assert validate_volume_structure(s)["passes"] is True
    print("test_high_volume_passes OK")


def test_low_volume_fails_gate():
    chart = {"volume": 50.0, "volume_series": [100.0] * 20}   # ratio 0.5
    s = compute_volume_structure(chart)
    assert _approx(s["vol_vs_avg_ratio"], 0.5)
    assert s["volume_spike"] is False
    v = validate_volume_structure(s)
    assert v["passes"] is False
    assert v["checks"]["volume_ok"] is False
    assert v["reasons"] == ["low_volume"]
    print("test_low_volume_fails_gate OK")


def test_ratio_boundary():
    s_pass = compute_volume_structure({"volume": 100.0, "volume_series": [100.0] * 20})
    assert _approx(s_pass["vol_vs_avg_ratio"], 1.0)
    assert validate_volume_structure(s_pass)["passes"] is True   # 1.0 inclusive
    s_fail = compute_volume_structure({"volume": 99.0, "volume_series": [100.0] * 20})
    assert validate_volume_structure(s_fail)["passes"] is False  # 0.99 < 1.0
    print("test_ratio_boundary OK")


def test_short_series_returns_none():
    chart = {"volume": 100.0, "volume_series": [100.0] * 10}  # < 20
    s = compute_volume_structure(chart)
    assert s["avg_volume_20d"] is None
    assert s["vol_vs_avg_ratio"] is None
    assert validate_volume_structure(s)["passes"] is True     # no-opinion
    print("test_short_series_returns_none OK")


def test_zero_average_no_div():
    chart = {"volume": 100.0, "volume_series": [0.0] * 20}    # avg 0 -> no div
    s = compute_volume_structure(chart)
    assert s["vol_vs_avg_ratio"] is None
    assert validate_volume_structure(s)["passes"] is True
    print("test_zero_average_no_div OK")


def test_nan_volume_handled():
    nan = float("nan")
    # latest volume NaN -> ratio None, no raise
    s1 = compute_volume_structure({"volume": nan, "volume_series": [100.0] * 20})
    assert s1["vol_vs_avg_ratio"] is None
    assert validate_volume_structure(s1)["passes"] is True
    # NaN inside the series is scrubbed, computation still works
    s2 = compute_volume_structure({"volume": 150.0, "volume_series": [100.0] * 20 + [nan]})
    assert _approx(s2["avg_volume_20d"], 100.0)
    assert _approx(s2["vol_vs_avg_ratio"], 1.5)
    print("test_nan_volume_handled OK")


def test_none_metrics_no_opinion_pass():
    v = validate_volume_structure({"vol_vs_avg_ratio": None})
    assert v["passes"] is True
    assert v["checks"] == {"volume_ok": True}
    assert v["reasons"] == []
    print("test_none_metrics_no_opinion_pass OK")


def test_non_dict_chart_no_raise():
    s = compute_volume_structure(None)
    assert s["vol_vs_avg_ratio"] is None
    assert s["avg_volume_20d"] is None
    print("test_non_dict_chart_no_raise OK")


def test_missing_volume_key():
    chart = {"close_series": [100.0] * 20}   # no volume / volume_series keys
    s = compute_volume_structure(chart)
    assert s["volume"] is None
    assert s["avg_volume_20d"] is None
    assert s["vol_vs_avg_ratio"] is None
    assert validate_volume_structure(s)["passes"] is True
    print("test_missing_volume_key OK")


if __name__ == "__main__":
    test_high_volume_passes()
    test_low_volume_fails_gate()
    test_ratio_boundary()
    test_short_series_returns_none()
    test_zero_average_no_div()
    test_nan_volume_handled()
    test_none_metrics_no_opinion_pass()
    test_non_dict_chart_no_raise()
    test_missing_volume_key()
    print("ALL TESTS PASSED")

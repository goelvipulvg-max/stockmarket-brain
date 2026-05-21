import pytest
from unittest.mock import MagicMock, patch
from agents.tier3_position_manager import (
    apply_rules,
    evaluate_with_claude,
    format_pick_message,
    format_summary_message,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_signal(**kwargs):
    base = {
        "id": 1,
        "ticker": "RELIANCE.NS",
        "source": "TIER2F",
        "direction": "BUY",
        "confidence": 8,
        "rsi": 55.0,
        "macd": 12.5,
        "entry_price": 2450.0,
        "target_price": 2550.0,
        "stop_loss": 2380.0,
        "reason": "MACD crossover with RSI at 55",
    }
    base.update(kwargs)
    return base


# ── apply_rules ───────────────────────────────────────────────────────────────

def test_rule_duplicate_open():
    signal = make_signal(id=1, ticker="RELIANCE.NS", source="TIER2F")
    open_trades = [{"id": 2, "ticker": "RELIANCE.NS", "source": "TIER2F", "status": "OPEN"}]
    passed, reason = apply_rules(signal, open_trades)
    assert passed is False
    assert reason == "duplicate_open_position_for_source_TIER2F"


def test_rule_confidence_threshold():
    signal = make_signal(confidence=7)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "confidence_below_threshold"


def test_rule_extreme_rsi_buy():
    signal = make_signal(direction="BUY", rsi=82.0)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "extreme_rsi"


def test_rule_extreme_rsi_sell():
    signal = make_signal(direction="SELL", rsi=18.0)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "extreme_rsi"


def test_rule_all_pass():
    signal = make_signal(id=1, ticker="RELIANCE.NS", confidence=8, rsi=55.0, direction="BUY")
    open_trades = [{"id": 2, "ticker": "TCS.NS", "status": "OPEN"}]
    passed, reason = apply_rules(signal, open_trades)
    assert passed is True
    assert reason is None


# ── evaluate_with_claude ──────────────────────────────────────────────────────

def test_claude_approve():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = (
        '{"verdict": "APPROVE", "confidence": 9, "reason": "Strong signal, no negative catalysts"}'
    )
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 9
    assert "_parse_error" not in result


def test_claude_reject():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = (
        '{"verdict": "REJECT", "confidence": 3, "reason": "Regulatory action pending"}'
    )
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "REJECT"
    assert "_parse_error" not in result


def test_claude_parse_error():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = "not valid json {{{"
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "REJECT"
    assert result.get("_parse_error") is True


# ── format_pick_message ───────────────────────────────────────────────────────

def test_summary_message_format():
    approved = ["RELIANCE.NS", "TCS.NS"]
    rejected_reasons = [
        "confidence_below_threshold",
        "confidence_below_threshold",
        "duplicate_open_position",
        "claude_reject",
    ]
    msg = format_summary_message(approved, rejected_reasons, "07 May 2026")
    assert "Approved: 2" in msg
    assert "Rejected: 4" in msg
    assert "50,000" in msg
    assert "2 × confidence_below_threshold" in msg


def test_no_signals_today():
    msg = format_summary_message([], [], "07 May 2026")
    assert "Approved: 0" in msg
    assert "Rejected: 0" in msg
    assert "₹0" in msg

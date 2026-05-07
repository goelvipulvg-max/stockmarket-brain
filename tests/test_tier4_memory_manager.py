import pytest
from unittest.mock import MagicMock
from agents.tier4_memory_manager import compute_stats, format_memory_text
from agents.tier3_position_manager import evaluate_with_claude

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_trade(ticker="RELIANCE.NS", direction="BUY", confidence=9, status="TARGET_HIT"):
    return {
        "ticker": ticker,
        "direction": direction,
        "confidence_tier2": confidence,
        "status": status,
    }


# ── compute_stats ─────────────────────────────────────────────────────────────

def test_compute_stats_by_confidence():
    trades = [
        make_trade(confidence=8, status="TARGET_HIT"),
        make_trade(confidence=8, status="SL_HIT"),
        make_trade(confidence=8, status="SL_HIT"),
        make_trade(confidence=9, status="TARGET_HIT"),
        make_trade(confidence=9, status="TARGET_HIT"),
        make_trade(confidence=9, status="SL_HIT"),
        make_trade(confidence=10, status="TARGET_HIT"),
    ]
    stats = compute_stats(trades)
    assert stats["by_confidence"][8] == {"wins": 1, "total": 3}
    assert stats["by_confidence"][9] == {"wins": 2, "total": 3}
    assert stats["by_confidence"][10] == {"wins": 1, "total": 1}


def test_compute_stats_by_ticker_min2():
    trades = [
        make_trade(ticker="RELIANCE.NS", status="TARGET_HIT"),
        make_trade(ticker="RELIANCE.NS", status="SL_HIT"),
        make_trade(ticker="TCS.NS", status="TARGET_HIT"),       # only 1 trade — must be excluded
        make_trade(ticker="INFY.NS", status="SL_HIT"),
        make_trade(ticker="INFY.NS", status="SL_HIT"),
    ]
    stats = compute_stats(trades)
    assert "RELIANCE.NS" in stats["by_ticker"]
    assert "INFY.NS" in stats["by_ticker"]
    assert "TCS.NS" not in stats["by_ticker"]
    assert stats["by_ticker"]["RELIANCE.NS"] == {"wins": 1, "total": 2}
    assert stats["by_ticker"]["INFY.NS"] == {"wins": 0, "total": 2}


def test_compute_stats_by_direction():
    trades = [
        make_trade(direction="BUY", status="TARGET_HIT"),
        make_trade(direction="BUY", status="TARGET_HIT"),
        make_trade(direction="BUY", status="SL_HIT"),
        make_trade(direction="SELL", status="SL_HIT"),
        make_trade(direction="SELL", status="TARGET_HIT"),
    ]
    stats = compute_stats(trades)
    assert stats["by_direction"]["BUY"] == {"wins": 2, "total": 3}
    assert stats["by_direction"]["SELL"] == {"wins": 1, "total": 2}


# ── format_memory_text ────────────────────────────────────────────────────────

def test_format_memory_text():
    stats = {
        "by_confidence": {
            9: {"wins": 7, "total": 11},
        },
        "by_ticker": {
            "RELIANCE.NS": {"wins": 3, "total": 4},
        },
        "by_direction": {
            "BUY": {"wins": 9, "total": 16},
        },
        "total_resolved": 11,
    }
    text = format_memory_text(stats, "2026-05-07")
    assert "2026-05-07" in text
    assert "Conf 9" in text
    assert "7W/11T" in text
    assert "64%" in text
    assert "RELIANCE.NS" in text
    assert "3W/4T" in text
    assert "BUY" in text
    assert "9W/16T" in text


def test_zero_resolved_trades():
    stats = compute_stats([])
    assert stats["total_resolved"] == 0
    text = format_memory_text(stats, "2026-05-07")
    assert text == "No resolved trades yet."


# ── MIN_SAMPLES threshold ─────────────────────────────────────────────────────

def test_format_confidence_insufficient_data():
    stats = {
        "by_confidence": {8: {"wins": 1, "total": 2}},
        "by_ticker": {},
        "by_direction": {"BUY": {"wins": 5, "total": 8}},
        "total_resolved": 2,
    }
    text = format_memory_text(stats, "2026-05-07")
    assert "Conf 8: 2T — insufficient data" in text
    assert "%" not in text.split("By confidence:")[1].split("By")[0]


def test_format_direction_insufficient_data():
    stats = {
        "by_confidence": {9: {"wins": 4, "total": 5}},
        "by_ticker": {},
        "by_direction": {"SELL": {"wins": 1, "total": 1}},
        "total_resolved": 6,
    }
    text = format_memory_text(stats, "2026-05-07")
    assert "SELL: 1T — insufficient data" in text
    direction_block = text.split("By direction:")[1]
    assert "%" not in direction_block


def test_format_mixed_confidence():
    stats = {
        "by_confidence": {
            8: {"wins": 1, "total": 2},   # below threshold
            9: {"wins": 7, "total": 11},  # above threshold
        },
        "by_ticker": {},
        "by_direction": {"BUY": {"wins": 8, "total": 13}},
        "total_resolved": 13,
    }
    text = format_memory_text(stats, "2026-05-07")
    assert "Conf 8: 2T — insufficient data" in text
    assert "Conf 9: 7W/11T = 64%" in text


# ── Tier-3 integration ────────────────────────────────────────────────────────

def test_tier3_uses_memory_text():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = (
        '{"verdict": "APPROVE", "confidence": 9, "reason": "ok"}'
    )
    signal = {
        "id": 1, "ticker": "RELIANCE.NS", "direction": "BUY",
        "confidence": 9, "rsi": 55.0, "macd": 12.5,
        "entry_price": 2450.0, "target_price": 2550.0,
        "stop_loss": 2380.0, "reason": "MACD crossover",
    }
    memory = "Conf 9: 7W/11T = 64%"
    evaluate_with_claude(signal, [], [], mock_client, memory_text=memory)

    call_args = mock_client.messages.create.call_args
    prompt = call_args.kwargs["messages"][0]["content"]
    assert memory in prompt

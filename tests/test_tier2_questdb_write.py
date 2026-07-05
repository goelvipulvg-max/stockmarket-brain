import sys
import os
import subprocess
from unittest.mock import patch
from datetime import datetime, timezone

# Prevent module-level Supabase/Anthropic init from requiring real credentials
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.tier2_signals import log_signal_questdb

SAMPLE_DATA = {
    "ticker": "RELIANCE.NS",
    "close": 2900.0,
    "rsi": 45.2,
    "macd": 0.5,
    "macd_signal": 0.3,
    "support": 2800.0,
    "resistance": 3100.0,
    "volume": 1000000,
}

SAMPLE_BUY_SIGNAL = {
    "signal": "BUY",
    "confidence": 8,
    "reason": "RSI oversold, MACD bullish crossover",
    "entry": 2850.0,
    "target": 3050.0,
    "stop_loss": 2750.0,
}


def test_buy_signal_inserts_correct_row():
    """Verifies full column mapping for a BUY signal."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_signal_questdb(SAMPLE_DATA, SAMPLE_BUY_SIGNAL)
        mock_exec.assert_called_once()
        sql, rows = mock_exec.call_args[0]
        assert len(rows) == 1
        row = rows[0]
        # Tuple order matches INSERT column list:
        # ts, signal_id, symbol, strategy, direction, confidence,
        # entry_target, stop_loss, take_profit, reasoning, source, triggered, trade_id
        assert row[2] == "RELIANCE.NS"                              # symbol
        assert row[3] == "tier2-swing"                              # strategy
        assert row[4] == "BUY"                                      # direction
        assert row[5] == 8.0                                        # confidence as float
        assert row[6] == 2850.0                                     # entry_target
        assert row[7] == 2750.0                                     # stop_loss
        assert row[8] == 3050.0                                     # take_profit
        assert row[9] == "RSI oversold, MACD bullish crossover"     # reasoning
        assert row[10] == "deepseek-v4-flash"                       # source (model migrated Haiku -> DeepSeek)
        assert row[11] is False                                     # triggered
        assert row[12] == ""                                        # trade_id


def test_ts_is_midnight_utc():
    """ts must be start-of-day UTC — DEDUP key must be stable across re-runs."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_signal_questdb(SAMPLE_DATA, SAMPLE_BUY_SIGNAL)
        row = mock_exec.call_args[0][1][0]
        ts = row[0]
        assert ts.hour == 0
        assert ts.minute == 0
        assert ts.second == 0
        assert ts.microsecond == 0
        assert ts.tzinfo is None  # QuestDB wire rejects timestamptz — must be naive UTC


def test_signal_id_contains_ticker_and_date():
    """signal_id must be {ticker}_{YYYYMMDD} — deterministic per stock per day."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_signal_questdb(SAMPLE_DATA, SAMPLE_BUY_SIGNAL)
        row = mock_exec.call_args[0][1][0]
        signal_id = row[1]
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert signal_id == f"RELIANCE.NS_{today}"


def test_ts_and_signal_id_share_same_date():
    """ts and signal_id derive from the same datetime.now() call — no midnight race."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_signal_questdb(SAMPLE_DATA, SAMPLE_BUY_SIGNAL)
        row = mock_exec.call_args[0][1][0]
        ts = row[0]
        signal_id = row[1]
        date_from_ts = ts.strftime("%Y%m%d")
        date_from_signal_id = signal_id.split("_")[-1]
        assert date_from_ts == date_from_signal_id


def test_questdb_failure_does_not_raise():
    """QuestDB write failure must be non-fatal — must not propagate to caller."""
    with patch("utils.questdb_client.executemany", side_effect=Exception("connection refused")):
        log_signal_questdb(SAMPLE_DATA, SAMPLE_BUY_SIGNAL)  # must not raise


def test_script_importable_when_run_directly():
    """python agents/tier2_signals.py must import cleanly, then REFUSE to run.

    Imports execute before the __main__ guard, so the ModuleNotFoundError
    assertion still detects the sys.path bug. The guard itself is a hard-kill
    (audit 2.5): before it, this subprocess ran the deprecated PRODUCTION
    pipeline -- load_dotenv(override=True) inside the script restores real
    .env creds over the scrubbed env below, so main() could insert real
    paper_trades rows (and call DeepSeek) from a plain pytest run.
    """
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    result = subprocess.run(
        [sys.executable, "agents/tier2_signals.py"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env={
            **{k: os.environ[k] for k in ("PATH",) if k in os.environ},
            **{k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP") if k in os.environ},
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
            "ANTHROPIC_API_KEY": "test-key",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_SWING_CHANNEL": "",
        },
    )
    assert "No module named 'utils'" not in result.stderr, (
        f"sys.path bug: script crashed with ModuleNotFoundError — fix not yet applied.\n"
        f"stderr:\n{result.stderr[:500]}"
    )
    assert result.returncode != 0, (
        f"hard-kill regressed: deprecated entrypoint ran instead of refusing.\n"
        f"stdout:\n{result.stdout[:500]}"
    )
    assert "DEPRECATED" in result.stderr, (
        f"hard-kill message missing from stderr.\nstderr:\n{result.stderr[:500]}"
    )

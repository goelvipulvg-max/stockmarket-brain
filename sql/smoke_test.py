import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.questdb_client import execute, query


def ts(offset_us: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(microseconds=offset_us)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")


def check_table(table: str, inserts: list[str], min_count: int = 2) -> None:
    print(f"\n--- {table} ---")
    for sql in inserts:
        execute(sql)
    time.sleep(1)  # WAL commit buffer
    rows = query(f"SELECT count(*) as cnt FROM {table}")
    count = rows[0]["cnt"]
    assert count >= min_count, f"Expected >= {min_count} rows, got {count}"
    sample = query(f"SELECT * FROM {table} LIMIT 1")
    print(f"  count={count}, sample keys={list(sample[0].keys())[:4]}")
    execute(f"TRUNCATE TABLE {table}")
    print(f"  PASS (truncated)")


def main():
    t1 = ts(0)
    t2 = ts(1000)

    check_table("paper_trades", [
        f"INSERT INTO paper_trades (entry_ts, trade_id, symbol, side, strategy, quantity, entry_price, exit_price, pnl, pnl_pct, holding_days, status, signal_id, notes)"
        f" VALUES ('{t1}', 'T001', 'RELIANCE', 'BUY', 'SWING', 10, 2800.5, 0.0, 0.0, 0.0, 0, 'OPEN', 'S001', 'smoke')",

        f"INSERT INTO paper_trades (entry_ts, trade_id, symbol, side, strategy, quantity, entry_price, exit_price, pnl, pnl_pct, holding_days, status, signal_id, notes)"
        f" VALUES ('{t2}', 'T002', 'TCS', 'SELL', 'SWING', 5, 3500.0, 0.0, 0.0, 0.0, 0, 'OPEN', 'S002', 'smoke')",
    ])

    t1, t2 = ts(0), ts(1000)
    check_table("ticks", [
        f"INSERT INTO ticks (ts, symbol, ltp, volume, bid, ask, oi) VALUES ('{t1}', 'INFY', 1450.5, 10000, 1449.0, 1451.0, 0)",
        f"INSERT INTO ticks (ts, symbol, ltp, volume, bid, ask, oi) VALUES ('{t2}', 'HDFCBANK', 1650.0, 8000, 1649.0, 1651.0, 0)",
    ])

    t1, t2 = ts(0), ts(1000)
    check_table("signals", [
        f"INSERT INTO signals (ts, signal_id, symbol, strategy, direction, confidence, entry_target, stop_loss, take_profit, reasoning, source, triggered)"
        f" VALUES ('{t1}', 'SIG001', 'RELIANCE', 'SWING', 'BUY', 8.5, 2800.0, 2750.0, 2900.0, 'Strong momentum', 'tier2', false)",

        f"INSERT INTO signals (ts, signal_id, symbol, strategy, direction, confidence, entry_target, stop_loss, take_profit, reasoning, source, triggered)"
        f" VALUES ('{t2}', 'SIG002', 'TCS', 'SWING', 'SELL', 7.0, 3500.0, 3550.0, 3400.0, 'Bearish pattern', 'tier2', false)",
    ])

    t1, t2 = ts(0), ts(1000)
    check_table("news_events", [
        f"INSERT INTO news_events (ts, event_id, source, symbol, headline, url, sentiment, category, summary)"
        f" VALUES ('{t1}', 'EVT001', 'ET', 'INFY', 'Infosys wins deal', 'http://example.com/1', 0.8, 'CORPORATE', 'Major win')",

        f"INSERT INTO news_events (ts, event_id, source, symbol, headline, url, sentiment, category, summary)"
        f" VALUES ('{t2}', 'EVT002', 'ET', 'HDFCBANK', 'HDFC reports Q4', 'http://example.com/2', 0.5, 'EARNINGS', 'Q4 results')",
    ])

    print("\nAll smoke tests PASSED.")


if __name__ == "__main__":
    main()

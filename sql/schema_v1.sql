-- Table 1: paper_trades — one row per trade lifecycle (UPDATE on close)
CREATE TABLE IF NOT EXISTS paper_trades (
    entry_ts TIMESTAMP,
    trade_id STRING,
    symbol SYMBOL CAPACITY 1024 INDEX,
    side SYMBOL CAPACITY 8,
    strategy SYMBOL CAPACITY 32 INDEX,
    quantity LONG,
    entry_price DOUBLE,
    exit_price DOUBLE,
    exit_ts TIMESTAMP,
    pnl DOUBLE,
    pnl_pct DOUBLE,
    holding_days INT,
    status SYMBOL CAPACITY 8,
    signal_id STRING,
    notes STRING
) TIMESTAMP(entry_ts) PARTITION BY MONTH WAL;

-- Table 2: ticks — high-volume market data
CREATE TABLE IF NOT EXISTS ticks (
    ts TIMESTAMP,
    symbol SYMBOL CAPACITY 4096 INDEX,
    ltp DOUBLE,
    volume LONG,
    bid DOUBLE,
    ask DOUBLE,
    oi LONG
) TIMESTAMP(ts) PARTITION BY DAY WAL DEDUP UPSERT KEYS(ts, symbol);

-- Table 3: signals — generated trading signals (pre-trade)
CREATE TABLE IF NOT EXISTS signals (
    ts TIMESTAMP,
    signal_id STRING,
    symbol SYMBOL CAPACITY 1024 INDEX,
    strategy SYMBOL CAPACITY 32 INDEX,
    direction SYMBOL CAPACITY 8,
    confidence DOUBLE,
    entry_target DOUBLE,
    stop_loss DOUBLE,
    take_profit DOUBLE,
    reasoning STRING,
    source SYMBOL CAPACITY 16,
    triggered BOOLEAN,
    trade_id STRING
) TIMESTAMP(ts) PARTITION BY MONTH WAL DEDUP UPSERT KEYS(ts, signal_id);

-- Table 4: news_events — RSS-driven news (one row per symbol mentioned)
CREATE TABLE IF NOT EXISTS news_events (
    ts TIMESTAMP,
    event_id STRING,
    source SYMBOL CAPACITY 32 INDEX,
    symbol SYMBOL CAPACITY 1024 INDEX,
    headline STRING,
    url STRING,
    sentiment DOUBLE,
    category SYMBOL CAPACITY 32,
    summary STRING
) TIMESTAMP(ts) PARTITION BY MONTH WAL DEDUP UPSERT KEYS(ts, event_id, symbol);

-- Migration: after_hours_queue v2
-- Drops old schema (generic JSONB) and recreates with typed columns for the After Hours Pipeline.

DROP TABLE IF EXISTS after_hours_queue;

CREATE TABLE after_hours_queue (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    company_name        TEXT,
    event_type          TEXT,
    announcement_time   TEXT,
    tradeable_score     INTEGER,
    expected_gap_pct    NUMERIC(6,2),
    recommended_action  TEXT,
    entry_price_low     NUMERIC(10,2),
    entry_price_high    NUMERIC(10,2),
    target_price        NUMERIC(10,2),
    stop_loss           NUMERIC(10,2),
    confidence          TEXT,
    telegram_sent       BOOLEAN DEFAULT FALSE,
    status              TEXT DEFAULT 'PENDING',
    source_url          TEXT,
    url_hash            TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

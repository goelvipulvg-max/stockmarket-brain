-- Guardian Phase 1 — tier1_guardian_alerts table
-- Target: Neon database 'stockmarket-brain', schema 'public'
-- Execute manually in Neon console (https://console.neon.tech)
-- Created: 2026-05-12

CREATE TABLE IF NOT EXISTS tier1_guardian_alerts (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          VARCHAR(20) NOT NULL,
    score           INTEGER NOT NULL,
    alert_type      VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'SENT',
    headline        TEXT,
    news_event_ids  JSONB,
    reasoning       TEXT,
    sources_count   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tier1_guardian_alerts_symbol_ts
    ON tier1_guardian_alerts (symbol, ts DESC);

CREATE INDEX IF NOT EXISTS idx_tier1_guardian_alerts_ts
    ON tier1_guardian_alerts (ts DESC);

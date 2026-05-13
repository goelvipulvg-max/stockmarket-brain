-- ============================================================================
-- Fundamental Signals Schema
-- Phase 1 of fundamental analysis layer
--
-- Project: goelvipulvg-max/stockmarket-brain
-- Database: Neon (neondb / 'Nifty 500' branch)
--
-- Architecture flow:
--   Supabase filings_log (NSE filings)
--     → Agent-1 Haiku 4.5 (classifier)
--     → Programmatic filters (liquidity, market cap)
--     → Agent-2 Haiku 4.5 (signal synthesizer)
--     → THIS TABLE (fundamental_signals)
--     → Telegram "Fundamental Signals" channel
--
-- Cross-DB note: source_filing_id references Supabase filings_log.id
--                No FK constraint possible across databases.
--                Application layer must validate references.
-- ============================================================================


-- ─── PART 1: Main table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fundamental_signals (
    -- Identity & References
    id                       BIGSERIAL    PRIMARY KEY,
    symbol                   TEXT         NOT NULL,
    source_filing_id         BIGINT       NOT NULL,

    -- Timing
    signal_generated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    filing_classified_at     TIMESTAMPTZ,
    horizon_days             INTEGER      NOT NULL DEFAULT 10
                             CHECK (horizon_days BETWEEN 1 AND 60),

    -- Agent-1 Output (Classification)
    agent1_classification    JSONB        NOT NULL,

    -- Programmatic Filter Results
    liquidity_pass           BOOLEAN,
    market_cap_pass          BOOLEAN,
    filter_metadata          JSONB,

    -- Agent-2 Output (Synthesis) — NULL if filter rejected before Agent-2
    agent2_synthesis         JSONB,

    -- Core Signal (denormalized for query speed)
    signal                   TEXT         NOT NULL
                             CHECK (signal IN ('BUY','SELL','HOLD','REJECTED')),
    confidence               INTEGER      CHECK (confidence BETWEEN 1 AND 10),
    target_price             NUMERIC(12, 2),
    stop_loss                NUMERIC(12, 2),

    -- F&O Future-Proofing (scraper deferred to F&O execution phase)
    fno_banned               BOOLEAN      DEFAULT NULL,
    recommended_instrument   TEXT         DEFAULT 'cash_equity'
                             CHECK (recommended_instrument IN
                                ('cash_equity','futures','options','auto')),

    -- De-dup & State Management
    supersedes_signal_id     BIGINT       REFERENCES fundamental_signals(id),
    status                   TEXT         NOT NULL DEFAULT 'active'
                             CHECK (status IN
                                ('active','superseded','expired','closed')),

    -- Notification Tracking
    telegram_sent            BOOLEAN      NOT NULL DEFAULT FALSE,
    telegram_sent_at         TIMESTAMPTZ,
    telegram_suppress_reason TEXT,

    -- Audit & Reproducibility
    agent_versions           JSONB,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_signal_per_filing UNIQUE (source_filing_id)
);


-- ─── PART 2: Indexes ────────────────────────────────────────────────────

-- Hot path: latest signal per symbol
CREATE INDEX IF NOT EXISTS idx_fund_signals_symbol_time
    ON fundamental_signals(symbol, signal_generated_at DESC);

-- Hot path: active actionable signals (partial index — smaller, faster)
CREATE INDEX IF NOT EXISTS idx_fund_signals_active_actionable
    ON fundamental_signals(signal, confidence DESC, signal_generated_at DESC)
    WHERE status = 'active' AND signal IN ('BUY','SELL');

-- Time-range queries (analytics, backtest, daily reports)
CREATE INDEX IF NOT EXISTS idx_fund_signals_generated_at
    ON fundamental_signals(signal_generated_at DESC);

-- Supersession chain lookups
CREATE INDEX IF NOT EXISTS idx_fund_signals_supersedes
    ON fundamental_signals(supersedes_signal_id)
    WHERE supersedes_signal_id IS NOT NULL;

-- Status-based queries
CREATE INDEX IF NOT EXISTS idx_fund_signals_status
    ON fundamental_signals(status, signal_generated_at DESC);


-- ─── PART 3: View — Active signals per symbol ───────────────────────────
CREATE OR REPLACE VIEW active_fundamental_signals AS
SELECT DISTINCT ON (symbol)
    id,
    symbol,
    source_filing_id,
    signal_generated_at,
    horizon_days,
    signal,
    confidence,
    target_price,
    stop_loss,
    agent1_classification,
    agent2_synthesis,
    fno_banned,
    recommended_instrument,
    status,
    EXTRACT(EPOCH FROM (
        signal_generated_at + (horizon_days || ' days')::interval - NOW()
    )) / 86400 AS days_remaining
FROM fundamental_signals
WHERE status = 'active'
  AND signal_generated_at + (horizon_days || ' days')::interval > NOW()
  AND signal IN ('BUY', 'SELL')
ORDER BY symbol, signal_generated_at DESC, confidence DESC;


-- ─── PART 4: Documentation (column comments) ────────────────────────────
COMMENT ON TABLE fundamental_signals IS
    'Swing trade signals (5-15 day horizon) generated from NSE corporate filings '
    'via two-agent Haiku 4.5 pipeline. Universe: Nifty 500. Source: Supabase filings_log. '
    'MVP advisory only (not auto-promoted to paper_trades). Phase: 1.0.';

COMMENT ON COLUMN fundamental_signals.source_filing_id IS
    'References Supabase filings_log.id. No FK constraint (cross-database). '
    'Validate at application layer before insert.';

COMMENT ON COLUMN fundamental_signals.signal IS
    'BUY/SELL = actionable. HOLD = Agent-2 evaluated but no conviction. '
    'REJECTED = programmatic filter rejected before Agent-2 (no synthesis).';

COMMENT ON COLUMN fundamental_signals.agent1_classification IS
    'Expected keys: {category, sentiment, materiality_score, key_facts[], '
    'red_flags[]|null, confidence (1-10)}.';

COMMENT ON COLUMN fundamental_signals.agent2_synthesis IS
    'Expected keys: {entry_zone:{low,high}, target_price, stop_loss, '
    'rationale, catalyst_decay_days}. NULL when signal=REJECTED.';

COMMENT ON COLUMN fundamental_signals.fno_banned IS
    'NULL = not checked (F&O scraper deferred to F&O execution phase). '
    'FALSE/TRUE populated only when scraper active. '
    'Cash equity execution unaffected by F&O ban.';

COMMENT ON COLUMN fundamental_signals.recommended_instrument IS
    'Default cash_equity (5-15 day swing typical). '
    'futures/options require fno_banned check before execution.';

COMMENT ON COLUMN fundamental_signals.supersedes_signal_id IS
    'Set when this signal replaces a prior active signal for same symbol. '
    'Prior signal status should transition to superseded via application logic.';

COMMENT ON COLUMN fundamental_signals.status IS
    'active = current. superseded = replaced by newer signal. '
    'expired = horizon_days exceeded. closed = manually closed.';

COMMENT ON COLUMN fundamental_signals.agent_versions IS
    'Reproducibility tracking: {agent1_model, agent2_model, '
    'prompt_versions:{agent1, agent2}, git_sha}.';

COMMENT ON COLUMN fundamental_signals.telegram_suppress_reason IS
    'If telegram_sent=FALSE, reason: "dup_4h_window", "low_conf", '
    '"hold_signal", "error", etc.';


-- ─── PART 5: Sample insert (for reference / smoke test) ─────────────────
-- DO NOT EXECUTE — example only, shows expected data shape
/*
INSERT INTO fundamental_signals (
    symbol, source_filing_id, filing_classified_at,
    agent1_classification,
    liquidity_pass, market_cap_pass, filter_metadata,
    agent2_synthesis,
    signal, confidence, target_price, stop_loss,
    agent_versions
) VALUES (
    'RELIANCE', 12345, '2026-05-13 13:00:00+00',
    '{
        "category": "results",
        "sentiment": "positive",
        "materiality_score": 9,
        "key_facts": ["Q4 revenue +18% YoY", "EBITDA margin 28% (best in 6Q)"],
        "red_flags": null,
        "confidence": 9
    }'::jsonb,
    TRUE, TRUE,
    '{"liquidity_actual_inr_cr": 450, "market_cap_inr_cr": 1850000}'::jsonb,
    '{
        "entry_zone": {"low": 2840, "high": 2880},
        "target_price": 3100,
        "stop_loss": 2720,
        "rationale": "Strong Q4 beat, margin expansion thesis intact, ...",
        "catalyst_decay_days": 14
    }'::jsonb,
    'BUY', 8, 3100, 2720,
    '{
        "agent1_model": "claude-haiku-4-5-20251001",
        "agent2_model": "claude-haiku-4-5-20251001",
        "prompt_versions": {"agent1": "v1.0", "agent2": "v1.0"},
        "git_sha": "abc1234"
    }'::jsonb
);
*/
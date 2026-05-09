import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.neon_client import get_neon_connection

TABLES = {
    "company_profiles": """
        CREATE TABLE IF NOT EXISTS company_profiles (
            symbol          TEXT PRIMARY KEY,
            company_name    TEXT,
            sector          TEXT,
            industry        TEXT,
            business_summary TEXT,
            key_metrics     JSONB,
            risk_factors     JSONB,
            moat_analysis   JSONB,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """,
    "pattern_library": """
        CREATE TABLE IF NOT EXISTS pattern_library (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT,
            pattern_name    TEXT,
            pattern_data    JSONB,
            success_rate    NUMERIC(5,2),
            sample_size     INTEGER,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """,
    "research_cache": """
        CREATE TABLE IF NOT EXISTS research_cache (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT,
            query_hash      TEXT,
            query_text      TEXT,
            response_text   TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            expires_at      TIMESTAMPTZ
        )
    """,
    "after_hours_queue": """
        CREATE TABLE IF NOT EXISTS after_hours_queue (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT,
            event_type      TEXT,
            event_data      JSONB,
            priority        INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'pending',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            processed_at    TIMESTAMPTZ
        )
    """,
    "event_outcomes": """
        CREATE TABLE IF NOT EXISTS event_outcomes (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT,
            event_type      TEXT,
            event_date      DATE,
            signal_generated BOOLEAN,
            trade_result    TEXT,
            outcome_score   NUMERIC(5,2),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """,
}


def main():
    conn = get_neon_connection()
    failed = 0

    for name, ddl in TABLES.items():
        try:
            with conn.cursor() as cur:
                cur.execute(ddl)
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1

    conn.close()

    if failed:
        print(f"\n{failed} table(s) failed.")
        sys.exit(1)
    else:
        print(f"\nAll {len(TABLES)} tables created successfully.")


if __name__ == "__main__":
    main()

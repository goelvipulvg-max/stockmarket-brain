import sys
import os
from unittest.mock import patch
from datetime import datetime

# Prevent module-level Supabase/Anthropic init from requiring real credentials.
# tier1_news uses plain load_dotenv() (no override), so vars set here survive the import.
# supabase.create_client rejects empty-string URLs — use a fake-but-truthy URL.
os.environ.setdefault("SUPABASE_URL", "https://fake-test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_MOVERS_CHANNEL", "-100000000000")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.tier1_news import log_news_questdb

SAMPLE_TS       = datetime(2026, 5, 6, 10, 30, 0)   # naive UTC — intraday from pubDate
SAMPLE_SOURCE   = "ET Markets"
SAMPLE_URL      = "https://economictimes.com/article/rbi-cuts-rates"
SAMPLE_TITLE    = "RBI cuts rates by 25bps in surprise move"
SAMPLE_SCORE    = 8
SAMPLE_CATEGORY = "bullish"
SAMPLE_SUMMARY  = "RBI cuts benchmark rate by 25bps, first cut in two years."


def test_happy_path_inserts_correct_row():
    """Verifies full column mapping for a well-formed news article."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, SAMPLE_SUMMARY,
        )
        mock_exec.assert_called_once()
        sql, rows = mock_exec.call_args[0]
        assert len(rows) == 1
        row = rows[0]
        # Tuple order matches INSERT column list:
        # ts, event_id, source, symbol, headline, url, sentiment, category, summary
        assert row[0] == SAMPLE_TS                                    # ts
        assert row[2] == "ET Markets"                                  # source
        assert row[3] == "MARKET"                                      # symbol placeholder
        assert row[4] == SAMPLE_TITLE                                  # headline
        assert row[5] == SAMPLE_URL                                    # url
        assert row[6] == 8.0                                           # sentiment as float
        assert row[7] == "bullish"                                     # category
        assert row[8] == SAMPLE_SUMMARY                                # summary


def test_questdb_down_is_nonfatal():
    """QuestDB write failure must not propagate — Supabase write must be unaffected."""
    with patch("utils.questdb_client.executemany", side_effect=Exception("connection refused")):
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, SAMPLE_SUMMARY,
        )  # must not raise


def test_duplicate_call_invokes_executemany_twice():
    """DEDUP is DB-side (UPSERT), not app-side — both calls must reach QuestDB."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, SAMPLE_SUMMARY,
        )
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, SAMPLE_SUMMARY,
        )
        assert mock_exec.call_count == 2


def test_score_edge_values():
    """Boundary scores 0 and 10 must survive float() cast without error."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL, SAMPLE_TITLE, 0, SAMPLE_CATEGORY, SAMPLE_SUMMARY)
        row_zero = mock_exec.call_args[0][1][0]
        assert row_zero[6] == 0.0   # sentiment

    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL, SAMPLE_TITLE, 10, SAMPLE_CATEGORY, SAMPLE_SUMMARY)
        row_ten = mock_exec.call_args[0][1][0]
        assert row_ten[6] == 10.0   # sentiment


def test_apostrophe_in_headline_does_not_crash():
    """Parameterized query must safely handle apostrophes in title/summary."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            "India's RBI cuts rates by 25bps", SAMPLE_SCORE, SAMPLE_CATEGORY,
            "Governor D'Souza signals further easing.",
        )
        mock_exec.assert_called_once()


def test_none_and_empty_summary_coerced_to_empty_string():
    """None or empty summary must be stored as '' — not None (avoids DB type errors)."""
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, None,
        )
        row_none = mock_exec.call_args[0][1][0]
        assert row_none[8] == ""   # summary coerced from None

    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, "",
        )
        row_empty = mock_exec.call_args[0][1][0]
        assert row_empty[8] == ""  # summary unchanged


def test_ts_has_no_tzinfo():
    """ts passed to QuestDB must be naive UTC — regression guard for Part 1 timestamptz bug.

    QuestDB 9.3.5 rejects timezone-aware datetimes over Postgres wire with:
      psycopg2.DatabaseError: invalid constant: timestamptz
    """
    with patch("utils.questdb_client.executemany") as mock_exec:
        log_news_questdb(
            SAMPLE_TS, SAMPLE_SOURCE, SAMPLE_URL,
            SAMPLE_TITLE, SAMPLE_SCORE, SAMPLE_CATEGORY, SAMPLE_SUMMARY,
        )
        row = mock_exec.call_args[0][1][0]
        ts = row[0]
        assert ts.tzinfo is None, f"ts must be naive UTC, got tzinfo={ts.tzinfo}"

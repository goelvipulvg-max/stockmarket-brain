"""Integration test for Tier-2F insert path + Tier-3 scale handling.

Validates commits e4ed94a + 4f4ea12 + 9a9259a deterministically by mocking
the AI consensus stages (Haiku analyst + DeepSeek verifier) to force a PROCEED
verdict, running the real process_filing() against the real DB, and asserting
the paper_trades insert succeeds with confidence populated on the 0-100 scale.

Why mocks are needed here (not editing production code):
  - run_analyst / run_verifier are imported into the tier2_fundamental namespace
    (from utils.ai_consensus), so they are monkeypatched there. This avoids any
    real Anthropic / DeepSeek API calls -- the whole point of a deterministic test.
  - The real determine_consensus() is left intact (it is pure logic), so this
    test also exercises the genuine consensus decision path.
  - `source` is a hardcoded literal "TIER2F" in the trade_payload, so to avoid
    polluting the production source tag we wrap the module-level supabase client
    with a tiny proxy that rewrites source -> TIER2F_INTEGRATION_TEST on insert.
  - deploy_capital and _tg_send are mocked to avoid real capital-ledger writes
    and real Telegram sends.
  - TIER2F_TEST_MODE is forced True to bypass the market-dependent nifty_bearish
    skip, making the test deterministic regardless of live NIFTY mood.

Run: pytest tests/test_tier2f_insert_integration.py -v -m integration
"""
import os

import pytest
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

TEST_FILING_ID = 1418            # WHIRLPOOL, confirmed Nifty 500, RESULTS, score 8
TEST_SOURCE = "TIER2F_INTEGRATION_TEST"


# ============================================================
# Supabase client proxy -- rewrites source on paper_trades insert
# ============================================================

class _PaperTradesInsertProxy:
    """Wraps the paper_trades table object; rewrites `source` on insert only."""

    def __init__(self, real_table, source_override):
        self._real = real_table
        self._src = source_override

    def insert(self, payload, *args, **kwargs):
        if isinstance(payload, dict):
            payload = {**payload, "source": self._src}
        return self._real.insert(payload, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SbProxy:
    """Delegates to the real client; only paper_trades.insert is intercepted."""

    def __init__(self, real_sb, source_override):
        self._real = real_sb
        self._src = source_override

    def table(self, name):
        real_table = self._real.table(name)
        if name == "paper_trades":
            return _PaperTradesInsertProxy(real_table, self._src)
        return real_table

    def __getattr__(self, name):
        return getattr(self._real, name)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def supabase_client():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
    )


@pytest.fixture
def cleanup_test_trades(supabase_client):
    """Delete any rows tagged source=TIER2F_INTEGRATION_TEST before AND after.

    Pre-clean guards against a leftover row from a crashed prior run tripping the
    unique (ticker, date, source) constraint. Post-clean restores DB state.
    """
    supabase_client.table("paper_trades").delete().eq("source", TEST_SOURCE).execute()
    yield
    supabase_client.table("paper_trades").delete().eq("source", TEST_SOURCE).execute()


# ============================================================
# Test 1 -- full insert path (real process_filing, AI mocked to APPROVE)
# ============================================================

@pytest.mark.integration
def test_tier2f_insert_path_full_chain(monkeypatch, supabase_client, cleanup_test_trades):
    """Mock Haiku+Flash APPROVE -> real process_filing -> assert paper_trade inserted
    with confidence on the 0-100 scale and all required NOT NULL fields populated."""
    from agents import tier2_fundamental

    # --- Mock Stage 6 (Haiku analyst): tradeable, BULLISH, conf 75 ---
    def fake_analyst(context, prompt_template=None):
        return {
            "tradeable": True,
            "directional_bias": "BULLISH",
            "confidence": 75,
            "horizon": "MEDIUM",
            "stop_loss_pct": 5.0,
            "reasoning": "mocked_for_integration_test",
        }

    # --- Mock Stage 7 (DeepSeek verifier): CONFIRM, BULLISH, conf 80 ---
    def fake_verifier(context, analyst_output, prompt_template=None):
        return {
            "verdict": "CONFIRM",
            "agreement_score": 90,
            "my_directional_bias": "BULLISH",
            "my_confidence": 80,
            "reasoning": "mocked_for_integration_test",
        }

    monkeypatch.setattr(tier2_fundamental, "run_analyst", fake_analyst)
    monkeypatch.setattr(tier2_fundamental, "run_verifier", fake_verifier)

    # Bypass market-mood skip so the test is deterministic regardless of NIFTY.
    monkeypatch.setattr(tier2_fundamental, "TIER2F_TEST_MODE", True)

    # Tag inserted row with the test source (production code hardcodes "TIER2F").
    monkeypatch.setattr(
        tier2_fundamental,
        "sb",
        _SbProxy(tier2_fundamental.sb, TEST_SOURCE),
    )

    # Avoid real side effects: capital-ledger write + Telegram send.
    monkeypatch.setattr(tier2_fundamental, "deploy_capital", lambda *a, **k: None)
    monkeypatch.setattr(tier2_fundamental, "_tg_send", lambda *a, **k: None)

    # --- Execute the REAL pipeline ---
    result = tier2_fundamental.process_filing(filing_id=TEST_FILING_ID, dry_run=False)

    assert "skip" not in result, f"Pipeline unexpectedly skipped: {result.get('skip')} ({result})"
    assert "trade_id" in result, f"Expected a trade_id in result, got: {result}"

    # --- Query the inserted row by the test source tag ---
    rows = (
        supabase_client.table("paper_trades")
        .select("*")
        .eq("source", TEST_SOURCE)
        .eq("filing_id", TEST_FILING_ID)
        .execute()
    )

    assert len(rows.data) == 1, f"Expected exactly 1 test row, got {len(rows.data)}"
    row = rows.data[0]

    # confidence: (75 + 80) / 2 = 77.5 -> round() -> 78, on 0-100 scale
    assert row["confidence"] is not None, "confidence must not be NULL"
    assert 50 <= row["confidence"] <= 100, f"confidence must be 0-100 scale, got {row['confidence']}"
    assert row["confidence"] == 78, f"expected round((75+80)/2)=78, got {row['confidence']}"

    # required fields
    assert row["ticker"] == "WHIRLPOOL.NS", f"unexpected ticker {row['ticker']}"
    assert row["direction"] == "BUY", f"BULLISH bias should map to BUY, got {row['direction']}"
    assert row["entry_price"] > 0, "entry_price must be positive"
    assert row["target_price"] > 0, "target_price must be positive"
    assert row["stop_loss"] > 0, "stop_loss must be positive"
    assert row["quantity"] > 0, "quantity must be positive"
    assert row["status"] == "OPEN", f"status should be OPEN, got {row['status']}"


# ============================================================
# Test 2 -- Tier-3 accepts a 0-100 scale signal above threshold
# ============================================================

@pytest.mark.integration
def test_tier3_accepts_0_100_scale_signal():
    """apply_rules must accept confidence=78 (above the 0-100 threshold of 50)."""
    from agents.tier3_position_manager import apply_rules

    signal = {
        "id": 999,
        "ticker": "WHIRLPOOL.NS",
        "source": TEST_SOURCE,
        "direction": "BUY",
        "confidence": 78,            # 0-100 scale, above threshold of 50
        "rsi": 55.0,
        "macd": 12.5,
        "entry_price": 845.75,
        "target_price": 880.00,
        "stop_loss": 825.00,
        "reason": "integration_test_signal",
    }

    passed, reason = apply_rules(signal, [])

    assert passed is True, f"Tier-3 must accept confidence=78 on 0-100 scale; got reason={reason}"
    assert reason is None


# ============================================================
# Test 3 -- Tier-3 rejects below the 50 threshold
# ============================================================

@pytest.mark.integration
def test_tier3_rejects_below_50_threshold():
    """apply_rules must reject when confidence < 50 (post-9a9259a /100 threshold)."""
    from agents.tier3_position_manager import apply_rules

    signal = {
        "id": 998,
        "ticker": "WHIRLPOOL.NS",
        "source": TEST_SOURCE,
        "direction": "BUY",
        "confidence": 49,            # below threshold
        "rsi": 55.0,
        "macd": 12.5,
        "entry_price": 845.75,
        "target_price": 880.00,
        "stop_loss": 825.00,
        "reason": "integration_test_signal",
    }

    passed, reason = apply_rules(signal, [])

    assert passed is False
    assert reason == "confidence_below_threshold"

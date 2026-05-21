"""Phase 5 Batch B gate tests.

V5.1: Tier-0F poller dry-run -- mocked dispatch, real DB write verification.
V5.7a: Tier-3 apply_rules() blocks same-source duplicate.
V5.7b: Tier-3 apply_rules() allows different-source on same ticker.

V5.8 (full live pipeline timing) is post-deploy validation, not included here.

Run: pytest tests/test_phase5_batchB.py -v
"""

import pytest
from datetime import datetime, timezone

from agents.tier0f_poller import main as tier0f_main, get_client as get_sb
from agents import tier0f_poller as p_module
from agents.tier3_position_manager import apply_rules


# ============================================================
# V5.1 -- Tier-0F poller dry-run
# ============================================================

def test_V5_1_tier0f_poller_dispatches_and_marks_picked(monkeypatch):
    """Mock dispatch, insert 2 test filings, run poller, verify dispatched + marked."""
    sb = get_sb()

    # Mock dispatch to avoid real GitHub API call
    dispatch_calls = []
    def fake_dispatch(filing_id):
        dispatch_calls.append(filing_id)
        return True
    monkeypatch.setattr(p_module, '_dispatch_tier2f', fake_dispatch)

    # Insert 2 test material filings using v3 column names
    test_ids = []
    try:
        for i in range(2):
            r = sb.table('filings_log').insert({
                'symbol': f'V5TEST{i}',
                'company_name': f'V5 Test Co {i}',
                'event_type': 'TEST_V5_1',
                'exchange': 'NSE',
                'is_material': True,
                'material_score': 7,
                'picked_by_tier0f': False,
                'raw_title': f'V5.1 test filing {i}',
                'summary': 'Synthetic test filing -- V5.1 gate',
            }).execute()
            test_ids.append(r.data[0]['id'])

        # Run poller (non-dry-run -- dispatch is mocked, mark_picked runs real DB update)
        exit_code = tier0f_main(dry_run=False)

        # Verify
        assert exit_code == 0, "Poller should exit 0 on success"
        # All 2 test filings should be dispatched (poller may pick others too if backlog clean)
        assert all(tid in dispatch_calls for tid in test_ids), \
            f"All test filing IDs should be dispatched. Got: {dispatch_calls}"

        # Verify DB marked picked_by_tier0f=true
        check = sb.table('filings_log').select('id, picked_by_tier0f, picked_at')\
            .in_('id', test_ids).execute()
        for row in check.data:
            assert row['picked_by_tier0f'] is True, \
                f"Filing {row['id']} not marked picked_by_tier0f"
            assert row['picked_at'] is not None, \
                f"Filing {row['id']} missing picked_at timestamp"

    finally:
        # Cleanup
        if test_ids:
            sb.table('filings_log').delete().in_('id', test_ids).execute()


# ============================================================
# V5.7a -- Tier-3 blocks same-source duplicate
# ============================================================

def test_V5_7a_tier3_blocks_same_source_duplicate():
    """apply_rules() should return (False, duplicate_*) when ticker AND source match."""
    signal = {
        "id": 9991,
        "ticker": "RELIANCE.NS",
        "source": "TIER2F",
        "confidence": 9,
        "direction": "BUY",
        "rsi": 50,
    }
    open_trades = [
        {"id": 100, "ticker": "RELIANCE.NS", "source": "TIER2F", "status": "OPEN"},
    ]

    passed, reason = apply_rules(signal, open_trades)

    assert passed is False, "Same-source duplicate should be BLOCKED"
    assert "duplicate" in reason.lower(), f"Reason should mention 'duplicate'. Got: {reason}"
    assert "TIER2F" in reason, f"Reason should include source name 'TIER2F'. Got: {reason}"


# ============================================================
# V5.7b -- Tier-3 allows different-source on same ticker
# ============================================================

def test_V5_7b_tier3_allows_different_source_same_ticker():
    """apply_rules() should NOT block when ticker matches but source differs.

    Note: apply_rules() may still reject for other reasons (confidence, rsi, direction).
    This test only verifies the duplicate rule does NOT trigger.
    """
    signal = {
        "id": 9992,
        "ticker": "RELIANCE.NS",
        "source": "TIER1F",
        "confidence": 9,
        "direction": "BUY",
        "rsi": 50,
    }
    open_trades = [
        {"id": 100, "ticker": "RELIANCE.NS", "source": "TIER2F", "status": "OPEN"},
    ]

    passed, reason = apply_rules(signal, open_trades)

    # Should NOT be blocked by duplicate rule specifically
    if passed is False:
        assert "duplicate" not in str(reason).lower(), \
            f"Different-source should NOT be blocked by duplicate rule. Got: {reason}"

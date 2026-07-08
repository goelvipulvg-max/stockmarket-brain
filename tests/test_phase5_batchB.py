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

def test_V5_1_tier0f_poller_dispatches_without_marking(monkeypatch):
    """C-b: mock dispatch, insert 2 test filings, run poller, verify dispatched
    but NOT marked -- claiming moved to the Tier-2F run itself."""
    sb = get_sb()

    # Mock dispatch to avoid real GitHub API call
    dispatch_calls = []
    def fake_dispatch(filing_id):
        dispatch_calls.append(filing_id)
        return True
    monkeypatch.setattr(p_module, '_dispatch_tier2f', fake_dispatch)
    # Change-1 (884947a) set BATCH_LIMIT=1; restore batch capacity so one poller
    # pass can still cover both test rows (limit is read at query-build time).
    monkeypatch.setattr(p_module, 'BATCH_LIMIT', 10)

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

        # Run poller (non-dry-run -- dispatch is mocked; C-b: poller does NO DB write)
        exit_code = tier0f_main(dry_run=False)

        # Verify
        assert exit_code == 0, "Poller should exit 0 on success"
        # All 2 test filings should be dispatched (poller may pick others too if backlog clean)
        assert all(tid in dispatch_calls for tid in test_ids), \
            f"All test filing IDs should be dispatched. Got: {dispatch_calls}"

        # C-b: the poller must NOT consume the filings -- claiming is Tier-2F's job
        check = sb.table('filings_log').select('id, picked_by_tier0f, picked_at')\
            .in_('id', test_ids).execute()
        for row in check.data:
            assert row['picked_by_tier0f'] is False, \
                f"C-b: poller must NOT mark filing {row['id']} -- claiming is Tier-2F's job"
            assert row['picked_at'] is None, \
                f"C-b: poller must NOT set picked_at on filing {row['id']}"

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


# ============================================================
# C-b -- claim moved from poller to Tier-2F (eviction fix; supersedes P2-14)
# ============================================================

def test_Cb_poller_has_no_marking_helpers():
    """Pins the C-b deletion: the poller must not own any marking code."""
    assert not hasattr(p_module, '_mark_picked')
    assert not hasattr(p_module, '_unmark_picked')


def test_Cb_dispatch_failure_leaves_filing_unpicked(monkeypatch):
    """Failed dispatch: exit 1, and the poller touches NO DB in the loop."""
    monkeypatch.setattr(p_module, '_query_pending_filings',
                        lambda: [{'id': 4301, 'symbol': 'CB1'}])
    monkeypatch.setattr(p_module, '_dispatch_tier2f', lambda fid: False)

    class _BoobyTrapSB:
        def table(self, name):
            raise AssertionError("C-b: poller must not touch the DB during dispatch")
    monkeypatch.setattr(p_module, 'get_client', lambda: _BoobyTrapSB())

    exit_code = tier0f_main(dry_run=False)
    assert exit_code == 1, "Poller should report partial failure (exit 1) on dispatch failure"


class _FakeFilingsTable:
    """Serves the load (select) then the claim (update) chain in process_filing."""
    def __init__(self, claim_result):
        self._claim_result = claim_result
        self._mode = None
    def select(self, *_): self._mode = 'select'; return self
    def update(self, _payload): self._mode = 'update'; return self
    def eq(self, *_): return self
    def execute(self):
        class R: pass
        r = R()
        r.data = ([{'id': 4400, 'symbol': 'CBTEST'}] if self._mode == 'select'
                  else self._claim_result)
        return r


class _FakeSB:
    def __init__(self, claim_result): self._t = _FakeFilingsTable(claim_result)
    def table(self, name):
        assert name == 'filings_log'
        return self._t


def test_Cb_tier2f_skips_already_claimed(monkeypatch):
    """Claim matches 0 rows (duplicate dispatch) -> exit before ANY analysis."""
    from agents import tier2_fundamental as t2f
    monkeypatch.setattr(t2f, 'sb', _FakeSB(claim_result=[]))
    monkeypatch.setattr(t2f, 'is_in_ban',
                        lambda s: (_ for _ in ()).throw(AssertionError('analysis ran past a failed claim')))
    result = t2f.process_filing(4400)
    assert result == {'skip': 'already_claimed', 'filing_id': 4400}


def test_Cb_tier2f_claims_then_proceeds(monkeypatch):
    """Successful claim -> pipeline continues (short-circuited at Stage 1)."""
    from agents import tier2_fundamental as t2f
    monkeypatch.setattr(t2f, 'sb', _FakeSB(claim_result=[{'id': 4400}]))
    monkeypatch.setattr(t2f, 'is_in_ban', lambda s: True)
    result = t2f.process_filing(4400)
    assert result == {'skip': 'fno_ban', 'symbol': 'CBTEST'}

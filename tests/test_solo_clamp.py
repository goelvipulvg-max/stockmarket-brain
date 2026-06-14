"""DB-free unit tests for HOTFIX-4 (proper solo path) + HOTFIX-5 (confidence clamp).

Run: .venv\\Scripts\\python.exe tests\\test_solo_clamp.py

Makes NO live API calls — all AI functions, DB clients, and pre-pipeline
gates are mocked. Follows the same import-time dummy-env pattern as
test_close_expired.py and test_force_expire.py.
"""
import os
import sys
import pathlib
import contextlib
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Set dummy env vars BEFORE import so tier2_fundamental's module-level
# REQUIRED_ENVS check + load_dotenv + sb = get_client() don't crash.
# ---------------------------------------------------------------------------
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ["ANTHROPIC_API_KEY"] = "dummy"
os.environ["DEEPSEEK_API_KEY"] = "dummy"
os.environ["NEON_CONNECTION_STRING"] = "postgresql://dummy"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy"
os.environ["TELEGRAM_TIER3_CHANNEL"] = "dummy"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.tier2_fundamental as t2f

# ---------------------------------------------------------------------------
# Reusable factories
# ---------------------------------------------------------------------------

_MOCK_FILING = {
    "id": 1, "symbol": "TEST", "event_type": "RESULTS",
}

_MOCK_FUNDAMENTALS = {
    "sector": "Pharma", "market_cap_cr": 5000,
    "business_summary": "Test pharma company",
}

_STOCK_CHART = {    # returned when get_chart_snapshot("TEST.NS") is called
    "last_close": 1000.0, "rsi_14": 55, "macd": 1.2,
    "macd_signal": 0.8, "macd_hist": 0.4, "trend": "UPTREND",
    "sma_50": 950.0, "sma_200": 900.0, "support": 920.0,
    "resistance": 1080.0,
}

_NIFTY_CHART = {    # returned when get_chart_snapshot("^NSEI") is called
    "last_close": 23000.0, "rsi_14": 58, "macd": 10.0,
    "macd_signal": 8.0, "macd_hist": 2.0, "trend": "UPTREND",
    "sma_50": 22800.0, "sma_200": 22000.0, "support": 22500.0,
    "resistance": 23500.0,
}

_MOCK_PRICE_STRUCTURE = {
    "above_sma50": True, "pct_from_52wk_high": -15.0,
    "rs_vs_nifty_63d": 0.03,
}

_MOCK_PRICE_GATE = {"passes": True, "reasons": []}

_MOCK_VOL_STRUCTURE = {
    "vol_vs_avg_ratio": 1.2, "avg_volume_20d": 500000,
    "volume_spike": False,
}

_MOCK_VOL_GATE = {"passes": True, "reasons": []}


def _chart_side_effect(symbol):
    """Return stock chart for TEST.NS, NIFTY chart for ^NSEI."""
    if symbol == "^NSEI":
        return dict(_NIFTY_CHART)
    return dict(_STOCK_CHART)


class _FakeQuery:
    """Mimics a Supabase query builder — returns controlled rows from .execute().data."""
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeSupabase:
    """Returns _FakeQuery from .table()."""
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _FakeQuery(self._rows)


def _make_analyst(tradeable=True, bias="BULLISH", confidence=72,
                  stop_loss_pct=5.0, target_pct=8.0, horizon="MEDIUM",
                  expected_move_pct=None, reasoning="analyst output"):
    """Factory for valid analyst-format output (Haiku or DeepSeek-as-analyst)."""
    out = {
        "tradeable": tradeable,
        "directional_bias": bias,
        "confidence": confidence,
        "stop_loss_pct": stop_loss_pct,
        "target_pct": target_pct,
        "horizon": horizon,
        "reasoning": reasoning,
    }
    if expected_move_pct is not None:
        out["expected_move_pct"] = expected_move_pct
    return out


def _make_verifier(verdict="CONFIRM", agreement_score=80, bias="BULLISH",
                   confidence=70, stop_loss_pct=4.5, target_pct=7.0,
                   reasoning="verifier agrees"):
    """Factory for valid verifier-format output (DeepSeek as verifier)."""
    return {
        "verdict": verdict,
        "agreement_score": agreement_score,
        "my_directional_bias": bias,
        "my_confidence": confidence,
        "my_stop_loss_pct": stop_loss_pct,
        "my_target_pct": target_pct,
        "reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# Context manager: mock the full pipeline for DB-free testing.
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _mock_pipeline(**overrides):
    """Temporarily mock all tier2_fundamental module attributes needed for
    a DB-free process_filing() call. Override specific attributes via kwargs.

    Usage:
        with _mock_pipeline(run_analyst=..., run_verifier=...):
            result = t2f.process_filing(1, dry_run=True)
    """
    defaults = {
        "sb": _FakeSupabase([dict(_MOCK_FILING)]),
        "is_in_ban": MagicMock(return_value=False),
        "check_liquidity": MagicMock(return_value=(True, 50_00_00_000)),
        "get_fundamentals": MagicMock(return_value=dict(_MOCK_FUNDAMENTALS)),
        "get_chart_snapshot": MagicMock(side_effect=_chart_side_effect),
        "compute_price_structure": MagicMock(return_value=dict(_MOCK_PRICE_STRUCTURE)),
        "validate_price_structure": MagicMock(return_value=dict(_MOCK_PRICE_GATE)),
        "compute_volume_structure": MagicMock(return_value=dict(_MOCK_VOL_STRUCTURE)),
        "validate_volume_structure": MagicMock(return_value=dict(_MOCK_VOL_GATE)),
        "get_relevant_patterns": MagicMock(return_value=[]),
        "get_filing_memory_brief": MagicMock(return_value=""),
        "_tg_send": MagicMock(return_value=None),
        # AI functions — overrides supply the test-specific behaviour.
        # Safe defaults below prevent live API calls if an override is missed.
        "run_analyst": MagicMock(return_value=_make_analyst()),
        "run_verifier": MagicMock(return_value=_make_verifier()),
        "_run_deepseek_as_analyst": MagicMock(
            return_value=_make_analyst(confidence=78)),
    }
    defaults.update(overrides)
    patch_managers = [patch.object(t2f, name, val) for name, val in defaults.items()]
    with contextlib.ExitStack() as stack:
        for mgr in patch_managers:
            stack.enter_context(mgr)
        yield


# ---------------------------------------------------------------------------
# HOTFIX-4: Solo path structural tests
# ---------------------------------------------------------------------------

def test_consensus_path_happy():
    """Both models up → consensus path, no fallback_mode."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=75)),
        run_verifier=MagicMock(return_value=_make_verifier(confidence=73)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["avg_conf"] == 74              # (75+73)/2, no haircut
    assert trade["fallback_mode"] is None
    assert trade["conviction"] == "MEDIUM"
    print("  ok: consensus_path_happy")


def test_solo_deepseek_path():
    """Haiku raises → DeepSeek-as-analyst succeeds → SOLO_DEEPSEEK, 0.9x haircut."""
    with _mock_pipeline(
        run_analyst=MagicMock(side_effect=RuntimeError("Anthropic down")),
        _run_deepseek_as_analyst=MagicMock(
            return_value=_make_analyst(confidence=78)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["fallback_mode"] == "SOLO_DEEPSEEK"
    assert trade["avg_conf"] == 70              # int(78 * 0.9) = 70, in [50,85]
    assert trade["conviction"] == "MEDIUM"       # 70 >= 65, < 80
    assert trade["direction"] == "BUY"           # from analyst key 'directional_bias'
    print("  ok: solo_deepseek_path")


def test_solo_haiku_path():
    """Haiku succeeds, DeepSeek verifier raises → SOLO_HAIKU, 0.9x haircut."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=80)),
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["fallback_mode"] == "SOLO_HAIKU"
    assert trade["avg_conf"] == 72              # int(80 * 0.9) = 72
    assert trade["conviction"] == "MEDIUM"
    print("  ok: solo_haiku_path")


def test_both_down_skip():
    """Both Haiku AND DeepSeek-as-analyst raise → 'both_apis_down' skip."""
    with _mock_pipeline(
        run_analyst=MagicMock(side_effect=RuntimeError("Anthropic down")),
        _run_deepseek_as_analyst=MagicMock(
            side_effect=RuntimeError("DeepSeek also down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result.get("skip") == "both_apis_down"
    print("  ok: both_down_skip")


def test_solo_below_confidence_floor_skips():
    """Solo path: haircut lands below 65 → SKIP with exact reason."""
    with _mock_pipeline(
        run_analyst=MagicMock(
            return_value=_make_analyst(tradeable=True, confidence=70)),
        # int(70*0.9)=63 < 65 → SKIP
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result.get("skip") == "Solo SOLO_HAIKU — confidence 63 < 65"
    print("  ok: solo_below_confidence_floor_skips")


def test_solo_not_tradeable_skips():
    """Solo path: analyst says not tradeable → 'haiku_not_tradeable' skip."""
    with _mock_pipeline(
        run_analyst=MagicMock(side_effect=RuntimeError("Anthropic down")),
        _run_deepseek_as_analyst=MagicMock(
            return_value=_make_analyst(tradeable=False, confidence=90)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result.get("skip") == "haiku_not_tradeable"
    print("  ok: solo_not_tradeable_skips")


def test_solo_missing_confidence_skips():
    """Solo path: analyst output has no 'confidence' key → SKIP with safe reason."""
    bad_output = _make_analyst(confidence=72)
    del bad_output["confidence"]   # remove key entirely
    with _mock_pipeline(
        run_analyst=MagicMock(side_effect=RuntimeError("Anthropic down")),
        _run_deepseek_as_analyst=MagicMock(return_value=bad_output),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result.get("skip") == "Solo — missing or invalid confidence field"
    print("  ok: solo_missing_confidence_skips")


# ---------------------------------------------------------------------------
# HOTFIX-5: Confidence clamp tests
# ---------------------------------------------------------------------------

def test_clamp_ceiling_consensus():
    """Consensus: avg_conf 95 → clamped to 85 → conviction HIGH."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=95)),
        run_verifier=MagicMock(return_value=_make_verifier(confidence=95)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["avg_conf"] == 85              # (95+95)/2 = 95, clamped to 85
    assert trade["conviction"] == "HIGH"
    print("  ok: clamp_ceiling_consensus")


def test_clamp_ceiling_solo():
    """Solo: model confidence 98 → 0.9x=88 → clamped to 85 → conviction HIGH."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=98)),
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["avg_conf"] == 85              # int(98*0.9)=88, clamped to 85
    assert trade["conviction"] == "HIGH"
    print("  ok: clamp_ceiling_solo")


def test_clamp_floor_consensus_blocked_by_gate():
    """Consensus: avg_conf 35 → blocked by determine_consensus (not the clamp).

    The clamp floor (50) is defense-in-depth below the primary 65 PROCEED gate.
    determine_consensus rejects avg_conf < 65 before the clamp ever runs.
    """
    with _mock_pipeline(
        run_analyst=MagicMock(
            return_value=_make_analyst(tradeable=True, confidence=35)),
        run_verifier=MagicMock(return_value=_make_verifier(confidence=35)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    # determine_consensus returns ("SKIP", "Avg confidence 35.0 < 65")
    assert result.get("skip") is not None
    assert "Avg confidence" in result.get("skip", "")
    assert "35" in result.get("skip", "")
    assert "65" in result.get("skip", "")
    print("  ok: clamp_floor_consensus_blocked_by_gate")


def test_clamp_floor_solo_blocked_by_gate():
    """Solo: conf=40 → haircut=36 → blocked at PROCEED gate (36 < 65).

    The clamp floor (50) is defense-in-depth; the primary 65 gate blocks first.
    """
    with _mock_pipeline(
        run_analyst=MagicMock(
            return_value=_make_analyst(tradeable=True, confidence=40)),
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    # Solo gate: haircut 36 < 65 → SKIP
    assert result.get("skip") == "Solo SOLO_HAIKU — confidence 36 < 65"
    print("  ok: clamp_floor_solo_blocked_by_gate")


def test_in_band_unchanged_consensus():
    """Confidence 72/70 in-band → unchanged after clamp → MEDIUM."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=72)),
        run_verifier=MagicMock(return_value=_make_verifier(confidence=70)),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["avg_conf"] == 71              # (72+70)/2 = 71, in [50,85]
    assert trade["conviction"] == "MEDIUM"
    print("  ok: in_band_unchanged_consensus")


def test_in_band_unchanged_solo():
    """Solo: confidence 75 → 0.9x = 67 → in [50,85] → MEDIUM."""
    with _mock_pipeline(
        run_analyst=MagicMock(return_value=_make_analyst(confidence=75)),
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["avg_conf"] == 67              # int(75*0.9) = 67, unchanged
    assert trade["conviction"] == "MEDIUM"
    print("  ok: in_band_unchanged_solo")


# ---------------------------------------------------------------------------
# Key-schema safety: solo paths never touch verifier keys
# ---------------------------------------------------------------------------

def test_solo_deepseek_direction_bias_from_analyst_key():
    """SOLO_DEEPSEEK reads 'directional_bias' (analyst key), not 'my_directional_bias'."""
    analyst_out = _make_analyst(bias="BEARISH", confidence=78)
    # Verify analyst format does NOT have verifier keys
    assert "my_directional_bias" not in analyst_out
    assert "my_confidence" not in analyst_out

    with _mock_pipeline(
        run_analyst=MagicMock(side_effect=RuntimeError("Anthropic down")),
        _run_deepseek_as_analyst=MagicMock(return_value=analyst_out),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["direction"] == "SELL"          # from analyst key 'directional_bias'
    assert trade["fallback_mode"] == "SOLO_DEEPSEEK"
    print("  ok: solo_deepseek_direction_bias_from_analyst_key")


def test_solo_haiku_direction_bias_from_analyst_key():
    """SOLO_HAIKU reads 'directional_bias' (analyst key), not 'my_directional_bias'."""
    with _mock_pipeline(
        run_analyst=MagicMock(
            return_value=_make_analyst(bias="BULLISH", confidence=82)),
        run_verifier=MagicMock(side_effect=RuntimeError("DeepSeek down")),
    ):
        result = t2f.process_filing(1, dry_run=True)

    assert result["dry_run"] is True
    trade = result["would_trade"]
    assert trade["direction"] == "BUY"           # from analyst key 'directional_bias'
    assert trade["fallback_mode"] == "SOLO_HAIKU"
    print("  ok: solo_haiku_direction_bias_from_analyst_key")


if __name__ == "__main__":
    # Run all tests manually (no pytest dependency needed for basic assert suite)
    import traceback

    tests = [
        # HOTFIX-4: solo path structure
        test_consensus_path_happy,
        test_solo_deepseek_path,
        test_solo_haiku_path,
        test_both_down_skip,
        test_solo_below_confidence_floor_skips,
        test_solo_not_tradeable_skips,
        test_solo_missing_confidence_skips,
        # HOTFIX-5: confidence clamp
        test_clamp_ceiling_consensus,
        test_clamp_ceiling_solo,
        test_clamp_floor_consensus_blocked_by_gate,
        test_clamp_floor_solo_blocked_by_gate,
        test_in_band_unchanged_consensus,
        test_in_band_unchanged_solo,
        # Key-schema safety
        test_solo_deepseek_direction_bias_from_analyst_key,
        test_solo_haiku_direction_bias_from_analyst_key,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {test_fn.__name__} — {e}")
        except Exception:
            failed += 1
            print(f"ERROR: {test_fn.__name__}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        sys.exit(1)

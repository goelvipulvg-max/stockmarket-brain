"""DB-free unit tests for the G-1 two_source_gate fix (Batch D Session 3).

Run: .venv\\Scripts\\python.exe tests\\test_guardian_gate.py
 or: .venv\\Scripts\\python.exe -m pytest tests\\test_guardian_gate.py -v

two_source_gate is pure (no I/O). The module builds clients at import, so
dummy env goes first (mirrors test_money_seam_guards.py); no client is ever
queried here. Makes NO live calls.
"""
import os
import pathlib
import sys

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agents.tier1_guardian as tg                # noqa: E402


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


def _news(*sources):
    return [{"source": s, "title": "t"} for s in sources]


def _filing(score):
    return {"id": 1, "event_type": "X", "summary": "s", "material_score": score}


def test_solo_catastrophic_filing_passes():
    for score in (8, 9, 10):
        passes, count = tg.two_source_gate([], [_filing(score)])
        check(f"solo filing score {score} passes", passes, True)
        check(f"solo filing score {score} reports 1 source", count, 1)


def test_solo_material_but_not_catastrophic_fails():
    for score in (7, 6, 5):
        passes, _ = tg.two_source_gate([], [_filing(score)])
        check(f"solo filing score {score} still gated", passes, False)


def test_missing_or_zero_score_never_bypasses():
    for score in (None, 0):
        passes, _ = tg.two_source_gate([], [_filing(score)])
        check(f"solo filing score {score!r} still gated (fail-safe)", passes, False)


def test_news_corroboration_unchanged():
    passes, count = tg.two_source_gate(_news("ET", "Mint"), [])
    check("2 news outlets pass", passes, True)
    check("2 news outlets counted", count, 2)
    passes, _ = tg.two_source_gate(_news("ET"), [])
    check("1 news outlet gated", passes, False)
    passes, _ = tg.two_source_gate([], [])
    check("nothing at all gated", passes, False)


def test_low_filing_plus_one_outlet_still_two_sources():
    passes, count = tg.two_source_gate(_news("ET"), [_filing(3)])
    check("1 outlet + low filing pass (2 distinct)", passes, True)
    check("counted as 2 sources", count, 2)


def test_catastrophic_among_low_filings_passes():
    passes, count = tg.two_source_gate([], [_filing(2), _filing(8), _filing(5)])
    check("any catastrophic filing in the batch passes", passes, True)
    check("still 1 collapsed filing source", count, 1)


def test_threshold_constants():
    check("catastrophic threshold is 8", tg.CATASTROPHIC_FILING_SCORE, 8)
    check("news corroboration still 2", tg.MIN_SOURCES_REQUIRED, 2)


if __name__ == "__main__":
    for fn in [test_solo_catastrophic_filing_passes,
               test_solo_material_but_not_catastrophic_fails,
               test_missing_or_zero_score_never_bypasses,
               test_news_corroboration_unchanged,
               test_low_filing_plus_one_outlet_still_two_sources,
               test_catastrophic_among_low_filings_passes,
               test_threshold_constants]:
        print(f"\n{fn.__name__}:")
        fn()
    print("\nALL TESTS PASSED")

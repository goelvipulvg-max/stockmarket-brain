# Spec: Tier-2 sys.path CI Fix
**Date:** 2026-05-06
**Phase:** 3.5 Part 1 — post-ship bug fix
**Status:** Approved — reviewed 2026-05-06

---

## Problem

`agents/tier2_signals.py` has no `sys.path` fix at the top. When GitHub Actions CI runs:

```
python agents/tier2_signals.py
```

Python sets `sys.path[0]` to the script's directory (`<root>/agents/`), not the project root. Line 12:

```python
from utils import questdb_client
```

fails immediately with:

```
ModuleNotFoundError: No module named 'utils'
```

This crashes the ENTIRE script on import — not just QuestDB writes. Supabase logging, Telegram signals, and Claude Haiku analysis ALL fail silently in every scheduled CI run since Phase 3.5 Part 1 shipped (commits `ad9b0b7`, `325aecc`).

The bug was not caught locally because manual runs from the project root use `python -m` or IDE runners that add the project root to `sys.path` before script invocation.

---

## Root Cause

Python's script-mode execution (`python path/to/script.py`) sets `sys.path[0]` to the **directory containing the script file**, not the working directory. `tier2_signals.py` lives in `agents/`; `utils/` lives at the project root. Without an explicit `sys.path.insert(0, project_root)`, the import fails.

`tier1_news.py` had the same bug and was fixed in this session's Phase 3.5 Part 2 work (line 7 of that file).

---

## Scope

**In:** Add `sys.path.insert(0, project_root)` to `agents/tier2_signals.py` before the `from utils` import.

**Out:** Any changes to `.github/workflows/tier2_signals.yml` (already uses `pip install -r requirements.txt`), `utils/questdb_client.py`, `requirements.txt`, Supabase logic, or Telegram logic.

---

## Fix

Add two lines after `import os` in `tier2_signals.py`, before `from utils import questdb_client`:

```python
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` resolves:
- `__file__` → `.../agents/tier2_signals.py`
- `os.path.abspath(...)` → absolute path to script
- inner `dirname` → `.../agents/`
- outer `dirname` → `.../stockmarket-brain/`  ← project root

Identical pattern to `agents/tier1_news.py:7`.

---

## Post-Fix CI Behaviour

After the fix:
- Import succeeds
- `main()` runs all 10 WATCHLIST tickers
- Supabase `paper_trades` write works (uses secrets from CI env)
- QuestDB write attempts `localhost:8812` — fails with `connection refused` — **caught by `try/except` in `log_signal_questdb`** — non-fatal, prints warning, continues
- Telegram posting works (uses secrets from CI env)

QuestDB will not receive data from CI runs (no QuestDB in GitHub Actions). This is expected and acceptable — QuestDB is a local analytics layer, not a production system. CI success = Supabase + Telegram working.

---

## Testing Strategy

Add 1 new test to `tests/test_tier2_questdb_write.py`:

| # | Test | What it asserts |
|---|---|---|
| 6 | `test_script_importable_when_run_directly` | Subprocess runs `python agents/tier2_signals.py` from project root; `stderr` must NOT contain `"No module named 'utils'"`. RED before fix, GREEN after. |

Existing 5 tests remain unchanged and must stay green.

**Why subprocess?** The existing tests call `sys.path.insert` themselves (line 11 of test file), so they already work regardless of the fix. A subprocess test with no `PYTHONPATH` set is the only way to replicate the actual CI failure condition and prove the fix works.

---

## Files Changed

| File | Change |
|---|---|
| `agents/tier2_signals.py` | Add `import sys` + `sys.path.insert(0, ...)` after `import os`, before `from utils import questdb_client` |
| `tests/test_tier2_questdb_write.py` | Add 1 subprocess test (test #6) |

No other files change.

---

## CI Verification

After merge to main, trigger a manual `workflow_dispatch` run on `tier2_signals.yml` from the GitHub Actions tab. Confirm in the run log:

1. No `ModuleNotFoundError` in output
2. At least one ticker line: `RELIANCE.NS: BUY|SELL|HOLD | Confidence: N`
3. `QuestDB write failed (non-fatal)` expected — acceptable, not a regression
4. Supabase: `-> Paper trade logged` appears for BUY/SELL tickers

Local QuestDB verification is NOT required for this fix — QuestDB writes were never working in CI and will continue to fail gracefully. The fix restores Supabase + Telegram, which are the production-critical paths.

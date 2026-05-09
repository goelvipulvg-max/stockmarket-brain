# Tier-2 sys.path CI Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `ModuleNotFoundError: No module named 'utils'` that crashes every scheduled CI run of `tier2_signals.py` by adding the same two-line sys.path fix already present in `tier1_news.py`.

**Architecture:** Add `sys.path.insert(0, project_root)` at the top of `tier2_signals.py` before the `from utils` import. Write a subprocess-based RED test first to reproduce the CI failure condition, then apply the fix.

**Tech Stack:** Python 3.12, pytest, subprocess (stdlib), `.venv/Scripts/python.exe`

---

### Task 1: Write the failing test (RED)

**Files:**
- Modify: `tests/test_tier2_questdb_write.py`

- [ ] **Step 1: Open the test file and read the current imports**

Read `tests/test_tier2_questdb_write.py`. Note: it already has `import sys` and `import os` at the top (lines 1-2). The new test goes at the bottom of the file.

- [ ] **Step 2: Append the subprocess test to `tests/test_tier2_questdb_write.py`**

Add this function at the end of `tests/test_tier2_questdb_write.py`:

```python
def test_script_importable_when_run_directly():
    """python agents/tier2_signals.py must not crash with ModuleNotFoundError (simulates CI)."""
    import subprocess
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    result = subprocess.run(
        [sys.executable, "agents/tier2_signals.py"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env={
            **{k: os.environ[k] for k in ("PATH",) if k in os.environ},
            **{k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP") if k in os.environ},
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
            "ANTHROPIC_API_KEY": "test-key",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_SWING_CHANNEL": "",
        },
    )
    assert "No module named 'utils'" not in result.stderr, (
        f"sys.path bug: script crashed with ModuleNotFoundError — fix not yet applied.\n"
        f"stderr:\n{result.stderr[:500]}"
    )
```

- [ ] **Step 3: Run the new test to confirm it fails (RED)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tier2_questdb_write.py::test_script_importable_when_run_directly -v`

Expected output:
```
FAILED tests/test_tier2_questdb_write.py::test_script_importable_when_run_directly
AssertionError: sys.path bug: script crashed with ModuleNotFoundError
stderr:
Traceback (most recent call last):
  ...
ModuleNotFoundError: No module named 'utils'
```

If the test PASSES here, stop — the bug may not be reproducible in this environment. Investigate `sys.path` before proceeding.

- [ ] **Step 4: Confirm existing 5 tests still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tier2_questdb_write.py -v -k "not test_script_importable"`

Expected: `5 passed`

---

### Task 2: Implement the sys.path fix (GREEN)

**Files:**
- Modify: `agents/tier2_signals.py:1-12`

- [ ] **Step 5: Open `agents/tier2_signals.py` and locate lines 1-12**

Current state:
```python
import os
import json
import pandas as pd
import pandas_ta as ta
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(override=True)
from curl_cffi import requests as curl_requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from utils import questdb_client
```

- [ ] **Step 6: Add `import sys` and `sys.path.insert` after `import os`**

Change lines 1-2 to:
```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
```

The full top of the file after the edit:
```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import pandas as pd
import pandas_ta as ta
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(override=True)
from curl_cffi import requests as curl_requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from utils import questdb_client
```

- [ ] **Step 7: Run the new test to confirm it passes (GREEN)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tier2_questdb_write.py::test_script_importable_when_run_directly -v`

Expected:
```
PASSED tests/test_tier2_questdb_write.py::test_script_importable_when_run_directly
```

Note: the script may still fail for other reasons (Yahoo Finance, Anthropic API with `test-key`) but the assertion only checks for `ModuleNotFoundError` — those other failures are acceptable.

- [ ] **Step 8: Run the full test suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tier2_questdb_write.py -v`

Expected:
```
tests/test_tier2_questdb_write.py::test_buy_signal_inserts_correct_row PASSED
tests/test_tier2_questdb_write.py::test_ts_is_midnight_utc PASSED
tests/test_tier2_questdb_write.py::test_signal_id_contains_ticker_and_date PASSED
tests/test_tier2_questdb_write.py::test_ts_and_signal_id_share_same_date PASSED
tests/test_tier2_questdb_write.py::test_questdb_failure_does_not_raise PASSED
tests/test_tier2_questdb_write.py::test_script_importable_when_run_directly PASSED
6 passed
```

- [ ] **Step 9: Run the full project test suite to confirm no cross-file regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`

Expected: all tests pass (includes `test_news_questdb_write.py` 7 tests + `test_tier2_questdb_write.py` 6 tests = 13 total).

---

### Task 3: Commit

**Files:**
- Modified: `agents/tier2_signals.py`
- Modified: `tests/test_tier2_questdb_write.py`

- [ ] **Step 10: Stage and commit**

```bash
git add agents/tier2_signals.py tests/test_tier2_questdb_write.py
git commit -m "fix(tier2): add sys.path fix so utils/ is found when run directly or via CI"
```

- [ ] **Step 11: Push to main**

```bash
git push origin main
```

---

### Task 4: CI Verification

- [ ] **Step 12: Trigger a manual workflow run**

Go to: GitHub → Actions tab → "Tier-2 Swing Signals" workflow → "Run workflow" button → Run on `main`.

- [ ] **Step 13: Confirm the run log shows no ModuleNotFoundError**

In the "Run Tier-2 Signal Agent" step output, verify:
1. No line containing `ModuleNotFoundError: No module named 'utils'`
2. Output contains ticker lines like `RELIANCE.NS: BUY | Confidence: 8`
3. Output may contain `QuestDB write failed (non-fatal): OperationalError: ...` — this is expected and acceptable (no QuestDB in CI)
4. Output contains `-> Paper trade logged` for any BUY/SELL tickers

If the run still fails with ModuleNotFoundError: confirm the push landed (check GitHub commits), then re-trigger.

---

## Self-Review

**Spec coverage check:**
- ✅ Root cause (ModuleNotFoundError in CI) → Task 2 Step 6 adds the fix
- ✅ RED test to reproduce CI failure → Task 1 Steps 2-3
- ✅ All 5 existing tests stay green → Task 2 Steps 8-9
- ✅ Commit → Task 3
- ✅ CI manual verification → Task 4

**Placeholder scan:** None found — all steps contain exact code or exact commands.

**Type consistency:** No function signatures changed — fix is purely `sys.path` manipulation.

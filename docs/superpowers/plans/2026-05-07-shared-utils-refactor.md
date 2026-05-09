# Shared Utils Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract copy-pasted Supabase init and Telegram send logic into `utils/supabase_client.py` and `utils/telegram_client.py`, then update all 5 agent files to import from utils.

**Architecture:** Two thin utility modules, each with one exported function. Agents keep all domain logic (message formatting, table names, error handling strategy); utils only provide the shared infrastructure primitives. Pattern mirrors `utils/questdb_client.py`.

**Tech Stack:** Python 3.12, supabase-py 2.7+, requests, python-dotenv, pytest

---

## File Map

**Create:**
- `utils/supabase_client.py` — `get_client() -> Client`
- `utils/telegram_client.py` — `send_message(bot_token, chat_id, text, parse_mode)`
- `tests/test_supabase_client.py` — 3 unit tests
- `tests/test_telegram_client.py` — 4 unit tests

**Modify:**
- `agents/tier0_filings.py` — remove ANON_KEY + urllib Telegram, import utils
- `agents/tier1_news.py` — remove supabase init + requests Telegram HTTP block, import utils
- `agents/tier2_signals.py` — remove conditional supabase init + local send_telegram, import utils
- `agents/update_paper_trades.py` — remove supabase init + fatal-exit block, import utils
- `agents/upstox_paper_trade.py` — remove supabase init inside main() + fatal-exit block, import utils

**Do NOT touch:**
- `utils/questdb_client.py` (structure template only)
- `utils/__init__.py` (stays empty)
- `requirements.txt` (supabase + requests already present)
- `tests/test_tier2_questdb_write.py`, `tests/test_news_questdb_write.py` (run but don't modify)

---

## Task 1: Create `utils/supabase_client.py` (TDD)

**Files:**
- Create: `tests/test_supabase_client.py`
- Create: `utils/supabase_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supabase_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_get_client_raises_if_url_empty(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    from utils.supabase_client import get_client
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        get_client()


def test_get_client_raises_if_key_empty(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from utils.supabase_client import get_client
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        get_client()


def test_get_client_calls_create_client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    mock_client = MagicMock()
    with patch("utils.supabase_client.create_client", return_value=mock_client) as m:
        from utils.supabase_client import get_client
        result = get_client()
    assert result is mock_client
    m.assert_called_once_with("https://test.supabase.co", "test-key")
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_supabase_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'utils.supabase_client'`

- [ ] **Step 3: Write the implementation**

Create `utils/supabase_client.py`:

```python
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(override=True)


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url:
        raise ValueError("SUPABASE_URL missing from env")
    if not key:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY missing from env")
    return create_client(url, key)


if __name__ == "__main__":
    c = get_client()
    print(f"Supabase client OK: {type(c).__name__}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest tests/test_supabase_client.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```
git add utils/supabase_client.py tests/test_supabase_client.py
git commit -m "feat(utils): add supabase_client.py with get_client() factory"
```

---

## Task 2: Create `utils/telegram_client.py` (TDD)

**Files:**
- Create: `tests/test_telegram_client.py`
- Create: `utils/telegram_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telegram_client.py`:

```python
from unittest.mock import patch, MagicMock


def test_send_message_skips_if_no_token(capsys):
    from utils.telegram_client import send_message
    send_message("", "chat123", "hello")
    assert "missing" in capsys.readouterr().out


def test_send_message_skips_if_no_chat_id(capsys):
    from utils.telegram_client import send_message
    send_message("bot-token", "", "hello")
    assert "missing" in capsys.readouterr().out


def test_send_message_posts_correct_payload():
    mock_resp = MagicMock()
    mock_resp.ok = True
    with patch("utils.telegram_client.requests.post", return_value=mock_resp) as mock_post:
        from utils.telegram_client import send_message
        send_message("mytoken", "mychat", "hello", parse_mode="HTML")
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botmytoken/sendMessage",
        json={"chat_id": "mychat", "text": "hello", "parse_mode": "HTML"},
        timeout=10,
    )


def test_send_message_prints_warning_on_http_error(capsys):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.text = "Bad Request"
    with patch("utils.telegram_client.requests.post", return_value=mock_resp):
        from utils.telegram_client import send_message
        send_message("tok", "chat", "msg")
    assert "Telegram error" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_telegram_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'utils.telegram_client'`

- [ ] **Step 3: Write the implementation**

Create `utils/telegram_client.py`:

```python
import requests


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> None:
    if not bot_token or not chat_id:
        print("  Telegram config missing -- skipping")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    if not r.ok:
        print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")


if __name__ == "__main__":
    print("Import OK")
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest tests/test_telegram_client.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```
git add utils/telegram_client.py tests/test_telegram_client.py
git commit -m "feat(utils): add telegram_client.py with send_message() sender"
```

---

## Task 3: Refactor `agents/tier0_filings.py`

**Context:** tier0 is the most different file — it uses `SUPABASE_ANON_KEY` (not SERVICE_ROLE_KEY) and `urllib.request` for Telegram (not `requests`). Both change here.

**Files:**
- Modify: `agents/tier0_filings.py`

- [ ] **Step 1: Run existing full test suite to establish baseline**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all tests pass (record count for comparison after refactor).

- [ ] **Step 2: Apply changes to tier0_filings.py**

**Line 1** — remove `urllib.parse` (only used by the Telegram function being deleted; `urllib.request` stays for NSE fetch):

```python
import json, urllib.request
```

**Lines 2-3** — add utils imports, remove supabase direct import:

```python
import anthropic
from utils.supabase_client import get_client
from utils.telegram_client import send_message
```

**Line 14** — change client init (removes ANON_KEY usage):

```python
sb  = get_client()
```

**Lines 69-76** — delete the entire `send_telegram` function:

```python
# DELETE this entire function:
# def send_telegram(chat_id, text):
#     data = urllib.parse.urlencode({...}).encode()
#     with urllib.request.urlopen(...) as r:
#         return json.loads(r.read())
```

**Line 125** — update the call site (was `send_telegram(MOVERS_CHANNEL, msg)`):

```python
                send_message(BOT, MOVERS_CHANNEL, msg)
```

- [ ] **Step 3: Verify tier0 import loads without error**

```
.venv/Scripts/python.exe -c "import agents.tier0_filings; print('tier0 import OK')"
```

Expected: `tier0 import OK` — confirms urllib.parse is gone and requests-based send_message loads.

- [ ] **Step 4: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: same count as baseline, all pass.

- [ ] **Step 5: Commit**

```
git add agents/tier0_filings.py
git commit -m "refactor(tier0): use shared supabase_client + telegram_client utils"
```

---

## Task 4: Refactor `agents/tier1_news.py`

**Context:** tier1 uses `requests` for Telegram but only in `send_telegram()`. After refactor, the `requests` import is no longer needed in tier1 (telegram_client carries it). The domain-specific formatting inside `send_telegram()` stays; only the HTTP call is replaced.

**Note:** tier1's send_telegram previously passed `disable_web_page_preview: True` to the Telegram API. `send_message()` does not support this param. After refactor, link previews will appear in MOVERS channel messages. This is cosmetic only.

**Files:**
- Modify: `agents/tier1_news.py`

- [ ] **Step 1: Apply changes to tier1_news.py**

**Line 12** — remove `import requests` (no longer needed after Telegram extraction):

```python
# DELETE: import requests
```

**Line 15** — replace direct import:

```python
from utils.supabase_client import get_client
```

**Lines 25-26** — delete module-level Supabase config vars:

```python
# DELETE: SUPABASE_URL = os.getenv("SUPABASE_URL")
# DELETE: SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
```

**Line 33** — replace `create_client(...)` with util:

```python
supabase = get_client()
```

**Lines 134-154** — replace the `send_telegram` function body. Keep the formatting logic; replace only the `requests.post(...)` block and the `if not r.ok:` check:

```python
def send_telegram(source, title, url, score, category, summary):
    emoji = EMOJI.get(category, "⚪")
    text = (
        f"{emoji} *{category.upper()}* | Score: {score}/10\n"
        f"*{title}*\n\n"
        f"_{summary}_\n\n"
        f"📰 {source}\n"
        f"🔗 [Read More]({url})"
    )
    from utils.telegram_client import send_message
    send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_MOVERS_CHAT, text, parse_mode="Markdown")
```

(The `from utils.telegram_client import send_message` import can move to the top of the file with the other utils imports — either location works.)

- [ ] **Step 2: Add `from utils.telegram_client import send_message` to top-of-file imports**

After the `from utils.supabase_client import get_client` line, add:

```python
from utils.telegram_client import send_message
```

Then remove the inline import from inside `send_telegram()` and use `send_message(...)` directly.

- [ ] **Step 3: Verify tier1 import loads without error**

```
.venv/Scripts/python.exe -c "import agents.tier1_news; print('tier1 import OK')"
```

Expected: `tier1 import OK`

- [ ] **Step 4: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add agents/tier1_news.py
git commit -m "refactor(tier1): use shared supabase_client + telegram_client utils"
```

---

## Task 5: Refactor `agents/tier2_signals.py`

**Context:** tier2 has a conditional Supabase init (`None` if creds missing). The `try/except ValueError` pattern in `get_client()` preserves this. Existing tests set `SUPABASE_URL=""` at import time, which will trigger the ValueError → `supabase = None` path — same behavior as before.

**Files:**
- Modify: `agents/tier2_signals.py`

- [ ] **Step 1: Apply changes to tier2_signals.py**

**Line 13** — replace direct supabase import:

```python
from utils.supabase_client import get_client
from utils.telegram_client import send_message as tg_send
```

**Lines 26-32** — replace conditional Supabase init block:

```python
# DELETE:
# SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
# SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
# supabase: Client | None = (
#     create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
#     if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None
# )

# REPLACE WITH:
try:
    supabase = get_client()
except ValueError:
    supabase = None
```

**Lines 124-130** — delete the entire `send_telegram` function:

```python
# DELETE:
# def send_telegram(message):
#     if not TELEGRAM_BOT_TOKEN or not TELEGRAM_SWING_CHANNEL:
#         ...
#     r = requests.post(...)
#     r.raise_for_status()
```

**All call sites of `send_telegram(msg)`** (search with `grep -n "send_telegram" agents/tier2_signals.py`):

Replace each `send_telegram(msg)` with:

```python
tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_SWING_CHANNEL, msg)
```

- [ ] **Step 2: Verify import and existing tests**

```
.venv/Scripts/python.exe -c "import agents.tier2_signals; print('tier2 import OK')"
.venv/Scripts/python.exe -m pytest tests/test_tier2_questdb_write.py -v
```

Expected: `tier2 import OK`, all tier2 tests pass.

- [ ] **Step 3: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add agents/tier2_signals.py
git commit -m "refactor(tier2): use shared supabase_client + telegram_client utils"
```

---

## Task 6: Refactor `agents/update_paper_trades.py`

**Context:** No Telegram. Supabase client init is at module level with a fatal-exit guard if creds missing.

**Files:**
- Modify: `agents/update_paper_trades.py`

- [ ] **Step 1: Apply changes to update_paper_trades.py**

**Line 18** — replace direct supabase import:

```python
from utils.supabase_client import get_client
```

**Lines 27-34** — replace Supabase init + fatal-exit guard:

```python
# DELETE:
# SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
# SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
# if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
#     print("FATAL: Supabase config missing")
#     sys.exit(1)
# supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# REPLACE WITH:
try:
    supabase = get_client()
except ValueError as e:
    print(f"FATAL: {e}")
    sys.exit(1)
```

- [ ] **Step 2: Verify import loads without error**

```
.venv/Scripts/python.exe -c "import agents.update_paper_trades; print('update_paper_trades import OK')"
```

Expected: `update_paper_trades import OK`

- [ ] **Step 3: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add agents/update_paper_trades.py
git commit -m "refactor(update_paper_trades): use shared supabase_client util"
```

---

## Task 7: Refactor `agents/upstox_paper_trade.py`

**Context:** No Telegram. Supabase client is initialized inside `main()` (not at module level), with the fatal-exit guard also inside `main()`. Both move together.

**Files:**
- Modify: `agents/upstox_paper_trade.py`

- [ ] **Step 1: Apply changes to upstox_paper_trade.py**

**Line 22** — replace direct supabase import:

```python
from utils.supabase_client import get_client
```

**Lines 29-30** — delete module-level Supabase env var reads:

```python
# DELETE:
# SUPABASE_URL           = os.getenv("SUPABASE_URL", "").strip()
# SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
```

**Lines 106-115 inside `main()`** — replace the Supabase guard + init:

```python
# DELETE:
#     if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
#         print("FATAL: Supabase config missing from .env")
#         sys.exit(1)
# ... (lines 110-114 are unrelated, keep them) ...
#     sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# REPLACE the deleted guard + create_client line WITH (inside main(), after the UPSTOX check):
    try:
        sb = get_client()
    except ValueError as e:
        print(f"FATAL: {e}")
        sys.exit(1)
```

The unrelated lines (110-114: `now_ist`, `is_market_close`, print statements) stay in place between the UPSTOX check and the new Supabase block.

- [ ] **Step 2: Verify import loads without error**

```
.venv/Scripts/python.exe -c "import agents.upstox_paper_trade; print('upstox_paper_trade import OK')"
```

Expected: `upstox_paper_trade import OK`

- [ ] **Step 3: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```
git add agents/upstox_paper_trade.py
git commit -m "refactor(upstox_paper_trade): use shared supabase_client util"
```

---

## Task 8: Final Smoke Tests

- [ ] **Step 1: Utils self-tests**

```
.venv/Scripts/python.exe utils/supabase_client.py
```

Expected: `Supabase client OK: Client`

```
.venv/Scripts/python.exe utils/telegram_client.py
```

Expected: `Import OK`

- [ ] **Step 2: Agent dry-run (reads Supabase, no writes)**

```
.venv/Scripts/python.exe agents/update_paper_trades.py
```

Expected: prints open trade count, exits cleanly (or closes expired trades if any). No crash.

- [ ] **Step 3: tier0 Telegram path confirmation**

```
.venv/Scripts/python.exe -c "import agents.tier0_filings; print('tier0 OK')"
```

Expected: `tier0 OK` — confirms urllib.parse is fully removed and requests-based path loads.

- [ ] **Step 4: Full test suite final run**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all tests pass (includes original test_tier2_questdb_write + test_news_questdb_write + new test_supabase_client + test_telegram_client).

- [ ] **Step 5: Confirm no stray direct supabase imports in agents/**

```
grep -n "from supabase import" agents/*.py
```

Expected: no output (all direct imports have been replaced).

- [ ] **Step 6: Confirm no stray urllib.parse Telegram usage**

```
grep -n "urllib.parse.urlencode" agents/*.py
```

Expected: no output.

---

## Self-Review

**Spec coverage check:**
- [x] `utils/supabase_client.py` with `get_client()` → Task 1
- [x] `utils/telegram_client.py` with `send_message()` → Task 2
- [x] tier0: ANON_KEY → SERVICE_ROLE_KEY, urllib → requests → Task 3
- [x] tier1: supabase init + Telegram HTTP block extracted → Task 4
- [x] tier2: conditional init preserved via try/except, send_telegram removed → Task 5
- [x] update_paper_trades: fatal-exit pattern preserved → Task 6
- [x] upstox_paper_trade: init inside main() handled correctly → Task 7
- [x] Smoke test for tier0 Telegram path (urllib migration) → Task 8 Step 3
- [x] Full test suite runs after every task

**Known behavior changes (by design):**
- tier0 now uses `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_ANON_KEY` — both keys have insert access on `filings_log`
- tier1 Telegram messages no longer send `disable_web_page_preview: True` — link previews will appear in MOVERS channel (cosmetic only)
- tier2's `send_telegram` used `raise_for_status()`; `send_message` uses `r.ok` check — Telegram errors are now logged as warnings instead of exceptions (the caller's try-except around send_telegram already swallowed them anyway)

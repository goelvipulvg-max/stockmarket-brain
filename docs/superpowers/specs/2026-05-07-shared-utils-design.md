# Shared Utils Refactor — Design Spec
**Date:** 2026-05-07
**Phase:** Pre-Tier-3 cleanup
**Scope:** Step 1 of 2 — spec only. Implementation requires explicit confirmation.

## Problem
Supabase client init and Telegram send logic are copy-pasted across 5 agent files. Each copy has
slight variations (different key names, different error handling, different HTTP libraries). This
makes maintenance error-prone and will get worse as Tier-3 adds another agent.

## Goal
Extract into two shared utils:
- `utils/supabase_client.py` — one `get_client()` factory
- `utils/telegram_client.py` — one `send_message()` low-level sender

Agent files are updated to import from utils. Message formatting stays in each agent (it is
domain-specific and should not be generalized).

---

## Current State Survey

### Supabase init — 5 files, 3 patterns

| File | Key used | Init pattern | Behavior if missing |
|------|----------|--------------|---------------------|
| agents/tier0_filings.py | `SUPABASE_ANON_KEY` | `create_client(url, key)` | AttributeError crash |
| agents/tier1_news.py | `SUPABASE_SERVICE_ROLE_KEY` | `create_client(url, key)` | AttributeError crash |
| agents/tier2_signals.py | `SUPABASE_SERVICE_ROLE_KEY` | Conditional — may be `None` | Graceful skip |
| agents/update_paper_trades.py | `SUPABASE_SERVICE_ROLE_KEY` | `create_client(url, key)` | `sys.exit(1)` |
| agents/upstox_paper_trade.py | `SUPABASE_SERVICE_ROLE_KEY` | `create_client(url, key)` | `sys.exit(1)` |

Note: tier0 uses `SUPABASE_ANON_KEY` — all others use `SUPABASE_SERVICE_ROLE_KEY`. After
refactor, tier0 will also use `SUPABASE_SERVICE_ROLE_KEY` (both keys have insert permission;
using the same key removes a discrepancy with no functional downside).

### Telegram — 3 files, 3 different function signatures

| File | Function signature | HTTP library | Parse mode | Channel env var |
|------|--------------------|--------------|------------|-----------------|
| agents/tier0_filings.py | `send_telegram(chat_id, text)` | urllib (stdlib) | HTML | `TELEGRAM_MOVERS_CHANNEL` |
| agents/tier1_news.py | `send_telegram(source, title, url, score, category, summary)` | requests | Markdown | `TELEGRAM_MOVERS_CHANNEL` |
| agents/tier2_signals.py | `send_telegram(message)` | requests | HTML | `TELEGRAM_SWING_CHANNEL` |

The domain-specific formatting (emoji, score display, markdown layout) differs per agent and
stays in each agent. Only the raw HTTP POST is extracted.

---

## utils/supabase_client.py — Public API

```python
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv(override=True)

def get_client() -> Client:
    """Return a Supabase client from env. Raises ValueError if credentials missing."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from env")
    return create_client(url, key)
```

Callers own the error handling:
- Graceful degradation (tier2): `try: sb = get_client()` / `except ValueError: sb = None`
- Fatal exit (update_paper_trades, upstox_paper_trade): `try: sb = get_client()` / `except ValueError as e: sys.exit(1)`
- No handling needed (tier0, tier1): call directly — will raise on misconfigured env just like today

`if __name__ == "__main__"` self-test: connect and print client repr (mirrors questdb_client.py pattern).

---

## utils/telegram_client.py — Public API

```python
import requests

def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> None:
    """POST a message to Telegram. Prints warning on failure, never raises."""
    if not bot_token or not chat_id:
        print("  Telegram config missing — skipping")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    if not r.ok:
        print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")
```

Design decisions:
- Never raises (uses `r.ok` check, not `raise_for_status`) — Telegram send is non-fatal in all agents
- `bot_token` and `chat_id` are passed as args, not read from env — callers supply them from
  their own env vars (each agent uses different channels)
- Default `parse_mode="HTML"` matches tier0 and tier2 convention; tier1 will pass `"Markdown"`

`if __name__ == "__main__"` self-test: print "Import OK" without making live network calls.

---

## Per-Agent Changes

### agents/tier0_filings.py
**Supabase:**
- Remove: `from supabase import create_client`, `SUPABASE_URL` / `SUPABASE_ANON_KEY` env reads,
  `sb = create_client(...)`
- Add: `from utils.supabase_client import get_client`, `sb = get_client()`
- Key change: switches from `SUPABASE_ANON_KEY` to `SUPABASE_SERVICE_ROLE_KEY`

**Telegram:**
- Remove: local `send_telegram(chat_id, text)` function (urllib-based)
- Add: `from utils.telegram_client import send_message`
- Change call site: `send_telegram(MOVERS_CHANNEL, msg)` -> `send_message(BOT, MOVERS_CHANNEL, msg)`

### agents/tier1_news.py
**Supabase:**
- Remove: `from supabase import create_client`, `SUPABASE_URL` / `SUPABASE_KEY` vars,
  `supabase = create_client(...)`
- Add: `from utils.supabase_client import get_client`, `supabase = get_client()`

**Telegram:**
- Remove: `requests.post(...)` block inside local `send_telegram()` function
- Add: `from utils.telegram_client import send_message`
- Restructure: keep domain-specific formatting logic in `send_telegram()`; replace the HTTP block
  with `send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_MOVERS_CHAT, text, parse_mode="Markdown")`

### agents/tier2_signals.py
**Supabase:**
- Remove: `from supabase import create_client, Client`, `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`
  vars, conditional `create_client(...)` inline
- Add: `from utils.supabase_client import get_client`
- Change init: wrap in `try/except ValueError` -> `supabase = None` on failure

**Telegram:**
- Remove: local `send_telegram(message)` function
- Add: `from utils.telegram_client import send_message`
- Change call site: `send_telegram(msg)` -> `send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_SWING_CHANNEL, msg)`

### agents/update_paper_trades.py
**Supabase only (no Telegram):**
- Remove: `from supabase import create_client, Client`, env vars, `supabase = create_client(...)`,
  `if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY: sys.exit(1)` block
- Add: `from utils.supabase_client import get_client`
- Change init: `try: supabase = get_client()` / `except ValueError: print("FATAL:..."); sys.exit(1)`

### agents/upstox_paper_trade.py
**Supabase only (no Telegram):**
- Same pattern as update_paper_trades.py above.

---

## Files NOT touched
- `utils/questdb_client.py` — reference only (pattern to mirror)
- `utils/__init__.py` — already exists, stays empty
- `requirements.txt` — `supabase` and `requests` already present; no new packages needed
- `tests/` — existing tests mock at the agent level; imports change but mock targets don't

---

## Smoke Test Plan

After implementation:

1. Import smoke test (no network):
   `.venv/Scripts/python.exe -c "from utils.supabase_client import get_client; print('OK')"`
   `.venv/Scripts/python.exe -c "from utils.telegram_client import send_message; print('OK')"`

2. Self-tests:
   `.venv/Scripts/python.exe utils/supabase_client.py` -- expect `Supabase client OK`
   `.venv/Scripts/python.exe utils/telegram_client.py` -- expect `Import OK`

3. Agent dry-run (reads only, no writes):
   `.venv/Scripts/python.exe agents/update_paper_trades.py` -- reads OPEN trades from Supabase,
   exits cleanly

4. tier0 Telegram path (urllib -> requests migration):
   `.venv/Scripts/python.exe -c "import agents.tier0_filings; print('tier0 import OK')"` --
   confirms urllib is gone and requests-based send_message loads without ImportError.
   This is the only file switching HTTP libraries; explicit import check catches any residual
   urllib reference or missing requests import.

5. Existing test suite:
   `.venv/Scripts/python.exe -m pytest tests/ -v` -- all tests must pass unchanged

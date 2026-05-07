# Tier-3 Position Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `agents/tier3_position_manager.py` — a signal filter and capital allocator that triggers after Tier-2, applies rule-based and Claude re-evaluation filters to today's signals, logs all decisions to `tier3_decisions`, and posts approved picks + a daily summary to a dedicated Telegram channel.

**Architecture:** Single script with four pure functions (`apply_rules`, `evaluate_with_claude`, `format_pick_message`, `format_summary_message`) plus `log_decision` and `main`. The Supabase client is created inside `main()` so test imports don't raise on missing credentials; `anthropic_client` is module-level (Anthropic SDK doesn't validate the key at init time). GitHub Actions `workflow_run` trigger fires the script only when Tier-2 succeeds.

**Tech Stack:** Python 3.12, supabase-py 2.x, anthropic SDK, python-dotenv, zoneinfo, pytest + unittest.mock

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `agents/tier3_position_manager.py` | Main agent script |
| Create | `tests/test_tier3_position_manager.py` | 10 unit tests (mock-only) |
| Create | `.github/workflows/tier3_position_manager.yml` | GitHub Actions workflow |
| Modify | `.env.example` | Add `TELEGRAM_TIER3_CHANNEL=` |
| Manual (Supabase SQL editor) | — | Create `tier3_decisions` table |

---

## Task 1: Create `tier3_decisions` table + update `.env.example`

**Files:**
- Manual: Supabase SQL editor
- Modify: `.env.example`

- [ ] **Step 1: Run this SQL in the Supabase SQL editor** (Dashboard → SQL Editor → New query)

```sql
CREATE TABLE tier3_decisions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    paper_trade_id INT REFERENCES paper_trades(id),
    direction TEXT NOT NULL,
    confidence_tier2 INT NOT NULL,
    rule_pass BOOL NOT NULL,
    confidence_tier3 INT,
    approved BOOL NOT NULL,
    reject_reason TEXT,
    position_size INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(signal_date, ticker)
);
```

Expected: "Success. No rows returned."

- [ ] **Step 2: Verify the table exists**

Run in Supabase SQL editor:
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'tier3_decisions' ORDER BY ordinal_position;
```

Expected: 12 rows listing the columns above.

- [ ] **Step 3: Add `TELEGRAM_TIER3_CHANNEL` to `.env.example`**

Current `.env.example` content:
```
QUESTDB_HOST=localhost
QUESTDB_PORT=8812
QUESTDB_USER=admin
QUESTDB_PASSWORD=quest
QUESTDB_DB=qdb
```

New content (append the line):
```
QUESTDB_HOST=localhost
QUESTDB_PORT=8812
QUESTDB_USER=admin
QUESTDB_PASSWORD=quest
QUESTDB_DB=qdb
TELEGRAM_TIER3_CHANNEL=
```

- [ ] **Step 4: Add `TELEGRAM_TIER3_CHANNEL` to your local `.env` file**

Open `.env` and add the actual channel ID value (e.g. `-1001234567890`). This is a manual step — the value is the Telegram channel chat ID for TIER3_PICKS.

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "chore(tier3): add TELEGRAM_TIER3_CHANNEL to env.example and create tier3_decisions table"
```

---

## Task 2: Create agent stub file

**Files:**
- Create: `agents/tier3_position_manager.py`

- [ ] **Step 1: Create the file with imports and function stubs**

Create `agents/tier3_position_manager.py` with this exact content:

```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client
from utils.telegram_client import send_message as tg_send

IST = ZoneInfo("Asia/Kolkata")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_TIER3_CHANNEL = os.getenv("TELEGRAM_TIER3_CHANNEL", "").strip()

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)


def apply_rules(signal: dict, open_trades: list) -> tuple:
    raise NotImplementedError


def evaluate_with_claude(signal: dict, filings: list, news: list, client) -> dict:
    raise NotImplementedError


def format_pick_message(signal: dict, tier3_confidence: int, tier3_reason: str) -> str:
    raise NotImplementedError


def format_summary_message(approved: list, rejected_reasons: list, date_str: str) -> str:
    raise NotImplementedError


def log_decision(supabase, decision: dict) -> None:
    raise NotImplementedError


def main():
    raise NotImplementedError


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Tier-3 Position Manager crashed — {type(e).__name__}: {e}")
        sys.exit(1)
```

- [ ] **Step 2: Verify the import works**

```bash
.venv/Scripts/python.exe -c "import agents.tier3_position_manager; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add agents/tier3_position_manager.py
git commit -m "feat(tier3): add agent stub with function signatures"
```

---

## Task 3 (TDD): `apply_rules`

**Files:**
- Create: `tests/test_tier3_position_manager.py`
- Modify: `agents/tier3_position_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tier3_position_manager.py` with this content:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.tier3_position_manager import (
    apply_rules,
    evaluate_with_claude,
    format_pick_message,
    format_summary_message,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_signal(**kwargs):
    base = {
        "id": 1,
        "ticker": "RELIANCE.NS",
        "direction": "BUY",
        "confidence": 8,
        "rsi": 55.0,
        "macd": 12.5,
        "entry_price": 2450.0,
        "target_price": 2550.0,
        "stop_loss": 2380.0,
        "reason": "MACD crossover with RSI at 55",
    }
    base.update(kwargs)
    return base


# ── apply_rules ───────────────────────────────────────────────────────────────

def test_rule_duplicate_open():
    signal = make_signal(id=1, ticker="RELIANCE.NS")
    open_trades = [{"id": 2, "ticker": "RELIANCE.NS", "status": "OPEN"}]
    passed, reason = apply_rules(signal, open_trades)
    assert passed is False
    assert reason == "duplicate_open_position"


def test_rule_confidence_threshold():
    signal = make_signal(confidence=7)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "confidence_below_threshold"


def test_rule_extreme_rsi_buy():
    signal = make_signal(direction="BUY", rsi=82.0)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "extreme_rsi"


def test_rule_extreme_rsi_sell():
    signal = make_signal(direction="SELL", rsi=18.0)
    passed, reason = apply_rules(signal, [])
    assert passed is False
    assert reason == "extreme_rsi"


def test_rule_all_pass():
    signal = make_signal(id=1, ticker="RELIANCE.NS", confidence=8, rsi=55.0, direction="BUY")
    open_trades = [{"id": 2, "ticker": "TCS.NS", "status": "OPEN"}]
    passed, reason = apply_rules(signal, open_trades)
    assert passed is True
    assert reason is None
```

- [ ] **Step 2: Run the tests — expect FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_rule_duplicate_open tests/test_tier3_position_manager.py::test_rule_confidence_threshold tests/test_tier3_position_manager.py::test_rule_extreme_rsi_buy tests/test_tier3_position_manager.py::test_rule_extreme_rsi_sell tests/test_tier3_position_manager.py::test_rule_all_pass -v
```

Expected: all 5 FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `apply_rules` in `agents/tier3_position_manager.py`**

Replace the `apply_rules` stub:

```python
def apply_rules(signal: dict, open_trades: list) -> tuple:
    for trade in open_trades:
        if trade["ticker"] == signal["ticker"] and trade["id"] != signal["id"]:
            return False, "duplicate_open_position"
    if signal["confidence"] < 8:
        return False, "confidence_below_threshold"
    rsi = signal.get("rsi") or 50.0
    if signal["direction"] == "BUY" and rsi > 80:
        return False, "extreme_rsi"
    if signal["direction"] == "SELL" and rsi < 20:
        return False, "extreme_rsi"
    return True, None
```

- [ ] **Step 4: Run the tests — expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_rule_duplicate_open tests/test_tier3_position_manager.py::test_rule_confidence_threshold tests/test_tier3_position_manager.py::test_rule_extreme_rsi_buy tests/test_tier3_position_manager.py::test_rule_extreme_rsi_sell tests/test_tier3_position_manager.py::test_rule_all_pass -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tier3_position_manager.py tests/test_tier3_position_manager.py
git commit -m "feat(tier3): implement apply_rules with 5 passing tests"
```

---

## Task 4 (TDD): `evaluate_with_claude`

**Files:**
- Modify: `tests/test_tier3_position_manager.py`
- Modify: `agents/tier3_position_manager.py`

- [ ] **Step 1: Append these 3 tests to `tests/test_tier3_position_manager.py`**

```python
# ── evaluate_with_claude ──────────────────────────────────────────────────────

def test_claude_approve():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = (
        '{"verdict": "APPROVE", "confidence": 9, "reason": "Strong signal, no negative catalysts"}'
    )
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 9
    assert "_parse_error" not in result


def test_claude_reject():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = (
        '{"verdict": "REJECT", "confidence": 3, "reason": "Regulatory action pending"}'
    )
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "REJECT"
    assert "_parse_error" not in result


def test_claude_parse_error():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content[0].text = "not valid json {{{"
    result = evaluate_with_claude(make_signal(), [], [], mock_client)
    assert result["verdict"] == "REJECT"
    assert result.get("_parse_error") is True
```

- [ ] **Step 2: Run the 3 new tests — expect FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_claude_approve tests/test_tier3_position_manager.py::test_claude_reject tests/test_tier3_position_manager.py::test_claude_parse_error -v
```

Expected: 3 FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `evaluate_with_claude` in `agents/tier3_position_manager.py`**

Replace the `evaluate_with_claude` stub:

```python
def evaluate_with_claude(signal: dict, filings: list, news: list, client) -> dict:
    ticker_base = signal["ticker"].replace(".NS", "")

    filings_text = "\n".join(
        f"- [{f['event_type']}] {f['summary']} (score: {f['material_score']})"
        for f in filings
    ) if filings else "None"

    news_text = "\n".join(
        f"- {n['title']}: {n['summary']} (score: {n['score']})"
        for n in news
    ) if news else "None"

    prompt = f"""You are a position manager for an NSE swing trading system.

Signal from Tier-2:
- Ticker: {signal['ticker']}
- Direction: {signal['direction']}
- Entry: ₹{signal['entry_price']} | Target: ₹{signal['target_price']} | SL: ₹{signal['stop_loss']}
- Tier-2 Confidence: {signal['confidence']}/10
- Reason: {signal['reason']}
- RSI: {signal['rsi']} | MACD: {signal['macd']}

Recent filings for {ticker_base} (last 3):
{filings_text}

Recent market news (general, last 5):
{news_text}

Respond ONLY in this JSON format:
{{"verdict": "APPROVE" or "REJECT", "confidence": <int 1-10>, "reason": "<one line>"}}

APPROVE if the signal is supported or not contradicted by filings/news.
REJECT only if there is a specific negative catalyst (bad earnings, regulatory action, major negative news)."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"verdict": "REJECT", "confidence": 0, "reason": "parse_error", "_parse_error": True}
```

- [ ] **Step 4: Run the 3 tests — expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_claude_approve tests/test_tier3_position_manager.py::test_claude_reject tests/test_tier3_position_manager.py::test_claude_parse_error -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tier3_position_manager.py tests/test_tier3_position_manager.py
git commit -m "feat(tier3): implement evaluate_with_claude with 3 passing tests"
```

---

## Task 5 (TDD): `format_pick_message` + `format_summary_message`

**Files:**
- Modify: `tests/test_tier3_position_manager.py`
- Modify: `agents/tier3_position_manager.py`

- [ ] **Step 1: Append these 2 tests to `tests/test_tier3_position_manager.py`**

```python
# ── format_pick_message ───────────────────────────────────────────────────────

def test_summary_message_format():
    approved = ["RELIANCE.NS", "TCS.NS"]
    rejected_reasons = [
        "confidence_below_threshold",
        "confidence_below_threshold",
        "duplicate_open_position",
        "claude_reject",
    ]
    msg = format_summary_message(approved, rejected_reasons, "07 May 2026")
    assert "Approved: 2" in msg
    assert "Rejected: 4" in msg
    assert "50,000" in msg
    assert "2 × confidence_below_threshold" in msg


def test_no_signals_today():
    msg = format_summary_message([], [], "07 May 2026")
    assert "Approved: 0" in msg
    assert "Rejected: 0" in msg
    assert "₹0" in msg
```

- [ ] **Step 2: Run the 2 new tests — expect FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_summary_message_format tests/test_tier3_position_manager.py::test_no_signals_today -v
```

Expected: 2 FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `format_pick_message` and `format_summary_message` in `agents/tier3_position_manager.py`**

Replace the `format_pick_message` stub:

```python
def format_pick_message(signal: dict, tier3_confidence: int, tier3_reason: str) -> str:
    direction = signal["direction"]
    arrow = "\U0001f4c8" if direction == "BUY" else "\U0001f4c9"
    return (
        f'✅ <b>TIER-3 APPROVED</b> — <b>{signal["ticker"]}</b>\n\n'
        f'{arrow} Direction: {direction}\n'
        f'\U0001f4b0 Entry: ₹{signal["entry_price"]:.2f} | Target: ₹{signal["target_price"]:.2f} | SL: ₹{signal["stop_loss"]:.2f}\n'
        f'\U0001f3af Tier-2 Confidence: {signal["confidence"]}/10 | Tier-3 Confidence: {tier3_confidence}/10\n'
        f'\U0001f4b5 Position Size: ₹25,000\n\n'
        f'\U0001f4dd Tier-2: {signal["reason"]}\n'
        f'\U0001f50d Tier-3: {tier3_reason}'
    )
```

Replace the `format_summary_message` stub:

```python
def format_summary_message(approved: list, rejected_reasons: list, date_str: str) -> str:
    total_capital = len(approved) * 25000
    reason_counts = Counter(rejected_reasons)
    breakdown = "\n".join(
        f"• {count} × {reason}" for reason, count in reason_counts.items()
    )
    msg = (
        f'\U0001f4cb <b>Tier-3 Daily Summary — {date_str}</b>\n\n'
        f'✅ Approved: {len(approved)}  |  ❌ Rejected: {len(rejected_reasons)}\n'
        f'\U0001f4b0 Total capital to deploy today: ₹{total_capital:,}'
    )
    if breakdown:
        msg += f'\n\nRejected breakdown:\n{breakdown}'
    return msg
```

- [ ] **Step 4: Run the 2 tests — expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py::test_summary_message_format tests/test_tier3_position_manager.py::test_no_signals_today -v
```

Expected: 2 passed

- [ ] **Step 5: Run all 10 tests together to confirm nothing broke**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py -v
```

Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add agents/tier3_position_manager.py tests/test_tier3_position_manager.py
git commit -m "feat(tier3): implement format_pick_message and format_summary_message with tests"
```

---

## Task 6: Implement `log_decision` + `main`

**Files:**
- Modify: `agents/tier3_position_manager.py`

- [ ] **Step 1: Replace the `log_decision` stub**

```python
def log_decision(supabase, decision: dict) -> None:
    try:
        supabase.table("tier3_decisions").insert(decision).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "23505" in str(e):
            print(f"  -> Already decided for {decision['ticker']} today, skipping")
        else:
            print(f"  -> tier3_decisions log failed: {type(e).__name__}: {e}")
```

- [ ] **Step 2: Replace the `main` stub**

```python
def main():
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    date_display = now_ist.strftime("%d %b %Y")
    print(f"Running Tier-3 Position Manager — {today_str}")

    supabase = get_client()

    signals = (
        supabase.table("paper_trades")
        .select("*")
        .eq("signal_date", today_str)
        .eq("status", "OPEN")
        .execute()
        .data
    )
    signals = [s for s in signals if s["direction"] in ("BUY", "SELL")]
    print(f"Signals from Tier-2 today: {len(signals)}")

    if not signals:
        summary = format_summary_message([], [], date_display)
        tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, summary)
        print("No signals today. Summary posted.")
        return

    open_trades = (
        supabase.table("paper_trades")
        .select("id,ticker,status")
        .eq("status", "OPEN")
        .execute()
        .data
    )

    news = (
        supabase.table("news_log")
        .select("title,summary,score")
        .order("fetched_at", desc=True)
        .limit(5)
        .execute()
        .data
    )

    approved = []
    rejected_reasons = []

    for signal in signals:
        ticker = signal["ticker"]
        print(f"\n{ticker}:")

        rule_pass, reject_reason = apply_rules(signal, open_trades)
        if not rule_pass:
            print(f"  REJECTED by rules: {reject_reason}")
            log_decision(supabase, {
                "signal_date": today_str,
                "ticker": ticker,
                "paper_trade_id": signal["id"],
                "direction": signal["direction"],
                "confidence_tier2": signal["confidence"],
                "rule_pass": False,
                "approved": False,
                "reject_reason": reject_reason,
                "position_size": 0,
            })
            rejected_reasons.append(reject_reason)
            continue

        ticker_base = ticker.replace(".NS", "")
        filings = (
            supabase.table("filings_log")
            .select("event_type,summary,material_score")
            .eq("symbol", ticker_base)
            .order("published_at", desc=True)
            .limit(3)
            .execute()
            .data
        )

        result = evaluate_with_claude(signal, filings, news, anthropic_client)
        verdict = result["verdict"]
        tier3_confidence = result["confidence"]
        tier3_reason = result["reason"]
        is_parse_error = result.get("_parse_error", False)

        is_approved = verdict == "APPROVE"
        final_reject_reason = None if is_approved else (
            "claude_parse_error" if is_parse_error else "claude_reject"
        )

        log_decision(supabase, {
            "signal_date": today_str,
            "ticker": ticker,
            "paper_trade_id": signal["id"],
            "direction": signal["direction"],
            "confidence_tier2": signal["confidence"],
            "rule_pass": True,
            "confidence_tier3": None if is_parse_error else tier3_confidence,
            "approved": is_approved,
            "reject_reason": final_reject_reason,
            "position_size": 25000 if is_approved else 0,
        })

        if is_approved:
            print(f"  APPROVED — Tier-3 confidence: {tier3_confidence}/10")
            approved.append(signal)
            msg = format_pick_message(signal, tier3_confidence, tier3_reason)
            tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, msg)
        else:
            print(f"  REJECTED by Claude: {final_reject_reason}")
            rejected_reasons.append(final_reject_reason)

    summary = format_summary_message(approved, rejected_reasons, date_display)
    tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, summary)
    print(f"\nDone. Approved: {len(approved)} | Rejected: {len(rejected_reasons)}")
```

- [ ] **Step 3: Run all 10 tests to confirm nothing broke**

```bash
.venv/Scripts/python.exe -m pytest tests/test_tier3_position_manager.py -v
```

Expected: 10 passed

- [ ] **Step 4: Smoke test the import**

```bash
.venv/Scripts/python.exe -c "import agents.tier3_position_manager; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 5: Commit**

```bash
git add agents/tier3_position_manager.py
git commit -m "feat(tier3): implement log_decision and main orchestration"
```

---

## Task 7: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/tier3_position_manager.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/tier3_position_manager.yml` with this exact content:

```yaml
# ============================================================
# StockMarket-Brain | Tier-3 Position Manager
# ============================================================
# Trigger: fires automatically when Tier-2 Swing Signals succeeds
# Duration: ~2-3 min per run (10 tickers, Claude calls for rule-passers)
# Output:   Telegram TIER3_PICKS channel
# Manual:   Actions tab → "Run workflow" button
# ============================================================

name: Tier-3 Position Manager

on:
  workflow_run:
    workflows: ["Tier-2 Swing Signals"]
    types: [completed]
  workflow_dispatch:

jobs:
  run-tier3:
    if: ${{ github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Tier-3 Position Manager
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_TIER3_CHANNEL: ${{ secrets.TELEGRAM_TIER3_CHANNEL }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python agents/tier3_position_manager.py
```

Note: the `if` condition includes `workflow_dispatch` so you can also trigger it manually from the GitHub Actions tab for testing without waiting for Tier-2 to run.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/tier3_position_manager.yml
git commit -m "feat(tier3): add GitHub Actions workflow with workflow_run trigger"
```

---

## Task 8: Full test suite + final verification

**Files:** none new

- [ ] **Step 1: Run the full test suite**

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all existing tests pass (was 20 before this feature; now 30 with the 10 new tier3 tests). Exact count: confirm all pass, 0 failed.

- [ ] **Step 2: Add `TELEGRAM_TIER3_CHANNEL` to GitHub Actions secrets**

In the GitHub repo: Settings → Secrets and variables → Actions → New repository secret.
Name: `TELEGRAM_TIER3_CHANNEL`
Value: the Telegram channel chat ID for the TIER3_PICKS channel.

This is a manual step — the workflow will silently produce no Telegram output until this secret is set.

- [ ] **Step 3: Verify git log shows all task commits**

```bash
git log --oneline -8
```

Expected commits (most recent first):
```
feat(tier3): add GitHub Actions workflow with workflow_run trigger
feat(tier3): implement log_decision and main orchestration
feat(tier3): implement format_pick_message and format_summary_message with tests
feat(tier3): implement evaluate_with_claude with 3 passing tests
feat(tier3): implement apply_rules with 5 passing tests
feat(tier3): add agent stub with function signatures
chore(tier3): add TELEGRAM_TIER3_CHANNEL to env.example and create tier3_decisions table
```

- [ ] **Step 4: Push to origin**

```bash
git push
```

Expected: push succeeds, Tier-3 workflow appears in GitHub Actions tab.

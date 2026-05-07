# Tier-3 Position Manager — Design Spec
**Date:** 2026-05-07
**Status:** Approved

## Overview

Tier-3 is a signal filter and capital allocator that runs after Tier-2 each morning. It reads today's Tier-2 signals from `paper_trades`, applies a two-stage filter (rules, then Claude re-evaluation), and posts approved picks with position sizes to a dedicated Telegram channel. All decisions — approved and rejected — are logged to a new `tier3_decisions` Supabase table for analysis.

This is a read-only agent: it does not place Upstox orders. It produces actionable picks that the user executes manually.

---

## Architecture

### Trigger
GitHub Actions `workflow_run` event, triggered on completion of the **Tier-2 Swing Signals** workflow (`on: workflow_run: workflows: ["Tier-2 Swing Signals"], types: [completed]`). Tier-3 only runs when Tier-2 succeeds (`if: github.event.workflow_run.conclusion == 'success'`).

### Single script
`agents/tier3_position_manager.py` — follows the same structure as all other agents (imports from `utils/`, reads `.env`, uses `get_client()` and `send_message()`).

### New env var
`TELEGRAM_TIER3_CHANNEL` — added to `.env`, `.env.example`, and GitHub Actions secrets.

---

## Data Flow

```
Tier-2 workflow succeeds
        ↓
Tier-3 workflow triggers (workflow_run)
        ↓
1. Read today's signals from paper_trades
   WHERE signal_date = today AND direction IN ('BUY','SELL') AND status = 'OPEN'
        ↓
2. Rule-based filter (per signal)
   PASS → Claude stage
   FAIL → log to tier3_decisions (approved=false, rule_pass=false)
        ↓
3. Claude re-evaluation (per signal that passed rules)
   Input: signal details + last 3 filings (ticker-specific) + last 5 news (general market)
   Output: {verdict: APPROVE|REJECT, confidence: 1-10, reason: "one line"}
   APPROVE → log (approved=true, position_size=25000)
   REJECT  → log (approved=false, rule_pass=true)
        ↓
4. Post each approved pick to TIER3_PICKS Telegram channel
        ↓
5. Post daily summary to TIER3_PICKS
```

---

## Stage 1: Rule-Based Filter

Three rules applied in order — first failure short-circuits the rest. Each rejection records a `reject_reason` string.

| Rule | Condition to reject | `reject_reason` |
|------|---------------------|-----------------|
| No duplicate open positions | Another `OPEN` trade exists in `paper_trades` for the same ticker (different `id`) | `duplicate_open_position` |
| Minimum confidence | Tier-2 confidence < 8 | `confidence_below_threshold` |
| No extreme RSI | RSI > 80 on a BUY signal, or RSI < 20 on a SELL signal | `extreme_rsi` |

---

## Stage 2: Claude Re-Evaluation

One `claude-haiku-4-5-20251001` call per signal that passed rules. Temperature: 0.

### Context fetched per signal
- **Filings (ticker-specific):** last 3 rows from `filings_log` WHERE `symbol = ticker.replace('.NS', '')` ORDER BY `published_at DESC` — fields: `event_type`, `summary`, `material_score`
- **News (general market):** last 5 rows from `news_log` ORDER BY `fetched_at DESC` — fields: `title`, `summary`, `score`

`news_log` has no ticker column; news is general NSE market context, not per-ticker. Both sections are clearly labeled in the prompt.

### Prompt
```
You are a position manager for an NSE swing trading system.

Signal from Tier-2:
- Ticker: {ticker}
- Direction: {direction}
- Entry: ₹{entry_price} | Target: ₹{target_price} | SL: ₹{stop_loss}
- Tier-2 Confidence: {confidence}/10
- Reason: {reason}
- RSI: {rsi} | MACD: {macd}

Recent filings for {ticker_base} (last 3):
{filings or "None"}

Recent market news (general, last 5):
{news or "None"}

Respond ONLY in this JSON format:
{"verdict": "APPROVE" or "REJECT", "confidence": <int 1-10>, "reason": "<one line>"}

APPROVE if the signal is supported or not contradicted by filings/news.
REJECT only if there is a specific negative catalyst (bad earnings, regulatory action, major negative news).
```

### Approval logic
- `verdict == "APPROVE"` → signal approved, regardless of `confidence` score (confidence is stored for analysis only)
- Malformed JSON or any exception → `approved=false`, `reject_reason="claude_parse_error"` — fail safe

---

## `tier3_decisions` Table Schema

Created manually in Supabase SQL editor before first run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | `DEFAULT gen_random_uuid()` |
| `signal_date` | `date` | matches `paper_trades.signal_date` |
| `ticker` | `text` | e.g. `RELIANCE.NS` |
| `paper_trade_id` | `int` | FK to `paper_trades.id` |
| `direction` | `text` | `BUY` or `SELL` |
| `confidence_tier2` | `int` | Tier-2's original confidence score |
| `rule_pass` | `bool` | true if all 3 rules passed |
| `confidence_tier3` | `int` | Claude's confidence (null if rule_pass=false) |
| `approved` | `bool` | true only if rule_pass=true AND verdict=APPROVE |
| `reject_reason` | `text` | null if approved; one of: `duplicate_open_position`, `confidence_below_threshold`, `extreme_rsi`, `claude_reject`, `claude_parse_error` |
| `position_size` | `int` | `25000` if approved, `0` otherwise |
| `created_at` | `timestamptz` | `DEFAULT now()` |

**Unique constraint:** `UNIQUE(signal_date, ticker)` — one decision per ticker per day. Inserts use `ON CONFLICT (signal_date, ticker) DO NOTHING` so manual re-runs on the same day are safe no-ops.

### SQL to create
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

---

## Telegram Output

**Per approved pick** (one message per approved signal):
```
✅ <b>TIER-3 APPROVED</b> — <b>RELIANCE.NS</b>

📈 Direction: BUY
💰 Entry: ₹2,450.00 | Target: ₹2,550.00 | SL: ₹2,380.00
🎯 Tier-2 Confidence: 8/10 | Tier-3 Confidence: 9/10
💵 Position Size: ₹25,000

📝 Tier-2: Strong MACD crossover with RSI at 58
🔍 Tier-3: No negative catalysts in recent filings; momentum intact
```

**Daily summary** (always posted, even if 0 approved):
```
📋 <b>Tier-3 Daily Summary — 07 May 2026</b>

✅ Approved: 2  |  ❌ Rejected: 4
💰 Total capital to deploy today: ₹50,000

Rejected breakdown:
• 2 × confidence_below_threshold
• 1 × duplicate_open_position
• 1 × claude_reject
```

- HTML parse mode (consistent with all other agents)
- If 0 signals from Tier-2: summary shows `Approved: 0 | Rejected: 0` and `Total capital: ₹0`, no pick messages posted
- Rejected breakdown only lists reasons that have count > 0

---

## GitHub Actions Workflow

File: `.github/workflows/tier3_position_manager.yml`

```yaml
on:
  workflow_run:
    workflows: ["Tier-2 Swing Signals"]
    types: [completed]

jobs:
  run-tier3:
    if: github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: "pip"
      - run: pip install -r requirements.txt
      - name: Run Tier-3 Position Manager
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_TIER3_CHANNEL: ${{ secrets.TELEGRAM_TIER3_CHANNEL }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python agents/tier3_position_manager.py
```

---

## Testing

Unit tests in `tests/test_tier3_position_manager.py`. All tests use mocks (no live Supabase/Telegram/Claude calls).

| Test | What it verifies |
|------|-----------------|
| `test_rule_duplicate_open` | signal rejected when another OPEN trade exists for same ticker |
| `test_rule_confidence_threshold` | signal rejected when confidence < 8 |
| `test_rule_extreme_rsi_buy` | BUY signal rejected when RSI > 80 |
| `test_rule_extreme_rsi_sell` | SELL signal rejected when RSI < 20 |
| `test_rule_all_pass` | signal passes all 3 rules |
| `test_claude_approve` | APPROVE verdict → approved=true, position_size=25000 |
| `test_claude_reject` | REJECT verdict → approved=false, reject_reason=claude_reject |
| `test_claude_parse_error` | malformed JSON → approved=false, reject_reason=claude_parse_error |
| `test_summary_message_format` | summary string contains correct counts and capital total |
| `test_no_signals_today` | empty paper_trades → summary shows all zeros |

---

## Capital Sizing

- Fixed: **Rs 25,000 per approved trade**
- Total ST capital: Rs 2,50,000
- Max concurrent approved picks: 10 (watchlist size) × Rs 25,000 = Rs 2,50,000 — cannot exceed capital by design
- No Kelly, no confidence scaling — revisit after 4+ weeks of decisions accumulate in `tier3_decisions`

---

## Out of Scope (this version)

- Upstox live order placement
- Per-ticker news filtering (news_log has no ticker column)
- Max concurrent positions cap
- Sector concentration rules
- External prompt file (prompts/tier3.txt)

# Tier-4 Memory Manager — Design Spec
**Date:** 2026-05-07
**Status:** Approved

## Overview

Tier-4 is a daily learning agent that reads resolved trade outcomes from `tier3_decisions` + `paper_trades`, computes win-rate statistics across three dimensions (confidence band, ticker, direction), and writes a pre-formatted text summary to a `trade_memory` Supabase table. Tier-3 reads the latest row from `trade_memory` at startup and appends it verbatim to Claude's prompt — giving the position manager an improving historical context over time.

This is a read-then-write agent: reads from two existing tables, writes one row to one new table. No Anthropic API call in Tier-4 itself.

---

## Architecture

```
update_paper_trades.py workflow completes
        ↓
Tier-4 workflow triggers (workflow_run on "Update Paper Trades")
        ↓
agents/tier4_memory_manager.py
  1. Query tier3_decisions JOIN paper_trades → resolved trades (WIN/LOSS only)
  2. Compute: win rate by confidence band, by ticker (min 2 trades), by direction
  3. Format into a readable text block
  4. Upsert one row to trade_memory (upsert key: computed_date)
        ↓
(next morning) Tier-3 reads latest row from trade_memory
  → appends memory_text to Claude prompt in evaluate_with_claude()
```

### New files
- `agents/tier4_memory_manager.py` — new agent, same structure as all other agents
- `.github/workflows/tier4_memory_manager.yml` — workflow_run trigger on "Update Paper Trades"

### Modified files
- `agents/tier3_position_manager.py` — `main()` fetches latest `memory_text`; `evaluate_with_claude()` accepts and appends it to the prompt

### New Supabase table
- `trade_memory` — one row per calendar day, upsert on `computed_date`

### No new env vars
Reuses `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. No Anthropic key needed in Tier-4.

---

## Data Flow

### Tier-4: reading resolved trades

```sql
SELECT
    td.confidence_tier2,
    td.ticker,
    td.direction,
    pt.status          -- 'WIN' or 'LOSS'
FROM tier3_decisions td
JOIN paper_trades pt ON pt.id = td.paper_trade_id
WHERE pt.status IN ('WIN', 'LOSS')
  AND td.approved = true
```

Only `approved = true` trades are included — rejected signals never had capital deployed, so their outcomes are irrelevant to the memory.

### Tier-4: three stat blocks

1. **By confidence band** — group on `confidence_tier2` (8, 9, 10) → wins / total / win_pct
2. **By ticker** — group on `ticker` → wins / total / win_pct; only tickers with `total >= 2` shown (suppress single-trade noise)
3. **By direction** — group on `direction` (BUY / SELL) → wins / total / win_pct

### Tier-4: formatted output

```
=== Historical Performance (as of 2026-05-07) ===

By confidence:
  Conf 8: 3W/8T = 38%
  Conf 9: 7W/11T = 64%
  Conf 10: 4W/5T = 80%

By ticker (min 2 trades):
  RELIANCE.NS: 3W/4T = 75%
  INFY.NS: 1W/5T = 20%

By direction:
  BUY: 9W/16T = 56%
  SELL: 5W/8T = 63%
```

**Zero-data case:** If no resolved trades exist, `memory_text = "No resolved trades yet."` and `total_resolved = 0`. Tier-3 handles this gracefully — it appears in the prompt as harmless context.

---

## `trade_memory` Table Schema

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | `DEFAULT gen_random_uuid()` |
| `computed_date` | `date` | upsert key — `UNIQUE` constraint |
| `total_resolved` | `int` | total WIN+LOSS approved trades at time of run |
| `memory_text` | `text` | pre-formatted block Tier-3 appends verbatim |
| `created_at` | `timestamptz` | `DEFAULT now()` |

### SQL to create (manual, Supabase SQL editor)
```sql
CREATE TABLE trade_memory (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    computed_date DATE NOT NULL UNIQUE,
    total_resolved INT NOT NULL DEFAULT 0,
    memory_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Upsert pattern
```python
supabase.table("trade_memory").upsert(
    {"computed_date": today_str, "total_resolved": total, "memory_text": text},
    on_conflict="computed_date"
).execute()
```

Re-runs on the same day overwrite the existing row — safe if the workflow retries.

---

## Tier-3 Changes

### `main()` — fetch latest memory before signal loop
```python
memory_row = (
    supabase.table("trade_memory")
    .select("memory_text")
    .order("computed_date", desc=True)
    .limit(1)
    .execute()
    .data
)
memory_text = memory_row[0]["memory_text"] if memory_row else "No resolved trades yet."
```

`memory_text` is passed into each `evaluate_with_claude()` call.

### `evaluate_with_claude()` signature change
```python
def evaluate_with_claude(signal, filings, news, client, memory_text="No resolved trades yet."):
```

### Prompt addition (appended after news block)
```
Historical trading performance:
{memory_text}
```

No other changes to Tier-3. Rules (`apply_rules`) are unchanged. Memory is additive read-only context for Claude.

---

## GitHub Actions Workflow

File: `.github/workflows/tier4_memory_manager.yml`

```yaml
name: Tier-4 Memory Manager

on:
  workflow_run:
    workflows: ["Update Paper Trades"]
    types: [completed]
  workflow_dispatch:

jobs:
  run-tier4:
    if: ${{ github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: "3.12"
          cache: "pip"
      - run: pip install -r requirements.txt
      - name: Run Tier-4 Memory Manager
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python agents/tier4_memory_manager.py
```

The `workflow_run` reference uses `"Update Paper Trades"` — the exact `name:` field from `.github/workflows/update_paper_trades.yml`.

---

## Testing

Unit tests in `tests/test_tier4_memory_manager.py`. All tests use mock data — no live Supabase calls.

| Test | What it verifies |
|------|-----------------|
| `test_compute_stats_by_confidence` | correct wins/total/pct per confidence band (8, 9, 10) |
| `test_compute_stats_by_ticker_min2` | tickers with < 2 resolved trades are excluded |
| `test_compute_stats_by_direction` | BUY/SELL split computed correctly |
| `test_format_memory_text` | output string contains expected lines and percentages |
| `test_zero_resolved_trades` | returns "No resolved trades yet." and total_resolved=0 |
| `test_tier3_uses_memory_text` | `evaluate_with_claude` includes memory_text in the prompt passed to Claude |

6 new tests → total suite: 36 passing.

---

## Manual Steps (before first run)

1. Run `CREATE TABLE trade_memory (...)` SQL in Supabase SQL editor
2. No new GitHub Secrets required

---

## Out of Scope (this version)

- Minimum sample threshold before showing stats (e.g., hide confidence band until N ≥ 5) — revisit after 4+ weeks of data
- Sector-level win rate breakdown
- Time-of-week patterns (Monday vs Friday signals)
- Rolling window (e.g., last 30 days only) — currently uses all-time history
- Tier-3 acting on memory (e.g., auto-reject confidence-8 if win rate < 30%) — memory is context only, not rule input

# Design: Tier-2 QuestDB Dual-Write

**Date:** 2026-05-06
**Scope:** `agents/tier2_signals.py` — add parallel write to QuestDB `signals` table

## Problem

`tier2_signals.py` currently writes BUY/SELL signals to Supabase only.
QuestDB `signals` table exists with schema live but receives no data.

## Decision

Dual-write BUY/SELL signals: Supabase is primary, QuestDB is parallel.
QuestDB failure = warn + continue. HOLD signals are not written to either store.

## Implementation

### New function: `log_signal_questdb(data, signal)`

Added to `agents/tier2_signals.py`. Called in `main()` inside the existing
`if signal["signal"] != "HOLD":` guard, immediately after `log_paper_trade()`.

Uses `questdb_client.executemany(sql, [row])` — single-row call with `%s`
parameterization so psycopg2 handles escaping (safe for Claude-generated `reason` strings).

### Column mapping

| signals column | value |
|---|---|
| `ts` | `now_utc.replace(hour=0, minute=0, second=0, microsecond=0)` |
| `signal_id` | `f"{ticker}_{now_utc.strftime('%Y%m%d')}"` |
| `symbol` | `data['ticker']` |
| `strategy` | `'tier2-swing'` |
| `direction` | `signal['signal']` |
| `confidence` | `float(signal['confidence'])` |
| `entry_target` | `signal['entry']` |
| `stop_loss` | `signal['stop_loss']` |
| `take_profit` | `signal['target']` |
| `reasoning` | `signal['reason']` |
| `source` | `'claude-haiku'` |
| `triggered` | `False` |
| `trade_id` | `''` |

### DEDUP idempotency

Schema: `DEDUP UPSERT KEYS(ts, signal_id)`

`now_utc = datetime.now(timezone.utc)` is computed once per signal. `ts` is
normalized to **start-of-day UTC** (midnight). `signal_id` is `{ticker}_{YYYYMMDD}`.
Both derived from the same instant — no midnight race. Deterministic across
re-runs on the same day, so DEDUP fires correctly and re-runs produce upserts.

Using `datetime.now(timezone.utc)` (not deprecated `datetime.utcnow()`).

### Import change

`from datetime import datetime, timedelta` → add `timezone`.

### Error handling

```python
try:
    questdb_client.executemany(sql, [row])
    print("  -> QuestDB signal logged")
except Exception as e:
    print(f"  -> QuestDB write failed (non-fatal): {type(e).__name__}: {e}")
```

No re-raise. Supabase flow is never affected.

## Files changed

- `agents/tier2_signals.py` — add import, add function, add one call in `main()`
- No changes to `utils/questdb_client.py`
- No changes to `sql/schema_v1.sql`

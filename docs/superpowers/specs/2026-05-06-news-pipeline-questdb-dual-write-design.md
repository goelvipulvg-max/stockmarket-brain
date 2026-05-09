# Spec: News Pipeline QuestDB Dual-Write
**Date:** 2026-05-06
**Phase:** 3.5 Part 2
**Status:** Approved — reviewed 2026-05-06

---

## Problem

`agents/tier1_news.py` writes all fetched articles to Supabase `news_log` and sends high-score ones to Telegram. QuestDB `news_events` table exists (schema_v1.sql) but receives no data. We want the same dual-write pattern established in Phase 3.5 Part 1 (tier2_signals.py → QuestDB signals).

---

## Scope

- **In:** Add QuestDB parallel write for every article that already gets written to Supabase `news_log`.
- **Out:** Symbol extraction from headlines (deferred — no per-ticker NLP today), changes to Supabase flow, changes to Telegram flow, score threshold changes.

---

## Target Table

```sql
CREATE TABLE IF NOT EXISTS news_events (
    ts        TIMESTAMP,
    event_id  STRING,
    source    SYMBOL CAPACITY 32 INDEX,
    symbol    SYMBOL CAPACITY 1024 INDEX,
    headline  STRING,
    url       STRING,
    sentiment DOUBLE,
    category  SYMBOL CAPACITY 32,
    summary   STRING
) TIMESTAMP(ts) PARTITION BY MONTH WAL DEDUP UPSERT KEYS(ts, event_id, symbol);
```

DEDUP key: `(ts, event_id, symbol)` — three-column key. With `symbol="MARKET"` (constant), this effectively reduces to `(ts, event_id)` — one row per article per day.

---

## Column Mapping

| QuestDB column | Source in tier1_news.py | Notes |
|---|---|---|
| `ts` | `published_parsed` from feedparser entry if available; else `datetime.now(timezone.utc)` truncated to midnight | See ts strategy below. Must be naive UTC — QuestDB 9.3.5 rejects timestamptz over Postgres wire. |
| `event_id` | `url_hash(url)` | Already computed by existing helper. Stable, unique per URL. |
| `source` | `source` param | Direct passthrough (e.g. "ET Markets"). |
| `symbol` | `"MARKET"` | Literal placeholder. No ticker extraction today. Part of DEDUP key — must be non-null. |
| `headline` | `title` | Direct passthrough. May contain apostrophes — MUST use parameterized query. |
| `url` | `url` | Direct passthrough. |
| `sentiment` | `float(score)` | Raw 1–10 scale from Haiku classifier. No normalization. |
| `category` | `category` | Direct passthrough ("bullish"/"bearish"/"neutral"). |
| `summary` | `summary` or `""` | Empty string if summary is None/empty. Parameterized query mandatory. |

---

## ts Strategy — pubDate vs Ingestion Time

**feedparser 6.0.12** (confirmed from `.venv` source) exposes `entry.published_parsed` as a `time.struct_time` **already normalized to UTC**. Handles `<pubDate>`, `<published>`, `<issued>`, `<dc:date>` tag variants.

```python
pub = entry.get("published_parsed")
if pub:
    ts = datetime(*pub[:6])   # naive UTC — feedparser already normalized
else:
    # pubDate absent from feed — fall back to midnight UTC ingestion ts
    # NOTE: intraday granularity lost for this article; future backtesting
    # will see it as 00:00:00 UTC on the ingestion day.
    ts = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
```

Both paths produce naive UTC datetime. DEDUP fires correctly: same article on same day always maps to the same `ts` (pubDate is stable; fall-back is run-date-stable within same day).

**`ts` is computed at the call site (in `run()` loop), passed into `log_news_questdb()`** — not computed inside the function — so pubDate from the RSS entry is available.

---

## New Function

```python
def log_news_questdb(ts, source, url, title, score, category, summary):
    """Parallel write to QuestDB news_events. Non-fatal — warns and continues on failure."""
```

**Signature change vs original spec:** `ts` is now a parameter (computed in `run()` where the RSS entry is in scope) rather than computed inside the function.

**Single `datetime.now(timezone.utc)` call** only needed for the fall-back path — kept at call site.

**Key implementation notes:**
- `event_id = url_hash(url)` — deterministic from URL
- `symbol = "MARKET"` — placeholder; future symbol extraction will require a backfill decision for historical rows
- `summary = summary or ""` — guard for None/empty
- Parameterized INSERT via `questdb_client.executemany(sql, [row])`
- Wrapped in `try/except Exception` — prints warning, does NOT re-raise

---

## Call Site

`ts` computed in `run()` loop at entry processing time:

```python
for entry in entries:
    url     = entry.get("link", "").strip()
    title   = entry.get("title", "").strip()
    snippet = entry.get("summary", "")
    pub = entry.get("published_parsed")
    if pub:
        entry_ts = datetime(*pub[:6])
    else:
        entry_ts = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
    ...
    log_article(source, url, title, score, category, summary, entry_ts)
```

`log_article()` signature extended to accept `ts` and pass it to `log_news_questdb()`:

```python
def log_article(source, url, title, score, category, summary, ts):
    supabase.table("news_log").insert({...}).execute()
    log_news_questdb(ts, source, url, title, score, category, summary)   # ← ADD
```

`log_news_questdb` handles its own exception — if QuestDB is down, `log_article` returns normally.

---

## Import

Add at top of `tier1_news.py`:

```python
import utils.questdb_client as questdb_client
```

Same import pattern as `tier2_signals.py`.

---

## DEDUP Behaviour

- Same article ingested twice on the same day → 1 row (UPSERT fires on `ts + event_id + symbol`)
- Same article next day → new row (different `ts` from pubDate or fall-back midnight)
- `symbol = "MARKET"` is consistent across runs — DEDUP fires correctly
- pubDate is stable per article — re-running the agent produces the same `ts`, same DEDUP

---

## What Does NOT Change

- `log_article()` Supabase insert — unchanged (only signature extended)
- `is_duplicate()` URL-hash check against Supabase — unchanged
- Telegram send logic — unchanged
- `utils/questdb_client.py` — unchanged
- Score threshold (`SCORE_THRESHOLD = 6`) — unchanged; QuestDB gets ALL articles, same as Supabase

---

## Failure Modes

| Scenario | Behaviour |
|---|---|
| QuestDB down | `log_news_questdb` catches exception, prints warning, returns. Supabase write succeeds. |
| Duplicate insert | DEDUP UPSERT fires — 1 row, no error |
| Apostrophe in title/summary | Parameterized query handles safely |
| `summary` is None or empty | `summary or ""` coerces to empty string |
| `score` not castable to float | `float(score)` raises — caught by outer try/except |
| Feed item missing pubDate | Fall-back to midnight UTC ingestion ts; comment notes granularity loss |

---

## Testing Strategy — 7 unit tests (mock-based, no live QuestDB)

Mirror structure of `tests/test_tier2_questdb_write.py`.

| # | Test | What it asserts |
|---|---|---|
| 1 | Happy path | `executemany` called once with correct column values |
| 2 | QuestDB down | Exception in `executemany` → function returns without raising; Supabase write unaffected |
| 3 | Duplicate idempotency (mock) | Second call with same args → `executemany` called again (DEDUP handled at DB level, not app level) |
| 4 | Score edge values | `score=0` and `score=10` → `sentiment` = 0.0 and 10.0 respectively |
| 5 | Apostrophe in headline | Title `"India's RBI cuts rates"` → `executemany` called; no SQL injection or crash |
| 6 | Empty / None summary | `summary=None` and `summary=""` → `executemany` called with `""` as summary value, no crash |
| 7 | `ts.tzinfo is None` | Assert that `ts` passed to QuestDB has no tzinfo — regression guard for Part 1 timestamptz bug |

---

## Files Changed

| File | Change |
|---|---|
| `agents/tier1_news.py` | Add `log_news_questdb()`, extend `log_article()` signature, add `entry_ts` computation in loop, add import |
| `tests/test_news_questdb_write.py` | New — 7 unit tests |

No other files change.

# Plan: News Pipeline QuestDB Dual-Write
**Date:** 2026-05-06
**Phase:** 3.5 Part 2
**Spec:** docs/superpowers/specs/2026-05-06-news-pipeline-questdb-dual-write-design.md
**Status:** Draft — awaiting review

---

## Files Touched

| File | Change type |
|---|---|
| `agents/tier1_news.py` | Modify — add import, `entry_ts` in loop, extend `log_article()` signature, add `log_news_questdb()` |
| `tests/test_news_questdb_write.py` | Create — 7 unit tests |

No other files change. `utils/questdb_client.py` and `sql/schema_v1.sql` are read-only references.

---

## Step 1 — Write failing tests (TDD red phase)

Create `tests/test_news_questdb_write.py` with 7 tests. All must fail (ImportError or AssertionError) before implementation exists.

Tests (mirror structure of `tests/test_tier2_questdb_write.py`):

```
test_happy_path
    Mock questdb_client.executemany.
    Call log_news_questdb(ts, source, url, title, score, category, summary).
    Assert executemany called once.
    Assert row tuple contains correct values at known indices.

test_questdb_down_is_nonfatal
    Mock questdb_client.executemany to raise Exception("connection refused").
    Call log_news_questdb(...).
    Assert no exception raised (function swallows it).

test_duplicate_call_invokes_executemany_twice
    Call log_news_questdb twice with identical args.
    Assert executemany called exactly twice (DEDUP is DB-side, not app-side).

test_score_edge_values
    score=0  → sentiment param == 0.0
    score=10 → sentiment param == 10.0

test_apostrophe_in_headline
    title = "India's RBI cuts rates by 25bps"
    Assert executemany called without raising (parameterized query safe).

test_none_and_empty_summary
    summary=None → executemany called; summary value in row == ""
    summary=""   → executemany called; summary value in row == ""

test_ts_has_no_tzinfo
    Pass ts=datetime(2026, 5, 6, 10, 30, 0) (naive, no tzinfo).
    Assert ts argument captured by executemany has tzinfo == None.
    (Regression guard — Part 1 bug: timezone-aware ts rejected by QuestDB 9.3.5.)
```

**Verification:** `.\venv\Scripts\python.exe -m pytest tests/test_news_questdb_write.py -v` — expect 7 FAILED (function not yet defined).

---

## Step 2 — Implement `log_news_questdb()` in tier1_news.py (TDD green phase)

**2a. Add import** at top of `agents/tier1_news.py` (after existing imports):

```python
import utils.questdb_client as questdb_client
```

**2b. Add `log_news_questdb()` function** after `log_article()`:

```python
def log_news_questdb(ts, source, url, title, score, category, summary):
    # symbol="MARKET" is a placeholder — no per-article ticker extraction today.
    # Future symbol extraction will require a backfill decision for historical rows.
    try:
        sql = (
            "INSERT INTO news_events "
            "(ts, event_id, source, symbol, headline, url, sentiment, category, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        row = (
            ts,
            url_hash(url),
            source,
            "MARKET",
            title,
            url,
            float(score),
            category,
            summary or "",
        )
        questdb_client.executemany(sql, [row])
        print(f"  -> QuestDB news_event logged")
    except Exception as e:
        print(f"  -> QuestDB write failed (non-fatal): {type(e).__name__}: {e}")
```

**2c. Extend `log_article()` signature** to accept and forward `ts`:

```python
def log_article(source, url, title, score, category, summary, ts):
    supabase.table("news_log").insert({
        ...existing fields unchanged...
    }).execute()
    log_news_questdb(ts, source, url, title, score, category, summary)
```

**2d. Add `entry_ts` computation** in `run()` loop and pass to `log_article()`.

Add `from datetime import datetime, timezone` if not already imported (it is — line 7).

In the `for entry in entries:` loop, after extracting `url`, `title`, `snippet`:

```python
pub = entry.get("published_parsed")
if pub:
    entry_ts = datetime(*pub[:6])          # already naive UTC from feedparser
else:
    # pubDate absent — fall back to midnight UTC ingestion ts.
    # NOTE: intraday granularity lost for this article; future backtesting
    # will see it as 00:00:00 UTC on the ingestion day.
    entry_ts = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
```

Update `log_article()` call:

```python
log_article(source, url, title, score, category, summary, entry_ts)
```

**Verification:** `.\venv\Scripts\python.exe -m pytest tests/test_news_questdb_write.py -v` — expect 7 PASSED.

---

## Step 3 — Live smoke test (requires QuestDB running at localhost:8812)

Run once:
```
.\venv\Scripts\python.exe agents\tier1_news.py
```

Check QuestDB Web Console (http://localhost:9000):
```sql
SELECT count() FROM news_events;
SELECT * FROM news_events LIMIT 5;
```

Expect: rows with real pubDate timestamps (not all midnight), source values matching RSS_FEEDS keys, symbol="MARKET", sentiment 1.0–10.0.

**DEDUP idempotency check** — run agent a second time:
```
.\venv\Scripts\python.exe agents\tier1_news.py
```

Re-query:
```sql
SELECT count() FROM news_events;
```

Expect: count unchanged (UPSERT fired, no duplicates).

---

## Step 4 — Commit and push

Stage only the two changed files:

```
git add agents/tier1_news.py tests/test_news_questdb_write.py
git commit -m "feat(tier1): dual-write news articles to QuestDB news_events table"
git push origin main
```

---

## Rollback

If something breaks: `git revert HEAD` — removes dual-write, restores original `tier1_news.py`. Supabase flow is unaffected (fail-safe wrapper means QuestDB errors never propagate).

# Phase 4 — Batch A Execution Brief — Memory Seeding

**For:** Antigravity (Claude Code) execution
**Repo:** `goelvipulvg-max/stockmarket-brain` · Working dir `C:\dev\stockmarket-brain\`
**Reference:** `docs/stockmarket-brain-v3.1-master-plan.md` §6 Phase 4
**Scope:** Batch A only — memory seeding + `filings_log` backfill. Batch B (Phase 4b/4c) is a SEPARATE brief, do NOT build it here.

---

## 0. READ THIS FIRST — Reality Corrections (recon-verified)

A recon pass on `event_outcomes` (Neon) found the master plan §6 pseudocode
makes assumptions that **do not match the actual data**. The plan's
`seed_memory_from_event_outcomes()` is pseudocode only — follow THIS brief's
corrected logic, NOT the plan's printed code.

| # | Master plan assumed | Recon-verified reality | Required handling |
|---|---|---|---|
| C1 | `trade_result` is a clean enum (WIN/LOSS) mapped by `map_trade_result()` | `trade_result` is a **full AI summary text** with a `" \| Days to impact: N"` suffix — effectively unique per row, NOT an enum | Do NOT parse `trade_result` for the outcome. Use `outcome_score` instead (see C2). Store raw `trade_result` text into `full_context` JSONB only. |
| C2 | `outcome_score` is numeric, used directly | `outcome_score` is **text** (`'-5.72'`, `'4.04'`) | `float()`-cast before any compare/math. Guard against bad/empty values. |
| C3 | `signal_generated` is boolean | `signal_generated` is **text** (`'True'` / `'False'`) | Cast via `str(v).strip().lower() == 'true'` if used. |
| C4 | all event types covered | only **3** event_types exist: dividend (1,382), buyback (34), split (14) | Acceptable — seed all 1,430 rows as-is. Just know per-type aggregates beyond these 3 will be empty. |

**`event_outcomes` actual schema (8 cols):** `id`, `symbol` (bare, no `.NS`),
`event_type`, `event_date`, `signal_generated` (text), `trade_result` (text),
`outcome_score` (text), `created_at`. Total **1,430 rows**.

### Outcome mapping rule — LOCKED (±3% threshold)

`trade_memory_v2.outcome` is derived from `outcome_score`, using the **same ±3%
convention as `filing_memory.swing_verdict`** — one consistent definition of a
good/bad outcome across the whole memory system:

```
score = float(outcome_score)
score >  3.0   -> 'TARGET_HIT'
score < -3.0   -> 'SL_HIT'
otherwise      -> 'EXPIRED'
if outcome_score is missing/unparseable -> 'EXPIRED', and log a [WARN]
```

> **Caveat to preserve:** `event_outcomes.outcome_score` and
> `filing_memory.alpha_10d` are not provably the same measure — `outcome_score`'s
> exact semantics (raw move vs alpha, which window) is not 100% confirmed. We use
> ±3% for *convention consistency*, and we keep the mapping **reversible** by
> storing the raw `outcome_score` and raw `trade_result` in `full_context` JSONB.
> If the semantics are clarified later, rows can be re-mapped from `full_context`.

---

## Working agreements (unchanged — follow strictly)

- **Confirm-first, one file at a time.** Build/edit ONE file, then STOP for an
  individual edit approval. Never "allow all edits" — always approve each edit.
- **Recon before assuming.** If anything diverges from this brief, STOP and
  report — do not silently self-correct.
- **DDL only via Supabase Dashboard SQL Editor.** No DDL through supabase-py.
  Batch A has NO new DDL — all target tables already exist (verified: V1.5,
  V1.5b green).
- **Throwaway scripts** (`scripts/recon_*`, `scripts/check_*`, `scripts/smoke_*`)
  are deleted after use, never committed. Real tests (`tests/test_phase4_*`) ARE
  committed.
- **Windows:** `₹` crashes on cp1252 — use `Rs.` in all printed/stored strings.
  Inline `python -c` hits PowerShell's ~965-byte limit — write logic to a `.py`
  file and run with `.venv\Scripts\python.exe` + `PYTHONPATH=C:/dev/stockmarket-brain`.
  `Get-ChildItem` is a PowerShell cmdlet — do not force it through the Bash tool.
- **Git:** one command at a time. Add files explicitly (never `git add .`).
  Multi-line commit messages via heredoc. **After the commit, an explicit
  `git push`** — Antigravity does NOT auto-push.
- Machine-local files (`.claude/settings.local.json`, `scheduled_tasks.lock`,
  `dumps/`) are never committed.
- **No gassing** — every gate backed by real output. State FAIL/BLOCKED honestly.

---

## STEP 1 — `agents/memory_seed.py` — event_outcomes → trade_memory_v2

Create `agents/memory_seed.py`. A one-time idempotent seeding script.

**Function `seed_memory_from_event_outcomes()`:**

1. Read all rows: `SELECT * FROM event_outcomes` (Neon — use the canonical
   `get_neon_connection()` direct + psycopg2 pattern, or `neon_client.query()`
   for this read-only no-param query).
2. **Idempotency guard:** before inserting, check if seeding already ran —
   `SELECT count(*) FROM trade_memory_v2 WHERE source_type = 'SEED_EVENT_OUTCOME'`.
   If count > 0, print a `[SKIP] seeding already done (N rows)` and return
   without inserting. This makes the script safe to re-run.
3. For each `event_outcomes` row, build a `trade_memory_v2` insert dict:
   - `source_type` = `'SEED_EVENT_OUTCOME'`
   - `symbol_base` = `row['symbol']` (bare — already no `.NS`)
   - `event_type` = `row['event_type']`
   - `sector` = looked up from `company_profiles` (Neon) by symbol. The
     `company_profiles` symbols ARE `.NS`-suffixed — so query with
     `row['symbol'] + '.NS'`. If not found, `sector = None`.
   - `outcome` = the ±3% rule from §0 applied to `float(outcome_score)`.
   - `pattern_tags` = `['event_<type>', 'sector_<sector_or_unknown>', 'source_seed']`
     (lowercase, spaces → underscores).
   - `full_context` (JSONB) = `{'outcome_score_raw': row['outcome_score'],
     'trade_result_raw': row['trade_result'], 'event_date': str(row['event_date']),
     'signal_generated': row['signal_generated']}` — raw values preserved for
     reversibility (see §0 caveat).
   - `pnl_pct`, `holding_days`, `haiku_reasoning`, `deepseek_reasoning`,
     `nifty_mood`, `market_cap_cr`, `paper_trade_id` → leave NULL (seed rows
     have no live-trade data).
4. **Sector lookup efficiency:** do ONE `SELECT symbol, sector FROM company_profiles`
   up front, build a dict, reuse it — do not query per-row (1,430 queries is slow).
5. **Insert in batches** (e.g. 100 rows per `supabase.table(...).insert([...])`
   call) — not 1,430 single inserts.
6. Print a summary: total read, total inserted, outcome distribution
   (`TARGET_HIT` / `SL_HIT` / `EXPIRED` counts), how many had a sector matched,
   how many `[WARN]` unparseable scores.

Add an `if __name__ == '__main__': seed_memory_from_event_outcomes()` block so
it can be run directly.

**→ STOP after creating this file. Wait for edit approval. Do NOT run it yet.**

---

## STEP 2 — run STEP 1's seed + verify (no new file)

1. Run: `$env:PYTHONPATH="C:/dev/stockmarket-brain"; .venv\Scripts\python.exe agents\memory_seed.py`
2. Paste the full summary output.
3. **Do not proceed to Step 3 until the summary looks sane** — expect ~1,430
   inserted, outcome distribution non-degenerate (not all one bucket).

**→ STOP after running. Report the output.**

---

## STEP 3 — pattern extraction → pattern_insights

Add a function `extract_initial_patterns()` to `agents/memory_seed.py` (same
file — this is a second function, not a new file).

1. Read seeded rows: `SELECT * FROM trade_memory_v2 WHERE source_type = 'SEED_EVENT_OUTCOME'`.
2. Group by `(sector, event_type)`. For each group with **n >= 5**:
   - `sample_size` = n
   - `win_rate` = fraction of rows with `outcome = 'TARGET_HIT'` (a plain
     reproducible ratio — round to 3 decimals)
   - `avg_outcome_score` = mean of `float(full_context['outcome_score_raw'])`,
     skipping unparseable values
   - `confidence` = `'HIGH'` if n>=20, `'MEDIUM'` if n>=10, else `'LOW'`
   - `pattern_key` = `f"{sector_or_unknown}_{event_type}"` (lowercase, spaces→`_`)
   - `insight_text` = a short factual sentence, e.g.
     `"dividend events in <sector>: <n> samples, <win_rate*100>% positive, avg score <x>"`
   - `event_type`, `sector` columns set accordingly; `active = True`
3. **Idempotency:** `pattern_insights` has `uniq_pattern_key` UNIQUE WHERE
   `active = TRUE`. Use upsert semantics — `supabase.table('pattern_insights')
   .upsert(row, on_conflict='pattern_key')` — so re-running refreshes, never
   duplicates.
4. Print: number of groups, how many passed n>=5, how many were skipped for
   being too small.

Add `extract_initial_patterns()` to the `__main__` block (after seeding).

**→ STOP after editing the file. Wait for edit approval.**

---

## STEP 4 — run pattern extraction + verify

1. Run `agents\memory_seed.py` again (seeding will `[SKIP]` per its idempotency
   guard; pattern extraction runs).
2. Paste the pattern-extraction summary.

**→ STOP. Report output.**

---

## STEP 5 — `agents/filings_log_backfill.py` — filings_log → filing_memory

This is master plan §3.10 NOTE 1: a one-time backfill of existing **material**
`filings_log` rows into `filing_memory`. Recon count: **146 candidate rows**
(`material_score >= 6 AND event_type != 'OTHER'`).

Create `agents/filings_log_backfill.py`. Function `backfill_filings_log()`:

1. Read candidates from Supabase:
   `filings_log` where `material_score >= 6 AND event_type != 'OTHER'`.
2. For each row, build a `filing_memory` insert dict matching its schema
   (§4.4b): `url_hash`, `symbol_base`, `company_name`, `sector`, `event_type`,
   `material_score`, `filing_date`, `filing_timestamp`, `raw_title`,
   `ai_summary`, `pdf_extract`. Outcome columns (`base_price`, `alpha_*`,
   `outcome_*_status`) are left at their schema defaults (`PENDING`) — Batch B's
   backfill job fills them.
   - **`url_hash`:** use the row's existing `url_hash`. If a row has a NULL
     `url_hash`, **SKIP it with a `[WARN]`** — do NOT synthesize a hash (master
     plan §3.7: synthesizing risks duplicates). Report the skip count.
   - `filing_timestamp`: use `filings_log.classified_at` (NOT `published_at` —
     `published_at` is a verified-dead NULL column per §3.7 / V0.8).
   - `filing_date`: derive from `classified_at::date` if no dedicated column.
3. **Idempotency:** insert with `on_conflict='url_hash'` (the
   `filing_memory_url_hash_key` UNIQUE constraint — verified V1.5b green). A
   re-run inserts 0 duplicates. The §3.7 sync job may already have synced some
   of today's rows — `on_conflict` handles the overlap cleanly.
4. Print: candidates read, inserted, skipped-for-NULL-url_hash, skipped-as-duplicate.

Add an `if __name__ == '__main__'` block.

**→ STOP after creating the file. Wait for edit approval. Do NOT run yet.**

---

## STEP 6 — run backfill + verify

1. Run `agents\filings_log_backfill.py`.
2. Paste the summary.
3. Run it a SECOND time — confirm it inserts 0 new rows (idempotency).

**→ STOP. Report both runs' output.**

---

## STEP 7 — `tests/test_phase4_batchA.py` — committed gate test

Create `tests/test_phase4_batchA.py`. It must verify, with real assertions and
clear PASS/FAIL prints, the Batch A gates:

- **V4.1** — `trade_memory_v2` has ~1,430 rows with `source_type='SEED_EVENT_OUTCOME'`.
- **V4.1b** — `filing_memory` contains backfilled rows from `filings_log`
  (count of material backfilled rows > 0; and total ≈ 146 minus NULL-url_hash skips,
  allowing for overlap with already-synced rows).
- **V4.2** — `pattern_insights` has rows with `active=True` and valid
  `confidence` values.
- **V4.3** — a `get_relevant_patterns(event_type, sector)` style query returns
  at least one pattern for a known event type (`'dividend'`). If a
  `get_relevant_patterns()` helper does not exist yet, the test may inline the
  equivalent `pattern_insights` SELECT — do not build new production code in
  the test file.

Each gate prints `V4.x PASS` / `V4.x FAIL` with the actual numbers. The test
must exit non-zero if any gate fails.

**→ STOP after creating the file. Wait for edit approval.**

---

## STEP 8 — run the gate test

1. Run `tests\test_phase4_batchA.py`.
2. Paste full output — every gate's PASS/FAIL with numbers.

**→ STOP. Report.**

---

## STEP 9 — commit + push

Only after Steps 1–8 are green. Add files **explicitly**:

```
git add agents/memory_seed.py agents/filings_log_backfill.py tests/test_phase4_batchA.py
git status        # confirm ONLY these 3 files staged — no .claude/, no dumps/
git commit -m "$(cat <<'EOF'
feat(phase-4): Batch A — memory seeding + filings_log backfill

- agents/memory_seed.py: seeds 1,430 event_outcomes rows into trade_memory_v2
  (outcome via outcome_score +/-3% rule; trade_result is unstructured text,
  stored raw in full_context); extract_initial_patterns() -> pattern_insights
- agents/filings_log_backfill.py: one-time backfill of 146 material
  filings_log rows into filing_memory (master plan NOTE 1), url_hash dedup,
  filing_timestamp from classified_at
- tests/test_phase4_batchA.py: gates V4.1, V4.1b, V4.2, V4.3
EOF
)"
git push
```

Confirm the push succeeded (`git log --oneline -3` shows the commit, and the
branch is not ahead of origin).

**→ STOP. Report the commit hash and push confirmation.**

---

## Done criteria for Batch A

- [ ] `memory_seed.py` created, runs idempotently, ~1,430 seed rows in `trade_memory_v2`
- [ ] `pattern_insights` populated via upsert (no duplicates on re-run)
- [ ] `filings_log_backfill.py` created, 146 candidates backfilled to `filing_memory`, 2nd run inserts 0
- [ ] `test_phase4_batchA.py` — V4.1, V4.1b, V4.2, V4.3 all PASS
- [ ] One commit, pushed, only the 3 intended files

Batch B (Phase 4b outcome backfill job + Phase 4c retrieval brief) is a
SEPARATE brief — do not start it. After Batch A, STOP and report back.

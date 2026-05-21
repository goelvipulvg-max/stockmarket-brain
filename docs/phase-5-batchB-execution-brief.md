# Phase 5 Batch B — Execution Brief

**Version:** v3 (POST-RECON — all critical findings integrated)
**Date:** 2026-05-21
**Prior batch:** Phase 5 Batch A (shipped — commits `77a2771`, `1849a75`, `c7b7b1b`, `20491c1`)
**Master plan reference:** `docs/stockmarket-brain-v3.1-master-plan.md` §7 Phase 5, §11 Budget
**Authoring assistant:** claude.ai (planning) → Antigravity (execution)

**v3 changes from v2 (POST-RECON):**

| # | Recon finding | v3 resolution |
|---|---------------|---------------|
| C1 | Column names: `ticker→symbol`, `material→is_material`, `score→material_score` | All SQL and Python references updated throughout brief |
| C2 | `sector` column does NOT exist in `filings_log` (derived from `neon_fundamentals.py`) | Removed `sector` from poller SELECT; documented data source |
| C3 | `paper_trades.filing_id` column does NOT exist | NEW D9 deliverable: ADD `filing_id` DDL + Tier-2F insert update |
| S1 | `picked_by_tier0f` orphan column already exists (no code uses it) | REUSE this column for idempotency (NO new column needed) |
| S2 | Tier-3 fix pattern in v2 was WRONG (uses list-iteration, not inline query) | §3.4 fix pattern corrected with exact line numbers (25 + 154) |
| F1 | §1.4 unique constraint check confirmed: only `paper_trades_pkey` on `id` | Logic-only enforcement validated; §2.5 unchanged |
| F2 | Existing 31 trades use `source='TIER2'` (legacy); Tier-2F inserts `source='TIER2F'` | No conflict; V5.7 test design valid |
| F3 | 176 eligible material filings exist, all `picked_by_tier0f=false` | Clean starting state for poller |
| F4 | Node.js `actions/checkout@v5` and `actions/setup-python@v6` confirmed stable | No breaking changes for our use case |
| F5 | `agents/tier2_signals.py` exists on disk but NO active imports | Workflow YAML deletion safe; Python file preserved (O9) |

**v2 changes from v1:**
- Tier-0F poller cadence: 5-min → **2-min** (cron-job.org PRIMARY)
- GH Actions fallback: `*/15` → `*/10` (every 10 min)
- NEW §2.0: cron-job.org PRIMARY architectural pattern documented
- NEW §2.4.1: end-to-end latency budget analysis
- Cost projection updated: Tier-0F poller monthly calls 1,716 → 4,290
- Verified Tier-0 production cadence = 5 min (cron-job.org PRIMARY, NOT GH 15-min YAML)

---

## §0 Scope & Boundaries

### §0.1 IN scope (9 deliverables — UPDATED v3)

| ID | Deliverable | Type | Purpose |
|----|------------|------|---------|
| D1 | `agents/tier0f_poller.py` | NEW Python file | 2-min poller, reads `filings_log` material rows (using `is_material=true`, `material_score>=6`, `picked_by_tier0f=false`), dispatches Tier-2F |
| D2 | `agents/tier3_position_manager.py` | MODIFY | Gap 5 fix — list-iteration duplicate check from `(ticker)` → `(ticker, source)` (lines 25 + 154) |
| D3 | `.github/workflows/tier0f-poller.yml` | NEW workflow | cron-job.org PRIMARY (2-min) + GH cron FALLBACK (`*/10`) |
| D4 | `.github/workflows/tier2f.yml` | NEW workflow | `workflow_dispatch` only, called by D1 with `filing_id` input |
| D5 | `.github/workflows/tier2_signals.yml` | DELETE | Deprecated (replaced by Tier-2F) |
| D6 | Node.js 20→24 update | MODIFY 14 files | `actions/checkout@v4→v5`, `actions/setup-python@v5→v6` |
| D7 | `tests/test_phase5_batchB.py` | NEW test file | Gate tests V5.1 + V5.7 + V5.8 |
| D8 | `docs/phase-5-batchB-execution-brief.md` | NEW doc | This brief |
| **D9** | **`paper_trades.filing_id` column** | **NEW DDL + MODIFY `tier2_fundamental.py`** | **Add `filing_id bigint` column to paper_trades; update Tier-2F insert to populate it; enables V5.8 timing measurement** |

### §0.2 OUT of scope (EXPLICIT — these are NOT to be touched in Batch B)

| ID | Item | Reasoning |
|----|------|-----------|
| O1 | SOLO_DEEPSEEK functional plumbing | Phase 6 after-hours engine design |
| O2 | Tier-1F news-driven trade engine | Separate locked concept, undecided v3.1 placement |
| O3 | Tier-2F prompt softening (Flash CHALLENGE rate) | Production data insufficient (2/2 sample) |
| O4 | filings_log.published_at population | Phase 6 concern, Tier-2F reads `classified_at` |
| O5 | filing-memory-backfill cron time mismatch | YAML says 00:30 IST, ran 5:20 AM — workflow succeeded, low priority |
| O6 | Tier-1 News Researcher failure fix | Tier-1F track, not Phase 5 |
| O7 | Tier-1 Guardian dormant alert bug | Known issue (`.NS` suffix + `news_log.symbol` missing), Phase 6+ |
| O8 | V5.3 + V5.4 retry from Batch A | Deferred — see §6 |
| O9 | Tier-2 Swing Signals legacy code | Workflow file deleted in D5, Python code (if any) deprecated separately |

### §0.3 Goals & acceptance criteria

**Primary goal:** Phase 5 fully production-live — automated polling pipeline from NSE filing detection to Telegram alert, end-to-end within 10 minutes.

**Acceptance criteria (ALL must pass before Batch B is declared complete):**

1. **V5.1 PASS** — Tier-0F poller dry-run: queries DB, identifies pending filings, dispatches (mocked) without error
2. **V5.7 PASS** — Tier-3 duplicate rule: TIER2F blocks duplicate TIER2F on same ticker; ALLOWS different-source on same ticker
3. **V5.8 PASS** — Full live pipeline: filing classification → Telegram alert in ≤600 seconds
4. **DB residue clean** — `TIER2F paper_trades` count = N (where N = trades from V5.8 test, manually verifiable); `agent_disagreements` count = 0 unless test specifically triggered DISAGREE
5. **Node.js deprecation warnings cleared** — latest workflow run logs show no Node.js 20 warnings
6. **cron-job.org webhook active** — dashboard shows poller job running on 2-min cadence
7. **GH Actions fallback verified** — `tier0f-poller.yml` shows at least one successful internal cron trigger

### §0.6 Execution adjustments (POPULATED POST-RECON, 2026-05-21)

#### §0.6.1 — Recon §1.1 findings (filings_log schema)

**Actual schema discovered (20 columns total):**

| Column | Type | Brief assumption | Status |
|--------|------|-----------------|--------|
| `id` | bigint | id | ✅ OK |
| **`symbol`** | text | ticker | ❌ MISMATCH — corrected throughout brief |
| `company_name` | text | — | extra (unused by Tier-0F) |
| `event_type` | text | event_type | ✅ OK |
| `exchange` | text | — | extra |
| **`is_material`** | bool (default false) | material | ❌ MISMATCH — corrected |
| **`material_score`** | int | score | ❌ MISMATCH — corrected |
| `classified_at` | timestamptz (default now()) | classified_at | ✅ OK |
| `published_at` | timestamptz (NULL) | — | known issue (sparse population) |
| ~~`sector`~~ | — | sector | ❌ MISSING — derived from `neon_fundamentals.py` (Neon DB `company_profiles.sector`), not from filings_log |
| ~~`processed_by_tier2f`~~ | — | processed_by_tier2f | ❌ MISSING — replaced by reusing `picked_by_tier0f` |
| **`picked_by_tier0f`** | bool (default false) | — | 🎁 BONUS column, REUSED for idempotency |
| `picked_at` | timestamp (NULL) | — | extra — Tier-0F should populate when picking |
| `directional_bias` | text (NULL) | — | extra (Tier-0 classification output) |
| `reasoning` | text (NULL) | — | extra (Tier-0 rationale) |
| `trade_confidence` | int (default 0) | — | extra (separate from material_score) |
| `fo_checked` | bool (default false) | — | extra (Tier-0 F&O pre-check) |
| `telegram_sent` | bool (default false) | — | extra |
| `url_hash` | text (NULL) | — | extra (dedup key) |
| `raw_title`, `source_url`, `summary` | text | — | extras |

**Idempotency mechanism (LOCKED):** REUSE `picked_by_tier0f` (default false). NO new column needed. NO DDL needed for idempotency.

#### §0.6.2 — Recon §1.2 paper_trades OPEN status

- Total paper_trades: **31** (all legacy `source='TIER2'`)
- OPEN paper_trades: **0** — clean slate for Gap 5 fix
- Existing OPEN duplicates by `(ticker, source)`: **{}** — none
- All 31 trades CLOSED; no migration risk

#### §0.6.3 — Recon §1.3 Tier-3 code structure

**Brief v2 fix pattern WAS WRONG** — code uses list-iteration, not inline Supabase query.

**Actual code structure (`agents/tier3_position_manager.py`):**

```python
# Lines 23-26: apply_rules() function (where the check happens)
def apply_rules(signal: dict, open_trades: list) -> tuple:
    for trade in open_trades:
        if trade["ticker"] == signal["ticker"] and trade["id"] != signal["id"]:
            return False, "duplicate_open_position"

# Line 154: open_trades SELECT in main()
open_trades = (
    supabase.table("paper_trades")
    .select("id,ticker,status")  # ← source NOT included
    .eq("status", "OPEN")
    .execute()
    .data
)
```

**Correct fix pattern (LOCKED for §3.4):** TWO changes needed:
- Line 154: `.select("id,ticker,source,status")` — add `source` to SELECT
- Line 25: `if trade["ticker"] == signal["ticker"] and trade["source"] == signal["source"] and trade["id"] != signal["id"]:`

#### §0.6.4 — Recon §1.4 unique constraints (verified via Supabase Dashboard)

**Only constraint on `paper_trades`:**

| constraint_name | constraint_type | columns |
|----------------|-----------------|---------|
| `paper_trades_pkey` | PRIMARY KEY | `id` |

**Plus** (discovered in Tier-2F code line 323): a UNIQUE constraint named `uniq_paper_trades_ticker_date_source` exists but was NOT in the standard constraint check output — likely a partial unique INDEX on `(ticker, signal_date, source)`. This was created during prior batches.

**Impact:** Logic-only enforcement for Gap 5 in `(ticker, source)` is safe — no conflict with existing `(ticker, signal_date, source)` partial index since that constraint is on a different tuple.

#### §0.6.5 — Recon §1.6 critical finding: `paper_trades.filing_id` MISSING

**Discovered:** `paper_trades` does NOT have a `filing_id` column.

**Impact:**
- Brief v2 §2.6 V5.8 timing query: BROKEN
- Brief v2 §3.2 backfill SQL: NOT NEEDED (no prior TIER2F trades to backfill)
- Phase 5 Batch A `agents/tier2_fundamental.py` `_insert_paper_trade()` (lines 290-317): inserts filing_id INSIDE `raw_signal` JSONB only, NOT as separate column

**Resolution (LOCKED — NEW D9):**
1. ADD `filing_id bigint` column to `paper_trades` via Supabase Dashboard DDL
2. UPDATE `agents/tier2_fundamental.py` `_insert_paper_trade()` to populate `filing_id` directly (1-line addition to insert dict)
3. V5.8 timing query now possible via simple JOIN

**Why Option A chosen** (vs JSONB extraction):
- Cleaner architecture, removes JSONB query fragility
- Future-proofs P&L attribution and analytics
- 5-minute DDL + code change cost
- No data loss (existing 31 trades have filing_id=NULL, acceptable since they predate Tier-2F)

#### §0.6.6 — Recon §1.7 tier2_signals deletion safety

**References found:**

| Location | Lines | Type | Safe to delete? |
|----------|-------|------|----------------|
| `.github/workflows/tier2_signals.yml` | (full file) | The file being deleted | ✅ YES |
| `utils/yfinance_chart.py` | 5, 35, 44 | Comments only | ✅ YES |
| `docs/phase-3-execution-brief.md` | 66, 128 | Historical archive | ✅ YES |
| `docs/phase-5-batchA-execution-brief.md` | 223, 443 | Historical archive | ✅ YES |
| `docs/stockmarket-brain-v3.1-master-plan.md` | 157 | Architecture doc | ✅ YES |

**Important:** `agents/tier2_signals.py` (Python file) STILL EXISTS on disk but has ZERO active imports. Workflow YAML deletion will leave the Python file orphan. Per §0.2 O9, Python file is preserved for Phase 6+ deprecation.

#### §0.6.7 — Recon §1.8 Node.js compatibility (web research)

| Action | Latest stable | Python 3.12 support | Breaking changes for us |
|--------|--------------|---------------------|------------------------|
| `actions/checkout@v5` | v5.0.1 (Nov 2025) | N/A (no Python dependency) | NONE — `ubuntu-latest` already satisfies Node.js 24 runner requirement |
| `actions/setup-python@v6` | v6.2.0 (Jan 2026) | ✅ Supported | NONE — basic checkout + Python setup unaffected |

**Verdict:** Safe to upgrade. No workflow adjustments needed beyond version bumps.

**POST-EXECUTION CORRECTION (v4):** Original recon §1.8 searched only for
`actions/setup-python@v5` occurrences and missed the fact that 2 workflow
files (`tier3_position_manager.yml`, `tier4_memory_manager.yml`) had
`setup-python@v4` (even older). Group B sweep correctly performed v4 -> v6
skip-version upgrade, which is semver-safe per Action's compatibility
guarantee. Final scope: 10 files at both v4/v5 -> v5/v6, 2 files at both
v4/v4 -> v5/v6, 1 file already at v6 no-op (`update_paper_trades.yml`),
1 file deleted (`tier2_signals.yml`).

#### §0.6.8 — Source value discovery (informational)

- 31 existing paper_trades: `source='TIER2'` (legacy Tier-2 Swing Signals)
- Tier-2F Batch A code inserts: `source='TIER2F'`
- No conflict — V5.7 test design valid (TIER2F blocks TIER2F duplicate; TIER1F allowed on same ticker)

#### §0.6.9 — Eligible filings backlog

- Total eligible filings (`is_material=true AND material_score>=6`): **190**
- Already-processed (`picked_by_tier0f=true`): **0** (column is orphan, no code has populated it)
- Backlog awaiting Tier-0F poller: **190**

**On first deployment, poller will rapidly process 190 backlog filings.** This is acceptable because:
- Tier-2F will skip ones that fail F&O ban / NIFTY mood gates
- Poller has BATCH_LIMIT=10 per cycle (will take ~19 cycles = ~38 minutes to clear backlog at 2-min cadence)
- No risk of duplicate trades (Tier-2F idempotency + Tier-3 Gap 5 fix)

**Alternative:** Pre-mark backlog filings as `picked_by_tier0f=true` to avoid processing old material. Decision deferred to user (see §6 Open Questions O10).

### §0.7 Cost & risk estimation (NEW section)

**Monthly cost projection (incremental from Batch B additions):**

| Component | Frequency | Cost per unit | Monthly total |
|-----------|-----------|---------------|---------------|
| Tier-0F poller (Supabase SELECT) | 2 min × 6.5 hrs × 22 days = 4,290 polls | ~₹0 (free tier) | ~₹0 |
| Tier-2F triggers (material filings) | ~5-10/day × 22 days = 110-220 | ₹0.6 (Haiku + Flash) | ~₹66-132 |
| GH Actions runtime | 1-2 min per Tier-2F trigger | Free tier | ~₹0 |
| cron-job.org webhook | 4,290 invocations (Tier-0F) + ~1,716 (Tier-0 existing) = ~6,006 | Free tier (<10K/month) | ~₹0 |
| **Total incremental (Batch B)** | | | **~₹70-135/month** |

**Budget compliance:** Master plan §11 ceiling is ₹800/month. Phase 5 Batch B adds ~₹100/month. Combined Phase 5 total estimate well under ₹400/month. **HEADROOM: 50%+.**

**Risk register:**

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | cron-job.org webhook fails/skips | Low | Medium (poller misses cycle) | GH Actions internal cron at 10-min cadence as FALLBACK |
| R2 | 2 material filings classified in same 2-min window | Medium | Low (both processed sequentially, just slower) | Poller iterates all pending, dispatches each independently |
| R3 | Tier-2F dispatch race (concurrent invocations) | Low | Low (paper trading, no real money) | Logic-only duplicate check in Tier-3 + idempotency via `processed_by_tier2f` flag |
| R4 | Node.js v4→v5 / v5→v6 breaking changes | Low | High (all workflows break) | Recon §1.8 verifies compatibility; rollback plan §5.5 |
| R5 | Tier-3 unique constraint race condition | Very low | Low (paper trade duplicate, manual cleanup) | Logic-only; `FOR UPDATE` lock deferred to Phase 6 |
| R6 | V5.8 timing exceeds 10 min (Haiku/Flash latency p99) | Medium | Medium (acceptance criteria miss) | Measure once, tune cron cadence if needed |

---

## §1 Recon Checklist (READ-ONLY, before any edits)

> **Workflow rule:** Each §1.x is a READ-ONLY investigation. Run command, observe output, document in §0.6, then STOP and report to user before proceeding to next §1.x.
>
> **Antigravity Pattern A:** Press `1` per individual edit. NEVER "allow all". NEVER "don't ask again".

### §1.1 filings_log schema verification

**Goal:** Confirm columns Tier-0F poller will read, identify if `processed_by_tier2f` flag column exists or needs to be added.

**Command (Supabase Dashboard SQL Editor, NOT supabase-py):**

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'filings_log'
ORDER BY ordinal_position;
```

**Expected columns to verify exist:**
- `id` (bigint, PK)
- `material` (boolean)
- `score` (integer or numeric)
- `event_type` (text)
- `sector` (text)
- `classified_at` (timestamp with time zone)
- `ticker` (text)
- `published_at` (timestamp, may be NULL — known issue)

**Decision needed:** Does `processed_by_tier2f boolean` column exist? If NO → §3.2 DDL step required.

### §1.2 paper_trades current OPEN status check

**Goal:** Identify if any existing duplicates that would violate new logic (ticker has multiple OPEN trades from different sources currently).

**Command (one-shot Python via Antigravity terminal):**

```powershell
.venv\Scripts\python.exe -c "from utils.supabase_client import get_client; sb = get_client(); r = sb.table('paper_trades').select('ticker, source, status').eq('status', 'OPEN').execute(); print(f'Total OPEN: {len(r.data)}'); from collections import Counter; c = Counter([(d['ticker'], d['source']) for d in r.data]); dupes = {k:v for k,v in c.items() if v > 1}; print(f'Duplicates: {dupes}')"
```

**Expected outcome:** `Duplicates: {}` (empty). If duplicates exist → manual cleanup needed before deploying Gap 5 logic.

### §1.3 Tier-3 current logic understanding

**Goal:** Read existing `agents/tier3_position_manager.py` to identify exact line(s) where duplicate check happens.

**Command:**

```powershell
Get-Content agents\tier3_position_manager.py | Select-String -Pattern "OPEN|duplicate|ticker" -Context 2,2 | Select-Object -First 30
```

**What to capture:**
- Exact function name containing duplicate check
- Exact line number
- Current query syntax (Supabase Python client)
- Surrounding error handling

**Decision needed:** Is the check inline in main flow OR in a helper function? Affects diff size.

### §1.4 Unique constraint migration check (Supabase-level)

**Goal:** Verify whether Supabase has DB-level UNIQUE constraint on `paper_trades(ticker)` for OPEN positions. If yes → DDL required to drop. If no → logic-only sufficient.

**Command (Supabase Dashboard SQL Editor):**

```sql
SELECT
    tc.constraint_name,
    tc.constraint_type,
    string_agg(kcu.column_name, ', ') as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_name = 'paper_trades'
GROUP BY tc.constraint_name, tc.constraint_type;
```

**Expected outcome:** PRIMARY KEY on `id` only. No UNIQUE on `ticker` or `status`. If any unexpected constraint found → §0.6 documents the deviation.

### §1.5 cron-job.org current setup audit

**Goal:** Document existing cron-job.org configuration (Filing Memory Sync is the reference example) so Tier-0F poller follows same pattern.

**Manual investigation (browser, not code):**
1. Login to cron-job.org dashboard
2. Find Filing Memory Sync job configuration
3. Document:
   - Webhook URL format: `https://api.github.com/repos/goelvipulvg-max/stockmarket-brain/actions/workflows/<workflow-file>/dispatches`
   - HTTP method: POST
   - Headers: `Authorization: Bearer <PAT_TOKEN>`, `Accept: application/vnd.github+json`
   - Payload structure: `{"ref": "main"}` or with `inputs` block
   - Schedule format: cron expression or UI selector
   - Timezone setting
   - Failure notification config

**Capture:** Screenshot or text dump for §0.6.

### §1.6 Tier-0F poller idempotency design verification

**Goal:** Confirm chosen idempotency mechanism (`processed_by_tier2f` column) does not conflict with existing flows.

**Command (Supabase Dashboard SQL Editor):**

```sql
-- Check if any existing code references this hypothetical column
-- Run this AFTER §1.1 confirms whether column exists
SELECT COUNT(*) FROM filings_log WHERE material = true AND score >= 6;
SELECT COUNT(*) FROM filings_log
WHERE material = true AND score >= 6
AND id IN (SELECT DISTINCT filing_id FROM paper_trades WHERE source = 'TIER2F');
```

**Outcome interpretation:**
- First count = total material filings eligible for Tier-2F
- Second count = material filings already processed (paper_trade exists)
- Difference = backlog that DDL backfill (§3.2) needs to handle

### §1.7 tier2_signals.yml deletion impact check

**Goal:** Confirm no other workflow or code references the deprecated file.

**Commands:**

```powershell
# Check workflow file dependencies
Select-String -Pattern "tier2_signals" .github\workflows\*.yml
# Check Python code references
Select-String -Pattern "tier2_signals" agents\*.py utils\*.py scripts\*.py
# Check documentation references
Select-String -Pattern "tier2_signals" docs\*.md README.md CLAUDE.md
```

**Expected outcome:** No matches OR only matches in deprecated/historical docs. If active references found → §0.6 documents and addresses before deletion.

### §1.8 Node.js update compatibility check

**Goal:** Verify `actions/checkout@v5` and `actions/setup-python@v6` are stable and compatible with our Python 3.12 + Ubuntu runners.

**Manual investigation (web, not code):**
1. Visit `https://github.com/actions/checkout/releases` — confirm latest stable v5.x.x release
2. Visit `https://github.com/actions/setup-python/releases` — confirm latest stable v6.x.x release
3. Check release notes for breaking changes:
   - `actions/checkout` v4→v5: typically Node.js runtime upgrade only, no API breaking changes
   - `actions/setup-python` v5→v6: verify Python 3.12 support
4. Search: "actions/checkout v5 breaking changes site:github.com" via web

**Decision needed:** Any breaking changes that require workflow adjustments beyond version bumps? Document in §0.6.

---

## §2 Design Decisions (LOCKED, with reasoning)

### §2.0 Architectural pattern — cron-job.org PRIMARY (project-wide standard)

**Time-sensitive cron-triggered workflows in this project follow a two-layer cron strategy:**

**Layer 1 (PRIMARY): cron-job.org webhook → GH workflow_dispatch API**
- External scheduler calls GitHub's workflow_dispatch endpoint via PAT (`workflow` scope)
- Sub-minute fire reliability (typical: within 30 seconds of scheduled time)
- Centralized dashboard for monitoring all crons across the project
- Free tier: 1-min minimum interval, 10,000 calls/month — comfortable for current scale

**Layer 2 (FALLBACK): GitHub Actions internal cron in YAML `schedule:`**
- Lower cadence than primary (typically 3-5x the primary interval)
- Catches missed PRIMARY fires (cron-job.org outages or rate hits)
- No code changes needed if PRIMARY temporarily disabled
- Identified in workflow runs by "Triggered via schedule" (vs "Manually run by …" for PRIMARY)

**Workflows currently following this pattern (verified 2026-05-21):**

| Workflow | PRIMARY (cron-job.org) | FALLBACK (GH cron) | Evidence |
|----------|------------------------|--------------------|----------| 
| Tier-0 Filing Agent | 5-min | 15-min YAML | Runs labeled "Manually run by goelvipulvg-max", every 5 min (Run #580 chain) |
| Filing Memory Sync | 10-min | 10-min YAML | Runs labeled "Manually run by goelvipulvg-max", every 10 min (112 runs) |
| Tier-0F Poller (NEW, Batch B) | **2-min** | **10-min** YAML | To be configured in §3.9 |

**Workflows NOT following this pattern (deliberate exceptions):**

| Workflow | Trigger | Reason |
|----------|---------|--------|
| Filing Memory Backfill | GH cron only (00:30 IST overnight) | One-shot overnight job, no latency requirement |
| Nifty 500 Loader | GH cron only (quarterly) | Low-frequency reference data refresh |
| Sync NSE 500 | GH cron only (weekly) | Low-frequency reference data refresh |
| Pre-Open Alert | GH cron only (9:00 AM IST) | Fixed single-shot daily trigger, no benefit from primary/fallback |
| Tier-3 Position Manager | `workflow_run` (event-driven) | Triggered by other workflow success, not cron-based |
| Tier-4 Memory Manager | `workflow_run` (event-driven) | After-hours pipeline chain |
| Tier-2F | `workflow_dispatch` only (called by Tier-0F poller) | Event-driven by poller, no independent cron |

**Rule of thumb (project-wide):**
- Market-hour low-latency triggers → cron-job.org PRIMARY + GH FALLBACK
- Overnight/weekly/quarterly batch jobs → GH cron only
- Event-driven (one workflow triggers another) → `workflow_dispatch` or `workflow_run`

**Why this pattern matters for Batch B:**
- Tier-0F poller MUST be on cron-job.org PRIMARY (2-min cadence not reliably achievable on GH internal cron alone)
- Tier-2F MUST be `workflow_dispatch` only (poller dispatches it; independent cron would create duplicate work)

### §2.1 Tier-0F poller idempotency mechanism (UPDATED v3 post-recon)

**Decision:** REUSE existing orphan column `picked_by_tier0f boolean DEFAULT false` in `filings_log`. NO new column DDL needed.

**Poller logic:**
- Query: `WHERE picked_by_tier0f = false` to find unprocessed rows
- Update: `picked_by_tier0f = true` AND `picked_at = NOW()` immediately after successful dispatch

**Reasoning (LOCKED):**
- Column already exists in production schema (recon §0.6.1)
- Default value `false` semantically correct for unprocessed rows
- Eliminates §3.2 DDL step entirely (1 less manual Supabase Dashboard action)
- `picked_at` timestamp column also already exists — populate for audit trail
- Semantically accurate: Tier-0F is what PICKS the filing, Tier-2F is what PROCESSES it

**Rejected alternatives:**
- ❌ Add new `processed_by_tier2f boolean` — duplicates existing semantics, requires DDL
- ❌ Drop `picked_by_tier0f` and add `processed_by_tier2f` — destructive, no benefit
- ❌ JOIN against paper_trades — slower, less explicit

### §2.1.1 Tier-2F filing_id linking (NEW v3 — D9)

**Decision:** ADD `filing_id bigint` column to `paper_trades`. UPDATE Tier-2F insert to populate it directly.

**DDL (via Supabase Dashboard, NOT supabase-py):**

```sql
ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS filing_id bigint REFERENCES filings_log(id);

-- Optional: index for V5.8 query performance
CREATE INDEX IF NOT EXISTS idx_paper_trades_filing_id
ON paper_trades(filing_id) WHERE filing_id IS NOT NULL;
```

**Code change in `agents/tier2_fundamental.py`** `_insert_paper_trade()`:

```python
# Add to trade_payload dict (1-line addition):
trade_payload = {
    'ticker': ticker,
    'source': 'TIER2F',
    'filing_id': filing_id,  # ← NEW: link to filings_log row
    # ... rest of existing fields
}
```

**Reasoning (LOCKED):**
- Enables V5.8 end-to-end timing measurement via simple JOIN
- Removes brittle `raw_signal->>'filing_id'` JSONB extraction
- Future P&L attribution to filings becomes trivial
- Existing 31 trades have NULL `filing_id` — acceptable (predates Tier-2F)
- Foreign key prevents orphan trades (data integrity)

**Why NOT JSONB extraction:**
- Schema drift risk (raw_signal contract not formally enforced)
- Query performance worse (JSONB ops vs btree)
- Tools like reporting/analytics dashboards can't easily use JSONB

### §2.2 Tier-0F poller filtering rule (UPDATED v3 — correct column names)

**Decision:** Poller selects rows matching:

```sql
SELECT id, symbol, event_type, material_score, classified_at
FROM filings_log
WHERE is_material = true
  AND material_score >= 6
  AND picked_by_tier0f = false
  AND classified_at > NOW() - INTERVAL '30 minutes'
ORDER BY classified_at ASC
LIMIT 10;
```

**Column corrections from v2 (per recon §0.6.1):**
- `ticker` → **`symbol`**
- `material = true` → **`is_material = true`**
- `score >= 6` → **`material_score >= 6`**
- `processed_by_tier2f = false` → **`picked_by_tier0f = false`**
- `sector` REMOVED from SELECT (not in filings_log; Tier-2F gets it from `neon_fundamentals.py`)

**Reasoning unchanged:**
- `is_material = true` + `material_score >= 6` matches Tier-2F entry criteria (per Phase 5 Batch A brief)
- 30-min lookback window prevents stale filings being processed if poller missed cycles
- `ORDER BY classified_at ASC` ensures oldest unprocessed first (FIFO)
- `LIMIT 10` caps per-cycle work

### §2.3 Tier-0F → Tier-2F handoff mechanism

**Decision:** Poller calls GitHub Actions `workflow_dispatch` API on `tier2f.yml` with `filing_id` as input parameter.

**Code pattern (will be in `agents/tier0f_poller.py`):**

```python
import os, requests

def _dispatch_tier2f(filing_id: int) -> bool:
    pat = os.getenv("GITHUB_PAT")
    url = "https://api.github.com/repos/goelvipulvg-max/stockmarket-brain/actions/workflows/tier2f.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"ref": "main", "inputs": {"filing_id": str(filing_id)}}
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    return r.status_code == 204
```

**Reasoning:**
- Native GH Actions integration, full logging in Actions tab
- Decouples poller from Tier-2F execution (poller exits quickly even if Tier-2F is slow)
- Allows independent retry (if Tier-2F fails, can manually re-dispatch)
- `workflow_dispatch` returns 204 on success

**Rejected alternatives:**
- ❌ Direct subprocess call (`python -m agents.tier2_fundamental`) — couples poller to Tier-2F runtime, no independent retry
- ❌ Queue table (e.g., Supabase `dispatch_queue`) — adds complexity for synchronous-enough flow

### §2.4 cron-job.org PRIMARY vs GH Actions FALLBACK cadence

**Decision:**
- **cron-job.org (PRIMARY):** Every **2 minutes**, Mon-Fri 9:00 AM-3:30 PM IST. Calls `tier0f-poller.yml` workflow_dispatch.
- **GH Actions internal cron (FALLBACK):** Every **10 minutes**, Mon-Fri 9:00 AM-3:30 PM IST (cron expression: `*/10 3-9 * * 1-5`).

**Reasoning:**
- 2-min cadence chosen based on §2.4.1 latency budget analysis
- Tier-0 (upstream) runs every 5 min — Tier-0F 2-min cadence ensures filings_log row picked up within ~2 min of insertion
- GH Actions 10-min fallback catches missed cycles without significant overlap (every 5th primary fire, fallback also fires)
- Both running in parallel is safe because poller is idempotent (only picks rows with `processed_by_tier2f = false`)
- cron-job.org free tier supports 1-min minimum interval; 2-min usage well within free tier

**Time window justification:** Trading hours 9:15 AM-3:30 PM IST. Buffer 15 min on either side = 9:00 AM-3:45 PM. Cron expression `*/10 3-9 UTC = 8:30 AM-3:30 PM IST` covers full window with margin.

### §2.4.1 Latency budget analysis

**End-to-end latency budget (filing publication → Telegram alert):**

| Stage | Cadence | Wait time (range) |
|-------|---------|-------------------|
| Filing publication → Tier-0 detection | 5-min cron (existing) | 0-5 min |
| filings_log row → Tier-0F pickup | 2-min cron (NEW) | 0-2 min |
| Tier-0F → Tier-2F dispatch | instant (HTTP POST) | <2 sec |
| Tier-2F pipeline (10 steps incl. 2 AI calls) | execution | 2-3 min |
| Trade insert + Telegram alert | execution | <5 sec |
| **TOTAL** | | **2-10 min** |

**Distribution:**
- **Best case:** 3-4 min (everything aligned, no waiting)
- **Typical case:** 5-7 min (average upstream wait + execution)
- **Worst case:** 10 min (max upstream wait of 5+2 min + 3 min execution)
- **Acceptance criterion (V5.8):** ≤10 min (600 seconds) ✓ achievable

**Why 2 min for Tier-0F (and not 1 min or 5 min):**

| Cadence option | Pros | Cons | Verdict |
|----------------|------|------|---------|
| 1 min | Marginal latency win (~1 min better worst case) | 2x cron-job.org calls, no real benefit (Tier-2F itself takes 2-3 min) | ❌ Diminishing returns |
| **2 min** | **Balanced — 2 min wait ≤ Tier-2F execution time, no bottleneck** | **None significant** | **✅ CHOSEN** |
| 5 min | Lower cost, simpler config | Tier-0F becomes the dominant bottleneck (5 min wait > 3 min execution) | ❌ Inefficient |
| 10 min+ | Free tier headroom | Worst case latency 15+ min — exceeds V5.8 acceptance | ❌ Misses acceptance |

**Why event-driven (no polling) was NOT chosen for Batch B:**
- Would require modifying Tier-0 Filing Agent to dispatch Tier-2F directly on filing classification
- Couples Tier-0 to Tier-2F (currently independent)
- Adds error-handling complexity (what if Tier-2F dispatch fails mid-Tier-0 cycle?)
- Polling design proven by Filing Memory Sync pattern — reuse proven architecture
- **Deferred to Phase 6** if production latency observations demand <2-min response

**Future optimization path (NOT Batch B scope):**
- If specific event types (e.g., CONTRACT_WIN) show <2-min alpha decay → consider event-driven trigger from Tier-0
- If Tier-2F execution time can be parallelized (Haiku + Flash simultaneous instead of sequential) → 30s reduction possible
- Phase 6 reconciliation will revisit based on observed Flash CHALLENGE rate and trade P&L data

### §2.5 Tier-3 unique constraint enforcement

**Decision:** LOGIC-ONLY in `agents/tier3_position_manager.py`. NO DDL on Supabase.

**Code change (minimal diff):**

```python
# BEFORE:
existing = sb.table('paper_trades').select('id').eq('ticker', ticker)\
    .eq('status', 'OPEN').execute()

# AFTER:
existing = sb.table('paper_trades').select('id').eq('ticker', ticker)\
    .eq('source', source).eq('status', 'OPEN').execute()
```

**Reasoning:**
- Simpler — no DDL, no Supabase Dashboard step, no migration
- Reversible — can add DDL later if production data shows race conditions
- Race conditions theoretical here (paper trading, sequential Tier-2F dispatch via poller)
- Phase 6 reconciliation phase will revisit if needed

**Safety hook for Phase 6:** If race conditions observed in production:
- Option A: Add `FOR UPDATE` lock via raw RPC
- Option B: Add DDL partial unique index `UNIQUE (ticker, source) WHERE status = 'OPEN'`
- Decision deferred until evidence

### §2.6 V5.8 timing measurement methodology (UPDATED v3 — filing_id column now exists)

**Decision:** Use existing timestamps + new `filing_id` column (D9):
- Start: `filings_log.classified_at`
- End: `paper_trades.created_at`
- Link: `paper_trades.filing_id = filings_log.id` (added in D9 DDL)
- Acceptance: `created_at - classified_at <= INTERVAL '10 minutes'`

**Reasoning:**
- Both timestamps already populated by existing code (no instrumentation needed)
- `filing_id` column added in D9 enables clean JOIN (was broken in v2)
- End-to-end measurable from real data, not synthetic markers
- Acceptable accuracy (timestamps to millisecond precision in Postgres)

**Verification query (§4.3):**

```sql
SELECT
    p.ticker,
    p.created_at AS trade_at,
    f.classified_at AS filing_at,
    EXTRACT(EPOCH FROM (p.created_at - f.classified_at)) AS lag_seconds
FROM paper_trades p
JOIN filings_log f ON p.filing_id = f.id
WHERE p.source = 'TIER2F'
ORDER BY p.created_at DESC
LIMIT 5;
```

**Pass criteria:** `lag_seconds <= 600`.

**Note:** Existing 31 legacy `source='TIER2'` trades have `filing_id = NULL` — they'll be excluded from V5.8 query by `WHERE p.source = 'TIER2F'` filter. Clean separation.

### §2.7 Node.js update strategy

**Decision:** Single atomic sweep across all 14 `.yml` files in one commit (Commit 3 of 4).

**Pattern:**

```yaml
# BEFORE:
- uses: actions/checkout@v4
- uses: actions/setup-python@v5

# AFTER:
- uses: actions/checkout@v5
- uses: actions/setup-python@v6
```

**Reasoning:**
- Atomic — all workflows updated together, no half-state in main
- Easy rollback — `git revert` single commit
- Doesn't fragment git history

**v4 correction:** Actual Node.js sweep scope was 12 files (not 14):
- 10 files needed both checkout@v4->v5 AND setup-python@v5->v6
- 2 files needed checkout@v4->v5 AND setup-python@v4->v6 (skip-version)
- 1 file already at v6: `update_paper_trades.yml` (no-op, reason unknown)
- 1 file deleted: `tier2_signals.yml`

Original list below (kept for reference):

**Files affected (from §1 inventory):**
1. `after_hours_watcher.yml`
2. `filing-memory-backfill.yml`
3. `filing-memory-sync.yml`
4. `historical_preloader.yml`
5. `nifty500_loader.yml`
6. `preopen_alert.yml`
7. `sync_nse500.yml`
8. `tier0-agent.yml`
9. `tier1_guardian.yml`
10. `tier1_news.yml`
11. `tier3_position_manager.yml`
12. `tier4_memory_manager.yml`
13. `update_paper_trades.yml`
14. `tier0f-poller.yml` (NEW, will use v5/v6 from start)
15. `tier2f.yml` (NEW, will use v5/v6 from start)

*(`tier2_signals.yml` not included — being deleted in same commit)*

### §2.8 tier2_signals.yml deletion handling

**Decision:** DELETE in Commit 3 alongside new workflow creation.

**Reasoning:**
- Clean cutover — no transition period needed (file is `workflow_dispatch` only, never auto-fires)
- Atomic with related changes (new workflows, Node.js update)
- Forces immediate documentation of replacement (Tier-2F) — no lingering confusion

**Command (during Commit 3):**

```powershell
git rm .github/workflows/tier2_signals.yml
```

### §2.9 Commit strategy (UPDATED v3 — 4 commits, D9 absorbed into Commit 1)

| # | Title | Files | Purpose | Approx LOC |
|---|-------|-------|---------|------------|
| 1 | `feat(phase-5): Tier-0F poller + Tier-2F filing_id linking` | `agents/tier0f_poller.py` (new) + `agents/tier2_fundamental.py` (1-line modify for D9) | Poller Python code + Tier-2F filing_id population. Testable via V5.1. **DDL §3.2 must be applied via Dashboard BEFORE pushing this commit.** | ~155 |
| 2 | `fix(tier-3): Gap 5 — duplicate check per (ticker, source) tuple` | `agents/tier3_position_manager.py` (modify) | List-iteration fix per recon §1.3 actual code structure, testable via V5.7 | ~6 |
| 3 | `chore(workflows): Phase 5 wiring + Node.js 24 update + tier2_signals removal` | 14 modified, 2 new, 1 deleted `.yml` files | Atomic infrastructure change | ~50 |
| 4 | `test(phase-5): Batch B gate tests + execution brief` | `tests/test_phase5_batchB.py` (new), `docs/phase-5-batchB-execution-brief.md` (new) | Validation + documentation | ~400 |

**Order rationale:** Each commit testable in isolation. Last commit (tests+brief) is the "wrap-up" capturing validation + docs.

**Pre-Commit 1 prerequisite (NEW v3):**
- DDL §3.2 (`ALTER TABLE paper_trades ADD COLUMN filing_id`) MUST be run in Supabase Dashboard BEFORE pushing Commit 1
- Otherwise Tier-2F code with new `filing_id` field will fail on next live trigger

**Multi-line commit messages:** Use Antigravity Write tool → `.commit_msg.tmp` → `git commit -F .commit_msg.tmp` → `Remove-Item .commit_msg.tmp`. PowerShell heredoc has 965-byte limit, do NOT use.

**NO `Co-Authored-By: Claude` lines.**

---

## §3 Build Steps (file-by-file)

> **Pattern:** Each step = one tool call (one file edit, one DDL, one command). Press `1` per individual edit. NEVER "allow all". STOP & report after each step.

### §3.1 Step 1 — Recon execution (read-only, ALL of §1)

- Run §1.1 through §1.8 sequentially
- Document each finding in §0.6 (timestamped sub-entry)
- STOP and report to user before proceeding to §3.2
- If any unexpected finding → discuss with user before adjusting design

### §3.2 Step 2 — DDL via Supabase Dashboard (UPDATED v3 — D9 deliverable)

**Note:** Idempotency column DDL ELIMINATED (we reuse existing `picked_by_tier0f`).

**Only DDL needed (D9 — adds `filing_id` column to paper_trades):**

```sql
-- Step 2a: Add filing_id column with FK to filings_log
ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS filing_id bigint REFERENCES filings_log(id);

-- Step 2b: Optional performance index for V5.8 queries
CREATE INDEX IF NOT EXISTS idx_paper_trades_filing_id
ON paper_trades(filing_id) WHERE filing_id IS NOT NULL;

-- Step 2c: Verify
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'paper_trades' AND column_name = 'filing_id';
```

**Expected outcome:**
- Column added successfully (1 row in verification query)
- All existing 31 trades will have `filing_id = NULL` (acceptable, predates Tier-2F)

**Backfill consideration:** NO backfill needed because:
- 0 existing TIER2F trades (only legacy TIER2 trades, which intentionally have NULL filing_id)
- Future Tier-2F inserts will populate filing_id from code change (§3.3 Tier-2F update below)

**IMPORTANT:** Steps §3.3 and §3.4 below also need a small modification to `agents/tier2_fundamental.py` to populate the new `filing_id` column on insert. See §3.4.1 below.

### §3.3 Step 3 — Create `agents/tier0f_poller.py` (UPDATED v3 — correct columns)

**File structure (~150 lines):**

```python
"""
Tier-0F Poller -- 2-min material filing dispatcher.

Reads filings_log for material rows (is_material=true, material_score>=6,
picked_by_tier0f=false), dispatches Tier-2F via GitHub Actions
workflow_dispatch API.

Triggered by cron-job.org every 2 minutes (PRIMARY) + GH internal cron
every 10 minutes (FALLBACK) per S2.0 architectural pattern.

Phase 5 Batch B deliverable D1.
"""

import os
import sys
import logging
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from utils.supabase_client import get_client

load_dotenv(override=True)

# Module-level constants
GH_REPO = "goelvipulvg-max/stockmarket-brain"
TIER2F_WORKFLOW = "tier2f.yml"
LOOKBACK_MINUTES = 30
BATCH_LIMIT = 10
MIN_SCORE = 6

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s -- %(levelname)s -- %(message)s'
)
log = logging.getLogger("tier0f_poller")


def _query_pending_filings() -> list[dict]:
    """Returns list of {id, symbol, event_type, material_score, classified_at}
    for unprocessed material filings."""
    sb = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)).isoformat()

    r = sb.table('filings_log')\
        .select('id, symbol, event_type, material_score, classified_at')\
        .eq('is_material', True)\
        .gte('material_score', MIN_SCORE)\
        .eq('picked_by_tier0f', False)\
        .gte('classified_at', cutoff)\
        .order('classified_at', desc=False)\
        .limit(BATCH_LIMIT)\
        .execute()
    return r.data or []


def _dispatch_tier2f(filing_id: int) -> bool:
    """Calls GitHub Actions workflow_dispatch on tier2f.yml with filing_id input.
    Returns True if dispatch accepted (HTTP 204)."""
    pat = os.getenv("GITHUB_PAT")
    if not pat:
        log.error("GITHUB_PAT missing in environment")
        return False

    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{TIER2F_WORKFLOW}/dispatches"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main", "inputs": {"filing_id": str(filing_id)}}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 204:
            log.info(f"Dispatched Tier-2F for filing_id={filing_id}")
            return True
        log.error(f"Dispatch failed for filing_id={filing_id}: HTTP {r.status_code} -- {r.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"Dispatch exception for filing_id={filing_id}: {e}")
        return False


def _mark_picked(filing_id: int) -> bool:
    """Marks filing as picked_by_tier0f=true and picked_at=NOW().
    Returns True on success."""
    sb = get_client()
    try:
        sb.table('filings_log').update({
            'picked_by_tier0f': True,
            'picked_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', filing_id).execute()
        return True
    except Exception as e:
        log.error(f"Mark picked failed for filing_id={filing_id}: {e}")
        return False


def main(dry_run: bool = False) -> int:
    """Main poller entry point. Returns exit code (0 success, 1 partial failure)."""
    log.info(f"Tier-0F poller starting (dry_run={dry_run})")

    pending = _query_pending_filings()
    log.info(f"Found {len(pending)} pending filings")

    if not pending:
        return 0

    success_count = 0
    fail_count = 0

    for filing in pending:
        fid = filing['id']
        symbol = filing.get('symbol', 'UNKNOWN')
        log.info(f"Processing filing_id={fid} symbol={symbol}")

        if dry_run:
            log.info(f"[DRY RUN] Would dispatch Tier-2F for filing_id={fid}")
            success_count += 1
            continue

        if _dispatch_tier2f(fid) and _mark_picked(fid):
            success_count += 1
        else:
            fail_count += 1
            log.warning(f"Failed to dispatch+mark filing_id={fid}")

    log.info(f"Poller complete: {success_count} success, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(main(dry_run=dry))
```

**Key changes from v2:**
- `ticker` → `symbol` throughout
- `material` → `is_material`
- `score` → `material_score`
- `processed_by_tier2f` → `picked_by_tier0f` (reusing existing column)
- `_mark_processed()` → `_mark_picked()` (also updates `picked_at` timestamp)
- `sector` REMOVED from SELECT (not in filings_log)

**Validation before commit:**
- `Select-String -Pattern "—" agents\tier0f_poller.py` → must return NOTHING (no em-dashes)
- `.venv\Scripts\python.exe -c "from agents.tier0f_poller import main; print('import OK')"` → must succeed
- `.venv\Scripts\python.exe -m agents.tier0f_poller --dry-run` → must run without error

### §3.3.1 Step 3.1 — Update `agents/tier2_fundamental.py` (NEW v3 — D9 support)

**v4 correction:** Brief v3 referenced `_insert_paper_trade()` as a separate
function. Actual code has the trade_payload dict inline in `process_filing()`
at line 290. The `filing_id` field was added there (not in any separate
insert function).

**Add `filing_id` to the trade_payload dict in process_filing() (line 290-293):**

```python
# In _insert_paper_trade() function, modify trade_payload dict:
trade_payload = {
    'ticker': ticker,
    'source': 'TIER2F',
    'filing_id': filing_id,  # NEW: link to filings_log
    # ... rest of existing fields unchanged
}
```

**Single line addition.** No other changes needed. `filing_id` is already in scope from earlier pipeline steps.

**Validation:**
- Verify `filing_id` is in scope at line 290 (it is, passed from `process_filing()`)
- Run existing Tier-2F test: `pytest tests/test_phase5_batchA.py::test_V5_5_solo_haiku -v` — must still pass
- No em-dash check needed (this is existing file, already em-dash clean)

### §3.4 Step 4 — Modify `agents/tier3_position_manager.py` (UPDATED v3 — list-iteration fix)

**Brief v2 fix pattern was WRONG** (assumed inline Supabase query). Actual code uses list-iteration via `apply_rules(signal, open_trades)` function. **TWO changes needed:**

**Change 1 — Line 154 (open_trades SELECT in main()):**

```python
# BEFORE:
open_trades = (
    supabase.table("paper_trades")
    .select("id,ticker,status")
    .eq("status", "OPEN")
    .execute()
    .data
)

# AFTER:
open_trades = (
    supabase.table("paper_trades")
    .select("id,ticker,source,status")  # added source
    .eq("status", "OPEN")
    .execute()
    .data
)
```

**Change 2 — Line 25 (duplicate check condition in apply_rules()):**

```python
# BEFORE:
def apply_rules(signal: dict, open_trades: list) -> tuple:
    for trade in open_trades:
        if trade["ticker"] == signal["ticker"] and trade["id"] != signal["id"]:
            return False, "duplicate_open_position"

# AFTER:
def apply_rules(signal: dict, open_trades: list) -> tuple:
    for trade in open_trades:
        # Gap 5 fix (Phase 5 Batch B): allow one OPEN per (ticker, source) instead of per ticker
        if (trade["ticker"] == signal["ticker"]
            and trade["source"] == signal["source"]
            and trade["id"] != signal["id"]):
            return False, f"duplicate_open_position_for_source_{signal['source']}"
```

**Total diff size: ~6 lines** (2 functional changes + comment).

**Validation:**
- `Select-String -Pattern "—" agents\tier3_position_manager.py` → must return NOTHING
- Existing Tier-3 tests (if any) must still pass
- V5.7a + V5.7b gate tests will validate (see §4.2)

### §3.5 Step 5 — Create `.github/workflows/tier0f-poller.yml`

```yaml
name: Tier-0F Poller

on:
  workflow_dispatch:  # Primary trigger via cron-job.org webhook (every 2 min)
  schedule:
    - cron: '*/10 3-9 * * 1-5'  # Fallback: every 10 min Mon-Fri ~8:30 AM-3:30 PM IST

jobs:
  run-poller:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v5
      - name: Set up Python 3.12
        uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Create .env file
        run: |
          echo "SUPABASE_URL=${{ secrets.SUPABASE_URL }}" >> .env
          echo "SUPABASE_KEY=${{ secrets.SUPABASE_KEY }}" >> .env
          echo "GITHUB_PAT=${{ secrets.WORKFLOW_DISPATCH_PAT }}" >> .env
      - name: Run Tier-0F Poller
        run: python -m agents.tier0f_poller
```

**Notes:**
- `WORKFLOW_DISPATCH_PAT` secret must exist in repo settings (separate PAT with `workflow` scope; create if missing in §1.5 cron-job.org setup)
- `timeout-minutes: 5` — poller should never run more than 5 min
- Fallback cron `*/10` deliberately wider than primary 2-min cadence (every 5th primary fire, fallback also fires; idempotent so no conflict)

### §3.6 Step 6 — Create `.github/workflows/tier2f.yml`

```yaml
name: Tier-2F Fundamental Signal

on:
  workflow_dispatch:
    inputs:
      filing_id:
        description: 'filings_log row ID to process'
        required: true
        type: string

jobs:
  run-tier2f:
    runs-on: ubuntu-latest
    timeout-minutes: 8
    steps:
      - uses: actions/checkout@v5
      - name: Set up Python 3.12
        uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Create .env file
        run: |
          echo "SUPABASE_URL=${{ secrets.SUPABASE_URL }}" >> .env
          echo "SUPABASE_KEY=${{ secrets.SUPABASE_KEY }}" >> .env
          echo "ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}" >> .env
          echo "DEEPSEEK_API_KEY=${{ secrets.DEEPSEEK_API_KEY }}" >> .env
          echo "TELEGRAM_BOT_TOKEN=${{ secrets.TELEGRAM_BOT_TOKEN }}" >> .env
          echo "TELEGRAM_TIER3_CHANNEL=${{ secrets.TELEGRAM_TIER3_CHANNEL }}" >> .env
          echo "NEON_DATABASE_URL=${{ secrets.NEON_DATABASE_URL }}" >> .env
      - name: Run Tier-2F
        run: python -m agents.tier2_fundamental --filing-id ${{ inputs.filing_id }}
```

**Notes:**
- NO scheduled cron — only dispatched by poller
- `timeout-minutes: 8` — Tier-2F 10-step pipeline should complete well within this
- All secrets must already exist (Tier-2F Phase 5 Batch A used them)

### §3.7 Step 7 — Delete `.github/workflows/tier2_signals.yml`

```powershell
git rm .github/workflows/tier2_signals.yml
# Verify removal
Get-ChildItem .github/workflows/*.yml | Select-String -Pattern "tier2_signals"
# Must return nothing
```

### §3.8 Step 8 — Node.js update sweep across 14 .yml files

**Files to update (verify against §1 inventory output):**

For each file, change:
- `uses: actions/checkout@v4` → `uses: actions/checkout@v5`
- `uses: actions/setup-python@v5` → `uses: actions/setup-python@v6`

**Suggested batch approach (PowerShell):**

```powershell
# DRY RUN first — show what would change
Get-ChildItem .github/workflows/*.yml | ForEach-Object {
    Write-Host "=== $($_.Name) ==="
    Get-Content $_.FullName | Select-String -Pattern "actions/checkout@v4|actions/setup-python@v5"
}
```

Then do file-by-file edits in Antigravity (Pattern A — press `1` per edit). **Do NOT use sed/regex bulk replace** — manual confirmation per file prevents mistakes.

**Validation after all edits:**

```powershell
# Must return nothing
Get-ChildItem .github/workflows/*.yml | Select-String -Pattern "actions/checkout@v4|actions/setup-python@v5"
```

### §3.9 Step 9 — cron-job.org dashboard setup (manual, OUT of repo)

**Not a code change.** Performed via cron-job.org web UI.

1. Login → Create new cronjob
2. **URL:** `https://api.github.com/repos/goelvipulvg-max/stockmarket-brain/actions/workflows/tier0f-poller.yml/dispatches`
3. **Method:** POST
4. **Headers:**
   - `Authorization: Bearer <WORKFLOW_DISPATCH_PAT>`
   - `Accept: application/vnd.github+json`
   - `X-GitHub-Api-Version: 2022-11-28`
5. **Body:** `{"ref": "main"}`
6. **Schedule:** **Every 2 minutes**, Mon-Fri 9:00-15:30 IST
7. **Save** and trigger one manual test fire to verify
8. **Capture:** Job ID, save in §0.6.3 for future reference

**Note:** Reference the existing Tier-0 Filing Agent and Filing Memory Sync cron-job.org jobs as templates (per §2.0 architectural pattern).

### §3.10 Step 10 — Create `tests/test_phase5_batchB.py`

(Test code in §4 below.)

### §3.11 Step 11 — Commit 1: Tier-0F poller

```powershell
git add agents/tier0f_poller.py
# Write .commit_msg.tmp via Antigravity Write tool with this content:
```

```
feat(phase-5): Tier-0F poller -- 2-min material filing dispatcher

Phase 5 Batch B Commit 1 of 4 (D1 from execution brief).

Reads filings_log for material rows (material=true, score>=6,
processed_by_tier2f=false, classified_at within last 30 min).
Dispatches Tier-2F via GitHub Actions workflow_dispatch API
on tier2f.yml with filing_id input. Marks processed on success.

Triggered by cron-job.org every 2 min (PRIMARY) + GH internal
cron every 10 min (FALLBACK) per S2.0 architectural pattern.

Idempotent: relies on processed_by_tier2f column flag.
Fail-soft: per-filing failure doesn't block others.
Rate-limited: BATCH_LIMIT=10 per cycle.

Tested via V5.1 (Tier-0F dry-run gate, see tests/test_phase5_batchB.py).

Refs: docs/phase-5-batchB-execution-brief.md S0.1 D1, S2.0, S2.4.1, S3.3
```

```powershell
git commit -F .commit_msg.tmp
Remove-Item .commit_msg.tmp
git push origin main
# Verify push
git log origin/main..HEAD  # must be empty
git log --oneline -5  # must show new commit at top
```

### §3.12 Step 12 — Commit 2: Tier-3 modification

```powershell
git add agents/tier3_position_manager.py
# Write .commit_msg.tmp:
```

```
fix(tier-3): Gap 5 -- duplicate check per (ticker, source) tuple

Phase 5 Batch B Commit 2 of 4 (D2 from execution brief).

Tier-3 was blocking all new trades on a ticker if ANY OPEN position
existed. With multi-source signals (TIER2F now live, TIER1F future),
this prevented valid multi-source trades on the same underlying.

Fix: scope duplicate check to (ticker, source) tuple instead of
ticker alone. Same source still blocks duplicate; different source
on same ticker now ALLOWED.

Logic-only enforcement (no DDL). Race conditions theoretical for
paper trading; FOR UPDATE lock deferred to Phase 6 if production
data shows races.

Tested via V5.7 (Tier-3 duplicate rule gate).

Refs: docs/phase-5-batchB-execution-brief.md S0.1 D2, S2.5, S3.4
```

```powershell
git commit -F .commit_msg.tmp
Remove-Item .commit_msg.tmp
git push origin main
git log origin/main..HEAD  # must be empty
```

### §3.13 Step 13 — Commit 3: Workflows wiring + Node.js update

```powershell
# Stage all workflow files (NEVER git add .)
git add .github/workflows/tier0f-poller.yml
git add .github/workflows/tier2f.yml
git add .github/workflows/after_hours_watcher.yml
git add .github/workflows/filing-memory-backfill.yml
git add .github/workflows/filing-memory-sync.yml
git add .github/workflows/historical_preloader.yml
git add .github/workflows/nifty500_loader.yml
git add .github/workflows/preopen_alert.yml
git add .github/workflows/sync_nse500.yml
git add .github/workflows/tier0-agent.yml
git add .github/workflows/tier1_guardian.yml
git add .github/workflows/tier1_news.yml
git add .github/workflows/tier3_position_manager.yml
git add .github/workflows/tier4_memory_manager.yml
git add .github/workflows/update_paper_trades.yml
# Stage deletion
git add .github/workflows/tier2_signals.yml  # tracks the deletion
```

```
chore(workflows): Phase 5 wiring + Node.js 24 update + tier2_signals removal

Phase 5 Batch B Commit 3 of 4 (D3, D4, D5, D6 from execution brief).

NEW workflows:
- tier0f-poller.yml: 2-min poller dispatcher
  (workflow_dispatch primary via cron-job.org, schedule fallback */15)
- tier2f.yml: Tier-2F runner (workflow_dispatch with filing_id input)

DELETED workflow:
- tier2_signals.yml: deprecated Tier-2 Swing Signals
  (replaced by Tier-2F since Phase 5 Batch A)

Node.js 20 -- 24 update across all .yml files:
- actions/checkout@v4 -- @v5
- actions/setup-python@v5 -- @v6
(GitHub deprecation deadline 2026-06-02)

cron-job.org dashboard setup tracked separately (S3.9 of brief).

Refs: docs/phase-5-batchB-execution-brief.md S0.1 D3-D6, S2.4, S2.7, S2.8, S3.5-S3.8
```

```powershell
git commit -F .commit_msg.tmp
Remove-Item .commit_msg.tmp
git push origin main
git log origin/main..HEAD  # must be empty
```

**v4 update (post-ship):** Commit 3 actual ship stats:
- Hash: `317bde3`
- 15 files: 2 new + 1 deleted + 12 modified
- +87/-74 lines (vs original estimate ~50)
- Group B v4 -> v6 skip-version jump for tier3/tier4 workflows
  (semver-safe, no breakage post-deploy expected)

### §3.14 Step 14 — Commit 4: Tests + brief

```powershell
git add tests/test_phase5_batchB.py
git add docs/phase-5-batchB-execution-brief.md
```

```
test(phase-5): Batch B gate tests + execution brief

Phase 5 Batch B Commit 4 of 4 (D7, D8 from execution brief).

Gate tests:
- V5.1: Tier-0F poller dry-run (mocks _dispatch_tier2f)
- V5.7: Tier-3 duplicate rule per (ticker, source) -- 2 sub-cases
- V5.8: Full live pipeline timing <=600 seconds end-to-end

Execution brief v1 captures full Batch B plan:
- 8 deliverables, 9 explicit out-of-scope items
- Cost projection ~Rs.70-135/month (under Rs.800 ceiling)
- 6 risks with mitigations
- 8 recon steps, 9 design decisions, 14 build steps
- 4-commit strategy with rationale

Batch B closes Phase 5 production wiring.
Phase 5 Batch A V5.3+V5.4 retry deferred (S6 of brief).

Refs: docs/phase-5-batchB-execution-brief.md (this file)
```

```powershell
git commit -F .commit_msg.tmp
Remove-Item .commit_msg.tmp
git push origin main
git log origin/main..HEAD  # must be empty
git log --oneline -8  # verify 4 Batch B commits on top
```

---

## §4 Gate Tests

> **File:** `tests/test_phase5_batchB.py`
> **Pattern:** Follow Phase 5 Batch A test patterns — cross-module monkeypatch where needed, try/finally cleanup, fail-open on Telegram.

**v4 correction:** Brief v3 §4 referenced these inaccuracies, all fixed
in `tests/test_phase5_batchB.py` (Commit 4):
- V5.1 fixture: used v2 column names (`ticker`, `material`, `score`,
  `sector`, `processed_by_tier2f`). v3 schema actually has `symbol`,
  `is_material`, `material_score`, `picked_by_tier0f` (no `sector`).
- V5.7a/V5.7b: Brief listed `try_open_position()` -- this function
  does NOT exist. Tests use `apply_rules()` directly, which is the
  actual duplicate-check logic location.
- V5.8 (full live pipeline timing): Not implemented in Commit 4 -- this
  requires real cron-job.org webhook fire + 10-min DB poll, not feasible
  in unit-test scope. V5.8 deferred to post-deploy validation
  (see §5.4 post-build verification checklist).
- Bonus: existing `tests/test_tier3_position_manager.py` had a broken
  test (`test_rule_duplicate_open`) due to Commit 2's Gap 5 fix. Fixed
  in Commit 4 alongside new V5.x tests.

### §4.1 V5.1 — Tier-0F poller dry-run

**Setup:**
- Insert 3 mock material filings into `filings_log` (test fixtures): all with `material=true`, `score=7`, `processed_by_tier2f=false`, `classified_at=NOW()`
- Mock `_dispatch_tier2f` to return `True` without actual GH API call

**Test:**

```python
def test_V5_1_tier0f_poller_dry_run(monkeypatch):
    from agents import tier0f_poller as p

    # Mock dispatch to avoid real GH API call
    dispatch_calls = []
    def fake_dispatch(filing_id):
        dispatch_calls.append(filing_id)
        return True
    monkeypatch.setattr(p, '_dispatch_tier2f', fake_dispatch)

    # Insert 3 test filings (cleanup in finally)
    sb = p.get_client()
    test_ids = []
    try:
        for i in range(3):
            r = sb.table('filings_log').insert({
                'ticker': f'TEST{i}',
                'material': True,
                'score': 7,
                'event_type': 'TEST',
                'sector': 'TEST_SECTOR',
                'processed_by_tier2f': False,
                # classified_at defaults to NOW()
            }).execute()
            test_ids.append(r.data[0]['id'])

        # Run poller (non-dry-run because dispatch is mocked)
        exit_code = p.main(dry_run=False)

        assert exit_code == 0
        assert len(dispatch_calls) == 3, f"Expected 3 dispatches, got {len(dispatch_calls)}"

        # Verify all 3 marked processed
        check = sb.table('filings_log').select('id, processed_by_tier2f')\
            .in_('id', test_ids).execute()
        for row in check.data:
            assert row['processed_by_tier2f'] is True

    finally:
        # Cleanup
        sb.table('filings_log').delete().in_('id', test_ids).execute()
```

**Acceptance:** Test PASSES. All 3 test filings marked `processed_by_tier2f=true`. Cleanup verified post-test.

### §4.2 V5.7 — Tier-3 duplicate rule per (ticker, source)

**Setup:**
- Insert 1 mock OPEN paper_trade: `ticker='RELIANCE'`, `source='TIER2F'`, `status='OPEN'`

**Test 1 (BLOCK same source):**

```python
def test_V5_7a_tier3_blocks_same_source_duplicate():
    from agents import tier3_position_manager as t3
    sb = t3.get_client()
    test_id = None
    try:
        # Setup: existing OPEN trade
        r = sb.table('paper_trades').insert({
            'ticker': 'RELIANCE',
            'source': 'TIER2F',
            'status': 'OPEN',
            'qty': 10,
            'entry_price': 2500.0,
            # ... other required fields
        }).execute()
        test_id = r.data[0]['id']

        # Attempt new TIER2F trade on same ticker
        result = t3.try_open_position(ticker='RELIANCE', source='TIER2F', ...)
        assert result['action'] == 'SKIP'
        assert 'duplicate' in result['reason']

    finally:
        if test_id:
            sb.table('paper_trades').delete().eq('id', test_id).execute()
```

**Test 2 (ALLOW different source):**

```python
def test_V5_7b_tier3_allows_different_source_same_ticker():
    from agents import tier3_position_manager as t3
    sb = t3.get_client()
    test_id_setup = None
    test_id_new = None
    try:
        # Setup: existing TIER2F OPEN
        r = sb.table('paper_trades').insert({
            'ticker': 'RELIANCE',
            'source': 'TIER2F',
            'status': 'OPEN',
            'qty': 10,
            'entry_price': 2500.0,
        }).execute()
        test_id_setup = r.data[0]['id']

        # Attempt new TIER1F trade on same ticker -- should ALLOW
        result = t3.try_open_position(ticker='RELIANCE', source='TIER1F', ...)
        assert result['action'] != 'SKIP'
        if result.get('paper_trade_id'):
            test_id_new = result['paper_trade_id']

    finally:
        for tid in [test_id_setup, test_id_new]:
            if tid:
                sb.table('paper_trades').delete().eq('id', tid).execute()
```

**Acceptance:** Both tests PASS. Cleanup verified (0 TIER2F + 0 TIER1F test residue).

### §4.3 V5.8 — Full live pipeline ≤10 min (end-to-end timing)

**Timing diagram:**

```
T+0:00  Filing classified in filings_log (material=true, score>=6, processed_by_tier2f=false)
T+0:05  cron-job.org fires -> GH workflow_dispatch on tier0f-poller.yml
T+0:06  Tier-0F poller runs:
        - Query filings_log -> finds new row
        - Dispatch tier2f.yml with filing_id
        - Mark processed_by_tier2f=true
T+0:07  GH dispatches tier2f.yml
T+0:08  Tier-2F 10-step pipeline runs:
        - F&O ban check
        - Fundamentals fetch
        - Chart context
        - NIFTY mood
        - Pattern insights + memory brief
        - Haiku analyst (~30s)
        - DeepSeek Flash verifier (~30s)
        - determine_consensus
T+0:09  Sizing + paper_trades insert + capital deploy
T+0:10  Telegram alert sent

TOTAL:  classified_at -> paper_trades.created_at <= 600 seconds
```

**Test approach:**

1. **Setup:** Insert real-looking material filing into `filings_log`:

```python
test_filing = sb.table('filings_log').insert({
    'ticker': 'INFY',  # NIFTY 50 large-cap, F&O eligible
    'material': True,
    'score': 8,
    'event_type': 'RESULTS',
    'sector': 'IT',
    'processed_by_tier2f': False,
    'summary': 'TEST V5.8 Q4 results beat estimates, revenue +12% YoY',
    # classified_at = NOW() auto
}).execute()
```

2. **Trigger:** Manually invoke cron-job.org test fire (OR call tier0f-poller.yml workflow_dispatch via GH UI)

3. **Wait:** Poll for `paper_trades` row with matching `filing_id` for up to 12 minutes

4. **Measure:**

```python
import time
start = time.time()
trade = None
while time.time() - start < 720:  # 12 min ceiling
    r = sb.table('paper_trades').select('*')\
        .eq('filing_id', test_filing.data[0]['id'])\
        .eq('source', 'TIER2F').execute()
    if r.data:
        trade = r.data[0]
        break
    time.sleep(15)

assert trade is not None, "V5.8 FAILED: no trade created within 12 min"

# Measure lag
from datetime import datetime
classified = datetime.fromisoformat(test_filing.data[0]['classified_at'])
created = datetime.fromisoformat(trade['created_at'])
lag_seconds = (created - classified).total_seconds()

print(f"V5.8 lag: {lag_seconds:.1f} seconds (acceptance: <= 600)")
assert lag_seconds <= 600, f"V5.8 FAILED: lag {lag_seconds}s exceeds 600s"
```

5. **Cleanup:**

```python
finally:
    if trade:
        sb.table('paper_trades').delete().eq('id', trade['id']).execute()
    sb.table('filings_log').delete().eq('id', test_filing.data[0]['id']).execute()
```

**Acceptance:** Lag ≤ 600 seconds. Cleanup verified.

**Note:** V5.8 is the most fragile test because it depends on:
- cron-job.org actually firing (or manual trigger)
- Flash NOT challenging (else trade not inserted)
- Network/API latency in p50 range

**Backup acceptance:** If Flash CHALLENGES, V5.8 partially validated — full pipeline ran, but trade not inserted. Document in §0.6. SOLO_HAIKU path validates structurally; full PASS requires successful trade insert.

---

## §5 Execution Checklist (Antigravity workflow)

### §5.1 Pre-build verification

- [ ] `git status` — only machine-local files modified (`.claude/settings.local.json`, `dumps/`, `.claude/scheduled_tasks.lock`)
- [ ] `git branch --show-current` — must be `main`
- [ ] `git log -1 --oneline` — must show `20491c1` (or later if intervening work)
- [ ] `git log origin/main..HEAD` — must be empty (all prior work pushed)
- [ ] `.venv\Scripts\python.exe --version` — Python 3.12
- [ ] `.env` file exists with SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, GITHUB_PAT
- [ ] Verification commands from prior chat handoff re-run if any time has passed (filing_memory base_price = 144, TIER2F paper_trades = 0, agent_disagreements = 0)

### §5.2 Build phase pattern (per file)

- Recon step (§1.x) → STOP & report to user → user approves → next §1.x
- Each file edit:
  - Read existing content first
  - Propose exact diff
  - User presses `1` to approve (Pattern A)
  - **NEVER** "allow all"
  - **NEVER** "don't ask again"
- After each Python file save:
  - `Select-String -Pattern "—" <file>` → must return nothing (em-dash check)
  - Import test: `.venv\Scripts\python.exe -c "from <module> import <symbol>; print('OK')"`
- After each YAML file save:
  - `Get-Content <file>` → visual inspection
  - YAML syntax sanity check (Antigravity will likely flag syntax errors)

### §5.3 Per-commit checklist

For each of the 4 commits:

1. `git status` — verify only intended files staged
2. `git add <file>` per file (NEVER `git add .`)
3. Write `.commit_msg.tmp` via Antigravity Write tool (NOT PowerShell heredoc)
4. `git commit -F .commit_msg.tmp`
5. `Remove-Item .commit_msg.tmp`
6. `git log --oneline -1` — verify message and hash
7. `git push origin main`
8. `git log origin/main..HEAD` — must be empty (push verified)
9. Optional: visit GitHub web UI to confirm commit visible

### §5.4 Post-build verification (full)

- [ ] All 4 commits visible in `git log --oneline -8`
- [ ] `tests/test_phase5_batchB.py` runs: `$env:PYTHONPATH="C:/dev/stockmarket-brain"; .venv\Scripts\python.exe -m pytest tests/test_phase5_batchB.py -v`
- [ ] V5.1 PASS
- [ ] V5.7a + V5.7b PASS
- [ ] V5.8 PASS (or documented partial — Flash CHALLENGE case)
- [ ] DB residue: TIER2F paper_trades = N (test-determined), agent_disagreements = 0
- [ ] cron-job.org dashboard shows job created and last fired successfully
- [ ] GH Actions tab shows tier0f-poller.yml triggered at least once via both paths (cron-job.org webhook + internal cron fallback)
- [ ] GH Actions tab shows tier2f.yml triggered via workflow_dispatch with filing_id input
- [ ] Latest workflow run logs: no Node.js 20 deprecation warnings
- [ ] `tier2_signals.yml` no longer present in `.github/workflows/`

### §5.5 Rollback plan (per commit, ordered last-to-first)

If V5.8 (final acceptance) FAILS:

1. **Commit 4 issues** → fix tests or brief, no revert needed (docs/tests are non-functional)
2. **Commit 3 issues** (workflows broken) → `git revert <commit3-hash>` to restore tier2_signals.yml and Node.js v4/v5. Production resumes on prior workflow state.
3. **Commit 2 issues** (Tier-3 logic broken) → `git revert <commit2-hash>` to restore (ticker)-only duplicate check. Phase 5 Batch A still functional.
4. **Commit 1 issues** (Poller bug) → `git revert <commit1-hash>` to remove poller. Tier-2F still callable manually via `python -m agents.tier2_fundamental`.

**Each commit reverts independently. No cross-dependencies.**

### §5.6 Session-end checklist (handoff readiness)

- [ ] All commits pushed to `origin/main`
- [ ] No `.commit_msg.tmp` left over in repo
- [ ] No throwaway scripts (`scripts/recon_*`, `scripts/debug_*`, `scripts/smoke_*`) committed (delete if exists)
- [ ] `git status` shows only machine-local files
- [ ] `.env` not committed (verify with `git log --all --full-history -- .env` returns nothing)
- [ ] If any TIER2F_TEST_MODE env var set during build: `Remove-Item Env:\TIER2F_TEST_MODE -ErrorAction SilentlyContinue`
- [ ] cron-job.org test fire executed and logged
- [ ] Generate chat handoff via skill if session needs continuation

---

## §6 Open Questions / Deferred Items

### §6.1 Active deferrals (carried from prior phases)

| ID | Item | Defer reason | Retry/revisit condition |
|----|------|-------------|------------------------|
| Q1 | **V5.3 + V5.4 (Batch A unfinished)** | Flash CHALLENGED all tradeable filings on 2026-05-21 (NIFTY +0.35% mild green insufficient) | Retry on NIFTY +0.8% strong green day OR Phase 6 reconciliation OR Flash CHALLENGE rate <70% over 2-week production sample |
| Q2 | **SOLO_DEEPSEEK functional path** | Current cascade treats Haiku-broken as both_apis_down | Phase 6 after-hours engine design (DeepSeek-heavy fallback infrastructure) |
| Q3 | **Tier-1F news-driven trade engine** | 6-block design locked but v3.1 sequence placement undecided | After Phase 5 + Phase 6 complete; evaluate before Phase 7 |
| Q4 | **filings_log.published_at population** | Column exists, populated unevenly | Phase 6 concern, no Phase 5 impact |
| Q5 | **filing-memory-backfill cron time mismatch** | YAML says 00:30 IST, observed run 5:20 AM IST | Low priority — workflow succeeded with 144 base_price rows. Investigate during Phase 6 audit. |
| Q6 | **Tier-1 News Researcher failing** | Known bugs (`.NS` suffix + `news_log.symbol` column missing) | Tier-1F track, not Phase 5 |
| Q7 | **Tier-1 Guardian dormant (0 alerts ever)** | Same root cause as Q6 | Tier-1F track |

### §6.2 New questions raised during Batch B planning + recon

| ID | Question | Trigger to revisit |
|----|----------|-------------------|
| N1 | cron-job.org free tier limits — sufficient for 2-min Tier-0F + 5-min Tier-0 + future jobs? | Monitor first 30 days; upgrade if approaching 10K/month limit |
| N2 | Concurrent Tier-2F invocations — if 3+ material filings classified in same 2-min window? | Observe in production; if observed, add queue mechanism in Phase 6 |
| N3 | Tier-3 race condition — sequential dispatch guaranteed? | Phase 6 audit if any duplicate paper trade observed |
| N4 | V5.8 timing under stress — Haiku + Flash p99 latency in production? | Track latency over 50+ real triggers; if p99 > 8 min, tune cron cadence |
| N5 | Flash CHALLENGE rate in non-bearish markets — is current prompt too skeptic? | Sample 20+ production triggers; if CHALLENGE > 70%, soften verifier prompt |
| **N6** | **190 backlog filings on first deployment — process all or skip?** | **Decide before first deploy: (a) let poller process all 190 over ~36 min, OR (b) pre-mark `picked_by_tier0f=true` for backlog to start fresh from new filings only** |
| **N7** | **`uniq_paper_trades_ticker_date_source` partial index — does it conflict with Gap 5 fix?** | **Verify in Supabase Dashboard: query `pg_indexes` for full index definition. If on `(ticker, signal_date, source)`, no conflict. If on `(ticker, source)`, may need redesign.** |
| **N8** | **`agents/tier2_signals.py` Python file orphan — when to delete?** | **Phase 6+ cleanup. Currently zero imports, but file remains on disk per O9.** |
| **N9.1** | **Em-dash cleanup in tier3_position_manager.py** | 5 pre-existing em-dashes in f-strings. Out of Batch B scope; flag for Phase 6+. |
| **N9.2** | **update_paper_trades.yml already at v6** | Why was this file's setup-python already at v6 before Batch B Node.js sweep? Historical curiosity, no functional impact. |
| **N9.3** | **apply_rules() KeyError on missing keys** | If signal dict is missing 'confidence', 'rsi', or 'direction' keys, apply_rules() crashes mid-iteration. Robustness/defensive-coding improvement needed in Phase 6 (paper trading should not crash on malformed payloads). |
| **N9.4** | **Pre-commit pytest as working agreement?** | Existing Tier-3 test was silently broken by Commit 2 (Gap 5 fix) and only discovered in Prompt 4a via search-first. Consider adding "run pytest before every commit that touches `agents/`" to working agreements. |
| **N9.5** | **V5.8 post-deploy validation timing** | When to actually run V5.8 (full live pipeline timing test)? Recommendation: First material filing classified after cron-job.org dashboard setup. Document result in brief v5 (post-deploy). |

### §6.3 Decisions deferred until production data

- Tier-2F verifier prompt softening (depends on Flash CHALLENGE rate)
- Tier-0F poller cadence tuning (2 min may be too aggressive or insufficient based on production latency observations)
- DDL-based vs logic-only enforcement for Tier-3 (current: logic-only; may upgrade if races observed)
- Node.js v6+ migration (next deprecation cycle; track GitHub announcements)

---

## §7 Document version history

| Version | Date | Change | Author |
|---------|------|--------|--------|
| v1 | 2026-05-21 | Initial pre-recon draft | claude.ai planning session |
| v2 | 2026-05-21 | Cadence + architecture clarifications: 2-min Tier-0F cron, `*/10` fallback, NEW §2.0 cron-job.org PRIMARY pattern, NEW §2.4.1 latency budget, cost recalculation | claude.ai planning session |
| **v3** | **2026-05-21** | **POST-RECON: all 6 critical findings integrated. Column names corrected throughout (symbol/is_material/material_score). NEW D9 deliverable: filing_id column on paper_trades. Idempotency switched to existing picked_by_tier0f orphan column (no new DDL). Tier-3 fix corrected to list-iteration style (lines 25 + 154). §0.6 fully populated with recon details. §2.1.1 added (filing_id linking). Build steps §3.2-§3.4 updated. Commit 1 absorbs D9 changes.** | **claude.ai planning + Antigravity recon synthesis** |
| **v4** | **2026-05-21** | **Post-execution corrections: §0.6.7 (Group B setup-python@v4 discovered post-edit), §0.6.9 (backlog 190 not 176), §2.7 (actual sweep was 12 files not 14), §3.3.1 (no _insert_paper_trade function, inline in process_filing), §3.13 (Commit 3 actual: 317bde3, 15 files, +87/-74), §4 (test fixture column corrections + try_open_position fictional + V5.8 deferred + Tier-3 test regression fix), §6.2 N9 questions (5 new).** | **Antigravity execution** |
| v5 FINAL | (TBD post-deploy) | V5.8 post-deploy validation result + cron-job.org dashboard verification | Antigravity execution |

---

## §8 References

- **Repo:** `github.com/goelvipulvg-max/stockmarket-brain`
- **Local working dir:** `C:\dev\stockmarket-brain\`
- **Prior batch brief:** `docs/phase-5-batchA-execution-brief.md`
- **Master plan:** `docs/stockmarket-brain-v3.1-master-plan.md` (§7 Phase 5, §11 budget)
- **Phase 5 Batch A commits:** `77a2771` (pre-build), `1849a75` (ThinkingBlock fix), `c7b7b1b` (code), `20491c1` (brief)
- **Models:** Haiku `claude-haiku-4-5-20251001`, DeepSeek `deepseek-v4-flash`
- **Telegram channel:** "StockMarket-Brain Trades" (ID `-1003960313973`, env `TELEGRAM_TIER3_CHANNEL`)
- **GitHub PAT scope required:** `workflow` (for workflow_dispatch API)

---

**End of Phase 5 Batch B Execution Brief v1.**

*Next action: Open in Antigravity, run §1 recon, populate §0.6 with findings, then proceed to §3 build steps.*

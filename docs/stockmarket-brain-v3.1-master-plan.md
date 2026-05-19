# Stock Market Brain — v3.1 Master Plan

**Date:** 2026-05-16 (v3.1 revision)
**Author:** Claude (chat) + Gaurav
**Repo:** `goelvipulvg-max/stockmarket-brain`
**Status:** LOCKED for execution — single source of truth
**Supersedes:** v1 (`tier2f-bulletproof-plan-v1.md`), v2 (`stockmarket-brain-v2-master-plan.md`), and v3 (`stockmarket-brain-v3-master-plan.md`)

> **Why v3.1 exists:** v3 was written on 2026-05-16 and Phase 0 was executed the
> *same day*. v3's §3 therefore predates the actual build and describes Phase 0
> as it was *planned*, not as it was *built* — and it diverges from reality in
> three places. v3.1 corrects §3 to match the as-built commits, folds in two
> deferred plan NOTES, and adds an explicit Execution Timeline (§0.5).
> **Everything else in v3 was sound and is carried forward unchanged.**

---

## §0 Executive Summary

Stock Market Brain is an **automated NSE filing-driven paper-trading system**. It
reads corporate announcements, analyzes them with a 2-model AI consensus, simulates
trades against a virtual ₹10 lakh portfolio, and learns from outcomes over time.

**The system has two trading engines:**

1. **Real-time engine** (market hours): live filings → 2-AI consensus → paper trade
2. **After-hours engine** (post-close): evening filings → next-day gap setups → pre-open execution

Both feed a **memory system** that is seeded on day one from 1,430 historical
filing outcomes and improves as live trades resolve.

**Honest scope (corrected from v1/v2):**

- No "deep 2-year fundamental research" exists — that was a wrong assumption. The system uses live yFinance charts + a per-company filing-summary history built from `research_cache`.
- The system tracks **simulated capital** via a virtual ledger that v3 builds from scratch — no capital tracking exists today.
- Confidence scores are **realistic (50-85% range)**. The system does NOT promise 90-95% accuracy — no equity system can. Current win rate is ~10% (3/31); a well-built system targets 55-65%.

**Cost ceiling:** ₹400-800/month (2-model verification, no daily trade cap, NIFTY500 universe).

---

## §0.5 Execution Timeline & Verification Model — NEW IN v3.1

This section governs *how* v3.1 is executed. It does not change any phase's
design — it makes the build cadence and the verification discipline explicit.

### The single source of truth

All implementation, Phase 0 through Phase 8, follows **this v3.1 document**. v3
and earlier are superseded. Antigravity (Claude Code) should be given v3.1 — never
v3 — as its reference, because v3's §3 describes Phase 0 incorrectly (see §3 header note).

### Build cadence

| When | What happens |
|---|---|
| **Sat 16-May + Sun 17-May** | Build/implement all remaining phases (Phase 1 → Phase 8) in Antigravity. Market is closed both days, so this is dedicated build time. Phase 0 is already complete (shipped 16-May). |
| **Mon 18-May (after ~3:30 PM IST)** | **Live verification pass** — the gates that need live market data. |
| **Thursday (this week, 22-May)** | **Deep end-to-end analysis** — full system verification, all engines, all loops. |

### Two-layer verification — both compulsory, neither optional

Every phase's verification gates are split into two parts. **A gate is never
skipped — it is split.** This is necessary because Sat/Sun are market-closed days,
so any gate that depends on live filings/prices/trades simply *cannot* be
evaluated on the weekend. It is not a shortcut; it is the only honest way to
verify during a market holiday.

**Layer 1 — Temp verification (immediately after each phase, including weekend).**
Everything that can be checked *without* live market data:
- Schema correctness — columns, indexes, tables, constraints exist as specified.
- Code health — modules import, no syntax errors, dry-runs succeed.
- Structural logic — functions return correct shapes on test/mock input.
- Idempotency — re-running an insert/sync does not duplicate.

Layer 1 runs the moment a phase's build is done. The next phase does not start
until the current phase's Layer-1 checks are green.

**Layer 2 — Live verification (Monday 18-May, market open).**
Everything that *only* live market data can prove:
- V0.1 — OTHER classification rate < 15% on the day's real filings.
- V0.4 — classification cadence ~5 min apart.
- V0.5 — P&L sign correct on a live SELL TARGET_HIT.
- V0.6 — Telegram 8-15 alerts/day.
- Real filings flowing end-to-end through Tier-0F → Tier-2F → sized paper trade.
- After-hours queue → pre-open execution against real overnight gaps.

**Layer 3 — Deep analysis (Thursday 22-May).**
Not a replacement for Layers 1-2 — a safety net *on top* of them. Runs the §10
end-to-end smoke tests (E2E-1 … E2E-6) plus capital reconciliation and the full
memory loop, verifying the whole system together once every component exists and
has seen real market data.

### The V0.1 dependency — eyes open

v3 §13 makes V0.1 (OTHER rate < 15%) a hard gate: nothing downstream should
proceed until V0.1 passes. v3.1 keeps that gate but acknowledges a deliberate,
already-made decision (recorded in the Phase 0 handoff): **Phase 0 was shipped in
full and verification deferred to Monday.** By the same logic, v3.1 permits
building Phase 1 → Phase 8 over the weekend *before* V0.1's Monday result.

This is a conscious trade-off, not an oversight:
- If V0.1 **passes** Monday → proceed; the weekend build stands.
- If V0.1 **fails** Monday → Phase 0's classification needs a fix. The
  weekend-built Phase 1-8 *code* survives — Phases 1-4 are schema, utilities,
  ledger, and memory scaffolding, none of which break from a classification bug.
  Only the engines (Phase 5/6) would be fed bad data until Phase 0 is corrected.
- Net: building ahead of V0.1 is **risky but recoverable** — not catastrophic.

If a lower-risk path is preferred at any point, the fallback is simply to pause
after Phase 4 and wait for Monday's V0.1 before building the engines.

---

## §1 Verified Reality — The Foundation v3 Stands On

Every fact below was confirmed by recon. v3 makes NO assumptions beyond these.

### 1.1 Tier-0 (live filings agent)

- 7-stage pipeline: fetch NSE → dedup → PDF parse → DeepSeek classify → tradeable gate → liquidity gate → market gate → gap calc → Telegram + Supabase write
- Runs every **15 minutes** during market hours (not hourly)
- Writes to **Supabase** `filings_log` (870 rows active)
- Does NOT write to `paper_trades`
- **93% of filings classified as "OTHER"** — root cause verified: `max_tokens=150` truncates JSON responses mid-string → parse fails → defaults to OTHER/score=0. Plus occasional empty API responses. The model itself is NOT broken.

### 1.2 Databases

| DB | Role | Key tables |
|---|---|---|
| **Supabase** | Active OLTP | paper_trades (31 rows), filings_log (870), tier3_decisions (11), trade_memory (6) |
| **Neon** | Reference data | research_cache (102K rows/117MB), event_outcomes (1,430), company_profiles (504), nse500_watchlist (504), pattern_library (17) |
| **QuestDB** | Time-series log | news_events |

### 1.3 What Neon actually holds

- **research_cache** — 102,323 rows. AI summaries of individual NSE filings (2024-2026). ~50% have NULL `response_text` (batch incomplete). Per-filing, not per-company research. **It is a frozen cache** — Tier-0 never writes to it, so it stopped updating. v3 does NOT rely on it as memory; v3 builds a live `filing_memory` table instead (§3.8, §4.4b).
- **event_outcomes** — 1,430 rows. Historical `(symbol, event_type, event_date) → (signal_generated, trade_result, outcome_score)`. 2-year span. Sparse: ~1-2 events per symbol. **This is the memory seed.**
- **company_profiles** — 504 companies. Basic info only (sector, industry, market_cap, 1-paragraph summary). `risk_factors` and `moat_analysis` columns are **100% NULL** — dead columns.
- **nse500_watchlist** — 504 stocks with ISIN codes. The canonical NIFTY500 universe.
- **No price history anywhere.** All price/chart data comes live from yFinance.

### 1.4 Capital tracking — does not exist

- `paper_trades` has NO `quantity`, `shares`, `position_size`, `capital_allocated`, or rupee `pnl` column. Only `pnl_pct` (percentage).
- No `portfolio`, `account_balance`, or `ledger` table.
- Only capital reference: hardcoded `position_size: 25000` in `tier3_decisions` and CLAUDE.md's "₹5L" documentation (used by no code).

### 1.5 Upstox — scaffold, never completed

- `upstox_paper_trade.py` is dead code (no workflow triggers it).
- Active paper-trade tracker is `update_paper_trades.py` — uses **Yahoo Finance**, not Upstox.
- Upstox sandbox does NOT support market data. v3 uses yFinance; Upstox deferred to future live-trading phase.

### 1.6 Existing agent behavior

- **Tier-2** (`tier2_signals.py`): 10-stock hardcoded watchlist, RSI+MACD, DeepSeek V4 Flash. Inserts 13 fields into paper_trades at line 126. No `source` field.
- **Tier-3** (`tier3_position_manager.py`): reads OPEN signals for today from paper_trades, writes to `tier3_decisions`. Does NOT filter by source. **Has a duplicate-position rule that blocks any ticker with an existing OPEN trade.**
- **update_paper_trades.py**: the real position tracker. Yahoo Finance, T1/T2/T3 trailing SL, manual trigger only (no cron).

### 1.7 The 9 Gaps (and v3's resolution)

| Gap | Verified Reality | v3 Resolution | Phase |
|---|---|---|---|
| 1 — Data | No deep 2-year research. research_cache = filing summaries. | yFinance live charts + per-company filing history from research_cache | §6 |
| 2 — Capital | Zero capital tracking | Build virtual ledger (₹10L simulated) | §5 |
| 3 — Memory | 31 trades, empty memory | Seed from event_outcomes (1,430) + research_cache | §6 |
| 4 — gap_calculator | 3 separate bugs | Fixed all 3 in Phase 0 (see §3.4) | §3 |
| 5 — Tier-3 duplicate rule | Blocks 2nd signal per ticker | Allow one OPEN per (ticker, source) | §4, §7 |
| 6 — P&L sign | ADANIENT SELL TARGET_HIT shows -15% | Fixed in Phase 0 (see §3.5) | §3 |
| 7 — After-hours scope | "deep fundamental" data doesn't exist | Redefine as next-day gap predictor | §8 |
| 8 — TCS/INFY missing | False alarm — they exist | No action | — |
| 9 — Empty API responses | Separate failure from truncation | Added retry logic in Phase 0 | §3 |

---

## §2 Build Sequence & Reasoning

The sequence is **dependency-driven**. Each phase below explains *why it sits where it sits*.

```
Phase 0 — Tier-0 v2 Fixes          [foundation repair]   ✅ DONE 16-May
   ↓ (clean filing data + stable event taxonomy)
Phase 1 — Schema Migrations        [all DB changes at once]
   ↓ (paper_trades has capital columns + source)
Phase 2 — Virtual Capital Ledger   [the money foundation]
   ↓ (system can now size positions in rupees)
Phase 3 — Shared Utilities         [reused by both engines]
   ↓ (chart fetch, fundamentals, F&O check, target generator)
Phase 4 — Memory Foundation + Seed [seeded from event_outcomes]
   ↓ (agents can query historical patterns)
Phase 5 — Real-Time Engine         [Tier-0F + Tier-2F]
   ↓ (validates the 2-model consensus pattern)
Phase 6 — After-Hours Engine       [reuses Phase 5 components]
   ↓
Phase 7 — Tier-4F Memory Orchestrator [nightly learning loop]
   ↓
Phase 8 — Integration + Monitoring [end-to-end verification]
```

**Why this order:**

- **Phase 0 first** — Everything downstream consumes filing data. With 93% "OTHER", every engine would train and trade on garbage. Non-negotiable first step. *(Complete — see §3.)*
- **Phase 1 before 2** — The capital ledger needs new columns on `paper_trades`. Doing all schema changes in one phase avoids migrating the same table twice.
- **Phase 2 before engines** — Engines must size positions in rupees. Without the ledger, "₹10 lakh" is meaningless and engines would need retrofitting later. This is the v2 mistake v3 avoids.
- **Phase 3 before engines** — Tier-2F and after-hours share ~60% of code (chart fetch, fundamentals lookup, F&O check, target generator, 2-model consensus). Building these once as utilities prevents the v2 broken-dependency bug where Phase 2 used code defined in Phase 3.
- **Phase 4 before engines** — Engines inject memory context into AI prompts. Memory must exist (and be seeded) before the first signal, or early signals are context-blind.
- **Phase 5 before 6** — Real-time engine is simpler to test (event-driven, immediate feedback). It validates the 2-model consensus pattern. After-hours then reuses that validated pattern plus adds timing complexity (queue + pre-open executor). Building the simpler engine first de-risks the harder one. *(Note: after-hours is the higher-value engine per business edge — but "higher value" and "build first" are different. Validating the consensus pattern on the simpler engine protects the valuable one.)*
- **Phase 7 after engines** — Tier-4F's nightly job needs live trades flowing to extract patterns. It also seeds from event_outcomes (Phase 4), but the *learning loop* needs real trade outcomes.
- **Phase 8 last** — End-to-end tests need all components present.

**Total: ~18-24 hours active build over multiple sessions.**

---

## §3 Phase 0 — Tier-0 v2 Fixes — ✅ COMPLETE (as-built)

> **v3.1 NOTE — READ THIS FIRST.** Phase 0 is **already built and committed**
> (16-May). This section describes Phase 0 **as it was actually shipped**, which
> differs from v3's original §3 in three places (§3.4 gap_calculator design,
> §3.7 cron, and a duplicate header). **For absolute as-built truth, the commits
> are authoritative; this section is the corrected narrative.** Do not re-implement
> anything in §3 — it is reference only.

**Goal:** Make filing classification correct and reliable. **Status:** Done. **Commits on `main`:** `ca3d84b` (0.1), `0d45748` (0.3), `17c37d9` (0.4), `5397e36` (0.5), `220ee07` (0.6), `b9bef48` (0.7), `fcd0906` (0.8). 0.2 was a Supabase SQL Editor schema change (no commit).

### 3.1 Fix #1 — DeepSeek max_tokens truncation (the 93% OTHER bug) — commit `ca3d84b`

**Root cause (verified by live test):** `max_tokens=150` cuts JSON responses mid-string. Parse fails → saved as OTHER/score=0.

**As-built — `agents/tier0_filings.py` `classify_filing()`:**

- `max_tokens` 150 → 400 (primary fix).
- `temperature=0.3` added (reduces hallucination).
- Retry loop added (empty response + JSON-parse failure).
- `summary` constrained to ≤12 words in the prompt so responses stay compact.
- **Bonus root-cause fix:** DeepSeek sometimes echoed the f-string template's
  `{{ }}` double braces — a `{{}}` stripping fix was added. This was a genuine
  *second* contributor to the OTHER problem, caught during the 0.1 build.

Live test passed: a real RESULTS filing classified as RESULTS, not OTHER.

### 3.2 Fix #9 — Empty API response retry — commit `ca3d84b`

DeepSeek occasionally returns an empty string for material filings — a failure
mode separate from truncation. The classify call is now wrapped in a retry loop
(`max_retries=2`, 2-second backoff) that retries on both empty responses and
JSON-parse failures, raising only after retries are exhausted.

### 3.3 Schema additions to Supabase `filings_log` — Phase 0.2 (Supabase SQL Editor, no commit)

Run directly in the Supabase Dashboard SQL Editor (DDL cannot go through supabase-py):

```sql
ALTER TABLE filings_log ADD COLUMN IF NOT EXISTS is_material BOOLEAN DEFAULT FALSE;
ALTER TABLE filings_log ADD COLUMN IF NOT EXISTS directional_bias TEXT;
ALTER TABLE filings_log ADD COLUMN IF NOT EXISTS reasoning TEXT;
ALTER TABLE filings_log ADD COLUMN IF NOT EXISTS picked_by_tier0f BOOLEAN DEFAULT FALSE;
ALTER TABLE filings_log ADD COLUMN IF NOT EXISTS picked_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_filings_pickup
ON filings_log (picked_by_tier0f, material_score, classified_at)
WHERE picked_by_tier0f = FALSE AND material_score >= 6;
```

Phase 0.2 **also pulled the `filing_memory` CREATE TABLE forward** (see §4.4b)
so that the Phase 0.7 sync job had a table to write to. This resolves the v3
§3.8 dependency. **Consequence for Phase 1:** the §4.4b `CREATE TABLE
filing_memory` is already done — it is `CREATE TABLE IF NOT EXISTS`, so harmless
to re-run, but Phase 1's prompt should note it is a no-op.

### 3.4 Fix #11 — Expanded event taxonomy — commit `0d45748`

The inline classify prompt was externalised to `prompts/tier0_classify_v2.txt`,
and the event taxonomy expanded **13 → 28 types** (the old 13 forced too much
into OTHER). Three fields were added to the classify JSON: `trade_confidence`
(1-100), `directional_bias` (BULLISH/BEARISH/NEUTRAL), `reasoning`.

Enum validation was added: if the model returns an `event_type` outside the
28-type enum, it is coerced to OTHER and logged with a `[WARN]`. Both
`save_to_supabase()` and `main()`'s fallback dict were updated to write the new
fields. Live test: all 7 expected fields present.

### 3.4b Fix #4 — gap_calculator's 3 bugs — commit `17c37d9` — **HYBRID design (as-built)**

> **v3.1 CORRECTION.** v3's original §3.4 printed a *pure Option A*
> implementation (`if not symbol: return (None, 0)`) — that approach was
> **considered and rejected** during the build, because no current caller passes
> `symbol`, so it would return `(None, 0)` for everything. The **HYBRID design
> below is what actually shipped.** v3's printed code is wrong; this is correct.

Recon confirmed THREE separate bugs in `_get_historical_gap()`:

| Bug | Code queried | Reality |
|---|---|---|
| A | `pattern_data->>'avg_gap_pct'` | key is `avg_impact_pct` |
| B | `pattern_data->>'sample_size'` | `sample_size` is a top-level column |
| C | `WHERE pattern_name = 'RESULTS'` | format is `Industrials_dividend` (`Sector_eventtype`) |

**As-built fix — `utils/gap_calculator.py`.** The signature became
`_get_historical_gap(event_type, symbol=None)` with **hybrid matching**:

- **`symbol` given** → exact sector match: look up the stock's sector from
  `company_profiles` (Neon, `.NS` suffix), build `pattern_name =
  f"{sector}_{event_type.lower()}"`, query `pattern_library` for that exact key.
- **`symbol` not given** → LIKE-suffix fallback: match `pattern_name LIKE
  '%_{event_type.lower()}'` and aggregate across sectors, so the function still
  returns a useful number even with no symbol.

Live test results: exact `('dividend','RELIANCE')` → `(1.82, 41)`; fallback
`('dividend')` → `(1.74, 240)`; miss `('results','RELIANCE')` → `(None, 0)`.

> **Build-time pitfall caught (do not repeat):** Antigravity first wrote
> `VALID_EVENT_TYPES = {{ }}` — a set-inside-a-set, invalid Python, `TypeError`
> on load. Double-brace escaping belongs **only** in the `.txt` prompt for
> `.format()`, never in Python source. Fixed to a single brace at review.

**Honest caveat:** `pattern_library` has only 17 rows, all dividend/buyback/split.
For RESULTS, M&A, CONTRACT_WIN there is no historical pattern — gap_calculator
falls back to `DEFAULT_GAPS` for those. The bug fix is correct, but coverage is
thin. See §3.10 NOTE 2 for the long-term rebuild plan.

### 3.5 Fix #6 — P&L sign convention — commit `5397e36` (+ 1 Supabase data fix)

**Symptom:** ADANIENT SELL, status=TARGET_HIT, `pnl_pct = -15.0%` — a SELL
hitting its target should be positive.

**Root cause (found, not just investigated):** Tier-2/Tier-3 target and
trailing-SL prices used **BUY-only multipliers** (`entry*1.10`, `entry*1.15`),
which are wrong for SELL trades.

**As-built fix:** a new helper `_dir_price(entry, mult, direction)` —
`BUY = entry*mult`, `SELL = entry*(2-mult)` — applied at all 6 target/SL sites.
`calc_pnl_pct()` and the hit-detection logic were **NOT** touched (they were
already correct — the formula `(entry - exit) / entry` is right for shorts).

**Data fix (Supabase SQL Editor):** the one already-bad row was corrected —
`paper_trades` id=52 (ADANIENT.NS SELL T3): `exit_price` 2921.34 → 2159.26,
`pnl_pct` -15.00 → +15.00.

This matters because memory learns from `trade_result`: a -15% loss tagged
TARGET_HIT would teach memory garbage.

### 3.6 Fix — Tier-0 trigger cadence 15 min → 5 min — commit `220ee07`

> **v3.1 CORRECTION.** v3's original §3.7 said "change `tier0-agent.yml` cron to
> `*/5`". That is **not** what was done. Recon during the 0.6 build found that
> **cron-job.org is the real PRIMARY trigger** for Tier-0 (it was set to 15 min).

**As-built:**

- **cron-job.org** job "Tier-0 Filings Agent" → changed to **every 5 minutes**.
  This is the primary trigger.
- **`.github/workflows/tier0-agent.yml`** GitHub cron → **left UNCHANGED** as a
  30-minute emergency fallback. Only its comment was updated to say so.

### 3.7 filing_memory sync job — commit `b9bef48`

**Why:** `research_cache` (Neon, 102K rows) is a *frozen* archive — Tier-0 never
writes to it. Memory must be **live**. The fix is a dedicated permanent
`filing_memory` table (schema §4.4b, created in Phase 0.2) fed by a lightweight
sync job — *not* an extra Neon write inside Tier-0 (that would risk Tier-0
missing its 5-min window).

**As-built:** new `agents/filing_memory_sync.py` + new
`.github/workflows/filing-memory-sync.yml` (cron `*/10 3-9 * * 1-5`, every 10
min during market hours). The job copies new material `filings_log` rows
(`material_score >= 6`, `event_type != 'OTHER'`, last 20-min window) into
`filing_memory`, deduplicated by the `url_hash` UNIQUE constraint.

NULL `url_hash` rows are **skipped with a warning** — a hash was deliberately
*not* synthesized from `source_url` (that risked creating duplicate rows later).
5 legacy rows have NULL `url_hash`.

Tested: 47 rows inserted; a second run inserted 0 (idempotent); the test rows
were then deleted, so `filing_memory` is intentionally back to 0 rows.

> **v3.1 watch item (for Monday verification).** The v3 §3.8 sync code wrote
> `"filing_timestamp": r.get("published_at")`. But `filings_log.published_at` is
> **always NULL/dead** (verified). If the as-built sync job kept that line,
> `filing_memory.filing_timestamp` will always be NULL — which the after-hours
> engine (Phase 6, 4-5 PM window detection) later needs. **Monday: add a
> `SELECT filing_timestamp FROM filing_memory` check. If always NULL, the fix is
> to use `classified_at` instead.**

### 3.8 Deprecate after_hours_watcher — commit `fcd0906`

`after_hours_watcher` was broken (Neon schema mismatch, 1 row in 15 days).
The `schedule:` block was **removed** from
`.github/workflows/after_hours_watcher.yml` (`workflow_dispatch` kept, plus a
`DEPRECATED` comment). `scripts/after_hours_watcher.py` was **left untouched** —
Phase 6 may salvage logic from it. Deprecate, not delete: the after-hours concept
is the core trading edge, and v3.1 §8 Phase 6 builds the proper replacement.

> **Action item:** confirm no stale `after_hours_watcher` job still exists on
> cron-job.org — if one does, it will keep hitting the now-deprecated workflow.

### 3.9 Phase 0 Verification Gates

> **v3.1 fix:** v3 had two `### 3.9` headers. The duplicate is removed; this is
> the single Phase 0 gates section.

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V0.1 | event_type distribution, last 24h | OTHER < 15% | Live (Mon) |
| V0.2 | recent rows | trade_confidence, is_material, directional_bias, reasoning populated | Live (Mon) |
| V0.3 | gap_calculator on a dividend stock | returns MEDIUM/HIGH confidence (not always LOW) | Live (Mon) |
| V0.4 | filings_log timestamps | ~5 min apart | Live (Mon) |
| V0.5 | P&L sign | a SELL TARGET_HIT shows positive pnl_pct | Live (Mon) |
| V0.6 | Telegram | 8-15 alerts/day | Live (Mon) |
| V0.7 | filing_memory sync | Monday's material filings present, no duplicates | Live (Mon) |
| V0.8 | filing_timestamp | not always NULL (see §3.7 watch item) | Live (Mon) |

**Monday 18-May checklist (run after ~3:30 PM IST, Supabase SQL Editor + GitHub Actions tab):**

- V0.1 — `SELECT event_type, count(*) FROM filings_log WHERE classified_at >= CURRENT_DATE GROUP BY event_type` → OTHER < 15%.
- V0.2 — `SELECT event_type, trade_confidence, is_material, directional_bias, reasoning FROM filings_log WHERE classified_at >= CURRENT_DATE LIMIT 10` → all populated.
- V0.4 — `SELECT classified_at FROM filings_log WHERE classified_at >= CURRENT_DATE ORDER BY classified_at DESC LIMIT 20` → ~5 min apart.
- V0.7 — `SELECT count(*), max(created_at) FROM filing_memory` → Monday's material filings present, no duplicates.
- V0.8 — `SELECT filing_timestamp FROM filing_memory WHERE filing_timestamp IS NOT NULL LIMIT 5` → returns rows (not all NULL).
- GitHub Actions tab — `tier0-agent` and `filing-memory-sync` green; `after_hours_watcher` not running on schedule.
- V0.3 / V0.5 / V0.6 — observed as live trades flow.

### 3.10 Plan NOTES folded in from the Phase 0 handoff — NEW IN v3.1

Two decisions were locked during the Phase 0 build but lived only in the chat
handoff. They are recorded here so they are not lost:

**NOTE 1 — Phase 4 also backfills existing filings_log into filing_memory.**
Alongside `event_outcomes` seeding (§6 Phase 4), Phase 4 must also do a **one-time
backfill** of existing *material* `filings_log` rows into `filing_memory`. Phase
4b's outcome job will then mature them instantly, since their 5d/10d/30d windows
are already in the past. All memory seeding is grouped in Phase 4. *(Reflected in
§6 Phase 4 below.)*

**NOTE 2 — A future phase rebuilds pattern_library from filing_memory.**
`pattern_library` today is only 17 rows (dividend/buyback/split) — bug-fixed but
thin. Once `filing_memory` has accumulated **~3 months of matured,
market-relative outcome data**, a future phase will **rebuild `pattern_library`
from `filing_memory`**, giving gap_calculator real coverage for RESULTS, M&A,
CONTRACT_WIN, etc. instead of `DEFAULT_GAPS`. This is deferred — not part of
Phases 1-8 — but is the intended long-term path. *(Tracked in §15.)*

---

## §4 Phase 1 — Schema Migrations

**Goal:** All database structural changes in one phase. **Duration:** ~45 min.

> **v3.1 pre-flight checks — run BEFORE the migrations below.** Two edge cases
> can make Phase 1 fail or silently misbehave; check both first.
>
> 1. **Duplicate `(ticker, signal_date)` rows.** After the `source` backfill,
>    all 31 existing `paper_trades` rows become `source='TIER2'`. If any two
>    share the same `(ticker, signal_date)`, the new composite UNIQUE index will
>    **fail to create**. Run first:
>    `SELECT ticker, signal_date, count(*) FROM paper_trades GROUP BY ticker, signal_date HAVING count(*) > 1;`
>    If rows return, resolve them before creating the index.
> 2. **CONSTRAINT vs INDEX.** `DROP CONSTRAINT IF EXISTS uniq_paper_trades_ticker_date`
>    only works if the old uniqueness is a *constraint*. If it is a plain
>    *unique index*, the DROP is a silent no-op and the stale index survives,
>    conflicting with new inserts. Check which it is first:
>    `SELECT conname FROM pg_constraint WHERE conrelid = 'paper_trades'::regclass;`
>    and `SELECT indexname FROM pg_indexes WHERE tablename = 'paper_trades';`
>    Drop whichever object actually holds the old uniqueness.
> 3. **`filing_memory` already exists** (created in Phase 0.2). The §4.4b
>    `CREATE TABLE filing_memory` is `IF NOT EXISTS` — harmless to re-run, but
>    treat it as a no-op verification, not a fresh create.

### 4.1 paper_trades — source column + capital columns

```sql
-- Source attribution
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'TIER2';
-- (the UPDATE below is redundant given NOT NULL DEFAULT, kept only as a safety net)
UPDATE paper_trades SET source = 'TIER2' WHERE source IS NULL;
-- Drop the OLD uniqueness object (constraint OR index — see pre-flight check 2)
ALTER TABLE paper_trades DROP CONSTRAINT IF EXISTS uniq_paper_trades_ticker_date;
-- DROP INDEX IF EXISTS uniq_paper_trades_ticker_date;  -- use this instead if it is an index
CREATE UNIQUE INDEX uniq_paper_trades_ticker_date_source
ON paper_trades (ticker, signal_date, source);

-- Capital / position sizing (Gap 2)
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS quantity INTEGER;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS position_size_rs NUMERIC;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS pnl_rs NUMERIC;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS horizon TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS max_holding_days INTEGER DEFAULT 10;
```

### 4.2 portfolio — the virtual ledger (Gap 2)

```sql
CREATE TABLE IF NOT EXISTS portfolio (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    starting_capital NUMERIC NOT NULL DEFAULT 1000000,   -- ₹10 lakh
    cash_available NUMERIC NOT NULL,
    capital_deployed NUMERIC NOT NULL DEFAULT 0,
    total_equity NUMERIC NOT NULL,                       -- cash + deployed (at cost) + open MTM
    realized_pnl_rs NUMERIC DEFAULT 0,
    unrealized_pnl_rs NUMERIC DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- A single 'current' row + daily snapshots for history
CREATE TABLE IF NOT EXISTS capital_ledger (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    paper_trade_id BIGINT REFERENCES paper_trades(id),
    txn_type TEXT NOT NULL,            -- DEPLOY / RELEASE / PNL_REALIZED
    amount_rs NUMERIC NOT NULL,        -- signed: negative = cash out
    cash_after NUMERIC NOT NULL,
    note TEXT
);
```

### 4.3 paper_trades_queue (after-hours)

```sql
CREATE TABLE IF NOT EXISTS paper_trades_queue (
    id BIGSERIAL PRIMARY KEY,
    queued_at TIMESTAMP DEFAULT NOW(),
    target_execution_date DATE NOT NULL,
    filing_id BIGINT,
    ticker TEXT NOT NULL,
    symbol_base TEXT NOT NULL,
    event_type TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'BUY',
    expected_gap_pct NUMERIC,
    entry_zone_low_pct NUMERIC,
    entry_zone_high_pct NUMERIC,
    max_entry_price NUMERIC,
    t1_target_pct NUMERIC,
    t2_target_pct NUMERIC,
    t3_target_pct NUMERIC,
    stop_loss_pct NUMERIC,
    horizon TEXT,
    max_holding_days INTEGER,
    haiku_confidence INTEGER,
    deepseek_confidence INTEGER,
    consensus BOOLEAN,
    full_reasoning JSONB,
    status TEXT DEFAULT 'QUEUED',      -- QUEUED / EXECUTED / EXPIRED / SKIPPED
    executed_at TIMESTAMP,
    skip_reason TEXT,
    source TEXT DEFAULT 'AFTER_HOURS'
);
CREATE INDEX idx_queue_exec_date ON paper_trades_queue (target_execution_date, status);
```

### 4.4 Memory tables

```sql
-- Seeded from event_outcomes, grows with live trades
CREATE TABLE IF NOT EXISTS trade_memory_v2 (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    source_type TEXT NOT NULL,         -- 'SEED_EVENT_OUTCOME' / 'LIVE_TRADE'
    paper_trade_id BIGINT,
    symbol_base TEXT NOT NULL,
    event_type TEXT,
    sector TEXT,
    market_cap_cr NUMERIC,
    haiku_reasoning TEXT,
    deepseek_reasoning TEXT,
    nifty_mood TEXT,
    outcome TEXT,                      -- TARGET_HIT / SL_HIT / EXPIRED / OPEN / SEED
    pnl_pct NUMERIC,
    holding_days INTEGER,
    pattern_tags TEXT[],
    full_context JSONB
);
CREATE INDEX idx_tm2_tags ON trade_memory_v2 USING GIN (pattern_tags);
CREATE INDEX idx_tm2_event_sector ON trade_memory_v2 (event_type, sector);

-- Aggregated patterns, refreshed nightly, injected into prompts
CREATE TABLE IF NOT EXISTS pattern_insights (
    id BIGSERIAL PRIMARY KEY,
    extracted_at TIMESTAMP DEFAULT NOW(),
    pattern_key TEXT NOT NULL,
    sector TEXT,
    event_type TEXT,
    sample_size INTEGER,
    win_rate NUMERIC,
    avg_outcome_score NUMERIC,
    insight_text TEXT,
    confidence TEXT,                   -- HIGH (n>=20) / MEDIUM (n>=10) / LOW (n>=5)
    active BOOLEAN DEFAULT TRUE
);
CREATE UNIQUE INDEX uniq_pattern_key ON pattern_insights (pattern_key) WHERE active = TRUE;

-- Model disagreements (learning gold)
CREATE TABLE IF NOT EXISTS agent_disagreements (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    filing_id BIGINT,
    ticker TEXT,
    event_type TEXT,
    haiku_decision TEXT,
    haiku_confidence INTEGER,
    haiku_reasoning TEXT,
    deepseek_decision TEXT,
    deepseek_confidence INTEGER,
    deepseek_reasoning TEXT,
    final_action TEXT,
    backtest_outcome TEXT,
    actual_price_move_pct NUMERIC,
    full_context JSONB
);
```

### 4.4b filing_memory — the company filing memory (10/10 design)

> **v3.1 NOTE.** This table was **already created in Phase 0.2** so the Phase 0.7
> sync job had a target. The CREATE below is `IF NOT EXISTS` — re-running it in
> Phase 1 is a harmless no-op. Treat Phase 1's job here as *verifying* the table
> matches this schema, not creating it.

**The core of the memory system.** A live, permanent record of every NIFTY500
material announcement + its AI summary + its **market-relative outcome**. Fed
live by the §3.7 sync job; outcomes filled by the §6 Phase 4b backfill job.

```sql
CREATE TABLE IF NOT EXISTS filing_memory (
    id BIGSERIAL PRIMARY KEY,
    -- Identity & dedup — exactly one row per filing
    url_hash TEXT UNIQUE NOT NULL,
    symbol_base TEXT NOT NULL,
    company_name TEXT,
    sector TEXT,
    event_type TEXT NOT NULL,
    material_score INTEGER,

    -- Filing content
    filing_date DATE NOT NULL,
    filing_timestamp TIMESTAMP,
    raw_title TEXT,
    ai_summary TEXT,
    pdf_extract JSONB,

    -- Outcome measurement — base = next-day OPEN (adjusted), market-relative
    base_price NUMERIC,
    nifty_base NUMERIC,
    price_5d NUMERIC, price_10d NUMERIC, price_30d NUMERIC,    -- adjusted close
    nifty_5d NUMERIC, nifty_10d NUMERIC, nifty_30d NUMERIC,
    raw_move_5d NUMERIC, raw_move_10d NUMERIC, raw_move_30d NUMERIC,
    alpha_5d NUMERIC, alpha_10d NUMERIC, alpha_30d NUMERIC,    -- stock_move − nifty_move

    -- Maturity tracking — each window fills on its own day
    outcome_5d_status TEXT DEFAULT 'PENDING',    -- PENDING / FILLED / FAILED
    outcome_10d_status TEXT DEFAULT 'PENDING',
    outcome_30d_status TEXT DEFAULT 'PENDING',

    -- Derived verdict — computed by rule, not AI guess
    swing_verdict TEXT,                          -- POSITIVE / NEGATIVE / NEUTRAL

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_fm_symbol_event ON filing_memory (symbol_base, event_type);
CREATE INDEX idx_fm_maturity
ON filing_memory (outcome_5d_status, outcome_10d_status, outcome_30d_status);
```

**swing_verdict rule (computed, reproducible — not AI):**

```
alpha_10d > +3%   → POSITIVE   (filing pushed stock 3%+ ahead of market)
alpha_10d < -3%   → NEGATIVE
otherwise         → NEUTRAL
```

**Design decisions baked in (the 6 things that make it 10/10):**

1. **Outcome is market-relative** — `alpha = stock_move − nifty_move`. A +6% stock move in a +5% market is only +1% real filing impact. Storing raw move would teach memory false patterns.
2. **Idempotency** — `url_hash UNIQUE` means a re-posted/duplicate filing can never create two rows.
3. **Maturity tracking** — 5d/10d/30d outcomes mature on different days; each `*_status` column fills independently when its window completes.
4. **Trading-day accurate** — outcome windows use the NSE trading calendar, not calendar days.
5. **Split/bonus safe** — outcomes use yFinance **adjusted close**, so a 5:1 split is not misread as an 80% crash.
6. **Material-only** — only `material_score >= 6` filings are stored. ~25/day, ~6,000/year, ~50 MB — Neon free tier safe. Raw `pdf_extract` JSONB retained 90 days, then dropped (summary + outcomes are the lasting value).

### 4.5 Gap 5 fix — Tier-3 duplicate-position rule

**Problem:** Tier-3 blocks any ticker with an existing OPEN trade. With two engines + no daily cap, RELIANCE could get both a TIER2F and an AFTER_HOURS signal — the second silently dies.

**Decision:** Allow one OPEN per `(ticker, source)`. The new composite UNIQUE index already enforces one-per-source-per-day at the DB level. Tier-3's in-code duplicate check must change from "any OPEN for this ticker" to "an OPEN for this ticker *with the same source*". This is a small, documented Tier-3 modification — Phase 5 handles it.

### 4.6 Phase 1 Verification Gates

All Phase 1 gates are **Layer 1 (temp / structural)** — they can be verified the
moment Phase 1's migrations run, no live market data needed.

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V1.0 | pre-flight | no duplicate (ticker, signal_date); old uniqueness object identified | Temp |
| V1.1 | paper_trades columns | source, quantity, position_size_rs, pnl_rs exist | Temp |
| V1.2 | composite unique index | uniq_paper_trades_ticker_date_source exists | Temp |
| V1.3 | portfolio, capital_ledger | tables exist | Temp |
| V1.4 | paper_trades_queue | exists, 20+ columns | Temp |
| V1.5 | trade_memory_v2, pattern_insights, agent_disagreements | all exist | Temp |
| V1.5b | filing_memory | exists, url_hash UNIQUE constraint present | Temp |
| V1.6 | existing Tier-2 insert | still succeeds (source defaults to TIER2) | Temp |

---

## §5 Phase 2 — Virtual Capital Ledger

**Goal:** Give the system real rupee-denominated capital tracking. **Duration:** ~2-3 hours.

### 5.1 Capital model

```
Starting capital:        ₹10,00,000
Max per trade:           12% of total equity  (≈ ₹1,20,000)
Max total deployed:      80%  (always keep ≥20% cash buffer)
Position sizing method:  risk-based
```

### 5.2 Position sizing formula

```python
def calculate_position_size(total_equity, cash_available, entry_price, stop_loss_price):
    """Risk-based sizing. Returns (quantity, position_size_rs) or (0, 0) if can't size."""

    RISK_PCT = 0.02          # risk 2% of equity per trade
    MAX_TRADE_PCT = 0.12     # never exceed 12% of equity in one trade
    MIN_CASH_BUFFER = 0.20   # keep 20% cash

    risk_amount = total_equity * RISK_PCT
    risk_per_share = abs(entry_price - stop_loss_price)
    if risk_per_share <= 0:
        return (0, 0)

    # Quantity from risk
    qty_by_risk = int(risk_amount / risk_per_share)

    # Cap by max trade size
    max_position = total_equity * MAX_TRADE_PCT
    qty_by_cap = int(max_position / entry_price)

    qty = min(qty_by_risk, qty_by_cap)
    position_size = qty * entry_price

    # Respect cash buffer
    deployable = cash_available - (total_equity * MIN_CASH_BUFFER)
    if position_size > deployable:
        qty = int(deployable / entry_price)
        position_size = qty * entry_price

    if qty <= 0:
        return (0, 0)
    return (qty, round(position_size, 2))
```

### 5.3 Ledger operations — `utils/capital_ledger.py`

```python
def get_current_portfolio():
    """Return the latest portfolio state."""
    rows = sb.table("portfolio").select("*").order("id", desc=True).limit(1).execute().data
    if not rows:
        # Initialize on first run
        return _initialize_portfolio()
    return rows[0]

def _initialize_portfolio():
    initial = {
        "starting_capital": 1000000,
        "cash_available": 1000000,
        "capital_deployed": 0,
        "total_equity": 1000000,
        "open_positions": 0,
    }
    sb.table("portfolio").insert(initial).execute()
    return initial

def deploy_capital(paper_trade_id, amount_rs):
    """Called when a trade opens. Deducts cash, logs ledger entry."""
    pf = get_current_portfolio()
    if amount_rs > pf["cash_available"]:
        raise ValueError(f"Insufficient cash: need {amount_rs}, have {pf['cash_available']}")
    new_cash = pf["cash_available"] - amount_rs
    sb.table("capital_ledger").insert({
        "paper_trade_id": paper_trade_id,
        "txn_type": "DEPLOY",
        "amount_rs": -amount_rs,
        "cash_after": new_cash,
        "note": f"Opened trade {paper_trade_id}"
    }).execute()
    _update_portfolio(cash=new_cash,
                      deployed=pf["capital_deployed"] + amount_rs,
                      open_count=pf["open_positions"] + 1)

def release_capital(paper_trade_id, position_size_rs, pnl_rs):
    """Called when a trade closes. Returns capital + P&L to cash."""
    pf = get_current_portfolio()
    returned = position_size_rs + pnl_rs
    new_cash = pf["cash_available"] + returned
    sb.table("capital_ledger").insert({
        "paper_trade_id": paper_trade_id,
        "txn_type": "PNL_REALIZED",
        "amount_rs": returned,
        "cash_after": new_cash,
        "note": f"Closed trade {paper_trade_id}, P&L ₹{pnl_rs}"
    }).execute()
    _update_portfolio(cash=new_cash,
                      deployed=pf["capital_deployed"] - position_size_rs,
                      open_count=pf["open_positions"] - 1,
                      realized_add=pnl_rs)
```

### 5.4 Integration points

- **On signal creation** (Tier-2F, after-hours executor): call `calculate_position_size()`, then `deploy_capital()`. Store `quantity` + `position_size_rs` on the paper_trades row. If sizing returns 0 (no cash / risk too wide), skip the trade and log why.
- **On trade close** (`update_paper_trades.py`): compute `pnl_rs = (exit_price - entry_price) * quantity` (sign-adjusted for SELL), call `release_capital()`, store `pnl_rs`.
- **Daily snapshot:** a small cron writes a `portfolio` row each evening for an equity curve.

### 5.5 Phase 2 Verification Gates

All Phase 2 gates are **Layer 1 (temp / structural)** — verifiable with test
inputs, no live market data needed.

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V2.1 | portfolio initialized | one row, cash = ₹10,00,000 | Temp |
| V2.2 | deploy_capital test | cash decreases, ledger entry created | Temp |
| V2.3 | release_capital test | cash returns + P&L applied | Temp |
| V2.4 | position sizing | respects 12% cap + 20% buffer | Temp |
| V2.5 | insufficient cash | trade skipped gracefully, logged | Temp |

---

## §6 Phase 3 — Shared Utilities + Phase 4 — Memory Foundation

### Phase 3 — Shared Utilities (~2 hours)

Build once, reused by both engines:

| Utility | Purpose |
|---|---|
| `utils/yfinance_chart.py` | 2-year daily chart → RSI, MACD, support/resistance, trend, last_close |
| `utils/neon_fundamentals.py` | company_profiles lookup (sector, mcap, business_summary) |
| `utils/filing_history.py` | Per-company filing history from research_cache (aggregate the scattered summaries) |
| `utils/fno_ban_list.py` | NSE F&O ban check, fail-open, 2h cache |
| `utils/trading_calendar.py` | NSE trading-day calendar — `add_trading_days()`, holiday-aware (needed for filing_memory outcome windows) |
| `utils/tiered_target_generator.py` | T1/T2/T3/T4 target levels from consensus |
| `utils/ai_consensus.py` | Haiku analyst + DeepSeek verifier + consensus logic + solo fallbacks |

`filing_history.py` is the honest answer to Gap 1: research_cache has scattered per-filing summaries — this utility aggregates them per company so an agent can see "RELIANCE's filing history over the last 2 years" even though no formal "research" exists.

### Phase 4 — Memory Foundation + Seeding (~3 hours)

**Seed from event_outcomes (the Gap 3 solution):**

```python
def seed_memory_from_event_outcomes():
    """One-time: import 1,430 historical outcomes into trade_memory_v2."""
    rows = neon_query("SELECT * FROM event_outcomes")
    for r in rows:
        # Map symbol → sector via company_profiles
        sector = lookup_sector(r["symbol"])
        outcome = map_trade_result(r["trade_result"])  # WIN→TARGET_HIT, etc.
        tags = [
            f"event_{r['event_type'].lower()}",
            f"sector_{(sector or 'unknown').lower().replace(' ','_')}",
            "source_seed",
        ]
        sb.table("trade_memory_v2").insert({
            "source_type": "SEED_EVENT_OUTCOME",
            "symbol_base": r["symbol"],
            "event_type": r["event_type"],
            "sector": sector,
            "outcome": outcome,
            "pattern_tags": tags,
            "full_context": {"outcome_score": r["outcome_score"],
                             "event_date": str(r["event_date"]),
                             "signal_generated": r["signal_generated"]},
        }).execute()
```

**Then extract initial patterns** — group seeded memory by `sector × event_type`, compute aggregate win rate and avg outcome_score, write to `pattern_insights`.

> **v3.1 NOTE 1 (folded from §3.10).** Phase 4 must ALSO do a **one-time backfill
> of existing material `filings_log` rows into `filing_memory`** — not just the
> `event_outcomes` seed above. These backfilled rows' 5d/10d/30d windows are
> already in the past, so Phase 4b's outcome job will mature them on its first
> run. Group all memory seeding here in Phase 4.

**Honest caveat:** 1,430 rows across 913 symbols is sparse. Per-symbol learning is impossible. Per-event-type aggregates ("dividend events average X") are meaningful. v3 uses memory for **aggregate context**, not per-symbol prediction. As live trades accumulate, `trade_memory_v2` grows and patterns sharpen.

**Pattern retrieval for prompts:**

```python
def get_relevant_patterns(event_type, sector, limit=3):
    return sb.table("pattern_insights").select("*") \
        .eq("active", True) \
        .or_(f"event_type.eq.{event_type},sector.eq.{sector}") \
        .order("confidence", desc=True).order("sample_size", desc=True) \
        .limit(limit).execute().data
```

### Phase 4b — filing_memory outcome backfill (the 10/10 piece)

**File:** `agents/filing_memory_backfill.py` — cron `0 19 * * 1-5` (after market close, daily).

The `filing_memory` table is fed live by the §3.7 sync job, but its outcome columns
(`alpha_5d`, `alpha_10d`, `alpha_30d`) start as PENDING. This job fills them — but
only when each window has actually matured.

```python
def backfill_filing_outcomes():
    """Daily. Fills only matured outcome windows.
    Trading-day aware. Market-relative. Split/bonus safe."""
    today = trading_calendar.today()

    # First-time rows: set the base price (next-day open after filing)
    new_rows = sb.table("filing_memory").select("*") \
        .is_("base_price", "null").execute().data
    for r in new_rows:
        filing_date = parse(r["filing_date"])
        base_date = trading_calendar.next_trading_day(filing_date)
        if base_date > today:
            continue  # next session hasn't happened yet
        try:
            r_base = yf_adjusted_open(r["symbol_base"], base_date)
            n_base = yf_adjusted_open("^NSEI", base_date)
            sb.table("filing_memory").update({
                "base_price": r_base, "nifty_base": n_base
            }).eq("id", r["id"]).execute()
        except Exception as e:
            print(f"  ⚠️ base price failed {r['symbol_base']}: {e}")

    # Outcome windows: fill each independently as it matures
    rows = sb.table("filing_memory").select("*") \
        .not_.is_("base_price", "null") \
        .or_("outcome_5d_status.eq.PENDING,"
             "outcome_10d_status.eq.PENDING,"
             "outcome_30d_status.eq.PENDING").execute().data

    for r in rows:
        filing_date = parse(r["filing_date"])
        updates = {}
        for window, col in [(5, "5d"), (10, "10d"), (30, "30d")]:
            if r[f"outcome_{col}_status"] != "PENDING":
                continue
            target_date = trading_calendar.add_trading_days(filing_date, window)
            if target_date > today:
                continue  # window not matured — leave PENDING
            try:
                stock_px = yf_adjusted_close(r["symbol_base"], target_date)
                nifty_px = yf_adjusted_close("^NSEI", target_date)
                raw_move = (stock_px - r["base_price"]) / r["base_price"] * 100
                nifty_move = (nifty_px - r["nifty_base"]) / r["nifty_base"] * 100
                alpha = raw_move - nifty_move          # market-relative
                updates[f"price_{col}"] = stock_px
                updates[f"nifty_{col}"] = nifty_px
                updates[f"raw_move_{col}"] = round(raw_move, 2)
                updates[f"alpha_{col}"] = round(alpha, 2)
                updates[f"outcome_{col}_status"] = "FILLED"
            except Exception as e:
                updates[f"outcome_{col}_status"] = "FAILED"

        # Compute swing_verdict once 10d outcome is in
        if updates.get("outcome_10d_status") == "FILLED":
            a = updates["alpha_10d"]
            updates["swing_verdict"] = ("POSITIVE" if a > 3
                                        else "NEGATIVE" if a < -3 else "NEUTRAL")
        if updates:
            updates["updated_at"] = now_iso()
            sb.table("filing_memory").update(updates).eq("id", r["id"]).execute()
```

### Phase 4c — filing_memory retrieval brief (what the agent actually sees)

When Tier-2F / after-hours generates a signal, it does NOT get a raw dump of 100+
filings. It gets a **focused brief** — ~50 words, AI-ready.

```python
def get_filing_memory_brief(symbol_base, current_event_type):
    """Compact, AI-ready company filing memory brief — not a raw dump."""
    rows = sb.table("filing_memory").select("*") \
        .eq("symbol_base", symbol_base) \
        .gte("material_score", 6) \
        .eq("outcome_10d_status", "FILLED") \
        .order("filing_date", desc=True).limit(30).execute().data

    if not rows:
        return "No matured material filing history for this company."

    by_event = {}
    for r in rows:
        by_event.setdefault(r["event_type"], []).append(r["alpha_10d"])

    lines = [f"{symbol_base} — Filing Memory ({len(rows)} material filings, 2yr):"]
    for ev, alphas in by_event.items():
        avg = sum(alphas) / len(alphas)
        wins = sum(1 for a in alphas if a > 3)
        lines.append(f"  {ev}: {len(alphas)} events, avg {avg:+.1f}% alpha(10d), "
                     f"{wins}/{len(alphas)} positive")

    same = [r for r in rows if r["event_type"] == current_event_type]
    if same:
        b = same[0]
        lines.append(f"  Most recent {current_event_type}: {b['filing_date']} "
                     f"→ {b['alpha_10d']:+.1f}% alpha in 10d")
    return "\n".join(lines)
```

This brief is injected into both engines' Haiku + DeepSeek prompts alongside
`get_relevant_patterns()`. The Adani-merger example: when a merger filing arrives,
the agents see Adani's past ACQUISITION/CONTRACT_WIN/RESULTS outcomes — concrete,
market-relative, decision-grade context.

### Phase 3+4 Verification Gates

Layer noted per gate — most are structural (temp), the last two need data flow.

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V3.1 | yfinance_chart on RELIANCE.NS | returns RSI/MACD/support/2-year data | Temp |
| V3.2 | filing_history on RELIANCE | returns aggregated past filings | Temp |
| V3.3 | fno_ban_list | returns list, fail-open on error | Temp |
| V3.4 | trading_calendar.add_trading_days | skips weekends + NSE holidays correctly | Temp |
| V4.1 | seed job | trade_memory_v2 has ~1,430 SEED rows | Temp |
| V4.1b | filings_log backfill | existing material filings appear in filing_memory | Temp |
| V4.2 | pattern extraction | pattern_insights populated | Temp |
| V4.3 | get_relevant_patterns | returns patterns for a test event | Temp |
| V4.4 | filing_memory sync | new material filings appear, no duplicates (url_hash) | Live (Mon) |
| V4.5 | outcome backfill | matured rows get alpha_5d/10d/30d; immature stay PENDING | Temp/Live |
| V4.6 | swing_verdict | computed correctly from alpha_10d rule | Temp |
| V4.7 | get_filing_memory_brief | returns ~50-word brief, not raw dump | Temp |

---

## §7 Phase 5 — Real-Time Engine (Tier-0F + Tier-2F)

**Goal:** Live filings → 2-AI consensus → sized paper trade. **Duration:** ~3-4 hours.

### 7.1 Tier-0F — event-driven poller

`agents/tier0f_poller.py` — polls Supabase `filings_log` every 5 min. **Never hits NSE** (Tier-0 owns NSE — the foundation/house principle). Picks up rows where `picked_by_tier0f = FALSE AND material_score >= 6 AND trade_confidence >= 60 AND event_type != 'OTHER'` and within last 30 min. Calls `tier2_fundamental.process_filing()` for each, then marks `picked_by_tier0f = TRUE`.

Cron: `*/5 3-9 * * 1-5`.

### 7.2 Tier-2F — the intelligent signal generator

`agents/tier2_fundamental.py`. Pipeline per filing:

1. F&O ban check (fail-open)
2. company_profiles lookup — skip if not in NIFTY500
3. yFinance 2-year chart snapshot
4. Market context — skip if NIFTY bearish (multiplier 0)
5. Pull relevant patterns from `pattern_insights`
6. **Haiku 4.5 analyst** — directional bias, expected move, horizon, confidence, reasoning
7. **DeepSeek V4 Flash verifier** — independent CONFIRM/CHALLENGE
8. Consensus logic — both agree → proceed; disagree → skip + log to `agent_disagreements`
9. `calculate_position_size()` + `deploy_capital()`
10. Insert into `paper_trades` with `source='TIER2F'`, `quantity`, `position_size_rs`

### 7.3 Consensus logic

```python
def determine_consensus(haiku, flash):
    if not haiku.get("tradeable"):
        return ("SKIP", "Analyst says not tradeable")
    if flash.get("verdict") == "CHALLENGE" and flash.get("agreement_score", 0) < 70:
        return ("SKIP", f"Verifier challenged ({flash['agreement_score']})")
    if haiku["directional_bias"] != flash["my_directional_bias"]:
        return ("SKIP", "Direction mismatch")
    avg_conf = (haiku["confidence"] + flash["my_confidence"]) / 2
    if avg_conf < 65:
        return ("SKIP", f"Avg confidence {avg_conf} < 65")
    return ("PROCEED", "Consensus reached")
```

### 7.4 Fallback modes

- Anthropic down → `SOLO_DEEPSEEK`: DeepSeek does both analyst + verifier roles, confidence haircut 10%
- DeepSeek down → `SOLO_HAIKU`: Haiku alone, confidence haircut 10%
- Both down → skip, log

### 7.5 Gap 5 fix applied here

Modify Tier-3's duplicate check: `paper_trades WHERE ticker=X AND status='OPEN' AND source=<same source>` instead of any-OPEN-for-ticker. A one-line filter addition. Document the change.

### 7.6 Phase 5 Verification Gates

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V5.1 | Tier-0F dry run | identifies candidates correctly | Temp |
| V5.2 | first Tier-2F call | Haiku + Flash both return valid JSON | Temp |
| V5.3 | paper_trades insert | row with source='TIER2F', quantity, position_size_rs | Temp |
| V5.4 | capital deployed | portfolio cash decreased | Temp |
| V5.5 | solo fallback | works with one API disabled | Temp |
| V5.6 | disagreement | logged to agent_disagreements, no trade | Temp |
| V5.7 | Tier-3 picks up TIER2F + lets a same-ticker AFTER_HOURS through | duplicate rule fixed | Temp |
| V5.8 | full live pipeline | real filing → Tier-0F → Tier-2F → sized trade within 10 min | Live (Mon) |

---

## §8 Phase 6 — After-Hours Engine

**Goal:** Post-close filings → next-day gap setups → pre-open execution. **Duration:** ~4 hours.

### 8.1 Redefined scope (Gap 7)

v2 framed after-hours as "deep fundamental analysis". That data doesn't exist. **v3 scope:** after-hours is a **post-close filing → next-day gap predictor**. It catches the 4-5 PM announcement window (when retail/algos can't react), analyzes overnight, and queues a sized trade for the next open. Honest, smaller, achievable.

### 8.2 Pipeline

`agents/after_hours_v2.py` — runs 4/5/6/8 PM IST:

1. Fetch filings posted after 3:30 PM today (NIFTY500 only)
2. Haiku 4.5 analyst (reuses `ai_consensus.py`)
3. PDF deep parse
4. company_profiles + filing_history context
5. Gap predictor (event type + pattern_library + recent momentum)
6. Tiered targets (T1 3% / T2 5% / T3 10% / T4 20%+ if conviction HIGH)
7. DeepSeek V4 Flash verifier → consensus
8. Write to `paper_trades_queue` + Telegram alert

> **v3.1 dependency note.** Step 1 ("filings posted after 3:30 PM") needs a real
> filing timestamp. If the §3.7 Monday check (V0.8) shows `filing_memory.
> filing_timestamp` is always NULL, this step must source its timestamp from
> `filings_log.classified_at` instead — fix that before building Phase 6's fetch.

### 8.3 Pre-open executor

`agents/after_hours_executor.py` — runs 8:30 AM IST:

1. Fetch today's QUEUED rows
2. Fresh yFinance price check
3. **Skip if overnight gap exceeded entry zone** (discipline — don't chase)
4. Skip if NIFTY bearish
5. `calculate_position_size()` + `deploy_capital()`
6. Insert into `paper_trades` with `source='AFTER_HOURS'`
7. Mark queue row EXECUTED / SKIPPED

### 8.4 Cron

```yaml
# after_hours_v2.yml
- cron: '30 10 * * 1-5'   # 4 PM IST
- cron: '30 11 * * 1-5'   # 5 PM IST
- cron: '30 12 * * 1-5'   # 6 PM IST
- cron: '30 14 * * 1-5'   # 8 PM IST
# after_hours_executor.yml
- cron: '0 3 * * 1-5'     # 8:30 AM IST
```

### 8.5 Phase 6 Verification Gates

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V6.1 | after-hours run | paper_trades_queue row + Telegram alert | Temp/Live |
| V6.2 | pre-open executor | queued → paper_trades with source='AFTER_HOURS' | Temp/Live |
| V6.3 | overnight gap skip | logged in skip_reason | Live (Mon) |
| V6.4 | capital sized | quantity + position_size_rs set | Temp |

---

## §9 Phase 7 — Tier-4F Memory Orchestrator

**Goal:** Nightly learning loop. **Duration:** ~3 hours.

### 9.1 Signal-time logging

Every Tier-2F / after-hours signal writes a `trade_memory_v2` row (`source_type='LIVE_TRADE'`, `outcome='OPEN'`) with both agents' reasoning, market context, and pattern tags.

### 9.2 Outcome backfill

When `update_paper_trades.py` closes a trade, it updates the matching `trade_memory_v2` row: `outcome`, `pnl_pct`, `holding_days`.

### 9.3 Nightly extraction — `agents/tier4f_nightly.py`

Runs 11:30 PM IST:

1. Aggregate closed `trade_memory_v2` rows by `sector × event_type`
2. Compute win rate, avg outcome, avg holding days (only combos with n≥5)
3. Generate insight text via **DeepSeek V4 Pro** (deep reasoning — Pro reserved for this nightly batch only, ~₹90/month)
4. Upsert `pattern_insights`
5. Backfill `agent_disagreements`: for disagreements 10+ days old, fetch actual price move, mark `backtest_outcome` — answers "when models disagree, who's right more often"

### 9.4 Pattern injection

`get_relevant_patterns()` feeds the top 3 patterns into Haiku + Flash prompts as a "HISTORICAL PATTERNS" block. The loop closes: trades → memory → patterns → smarter prompts → better trades.

### 9.5 Phase 7 Verification Gates

| Gate | Check | Pass | Layer |
|---|---|---|---|
| V7.1 | live signals | create trade_memory_v2 LIVE_TRADE rows | Temp |
| V7.2 | trade close | outcome propagates to memory | Temp |
| V7.3 | nightly job | pattern_insights refreshed | Temp |
| V7.4 | prompt injection | Tier-2F prompt includes patterns | Temp |
| V7.5 | disagreement backtest | backtest_outcome populated | Live |

---

## §10 Phase 8 — Integration + Monitoring

**Goal:** End-to-end verification + health alerts. **Duration:** ~2 hours.

The §10 end-to-end smoke tests are the core of the **Thursday 22-May deep
analysis pass** (§0.5 Layer 3). They are run once every component exists and has
seen real market data.

### 10.1 End-to-end smoke tests

| Test | Expected |
|---|---|
| E2E-1 | Live filing → Tier-0F → Tier-2F → sized paper_trade within 10 min |
| E2E-2 | After-hours filing → queue → pre-open → paper_trade traced |
| E2E-3 | Disagreement → logged, no trade |
| E2E-4 | API failure → solo mode trade still created |
| E2E-5 | Capital: portfolio cash + deployed reconciles after open/close cycle |
| E2E-6 | Memory: pattern_insights has rows, next signal's prompt includes them |

### 10.2 Health monitoring — `agents/health_monitor.py`

Daily 9 AM IST Telegram alert on: Tier-0 stalled, Tier-0F backlog >20, OTHER rate >20%, capital reconciliation mismatch, paper_trades insert failures, trades past max_holding_days not closed.

### 10.3 Daily summary

8 AM IST Telegram: yesterday's filings/signals/trades, today's queue, **portfolio equity in rupees** (cash + deployed + open MTM), realized P&L, win rate.

---

## §11 Cost Model

| Component | Daily | Monthly |
|---|---|---|
| Tier-0 DeepSeek classify (150 filings) | ₹2 | ₹60 |
| Tier-2F Haiku analyst (20 signals) | ₹8 | ₹240 |
| Tier-2F DeepSeek verifier | ₹0.50 | ₹15 |
| After-hours Haiku (10) | ₹4 | ₹120 |
| After-hours DeepSeek verifier | ₹0.25 | ₹8 |
| Tier-4F nightly DeepSeek V4 Pro | ₹3 | ₹90 |
| **Total** | **~₹18** | **~₹530** |

With 50% buffer: **~₹800/month**. Controls: material_score ≥6 gate, trade_confidence ≥60 gate, disagreement-skip, V4 Pro nightly-only.

---

## §12 Risk & Rollback

| Failure | Mitigation |
|---|---|
| Anthropic down | SOLO_DEEPSEEK fallback |
| DeepSeek down | SOLO_HAIKU fallback; Tier-0 retries |
| Neon down | fail-CLOSED (skip trades needing fundamentals) |
| Supabase down | writes blocked; cron logs accumulate, manual recovery |
| Bad classification regression | trade_confidence gate + 2-model consensus |
| Capital reconciliation drift | daily snapshot + health monitor alert |
| V0.1 fails Monday after weekend build | Phase 1-4 code (schema/utils/ledger/memory) survives; only engines fed bad data — fix Phase 0, re-verify (see §0.5) |

Each phase reverts via `git revert` of its commits; schema phases via `DROP` of added objects.

---

## §13 First Action

> **v3.1 update.** v3's §13 first action (Phase 0.1 max_tokens fix) is **done**.
> The first action under v3.1 is **Phase 1**.

The next step is **Phase 1 — Schema Migrations (§4)**, executed in Antigravity:

1. Run the §4 **pre-flight checks** first (duplicate rows; CONSTRAINT-vs-INDEX).
2. Run the §4.1–4.5 migrations via the Supabase SQL Editor (DDL).
3. Verify Layer-1 gates V1.0–V1.6.
4. Only then proceed to Phase 2.

Phase 0's live gates (V0.1–V0.8) are verified separately on **Monday 18-May** per
§0.5 — they do not block the weekend build, but a V0.1 failure triggers the §12
rollback row.

---

## §14 What Changed From v2 → v3

| Area | v2 (wrong) | v3 (verified) |
|---|---|---|
| Neon "2-year data" | Assumed deep research existed | Confirmed: only filing summaries + 1,430 outcomes |
| Capital | Assumed ₹10L tracked | Confirmed zero tracking → builds virtual ledger |
| Memory | "feed it Neon data" | Seeds from event_outcomes (1,430 rows), honest sparse caveat |
| Memory storage | "update research_cache" (frozen cache, wrong tool) | dedicated live `filing_memory` table — market-relative outcomes, dedup, maturity tracking, trading-day accurate, split-safe |
| Accuracy | implied 90-95% possible | Realistic 50-85% confidence, no false promise |
| gap_calculator | fixed 1 of 3 bugs | fixes all 3 |
| Tier-3 conflict | not addressed | duplicate-rule fix designed |
| P&L sign | not noticed | flagged + Phase 0 fix |
| Build order | broken dependency (Phase 2 used Phase 3 code) | dependency-driven, shared utils as own phase |
| Position sizing | absent | risk-based formula, 12% cap, 20% buffer |

---

## §14.5 What Changed From v3 → v3.1 — NEW

| Area | v3 | v3.1 |
|---|---|---|
| §3.4 gap_calculator | printed *rejected* pure-Option-A code (`if not symbol: return None`) | corrected to as-built HYBRID design (exact + LIKE fallback), with live test results and the `{{}}` pitfall noted |
| §3.7 cron | "change `tier0-agent.yml` to `*/5`" | corrected: cron-job.org is the PRIMARY trigger (set to 5 min); `tier0-agent.yml` left as 30-min GitHub fallback |
| §3 headers | two `### 3.9` headers (numbering bug) | de-duplicated; single Phase 0 gates section |
| §3 status | written as a future plan | rewritten as **as-built** with all 7 commit hashes; marked reference-only |
| Phase 4 backfill | only `event_outcomes` seed | NOTE 1 folded in — Phase 4 also backfills existing material `filings_log` into `filing_memory` (gates V4.1b added) |
| pattern_library rebuild | not mentioned | NOTE 2 folded in — future phase rebuilds `pattern_library` from `filing_memory` after ~3 months matured data (§15) |
| filing_timestamp risk | not flagged | §3.7 watch item + V0.8 gate + §8.2 dependency note — `published_at` is always NULL; verify Monday |
| Phase 1 migration risk | not flagged | §4 pre-flight checks added (duplicate `(ticker, signal_date)` rows; CONSTRAINT-vs-INDEX) |
| Execution model | implicit per-phase gates | explicit §0.5 — weekend build of Phases 1-8, two-layer verification (temp now / live Monday), Thursday deep analysis |
| First action (§13) | Phase 0.1 max_tokens fix | Phase 1 schema migrations (Phase 0 done) |
| Verification gates | single Pass column | added a **Layer** column (Temp / Live) to every gate table |

---

## §15 Deferred Work (post Phase 8)

Not part of Phases 0-8. Tracked here so it is not lost.

- **pattern_library rebuild from filing_memory** (v3.1 NOTE 2). Once `filing_memory`
  has ~3 months of matured market-relative outcomes, rebuild `pattern_library`
  (currently 17 thin rows) so gap_calculator gets real coverage for RESULTS,
  M&A, CONTRACT_WIN, etc., instead of falling back to `DEFAULT_GAPS`.
- **Upstox live-trading phase.** yFinance is the data source for all of v3.1.
  Upstox is deferred to a future live-trading phase (sandbox has no market data;
  `UPSTOX_ACCESS_TOKEN` also expires daily and would need an auto-refresh job first).
- **pdf_extract retention.** `filing_memory.pdf_extract` JSONB is kept 90 days
  then dropped — a small retention/cleanup job is needed once data ages past 90 days.

---

*Plan v3.1 locked: 2026-05-16. Built on 3 recon rounds + the verified Phase 0
as-built record. Zero unverified assumptions. v3.1 is the single source of truth —
supersedes v1, v2, and v3. Ready for Antigravity execution.*
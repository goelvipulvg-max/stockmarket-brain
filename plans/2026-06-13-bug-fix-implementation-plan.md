# Stockmarket-Brain — Bug-Fix Implementation Plan (PLAN ONLY)

## Context
An external deep audit (Fable 5, 2026-06-12) flagged 2 P0, 8 P1, 14 P2, 11 P3 findings plus a
"survivorship/B1" status and a suspected leaky pause. This session re-verified every P0/P1/P2
finding against the **real repo + both live DBs (read-only) + GitHub Actions state**, then built an
execution-ready fix plan. **No code, config, flag, migration, DB-write, or git action was taken.**

Implementation happens later, in a separate session, with per-edit approval. DDL/data fixes are run by
the owner in the Supabase/Neon SQL editor; code edits use explicit `git add <file>` + `.commit_msg.tmp`,
no push without approval.

> Naming note: Batch 0-B containment items are prefixed **HOTFIX-n** to avoid clashing with the
> backbone feature codenames **B1/B2/B6/B7** (which keep their original meaning).

---

## STEP 1 — Audit re-verification (verdicts)
Method: opened every cited `file:line`; ran read-only Supabase + Neon queries; inspected `gh` workflow
state and run history. Verdicts: ✅ VERIFIED · ⚠️ CHANGED · ❌ NOT REPRODUCED.

### P0
| ID | Verdict | Notes (current location) |
|----|---------|--------------------------|
| P0-1 Capital ledger race | ✅ VERIFIED | `utils/capital_ledger.py` `_update_portfolio` (32-60), `deploy_capital` (63-86), `release_capital` (89-108): read-modify-write on the single latest `portfolio` row, no lock/txn. `tier2f.yml` has **no `concurrency:` block** (confirmed). Poller dispatches one filing_id per `workflow_dispatch`, so a burst of ≥2 material filings in a cycle → parallel Tier-2F runs racing the same cash. |
| P0-2 Same-day look-ahead | ⚠️ CHANGED | Bug is **real**: `update_paper_trades.py:83` fetches `interval=1m&range=1d` (full day); hit detection (201-232) compares against `day_high/day_low` with **no entry-time knowledge**. **But the audit's premise is wrong**: it claims "no creation timestamp exists, cannot be corrected." `paper_trades` **has `signal_generated_at`**, populated intraday (id160=`09:24Z`, id161=`08:08Z`, id162=`04:24Z`). So **no `opened_at` DDL is needed** — the fix can gate on `signal_generated_at`. This materially de-risks/cheapens the fix. |

### P1
| ID | Verdict | Notes |
|----|---------|-------|
| P1-1 pattern_insights text sort | ✅ VERIFIED + LIVE | `pattern_insights_retriever.py:36` `.order("confidence", desc=True)`. Live: 11 HIGH + 4 LOW, all active, **no MEDIUM** → `'LOW' > 'HIGH'` alphabetically → `limit=3` returns 3 LOW, **excludes all HIGH**. |
| P1-2 `continue` starves time-stop | ✅ VERIFIED + LIVE | continues at `:154` (fetch fail), `:217` (BUY gap-WAIT), `:230` (SELL gap-WAIT) all precede the expiry check at `:235`. Live casualty: **GILLETTE id-161 OPEN at day 17** (signal 05-27, BUY, horizon SHORT=3, ₹24,855). LUPIN id-162 closed 06-08 15:31 IST same run. (Note: id-161 is a **BUY/long** with a *SHORT horizon* — the audit's "SHORT" meant horizon, not a short position.) |
| P1-3 Optimistic intrabar (target before SL) | ✅ VERIFIED | `:201-204` target checked first; SL only `if not new_status` (`:207-232`); `range=1d` only → across a gap, first run sees only today's range. |
| P1-4 Liquidity/gates protect alert not trade | ✅ VERIFIED | Tier-2F gates = F&O-ban / Nifty500 / chart / NIFTY-mood (`tier2_fundamental.py:186-227`); **no liquidity call**. `utils/liquidity_check.py:check_liquidity(symbol)` exists and is used by Tier-0 only. |
| P1-5 Solo fallback verifies null | ✅ VERIFIED | `run_verifier(context, None, …)` then `flash_output["my_confidence"]-10` and `["my_directional_bias"]` (KeyError risk). `ai_consensus.get_consensus()` (proper solo via `_run_deepseek_as_analyst`, ×0.9 haircut) exists and is **never called**. |
| P1-6 RR floor doesn't bind the ladder | ✅ VERIFIED | Ladder T1=3%/SL=5% ⇒ **RR 0.6** (`tiered_target_generator.py:25-29`). AI-SL rejection (incl. `rr_below_floor`) still trades the ladder. `reward_risk.passes_rr_floor()` exists but only gates AI-SL acceptance. |
| P1-7 No code clamp on confidence | ✅ VERIFIED | `CONFIDENCE_FLOOR/CEILING` (50/85) defined (`:59-60`), unused; no clamp before `_confidence_to_conviction` (`:366-374`). |
| P1-8 Mixed confidence scales | ✅ VERIFIED | `tier2_signals.py` writes 1-10; `tier3_position_manager.py:30` rejects `<50`. `tier2_signals.py` is **orphan (no workflow)** → dormant landmine, not live. |

### P2
| ID | Verdict | Notes |
|----|---------|-------|
| P2-1 No UNIQUE on filings_log.url_hash | ⚠️ CHANGED | Code dedup is SELECT-then-INSERT, no DB unique (VERIFIED). **Live magnitude differs**: 5,692 rows, **7 dup groups / 7 extra rows (all size 2)** + **46 NULL `url_hash` rows** — not "52 extra / 8 groups" (likely cleaned since the audit). Overlapping GH schedules confirmed (Step 2). |
| P2-2 FAILED windows permanent | ✅ VERIFIED | PENDING-only requery. Live: **11×5d + 11×10d FAILED** (22 windows). |
| P2-3 Late filings drop / 30-min lookback | ✅ VERIFIED | sync 20-min lookback, cron `*/10 3-9 UTC`; `filings_log_backfill.py` has no workflow; poller 30-min lookback; **158 unpicked material rows** live. |
| P2-4 Tier-3 re-alerts everything | ✅ VERIFIED | `workflow_run` + per-signal loop re-runs Claude + re-Telegrams earlier approved signals; only DB insert deduped. |
| P2-5 trading_calendar pre-Jan-1 wrong | ✅ VERIFIED | Built from current year only; pre-2026 dates silently mis-resolved. |
| P2-6 Blanket brace replacement | ✅ VERIFIED | `ai_consensus.py:51` + `tier0_filings.py:126` `{{→{ }}→}`; latent (flat responses today). |
| P2-7 Close-then-release window | ✅ VERIFIED | status set closed + DB update, **then** `release_capital`, no txn (3 close paths). |
| P2-8 Health Check-1 dead at its time | ✅ VERIFIED | cron 9:00 IST; stall check gated to 9:15-15:30 → always False. |
| P2-9 No daily portfolio snapshot | ✅ VERIFIED | `portfolio` = **1 row** (id1, snapshot_date 2026-05-18, updated in place); `portfolio_snapshot.py` unscheduled. Zero equity history. |
| P2-10 nifty500_loader still quarterly | ✅ VERIFIED | cron `0 2 1 1,4,7,10 *`; runs AVOID-listed loader; next fire Jul 1. |
| P2-11 Guardian blind/wrong (a-d) | ✅ VERIFIED | (a) queries `company_profiles` w/o `.NS` while table stores `.NS` (493/505) → context None; (b) 10-symbol name map; (c) `sources_list` always appends NSE_FILING; (d) EXIT advisory only. `company_profiles` is **Neon**. |
| P2-12 Calendar-day holding | ✅ VERIFIED | `:148` `(date-date).days`; docstring `:66` "Calendar-day based." |
| P2-13 Double-JSON raw_signal | ✅ VERIFIED + LIVE | `json.dumps` into JSONB at `:486` + `:603`; live `raw_signal` python type = `str` (`'{"haiku":…'`). |
| P2-14 Poller dispatch-then-mark race | ✅ VERIFIED | dispatch before `_mark_picked`; mark failure → re-dispatch; bounded by trade-level unique index. |

### P3 (touched in the plan, spot-verified)
P3-1 ✅ (only `tier2_fundamental.py:33` lacks `override=True`) · P3-2 ✅ (dead code: `get_consensus`, `CONFIDENCE_*`, gap_calculator symbol arm, `pdf_data`) · P3-3 ✅ (stale docstrings/prints + cron comments) · P3-4 ✅ (taxonomy drift) · P3-5 ✅ (preopen zombie; `after_hours_queue` 0 PENDING / 8 ALERTED, Neon) · P3-6 ✅ (Tier-4 per-updater cadence) · P3-7 ✅ (Tier-4 win-rate excludes EXPIRED) · P3-8 ✅ (OTHER gate prompt-only) · P3-9 ✅ (`pdf_extract` never written) · P3-10 ✅ (untracked clutter per git status) · P3-11 ✅ (live `capital_deployed = 24855.000000000015` float drift; `day_open` prev-close fallback).

### NEW findings the audit missed / corrected
- **NEW-A (corrects P0-2):** `signal_generated_at` is a usable intraday entry timestamp → P0-2 is fixable **today without DDL**.
- **NEW-B:** **46 filings_log rows have NULL `url_hash`** — they bypass dedup entirely (md5 of a string is never NULL → legacy/alternate insert path). Must be handled before a UNIQUE index. Recommend a **partial unique index `WHERE url_hash IS NOT NULL`**.
- **NEW-C (critical, see Step 2):** **All 17 GH workflows are "active"**; the **Tier-0F Poller (trading switch) fired via GitHub `schedule` on 06-11 and 06-12** → the trading path is **NOT paused**.
- **NEW-D:** GILLETTE id-161 is a **BUY/long**; force-expire P&L = `(exit − 8285)/8285 × position` (sign matters).
- **NEW-E (positive):** Capital identity holds to the rupee — `capital_ledger` latest `cash_after`=968,932.63 == `portfolio.cash_available`; `968,932.63 + 24,855 = 993,787.63 = total_equity`.

---

## STEP 2 — Pause state (CRITICAL — gates a safe resume)
**cron-job.org is disabled, but GitHub Actions schedule crons are NOT — they are live and firing.**

`gh run list` evidence (most recent weekday, today is Sat 06-13 so no runs expected):
- **Tier-0F Poller — `schedule` — 2026-06-12 11:10Z and 07:18Z, 2026-06-11** → *the trading dispatcher is live.*
- Tier-0 Filing Agent, Filing Memory Sync, Filing Memory Backfill, Health Monitor, Daily Summary, Pre-Open Alert, Tier-1 Guardian/News — all ran via `schedule` on 06-11/06-12.
- **Tier-2F / Tier-3 / Update Paper Trades** last ran **06-10** via `workflow_dispatch`/`workflow_run` (the cron-job.org → API chain) and **stopped after cron-job.org was disabled (~06-10)**. `update_paper_trades.yml` has **no schedule** (so the 06-08 LUPIN close + 06-10 runs were cron-job.org/manual).

**Interpretation (answers Q4):** Disabling cron-job.org stopped the 2-min poller webhook, the 5-min Tier-0, and the updater. But the **GitHub-native fallback schedules were never paused** — poller (every 10 min) + Tier-0 + sync etc. keep firing. **The only reason no trade has fired since 06-10 is luck** (no material filing landed inside the poller's 30-min lookback during a scheduled run), not a real pause. **The trading switch is ON.**

**Action required before any "resume":** disable the GitHub schedules (see HOTFIX-0). Minimum to stop trading = disable **Tier-0F Poller**.

---

## STEP 3 — The plan

### BATCH 0-A — Ship-now, zero-decision, low-risk hotfixes (no strategy/behaviour change)

**A1 — P0-1 concurrency group** (✅ VERIFIED)
- Touch: `.github/workflows/tier2f.yml` (top level, after `name:`).
- Change (code/YAML):
  ```yaml
  concurrency:
    group: tier2f-capital
    cancel-in-progress: false
  ```
- Effort 5 min · Fix-risk minimal (serializes bursts; slightly slower).
- Verify: dispatch two filing_ids; confirm queued (not parallel) in Actions.
- Rollback: revert YAML.
- Note: necessary but not sufficient — the `capital_ledger` RMW stays unguarded; the group closes the realistic exposure (poller-burst). A DB-side atomic decrement is the fuller fix → Batch C (C2).

**A2 — P1-1 pattern ordering** (✅ VERIFIED + live)
- Touch: `utils/pattern_insights_retriever.py:33-39`.
- Change (code): drop server `.order("confidence")` + `.limit`, rank client-side then slice:
  ```python
  RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
  rows = sb.table("pattern_insights").select("*").eq("active", True).or_(f"event_type.eq.{ev},sector.eq.{sec}").execute().data or []
  rows.sort(key=lambda r: (RANK.get((r.get("confidence") or "").upper(), 0), r.get("sample_size") or 0), reverse=True)
  return rows[:limit]
  ```
- Effort 30 min · Fix-risk minimal (fail-open preserved).
- Verify: REPL with live data → top-3 are HIGH, not LOW.
- Rollback: git revert.

**A3 — P2-1 UNIQUE index + 23505 tolerance** (⚠️ CHANGED: 7 dups/7 extra + 46 NULL)
- Part (i) **Supabase Dashboard SQL** (owner runs):
  ```sql
  -- preview
  SELECT url_hash, COUNT(*) FROM filings_log WHERE url_hash IS NOT NULL GROUP BY url_hash HAVING COUNT(*)>1;
  -- delete extras, keep earliest id
  DELETE FROM filings_log a USING filings_log b
   WHERE a.url_hash = b.url_hash AND a.url_hash IS NOT NULL AND a.id > b.id;
  -- enforce uniqueness on real hashes (NULL legacy rows allowed)
  CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uniq_filings_log_url_hash
    ON filings_log (url_hash) WHERE url_hash IS NOT NULL;
  ```
- Part (ii) **Code edit**: `agents/tier0_filings.py` save path — tolerate Postgres `23505` (unique_violation) as a benign duplicate-skip.
- Effort 1-2 h · Fix-risk low (DDL additive; delete removes only later-id dups; NULLs untouched).
- Verify: run Tier-0 twice → 0 new dups, no crash on conflict.
- Rollback: `DROP INDEX uniq_filings_log_url_hash;` + revert code.
- Blocks on **Q10** (NULL-hash handling — recommended: partial index, leave NULLs).

### BATCH 0-B — Decision-gated money-logic / behavioural hotfixes

**HOTFIX-0 — GitHub Actions pause** (NEW — the real containment) — **blocks on Q4 (answered) + your go**
- Touch: `gh workflow disable <name>` OR comment out `schedule:` in the YAMLs.
- Minimum (stop trading): disable **Tier-0F Poller**. Full stop: also Tier-0 Filing Agent, Filing Memory Sync, Filing Memory Backfill, Health Monitor, Daily Summary, Pre-Open Alert, Tier-1 Guardian, Tier-1 News.
- Effort 10 min · Fix-risk none. Verify: `gh run list` shows no new `schedule` runs next weekday. Rollback: `gh workflow enable` / restore YAML.
- **Decision:** trading-only vs everything.

**HOTFIX-1 — P1-2 expiry-before-skips** (✅ VERIFIED + live) — **blocks on Q11 (+ Q3)**
- Touch: `agents/update_paper_trades.py` — move `should_force_expire` (now `:235`) ahead of the fetch-fail continue (`:154`) and WAIT continues (`:217`,`:230`).
- Effort 1-2 h · Fix-risk medium (money logic).
- Verify: unit test `fetch=None` + `holding≥max` ⇒ EXPIRED; dry-run on a synthetic OPEN row.
- Rollback: git revert.

**HOTFIX-2 — P0-2 day-0 look-ahead guard** (⚠️ CHANGED — cheaper now) — **blocks on Q7**
- Touch: `agents/update_paper_trades.py` hit detection (`:201-232`).
- Change: when `signal_date == today`, suppress full-day `day_high/day_low` hit checks (LTP-only or skip day-0), using `signal_generated_at` as entry time. **No DDL.**
- Effort 1-2 h (reduced — no `opened_at` migration) · Fix-risk medium (changes day-0 exits).
- Verify: synthetic day-0 trade with a pre-entry spike ⇒ no false TARGET_HIT.
- Rollback: git revert.

**HOTFIX-3 — P1-4 liquidity gate into Tier-2F** (✅ VERIFIED) — **blocks on Q5**
- Touch: `agents/tier2_fundamental.py` `process_filing`, new Step ~1.5:
  `is_liquid, _ = check_liquidity(symbol); if not is_liquid: skip`.
- Effort 30 min · Fix-risk low-med (fewer trades). Verify: dry-run illiquid ⇒ skip, liquid ⇒ proceed. Rollback: revert.

**HOTFIX-4 — P1-5 proper solo path** (✅ VERIFIED) — **blocks on design decision**
- Touch: `agents/tier2_fundamental.py:303-336,355-357` (+ `utils/ai_consensus.py`).
- Option (i) route SOLO_DEEPSEEK through `_run_deepseek_as_analyst` / adopt `get_consensus()`; or (ii) minimally guard: if `haiku_output is None`, run DeepSeek with the **analyst** prompt and use `.get()` with safe defaults; reconcile haircut (−10 vs ×0.9).
- Effort 2 h · Fix-risk medium (fires only when Anthropic down). Verify: unit test forcing the haiku exception ⇒ no KeyError, sane confidence. Rollback: revert.

**HOTFIX-5 — P1-7 confidence clamp** (✅ VERIFIED) — **blocks on decision (clamp vs reject)**
- Touch: `agents/tier2_fundamental.py:366-374`; wire the dead `CONFIDENCE_FLOOR/CEILING`.
- Change: clamp model/avg confidence to `[50,85]` before conviction mapping.
- Effort 30 min · Fix-risk medium (changes conviction for out-of-band outputs). Verify: conf=95 ⇒ clamp 85 ⇒ stable conviction. Rollback: revert.

**HOTFIX-6 — P1-6 RR floor binds the ladder** (✅ VERIFIED) — **blocks on Q2 (core strategy)**
- Touch: `agents/tier2_fundamental.py:416-427` (+ `reward_risk.passes_rr_floor`).
- Change (IF Q2 = gate every trade): after ladder SL chosen, `passes_rr_floor(entry, sl, t1, direction)`; if fail ⇒ skip.
- Effort 1 h · Fix-risk **HIGH strategy impact** — a 0.6-RR ladder would block most ladder trades; likely the T1/SL ladder itself must be revisited, not just gated. Verify: dry-run; count signals that would be blocked. Rollback: revert.

**HOTFIX-7 — GILLETTE id-161 reconciliation** (✅ DONE — DB-verified 2026-06-13: EXPIRED @ 8016.50 / −3.24%) — was: blocks on price decision
- **Supabase Dashboard SQL** (owner runs): snapshot the row → set EXPIRED at the chosen exit → return capital to `portfolio`/`capital_ledger` (BUY: `pnl = (exit − 8285)/8285 × 24855`) → flag/exclude its `trade_memory_v2` outcome.
- **Exit date: 29 May 2026 (Fri) close** (owner-decided) — the last trading day inside the 3-day horizon; **30 May is a non-trading Saturday**. Remaining decision = the exit *price* on 29 May (close vs last-known).
- Effort 15 min · Fix-risk data-only. Verify: `open_positions→0`, cash → ~993,787.63, `capital_deployed→0`. Rollback: restore snapshot.
- ~~**Must precede any updater resume**~~ — **CLEARED 2026-06-13** (reconciled; the updater can no longer exit it at day-17 prices).

### PARALLEL RELIABILITY BATCH — Batch C (no trading-logic change unless noted; low effort/risk; verify via targeted query/unit; rollback git revert / drop schedule)

- **C1 Schedules/ops:** P2-9 schedule `portfolio_snapshot.py` daily (new yml) · P2-8 run Health Check-1 a 2nd time intra-market or pass a reference time · **P2-10 de-schedule `nifty500_loader.yml`** (pre-flight; Jul 1 next fire) · P2-3 schedule `filings_log_backfill.yml` daily ~20:00 IST + widen sync window · P3-6 Tier-4 → nightly cadence · P3-5 retire `preopen_alert` + `after_hours_queue` zombie.
- **C2 Data integrity:** P2-2 retry FAILED windows (include FAILED in requery, bounded attempts — recovers 22; ties to B2-backtest) · P2-13 stop `json.dumps` for `raw_signal`/`full_context` (**coordinate: update all CASE-decoding consumers in the same change**; optional one-time decode migration) · P2-7 make close+release idempotent / add reconcile-repair to health monitor · **P0-1 deeper fix**: DB-side atomic cash decrement / `SELECT … FOR UPDATE` · P2-14 mark-before-dispatch or idempotent dispatch key.
- **C3 Correctness-latent:** P2-5 extend `trading_calendar` to 2024+ (**gate before B1 step-4**) · P2-6 JSON-extraction regex instead of brace-strip (`ai_consensus.py:51`, `tier0_filings.py:126`) · P1-8 fix `tier2_signals` to /100 **or** mark dead (orphan) · P3-8 enforce `event_type≠OTHER` in the poller (match the prompt).
- **C4 Guardian (P2-11 a/b/c; d is Q3):** (a) query `company_profiles` with `.NS`; (b) widen name map / use `company_profiles` name; (c) append NSE_FILING only when filings non-empty.
- **C5 Hygiene:** P3-1 dotenv override (`tier2_fundamental.py:33`) · P3-2 delete dead code (only after HOTFIX-4/HOTFIX-5 decide `get_consensus`/`CONFIDENCE_*`) · P3-3 stale docstrings/prints/cron comments · P3-4 reconcile taxonomy (classify enum vs TRADEABLE_SCORES/DEFAULT_GAPS) · P3-7 label/scope EXPIRED consistently in Tier-4 win-rate · P3-9 populate or drop `filing_memory.pdf_extract` · P3-10 git hygiene (Q9) · P3-11 misc (float-round display, guardian scan limit).

### BACKBONE TRACK — feature work (reference only; locked order B1 → B7 → B2 → Phase 6)
- **B1 completion:** commit `backfill_membership.py` (Q9) → **decide exit schema (Q6:** add `left_on`/interval) before extending `sync_nse500.py` to append joins/exits → apply `memory_seed` membership filter with the **mandatory sequence: delete 946 SEED rows → reseed filtered → `extract_initial_patterns()`** (which wipes `pattern_insights` via `delete().neq("id",0)`; safe now, one supervised run) → **GUARD P2-5 calendar before any 2024-25 historical backfill (step 4).**
- **B7:** regime-conditional ±3% alpha thresholds (`filing_memory_backfill`/`memory_seed`/`filing_memory_brief`) — design vs `market_context` first.
- **B2:** event-study backtest — re-check per-category maturity (live: 5d FILLED=1047, 10d FILLED=590; need ≥20-30/category) → build `scripts/event_study.py` → fold in P2-2 retry.
- **Phase 6:** after-hours engine — retire the preopen/after_hours_queue zombie (P3-5) + reuse the fixed solo/consensus path (HOTFIX-4) first.

---

## STEP 4 — Decision gates (decide in one pass; each maps to the fix it blocks)
- **Q1 (B6 recompute):** was `scripts/b6_recompute_matured.py --apply` run after `e02c962`? (a) re-run now (idempotent if applied) / (b) leave. — *Cannot confirm from the repo: `e02c962` is HEAD, no snapshot file.* Blocks: trust of ~35 pre-fix matured alpha rows.
- **Q2 (RR intent):** (a) RR≥1.5 gates **every** trade → ladder T1/SL must change / (b) only AI-SL acceptance (status quo) / (c) raise T1 so ladder RR≥1.5. → blocks **HOTFIX-6**.
- **Q3 (advisory tiers):** (a) keep alert-only / (b) Tier-3 REJECT + Guardian EXIT actually close/flag trades. → blocks **C4(d)** + **HOTFIX-1** action choice.
- **Q4 (pause leak):** ANSWERED (Step 2) — GH schedules still live. Decision left = which set to disable in **HOTFIX-0**.
- **Q5 (liquidity):** (a) move ₹5Cr gate into trading path / (b) no. → blocks **HOTFIX-3**.
- **Q6 (B1 exits):** (a) add `left_on` nullable / (b) interval rows / (c) defer. → blocks backbone-B1 sync append.
- **Q7 (day-0 exits):** (a) `signal_generated_at` + LTP-only day-0 (now cheap, no DDL) / (b) accept + document. → blocks **HOTFIX-2**.
- **Q8 (horizons):** (a) calendar days (status quo) / (b) trading days (matches prompt). → blocks **P2-12** fix.
- **Q9 (hygiene):** (a) commit `backfill_membership.py` + delete `tmp_b9_results.json` / `tier2f-investigation-2026-05-22.md` / (b) leave. → blocks **P3-10**, backbone-B1 step 1.
- **Q10 (NEW — filings_log NULLs):** (a) partial unique index `WHERE url_hash IS NOT NULL` (**recommended**) / (b) backfill md5 then full unique. → blocks **A3**.
- **Q11 (NEW — fetch-fail expiry):** (a) close EXPIRED at last-known price / (b) alert-only, leave OPEN. → blocks **HOTFIX-1**.

---

## STEP 5 — Recommended execution order
1. **CONTAIN NOW (no strategy decision): HOTFIX-0 — disable the GitHub Actions schedules** (at minimum Tier-0F Poller). The trading switch is currently LIVE via GH `schedule`; this gates everything else.
2. **Ship Batch 0-A** (A1 concurrency · A2 pattern ordering · A3 unique index) — pure containment, no decision.
3. **One decision pass (Q1-Q11).**
4. ~~**GILLETTE id-161 reconciliation (HOTFIX-7)**~~ — ✅ DONE 2026-06-13 (EXPIRED @ 8016.50 / −3.24%); no longer a resume blocker.
5. **Batch 0-B gated hotfixes**, dependency order: **HOTFIX-2** (day-0 guard) → **HOTFIX-1** (expiry) → **HOTFIX-3** (liquidity) → **HOTFIX-4 + HOTFIX-5** (solo + clamp) → **HOTFIX-6** (RR, only if Q2 = gate).
6. **Batch C reliability** (parallel, anytime) — do **P2-10** + **P2-5** before any resume/backfill.
7. **Safe-resume order** (audit §6): monitors → memory plumbing → Tier-0 → updater (GILLETTE ✅ reconciled 2026-06-13) → **Tier-0F Poller LAST** — only after 0-A/0-B containment and the GH-pause confirmed.
8. **Backbone:** B1 → B7 → B2 → Phase 6, respecting the landmines (P2-5 under B1 step-4; the memory_seed delete-reseed-extract sequence; the nse500_membership exit-schema gap).

**Why:** verified P0s, the live casualty, and the live trading switch jump the queue (containment first); 0-A needs no decision so it ships immediately; all behavioural fixes wait behind one decision pass; the locked backbone (B1→B7→B2→Phase 6) is preserved and only begins after containment.

# Phase 5 Batch B - Execution Brief v5 Supplement

**Version:** v5 (POST-DEPLOY CLOSURE + FORWARD ROADMAP)
**Date:** 2026-05-23 (Saturday, ~8:30 AM IST)
**Supplements:** `docs/phase-5-batchB-execution-brief.md` (v1 -> v4)
**Status:** Phase 5 Batch B CLOSED. Pipeline GREEN, production-ready.
**Authoring:** Claude Code (Opus 4.7, 1M context), autonomous execution sessions
**Strategic decisions (locked by user):** Phase 6 first, then Tier-1F. Medium commitment (15-20 hrs/week). Comprehensive brief scope.

---

## How to read this supplement

The base brief (v1->v4) was written by claude.ai for planning and corrected by
the execution agent through Batch B build-out. It ends at "v5 FINAL (TBD
post-deploy)" in its own version history. This supplement IS that v5: it records
what happened during the 10-session, 2-day production-readiness push (May 22-23),
corrects the assumptions v4 still carried, documents the one genuinely critical
discovery (the confidence-scale DB constraint), states the current GREEN state with
evidence, and lays out the forward roadmap.

Read the base brief for design rationale (cron architecture, idempotency, latency
budget). Read this for what is actually true now and what comes next.

---

## §A Executive summary

Phase 5 Batch B is complete and the pipeline is production-ready (GREEN). The
automated path -- NSE filing detection -> Tier-0F poll -> Tier-2F fundamental
analysis (Haiku + DeepSeek consensus) -> paper_trades insert -> Tier-3 position
management -> Telegram alert -- is wired, tested, and deterministically validated
end-to-end.

Four commits shipped this cycle (chronological):

| # | Commit | What it did |
|---|--------|-------------|
| 1 | `e4ed94a` | Tier-2F env var fix in `tier2f.yml`: `SUPABASE_KEY` -> `SUPABASE_SERVICE_ROLE_KEY`, `NEON_DATABASE_URL` -> `NEON_CONNECTION_STRING` |
| 2 | `4f4ea12` | Tier-3 trigger fix: `workflow_run` now references "Tier-2F Fundamental Signal" (the deleted "Tier-2 Swing Signals" reference was dead) |
| 3 | `9a9259a` | Tier-2F confidence insert + scale alignment: signal confidence 0-100 end-to-end; Tier-3's own Claude verdict confidence preserved at 1-10 |
| 4 | `75ec95f` | Integration test suite + conftest `integration` marker + stale QuestDB test assertion fix |

Plus one manual DB migration the user ran in the Supabase Dashboard (see §C), which
was the missing half of commit `9a9259a`.

This supplement is the 5th commit of the cycle.

---

## §B Corrections to v4 (what the base brief still got wrong or did not anticipate)

The v4 corrections in the base brief fixed planning-time errors (column names,
file counts, the missing `_insert_paper_trade` function). The following are
corrections that only became visible during the May 22-23 production-readiness work
and were NOT captured anywhere in v1-v4:

| ID | v4 assumption | Reality discovered | Where |
|----|---------------|--------------------|-------|
| V5C1 | `9a9259a` "aligned the confidence scale" -- treated as complete | Code-only. The DB CHECK constraint `paper_trades_confidence_check` still enforced the OLD 1-10 scale and rejected every 0-100 value. The migration had a missing DB half. | §C |
| V5C2 | Acceptance criterion V5.8 (full live pipeline in <=600s) would be validated by organic Monday flow | Organic flow alone could not validate the insert path: Sessions C and D both legitimately SKIPPED before insert (not_nifty500, haiku_not_tradeable / index criteria). A deterministic integration test was required and built. | §D, §E |
| V5C3 | `source` value is set somewhere patchable for testing | `source` is a hardcoded string literal `"TIER2F"` in the `trade_payload` dict (`tier2_fundamental.py:292`). No constant. Test isolation required wrapping the supabase client with a proxy that rewrites `source` on insert. | §E |
| V5C4 | The repo test suite was "13 tests" (per Session E's 2-file run) | Full suite is 50 tests across many files (news/QuestDB, phase5 A+B, supabase, telegram, tier2 QuestDB, tier3, tier4). Session E never ran the full suite, so a pre-existing stale assertion went unseen. | §F |
| V5C5 | `agents/tier2_signals.py` is a dormant orphan with no behavior to track | It is dormant for the YAML pipeline, but it was migrated Haiku -> DeepSeek at some point: it now emits `source='deepseek-v4-flash'` (model line 112, source line 170). Its unit test still asserted `'claude-haiku'` and was silently red until the first full-suite run. | §F |

Note on N7 (base brief §6.2): the `uniq_paper_trades_ticker_date_source` partial
index did NOT conflict with the Gap 5 fix in production -- confirmed indirectly, the
integration test inserts under a distinct test source and the duplicate path is
exercised by V5.7a/b. N7 can be closed.

---

## §C The critical discovery: confidence-scale DB constraint (Sessions E -> F)

This is the single most important finding of the cycle. It was a latent production
blocker that no unit test and no organic run had surfaced.

**Symptom (Session E, May 23 ~7:00 AM):** the new integration test forced a consensus
APPROVE and ran the real `process_filing()`. The pipeline executed cleanly through
Stage 9 (sizing: qty=141) and attempted the insert at `tier2_fundamental.py:322`,
which the database rejected:

```
postgrest.exceptions.APIError 23514:
  new row for relation "paper_trades" violates check constraint
  "paper_trades_confidence_check"   (confidence=78)
```

**Root cause:** commit `9a9259a` migrated the application code to a 0-100 confidence
scale but the `paper_trades_confidence_check` CHECK constraint still encoded the
original 1-10 scale. A value of 78 (= round((75+80)/2)) violated it. `9a9259a` was a
code-only fix; the DB half of the migration was missing.

**Why it had never been caught:** Sessions C and D both skipped before the insert
(legitimate AI/universe gates), so the insert path with a /100 value had never
executed against the real DB. The 13 unit tests mock the DB and never hit the
constraint. The integration test was the FIRST code path to reach the insert with a
post-`9a9259a` confidence value.

**Resolution (Session F, May 23 ~7:30 AM):** the user migrated the constraint via
the Supabase Dashboard SQL Editor (per the project's DDL-via-Dashboard working
agreement):

```sql
-- confirmed old: CHECK (((confidence >= 1) AND (confidence <= 10)))
ALTER TABLE paper_trades DROP CONSTRAINT paper_trades_confidence_check;
ALTER TABLE paper_trades ADD CONSTRAINT paper_trades_confidence_check
  CHECK (confidence >= 0 AND confidence <= 100);
```

**Verification:** re-running the unchanged integration test took Test 1 from red to
green. A real `confidence=78` paper_trade now inserts successfully. This is a clean
before/after proof that the DB constraint was the only thing blocking the insert
path.

**Scale contract (now locked and validated):**

- Signal confidence (Tier-2F avg of Haiku + DeepSeek): **0-100**, stored in
  `paper_trades.confidence`, gated by the DB CHECK constraint `0..100`.
- Tier-3 acceptance threshold: `signal["confidence"] < 50` rejects
  (`tier3_position_manager.py:30`).
- Tier-3's OWN Claude verdict confidence (`evaluate_with_claude`) is a SEPARATE
  field, deliberately preserved at **1-10**. Do not confuse the two scales.

---

## §D What the integration test validates (deterministic, permanent)

File: `tests/test_tier2f_insert_integration.py` (committed in `75ec95f`,
`@pytest.mark.integration`, opt-in via `-m integration`).

| Test | Asserts |
|------|---------|
| `test_tier2f_insert_path_full_chain` | Mocks Haiku (tradeable=True, BULLISH, conf=75) + DeepSeek Flash (CONFIRM, BULLISH, conf=80); runs real `process_filing(1418)`; asserts a paper_trade inserts with `confidence=78` on the 0-100 scale, direction BUY, and all required NOT NULL fields positive. |
| `test_tier3_accepts_0_100_scale_signal` | `apply_rules` accepts confidence=78 (>= 50). |
| `test_tier3_rejects_below_50_threshold` | `apply_rules` rejects confidence=49 with reason `confidence_below_threshold`. |

**Test design choices worth preserving:**

- Mocks only the AI consensus stages (`run_analyst`, `run_verifier`) on the
  `tier2_fundamental` namespace -- zero real Anthropic/DeepSeek calls. The real
  `determine_consensus` runs (it is pure logic), so consensus is also covered.
- A supabase client proxy rewrites `source` -> `TIER2F_INTEGRATION_TEST` on insert,
  so production code stays unedited and production data stays untouched.
- `deploy_capital` and `_tg_send` are mocked (no capital-ledger write, no real
  Telegram).
- `TIER2F_TEST_MODE=True` bypasses the market-mood `nifty_bearish` skip so the test
  is deterministic regardless of live NIFTY.
- A cleanup fixture deletes any `source='TIER2F_INTEGRATION_TEST'` rows before and
  after each test.

---

## §E Acceptance criteria status (base brief §0.3)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| V5.1 -- Tier-0F poller dry-run dispatches + marks picked | PASS | `test_phase5_batchB.py::test_V5_1` green |
| V5.7 -- Tier-3 duplicate rule per (ticker, source) | PASS | `test_V5_7a` + `test_V5_7b` green |
| V5.8 -- full live pipeline <=600s | DEFERRED to Monday organic flow | Insert path now proven deterministically (§D); end-to-end wall-clock timing on a real filing still pending real market open |
| DB residue clean | PASS | 0 `TIER2F` paper_trades; 0 `TIER2F_INTEGRATION_TEST` leftover rows |
| Node.js deprecation cleared | PASS (Batch B) | Group B sweep, commit `317bde3` (per v4 §3.13) |
| cron-job.org webhook active | USER-OWNED | Dashboard config outside agent scope |
| GH Actions fallback verified | PASS (Batch B) | `tier0f-poller.yml` schedule trigger |

V5.8 is the only criterion not closeable from the desk: it needs a real filing
flowing through during market hours. The risk it was meant to catch (the insert
failing) is now eliminated by §C + §D.

---

## §F Incidental finding: stale QuestDB test (fixed in `75ec95f`)

The first full-suite run (50 tests) surfaced one unrelated failure:
`test_tier2_questdb_write.py::test_buy_signal_inserts_correct_row` expected
`source='claude-haiku'`. The Tier-2 SWING module `agents/tier2_signals.py` (separate
from Tier-2F) was migrated Haiku -> DeepSeek and now emits `'deepseek-v4-flash'`
(model line 112, source line 170). The test assertion was never updated -- a stale
expectation, not a production bug. Fixed the one-line assertion to match current
code. Full suite is now green.

This also retires base-brief question N8's urgency: `tier2_signals.py` is not just an
orphan, it has a live (if unused-by-pipeline) behavior contract. Decision on deleting
it remains Phase 6+ cleanup.

---

## §G Current production-ready state (as of 2026-05-23 ~8:30 AM IST)

- **Pipeline status:** GREEN.
- **Test suite:** 49 passed, 1 skipped (the intentional V5_3/V5_4 live-insert gate),
  including the 3 new integration tests (run with `-m integration`).
- **DB:** constraint migrated to 0..100; 0 `TIER2F` production paper_trades (clean
  baseline awaiting Monday); 0 leftover integration-test rows.
- **HEAD:** `75ec95f` on `main`, pushed; this supplement will be the next commit.
- **Reports on disk:** `dumps/session-d-final-validation-2026-05-22.md`,
  `dumps/session-e-integration-test-2026-05-23.md`,
  `dumps/session-f-post-migration-validation-2026-05-23.md`.

**Still unverified (defer to Monday organic flow):**

- Real Anthropic Haiku APPROVE on a live filing (mocked in tests).
- Real DeepSeek Flash CONFIRM on a live filing (mocked in tests).
- Telegram trade alert firing on the real device.
- Tier-3 reading a live signal end-to-end.
- V5.8 wall-clock latency on a real filing (<=600s budget).

---

## §H Session chronology (the 2-day closure)

| Day | Sessions | Commits | Reports |
|-----|----------|---------|---------|
| May 22 (Fri) | 9 sessions: API-key auth resolution, pipeline audit v1+v2, Session C verification (filing 1340 SKIP), Nifty500 universe discovery, Session D validation (filing 1418 WHIRLPOOL) | `e4ed94a`, `4f4ea12`, `9a9259a` | 6 dumps |
| May 23 (Sat) | 2 sessions: Session E (integration test, caught the DB constraint bug), Session F (post-migration validation + commit) | `75ec95f` | 2 dumps |

Key learning from the sequence: the value of a deterministic integration test was
exactly that it does not depend on "live AI mood" or universe gates. Sessions C and D
were legitimate skips that looked like progress but never exercised the insert. The
test closed that gap in one run -- and immediately found a real blocker.

---

## §I Forward roadmap

User-locked sequencing: **Phase 6 first, then Tier-1F.** Commitment: **Medium
(15-20 hrs/week realistic).** This roadmap is paced for that.

### §I.1 Immediate (Monday May 25, market open) -- close V5.8

1. Watch the first organic material filing flow Tier-0F -> Tier-2F -> insert ->
   Tier-3 -> Telegram during market hours.
2. Capture the V5.8 latency query (base brief §2.6) on the first real `TIER2F` row;
   confirm `lag_seconds <= 600`.
3. Confirm the real Telegram alert fires on-device.
4. If all green: Phase 5 Batch B is not just code-complete but production-confirmed.
   Tag a `v5 FINAL` note in the base brief version history.

### §I.2 Phase 6 (next major track) -- reconciliation + after-hours engine

Phase 6 is where the deferred items concentrate. Suggested ordering for a 15-20
hrs/week pace:

1. **Production-data hygiene first (low risk, high signal):**
   - N9.3: `apply_rules()` KeyError robustness -- defensive coding so a malformed
     signal payload cannot crash position management (paper trading must fail safe).
   - N9.4: adopt "run pytest before every commit touching `agents/`" as a working
     agreement (a broken Tier-3 test slipped through once already; the stale QuestDB
     test slipped through this cycle).
   - N9.1: clean the 5 pre-existing em-dashes in `tier3_position_manager.py` f-strings
     (cp1252 risk on Windows).
2. **SOLO_DEEPSEEK after-hours engine (Q2 / O1):** design the DeepSeek-heavy fallback
   so a Haiku outage degrades gracefully instead of being treated as both_apis_down.
3. **Latency + concurrency observations (N2, N3, N4, R5):** over the first ~50 real
   triggers, track Haiku+Flash p99, watch for concurrent-dispatch races, and decide
   whether the Tier-3 duplicate guard needs a DB-level partial unique index or a
   FOR UPDATE lock (currently logic-only by design).
4. **Flash CHALLENGE rate (Q1 / O3):** with a 2-week production sample, revisit
   whether the Tier-2F verifier prompt needs softening, and whether V5.3/V5.4 can be
   retried.
5. **Housekeeping (Q4, Q5, N8, N9.2):** `published_at` population, the
   filing-memory-backfill cron-time mismatch, deleting the `tier2_signals.py` orphan,
   and the `update_paper_trades.yml`-already-at-v6 curiosity.

### §I.3 Tier-1F News engine (after Phase 6) -- Q3 / O2 / O6 / O7

The 6-block Tier-1F design is locked; placement was always "after Phase 5 + Phase 6."
Its prerequisites cluster in the Tier-1 track bugs already logged:

- Q6 / O6: Tier-1 News Researcher failing (`.NS` suffix + `news_log.symbol` column
  missing).
- Q7 / O7: Tier-1 Guardian dormant (0 alerts ever) -- same root cause.

Fixing those is the natural on-ramp to Tier-1F and should be the first Tier-1F-track
work item once Phase 6 stabilizes.

---

## §J Open questions ledger (carried + updated)

| ID | Status after this cycle |
|----|-------------------------|
| Q1 V5.3/V5.4 retry | Still deferred; revisit with 2-week production sample (Phase 6). |
| Q2 SOLO_DEEPSEEK | Still deferred to Phase 6 after-hours engine. |
| Q3 Tier-1F engine | Sequenced AFTER Phase 6 per user decision. |
| Q4 published_at | Phase 6 housekeeping. |
| Q5 backfill cron mismatch | Phase 6 audit. |
| Q6/Q7 Tier-1 bugs | Tier-1F track on-ramp. |
| N2/N3/N4 concurrency+latency | Observe in first 50 real triggers (Phase 6). |
| N7 partial-index conflict | CLOSEABLE -- no conflict observed; Gap 5 fix validated. |
| N8 tier2_signals.py orphan | Phase 6 cleanup; note it has a live DeepSeek source contract (§F). |
| N9.1 em-dashes | Phase 6 cleanup. |
| N9.3 apply_rules KeyError | Phase 6 robustness item (raised priority -- fail-safe matters). |
| N9.4 pre-commit pytest | RECOMMEND adopting now (two near-misses this cycle). |
| O10 backlog pre-mark | User decision still open; low urgency (0 TIER2F trades, idempotent poller). |
| **V5N1 (new)** | DB schema migrations must ship in the SAME cycle as the code that depends on them. `9a9259a` split a scale migration across code (committed) and DB (not done), creating a latent blocker. Treat constraint/column changes as part of the code change's definition of done. |
| **V5N2 (new)** | Run the FULL suite (not a subset) before declaring done; subset runs hid a stale test for an unknown duration. |

---

## §K Version history (continuation of base brief)

| Version | Date | Change | Author |
|---------|------|--------|--------|
| v5 supplement | 2026-05-23 | Post-deploy closure: confidence-scale DB constraint discovery + fix (Sessions E/F), integration test suite, stale QuestDB test fix, GREEN state with evidence, forward roadmap (Phase 6 then Tier-1F, Medium pace). Closes N7. Raises V5N1/V5N2. | Claude Code (Opus 4.7) |
| v5 FINAL | (TBD Monday) | V5.8 organic latency confirmation + real Telegram alert + cron-job.org dashboard verification | (post-market-open) |

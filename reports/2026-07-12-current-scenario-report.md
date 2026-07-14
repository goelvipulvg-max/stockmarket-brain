# StockMarket-Brain — Current Scenario Report (Investigation Only)

**Date:** 2026-07-12 (Saturday) · **HEAD:** `a3f040b` (origin/main in sync) · **State:** 15 workflows active / 4 disabled (`gh workflow list` live-verified)
**Baseline:** [2026-07-04 full-system audit](2026-07-04-full-system-audit.md) (grade B−, 5 exec findings) · **Window examined:** staged-resume window 2026-07-06 → 2026-07-10 (5 trading days; Jul 11-12 = weekend)
**Method:** read-only reliability investigation — live Supabase + Neon queried via the dedicated `smb_audit_ro` role (INSERT privilege verified **false**, `BYPASSRLS=true`, session forced `default_transaction_read_only=on`); all 390 Tier-2F GitHub run logs harvested and stage-classified; zero code edits, zero flag changes, zero DB writes, zero trades. Report intentionally uncommitted (owner review first).

---

## 1. Executive Summary

**Posture in one line:** Operationally the system is *healthier* than on July 4 — every Batch D fix is verified live and the burst-eviction fix is production-validated — but the week's **zero trades are only ~70% "healthy filtering"**: the remaining 30% of the explanation is a **newly root-caused structural defect** — the DeepSeek verifier is token-starved on Tier-2F prompts, which has effectively disabled consensus mode all week.

### Top findings

**#1 — DeepSeek verifier "empty responses" root-caused: `max_tokens=600` starvation by hidden reasoning (NEW, HIGH).**
`deepseek-v4-flash` is a reasoning-emitting model. On a Tier-2F-verifier-sized prompt (~7.3K chars) it spends the **entire 600-token completion budget on `reasoning_content` and returns `content=""` with `finish_reason="length"` — reproduced 3/3 deterministically** (local repro, same client config as [utils/ai_consensus.py:25](../utils/ai_consensus.py), `max_tokens=600` at `:97`). In production since resume: of the 21 filings that reached the verifier stage, **17 (81%) got empty responses** (33 `[WARN] verifier attempt N: empty response` lines across Jul 7/8/9/10 = 12/4/5/12) → forced `SOLO_HAIKU`. It is not intermittent and not a key/endpoint problem — the key works (3/3 tiny-prompt calls OK; Tier-0 classify, same model with a short prompt, ran 362/362 green). The "empty response" label in `_retry_json` ([ai_consensus.py:44-49](../utils/ai_consensus.py)) masks that retries can never succeed on large prompts. **Direction (proposal only): raise verifier/solo `max_tokens` well above reasoning burn (e.g. 2-3K) or switch the verifier call to a non-reasoning mode, then re-run one dispatch to confirm.**

**#2 — Zero trades since resume: gate-by-gate funnel now fully quantified (§4).**
1,537 filings ingested → 385 dispatch candidates → 365 claimed → 343 actually analyzed → **0 reached Stage 9 → 0 trades**. Kill order: liquidity gate 128 (37%), not-Nifty500 107 (31%), analyst not-tradeable 87 (25%), verifier challenged 4, solo-bar refusals 17. **Consensus PROCEED count for the whole week: 0.** The RR-floor canary is **UNFIRED with certainty** (no filing reached Stage 9; grep of all 365 success-run logs shows zero `[STAGE 9]` lines). Verdict: the pre-AI gates are working as designed, but the AI-consensus stage is structurally broken by #1 — the system **cannot currently produce a consensus trade**.

**#3 — GitHub `schedule:` triggers under-fire 4-17% of design cadence repo-wide (NEW, MEDIUM).**
Intraday crons: updater fallback fired 11/~240 expected slots (4.6%), poller fallback 9/~210 (4.3%), tier0 20/~130 (15%), **Guardian 19/~110 (17%)**, News 22/~130 (17%). Daily crons (tier4, summary, snapshot, backfills, NSE sync) fired 5/5 — reliable. Two consequences: (a) the I-1/P-1 GH fallbacks **do work but are thin** — if cron-job.org dies, effective updater cadence is ~2-4 runs/day, not 12/hour; (b) Guardian and News have **no cron-job.org primary at all** — Guardian's real cadence is ~4 runs/day vs the 30-min design ([tier1_guardian.yml:8](../.github/workflows/tier1_guardian.yml)). Harmless at 0 open positions; a real protection-cadence gap the day positions open.

**#4 — Burst-eviction fix validated in production; pre-fix losses bounded at 22 filings (CLOSED).**
Timeline: `884947a` (BATCH_LIMIT 10→1) Jul 8 12:55 IST, `a3f040b` (claim moved into the Tier-2F run, [tier2_fundamental.py:189-203](../agents/tier2_fundamental.py)) Jul 8 21:31 IST. Tier-2F cancellations: 18 on Jul 7, 7 on Jul 8 (all before the fixes' effective windows), **0 on Jul 9-10**. Net pre-fix casualty count is exact: 365 filings marked picked − 343 analyzed = **22 filings marked-but-never-analyzed** (Jul 7-8, unrecoverable under old code; loss mode now impossible). The 22 `already_claimed` clean exits post-fix confirm the new duplicate-dispatch path works.

**#5 — F-1 backfill 1000-row cap still open and the historical hole grew: 2,307 all-time material candidates vs 1,982 filing_memory rows (−325; was −234 on Jul 5).**
[filings_log_backfill.py:20-23](../agents/filings_log_backfill.py) still selects with no `.order()`/`.range()` → PostgREST 1000-row window. Mitigant discovered: the 10-min **filing_memory_sync** (45-min lookback, [filing_memory_sync.py:53-60](../agents/filing_memory_sync.py), 157 green runs) is inserting *fresh* filings — 297 rows with `filing_date >= 2026-07-06` arrived — so the hole is concentrated in **historical** rows the nightly sweep can never reach.

### Grade movement vs July 4

| Dimension | Jul 4 | Today | Why |
|---|---|---|---|
| Architecture / design | A− | A− | Unchanged; claim-based dispatch (C-b) is a genuine design improvement |
| Reliability fixes | B+ | **A−** | Batch D 1-3 all verified live in code + DB; eviction fix production-validated |
| Money-seam integrity | C | **B+** | VOID in status CHECK live, v2 release guards applied (owner SQL confirmed in DB), seam-a/-c guards in code; identity rupee-exact |
| Paper-fidelity honesty | C+ | **B** | P1-3 pessimistic `first_touch`, boundary SL fills, `cost_rs` net-ledger all live ([update_paper_trades.py:75-98, :250-262, :565-584](../agents/update_paper_trades.py)) — but untested by fire (0 closes since) |
| Signal-path health | (n/a) | **D+** | NEW dimension: consensus mode structurally disabled by verifier starvation (#1); solo bar auto-refuses |
| Test / ops hygiene | D+ | B− | pytest gate landed (13f585f); GH-schedule thinness (#3) and snapshot no-retry are the residue |
| Strategy validation maturity | D | **D** | Unchanged and now *blocked by #1*: resolved TIER2F sample still n=3; a week of wall-clock produced zero new samples |

---

## 2. Part 1 — Previously-Flagged Items: Current Status

| # | Item | Status | One-line evidence |
|---|---|---|---|
| 1 | DeepSeek Verifier health | **STILL OPEN — root-caused** | 17/21 verifier calls empty Jul 7-10; 3/3 local repro: `finish=length`, `content_len=0`, `reasoning_len≈2200` at `max_tokens=600` |
| 2 | `portfolio_snapshots` table | **RESOLVED (works)** — one gap | Table exists, 4 rows: Jul 6/7/8/10; **Jul 9 missing** (snapshot run cancelled 12:43 UTC, no retry) |
| 3 | `filing_memory` outcome columns | **RESOLVED (confirmed plain text)** | Supabase (not Neon): `outcome_5d/10d/30d_status` all `text`, nullable, **zero CHECK constraints** (`pg_constraint` query returned `[]`) |
| 4 | GH schedule fallbacks (I-1/P-1) | **LANDED + firing, but thin** | [update_paper_trades.yml:9-16](../.github/workflows/update_paper_trades.yml), [tier0f-poller.yml:13-14](../.github/workflows/tier0f-poller.yml); fired 11 and 9 times respectively (4-5% of design cadence — see §3.2) |
| 5 | telegram_client silent-swallow + F-1 | **BOTH STILL OPEN** | [telegram_client.py:10-12, :18-19](../utils/telegram_client.py) print-and-continue, no retry/raise; [filings_log_backfill.py:20-23](../agents/filings_log_backfill.py) unpaginated |
| 6 | Batch D Session 3 commits | **ALL LANDED** | I-1/P-1/U-9 in `f7cbec4`; G-1 in `624bc0f`; tier2_signals hard-kill in `e227456` (details below) |
| 7 | B1 survivorship | **STILL BUILT-BUT-UNUSED** | Neon `nse500_membership` has 505 rows (2024-01-01→2026-03-28) but repo grep: only `scripts/backfill_membership.py` references it — nothing in the live signal path |
| 8 | B7 regime thresholds | **STILL ZERO** | Repo-wide grep: single comment mention ([event_study.py:186](../scripts/event_study.py)); no code |
| 9 | Phase 6 after-hours engine | **STILL NOT STARTED** | No `after_hours_v2`/engine files; old watcher deprecated in `scripts/`, workflow `disabled_manually`; fresh evidence of the cost: 11 post-market candidates missed Jul 8-9 (§4.1) |
| 10 | Phase 7 learning-loop retrieval | **STILL WRITE-ONLY** | `trade_memory_v2` readers = seed/backfill scripts + tests only; 946 SEED + 3 LIVE_TRADE rows; `pattern_insights` frozen since **2026-05-19** (max `extracted_at`), 15 rows |

### Item detail

**1. DeepSeek Verifier.** Config: `.env` has `DEEPSEEK_API_KEY` (works — 3/3 minimal calls returned valid JSON) and `DEEPSEEK_BASE_URL` — which is **dead config**: [ai_consensus.py:25](../utils/ai_consensus.py) hardcodes `base_url="https://api.deepseek.com"`, and [tier2f.yml:34](../.github/workflows/tier2f.yml) passes only the key to CI. `gh secret list` was denied (HTTP 403, PAT lacks secrets-read) so Secrets values are behaviorally validated only: CI DeepSeek calls succeed on short prompts (Tier-0: 362/362 runs green) and fail empty on long ones — consistent with the token-starvation mechanism, not credentials. Frequency since the July 9 flag: still happening through the last trading day (12 empty-response WARNs on Jul 10 alone). See §4.2 for the full mechanism.

**2. portfolio_snapshots.** Live schema confirmed (10 columns, `snapshot_date` + equity fields). Rows written on every scheduled run that executed: Jul 6, 7, 8, 10 — all four identical (cash 992,982.07 / deployed 0 / equity 992,982.07 / open_positions 0), consistent with a week of zero trades. The Jul 9 gap traces to run `29019064873` (job-level *cancelled* at 12:43:54 UTC — same minute as the updater's only failed run `29019057903`; a one-off runner/incident window, not a code defect). Observation: snapshot has no retry/backfill mechanism, so a cancelled daily run = a permanent hole in the equity curve.

**3. filing_memory constraints.** The table lives on **Supabase** (the prompt said Neon — Neon has no `filing_memory`; its legacy `filings_log` clone has no outcome columns; both `information_schema` sweeps for `outcome%status%` columns and CHECK constraints on Neon returned empty). On Supabase: `outcome_5d_status` / `outcome_10d_status` / `outcome_30d_status` are plain nullable `text` with **no CHECK constraints and no enum** — the sync can write any status string without DDL friction. Current value census: 5d = FILLED 1,632 / PENDING 350 (1,982 total; no other statuses in use).

**4. Schedule fallbacks.** Both `schedule:` blocks exist exactly as Batch D-3 wrote them (updater `*/10 3-10 * * 1-5` with the audit-I-1 comment; poller `*/10 3-9 * * 1-5`; poller also got its `tier0f-poller-run` concurrency group, [tier0f-poller.yml:7-9](../.github/workflows/tier0f-poller.yml)). They **have genuinely fired** (11 and 9 `schedule`-event runs respectively) — but at 4-5% of the nominal slot count; see §3.2 before treating them as real redundancy.

**5. telegram_client + F-1.** Unchanged since July 4. `send_message` swallows config-missing (`:10-12`) and HTTP errors (`:18-19` — print only, no retry, no raise); a transport exception would propagate, but every production caller wraps it in a fail-open `_tg_send` (e.g. [update_paper_trades.py:187-203](../agents/update_paper_trades.py)), so a failed alert is invisible except as a log line. F-1: the nightly backfill query still fetches with no order and no pagination; at 2,307 material candidates the 1000-row window leaves 325 historical rows permanently out of `filing_memory` (quantified live this session; the 10-min sync covers *new* rows, so the gap no longer grows for fresh filings — it grew +91 this week only because some new rows arrive solely via the capped sweep, e.g. when classified outside the sync's 45-min lookback).

**6. Batch D Session 3 — all landed, live-verified in code:**
- **I-1** updater GH fallback: `f7cbec4` → [update_paper_trades.yml:9-16](../.github/workflows/update_paper_trades.yml) (hour-10 UTC requirement documented in-file).
- **P-1** poller concurrency group: `f7cbec4` → [tier0f-poller.yml:7-9](../.github/workflows/tier0f-poller.yml).
- **U-9** Telegram close/upgrade alerts: `f7cbec4` → close alert after the idempotent flip ([update_paper_trades.py:274-277](../agents/update_paper_trades.py)), T1/T2 upgrade alerts (`:604-605`, `:630-632`), CRITICAL release-failure alerts (`:302-315`). Untested by fire — zero closes since resume.
- **G-1** Guardian lone-catastrophic-filing bypass: `624bc0f` → `CATASTROPHIC_FILING_SCORE = 8` ([tier1_guardian.py:30](../agents/tier1_guardian.py)), bypass logic with None-score fail-safe (`:256-260`).
- **tier2_signals hard-kill**: `e227456` → main guard is now `sys.exit("DEPRECATED: ...")` (file tail), and `.claude/settings.json` no longer allowlists its execution (verified by reading the current allow list). Residual note: `settings.json` still allowlists `python.exe agents/update_paper_trades.py` (a live-write command) — hygiene item, not a defect.

**7-10.** See table; nothing moved. For #10 specifically: Tier-2F *does* read `pattern_insights` and `filing_memory` briefs at signal time ([tier2_fundamental.py:283, :287](../agents/tier2_fundamental.py)) — but pattern_insights is a 15-row snapshot frozen at 2026-05-19 (no nightly refresher exists), and `trade_memory_v2` — the Phase 7 capture store — is consulted by no rupee-moving decision. The capture half keeps working (it will write on the next trade); the learning half remains unbuilt, exactly as July 4 said.

---

## 3. Part 2 — Operational Health (15 Active Workflows)

### 3.1 Run history, Jul 6 → Jul 12 (`gh run list --created ">=2026-07-06"`)

| Workflow | Runs | Success | Not-success | Trigger mix | Last success (UTC) | Verdict |
|---|---|---|---|---|---|---|
| Tier-0 Filing Agent | 362 | 362 | 0 | 342 dispatch / 20 schedule | Jul 10 10:56 | **HEALTHY** |
| Tier-0F Poller | 864 | 834 | 30 cancelled | 855 dispatch / 9 schedule | Jul 10 10:58 | **HEALTHY** (cancels = concurrency queue-trim, all Jul 9 03:54-10:24 UTC; next 2-min cycle rescans — lossless by design) |
| Tier-2F Fundamental | 390 | 365 | 25 cancelled | 390 dispatch | Jul 10 10:59 | **HEALTHY post-fix** (all 25 cancels pre-`a3f040b`; 0 on Jul 9-10) |
| Update Paper Trades | 375 | 374 | 1 cancelled | 364 dispatch / 11 schedule | Jul 10 12:38 | **HEALTHY** (single Jul 9 12:43 runner-cancel; one 5-min cycle missed, 0 OPEN trades → zero impact) |
| Tier-1 Guardian | 19 | 19 | 0 | 19 schedule | Jul 10 15:35 | **RUNNING but under-cadence** (~4/day vs 30-min design — §3.2); behavior correct: "Held positions: 0 … Exiting" |
| Tier-1 News | 22 | 22 | 0 | 22 schedule | Jul 10 10:52 | **RUNNING but under-cadence**; posting works (sample: Fetched 60 / Posted 5 / Errors 1; news_log +618 rows since Jul 6) |
| Tier-3 Position Mgr | 390 | 365 | 25 skipped | 390 workflow_run | Jul 10 11:00 | **HEALTHY** (mirrors Tier-2F; 0 decisions — nothing to adjudicate) |
| Tier-4 Memory Mgr | 5 | 5 | 0 | schedule | Jul 10 17:17 | **HEALTHY** (nightly; expectancy on n=3 — statistically meaningless, correctly scoped) |
| Daily Summary | 5 | 5 | 0 | schedule | Jul 10 06:26 | **HEALTHY** (`[sent]` confirmed in log) |
| Health Monitor | 47 | 47 | 0 | 32 dispatch / 15 schedule | Jul 10 11:22 | **HEALTHY** (cron-job.org recovery confirmed; Jul 10: "[health] all green … no alert sent") |
| Portfolio Snapshot | 5 | 4 | 1 cancelled | schedule | Jul 10 12:38 | **MOSTLY HEALTHY** — Jul 9 row permanently missing, no retry mechanism |
| Filings Log Backfill | 5 | 5 | 0 | schedule | Jul 10 16:36 | **RUNNING** (green but F-1-capped — it can never see rows past the 1000-window) |
| Filing Memory Sync | 157 | 157 | 0 | 146 dispatch / 11 schedule | Jul 10 10:11 | **HEALTHY** (inserted 297 fresh rows since Jul 6) |
| Filing Memory Backfill | 5 | 5 | 0 | schedule | Jul 10 20:17 | **HEALTHY** |
| Weekly NSE 500 Sync | 1 | 1 | 0 | schedule | Jul 12 05:40 | **HEALTHY** |

### 3.2 Cross-cutting: GH `schedule:` under-firing (NEW finding)

Fired-vs-design slot counts, Jul 6-10: updater **11/240 (4.6%)**, poller **9/210 (4.3%)**, tier0 **20/130 (15%)**, guardian **19/110 (17%)**, news **22/130 (17%)**. All once-daily crons fired 5/5. This is GitHub's well-known throttling/skipping of high-frequency scheduled workflows — not a repo bug — but it changes two risk assessments: (a) the I-1/P-1 fallbacks are *degraded-mode* insurance (hours-level gaps possible), not like-for-like redundancy; (b) **Guardian and News have no cron-job.org primary**, so their *actual* operating cadence is ~1/2.5h, not 1/30min. Proposal directions (no change made): add cron-job.org jobs for guardian/news post-resume, and/or a health-monitor staleness check on guardian's last-run timestamp.

**Jul 9 12:43 UTC micro-incident:** updater run 29019057903 and snapshot run 29019064873 both went job-level `cancelled` in the same minute (runner-level; `--log-failed` returns nothing). The same day carries all 30 poller queue-cancels. One-off; nothing recurred Jul 10.

### 3.3 Capital identity (live re-verified)

`portfolio` (single live row id=1): cash **992,982.07** + deployed **0** = equity **992,982.07** ✓ rupee-exact; `updated_at` still 2026-07-04 (no money motion since — correct for zero trades). `capital_ledger`: 0 rows since resume; last entry id=18 (2026-06-13). All 4 snapshots identical to the portfolio row ✓. Health Monitor's own identity check: green on every run. Seam-guard columns confirmed live in DB: `status` CHECK includes `'VOID'`, `capital_release_failed` and `cost_rs` columns exist (all currently 0 rows using them — nothing has closed).

### 3.4 Telegram channels — expected vs observed

| Channel (env) | Expected since resume | Observed | Verdict |
|---|---|---|---|
| TRADES_CHANNEL_ID (Tier-0 filing alerts) | Material-filing alerts | `telegram_sent=true` on 4/37/42/52/72 filings (Jul 6-10) = 207 alerts | **RECEIVING** |
| TIER3 (open/close/summary/health) | Daily summary + health alerts only (0 trades → 0 open/close alerts) | Daily Summary `[sent]` ×5; health silent = all-green; 0 open/close alerts — **correct silence** | **RECEIVING** |
| MOVERS (Tier-1 News) | Mover posts | "Posted: 5" in latest run; 618 news_log rows | **RECEIVING** |
| GUARDIAN | Nothing (0 open positions) | `tier1_guardian_alerts` total = 0; runs exit early | **CORRECT SILENCE** |
| LT / SWING (legacy Tier-2) | Nothing (path hard-killed) | No sends | **CORRECT SILENCE** |
| RESEARCH | Nothing (manual agent) | No sends | **CORRECT SILENCE** |

---

## 4. Part 3 — Why Zero Trades: Gate-by-Gate Funnel (PRIORITY)

Counts from live `filings_log`/`paper_trades` plus stage-classification of **all 365 successful Tier-2F run logs** (390 runs harvested; 25 cancelled runs produce no logs by nature). DB cross-checks: 0 new `paper_trades` rows (max id still 162), 4 `agent_disagreements`, 0 `tier3_decisions`, 0 `capital_ledger` rows — all consistent with the log-derived funnel.

### 4.1 The funnel (2026-07-06 → 2026-07-10)

| Stage | Count | Drop | Biggest reason at this arrow |
|---|---|---|---|
| Filings ingested (classified) | **1,537** | — | per-day: 41 / 359 / 381 / 382 / 374 |
| → material dispatch candidates (`is_material`, score≥6, ≠OTHER) | **385** | −1,152 | Tier-0 materiality filter (75% of all filings score ≤5) — working as designed |
| → marked picked (dispatched+claimed) | **365** | **−20** | (a) 9 on Jul 6 *before* L5 went live; (b) 11 on Jul 8-9 classified 16:17-16:57 IST — **after the poller's operating window**, silently expired out of the 30-min lookback (P-3 + the Phase-6 evening-hole in live form) |
| → actually analyzed by Tier-2F | **343** | **−22** | pre-fix burst-eviction casualties (Jul 7-8 only; marked-but-never-analyzed; loss mode closed by `a3f040b` — 0 evictions Jul 9-10) |
| → past F&O-ban gate | 343 | −0 | no banned symbols hit |
| → past liquidity gate (₹5 Cr ADV) | **215** | **−128** | **largest single killer (37% of analyzed)** — small-cap filings dominate the material stream |
| → past Nifty500 universe gate | **108** | **−107** | second killer (31%) — candidate not in `company_profiles` |
| → past chart/NIFTY-mood gates | 108 | −0 | zero `chart_unavailable`, zero `nifty_bearish` (NIFTY never BEARISH this week); dormant price/volume gates: shadow-log only, as configured |
| → analyst (Haiku) says tradeable | **21** | **−87** | analyst not-tradeable (25% of analyzed) — mostly routine RESULTS/DIVIDEND with no clear edge |
| → survived verifier stage | **0** | **−21** | split: **17 verifier-EMPTY → SOLO_HAIKU → all 17 refused at the solo bar** (0.9× haircut conf 52-64 < 65); **4 verifier-CHALLENGE** (AXISBANK, TORNTPHARM, SBIN, CHOICEIN — agreement 30-45, logged to `agent_disagreements`) |
| → Stage 9 (AI-SL / live RR floor / sizing) | **0** | — | **never reached → RR-floor canary UNFIRED (confirmed, not assumed)** |
| → `paper_trades` insert | **0** | — | zero trades |

(Plus 22 `already_claimed` duplicate-dispatch runs that exited cleanly at Stage 0 — the post-fix design working, not filings lost.)

### 4.2 The verifier root cause (the avoidable part)

Mechanism, established by controlled repro with the production prompt template ([prompts/tier2f_verifier_v1.txt](../prompts/tier2f_verifier_v1.txt)) and the exact client config of [ai_consensus.py:25, :95-105](../utils/ai_consensus.py):

```
deepseek-v4-flash, max_tokens=600, verifier-sized prompt (~7.3K chars)
→ finish_reason="length", completion_tokens=600 (ALL spent on reasoning_content ≈2,200 chars)
→ message.content = ""  → run_verifier returns ""  → _retry_json retries 2× (same result)
→ ValueError("verifier: empty response after 3 attempts") → SOLO_HAIKU fallback
```

- Reproduced **3/3**; a trivial prompt through the same client returns content instantly (3/3) — hence "intermittent-looking": short/simple filings occasionally finish reasoning within 600 tokens (the 4 CHALLENGE responses), long ones never do.
- Same reason Tier-0 (same model, short classify prompt, `max_tokens=400`) is untouched: 362/362 green.
- Production footprint since resume: **17 of 21 verifier calls (81%) starved**; per-day WARN counts 12/4/5/12 (Jul 7/8/9/10) — still active on the last trading day, i.e. **not resolved by anything currently deployed**.
- Knock-on: `_run_deepseek_as_analyst` (SOLO_DEEPSEEK, [ai_consensus.py:110-125](../utils/ai_consensus.py)) uses the same 600-token budget — the Anthropic-outage fallback would starve identically the day it is needed. (It fired 0 times this week; Haiku was 100% healthy.)

### 4.3 The solo-bar interaction

All 17 SOLO_HAIKU cases were refused: haircut confidences `[52, 52, 55, 61×13, 64]` vs floor 65 ([tier2_fundamental.py:361-375](../agents/tier2_fundamental.py)). The 61-cluster is raw Haiku confidence 68 × 0.9; the single 64 was raw 72 — one point short. Under the current bar, a solo trade needs raw conf ≥ 72.3, which Haiku produced 0 times in 4 days. **Consensus mode — the designed path — never got the chance**: verifier content arrived only 4 times, and all 4 were challenges.

### 4.4 Verdict: healthy filtering or avoidable bottleneck?

**Both, in sequence.** Stages 0-6 are healthy, deliberate filtering (335 of 343 analyzed filings die at gates that are working exactly as configured — liquidity, universe, analyst judgment). But the last arrow is an **avoidable structural bottleneck**: the verifier starvation converted every surviving candidate into either an auto-refused solo or was absent entirely. Honest counterfactual: with a healthy verifier, the 17 solo cases become consensus evaluations needing avg ≥65 + agreement + direction match; given the verifier's observed conservatism (its 4 responses were all challenges at conf 55-60), plausibly **0-3 trades** were actually lost this week. So zero trades is *mostly* explained by nothing-strong-enough — **but the system as deployed could not have traded even on a strong filing via consensus**, and it burned a week of the statistical-maturity clock (still n=3 resolved TIER2F) discovering that. That clock (July 4's "longest pole") is the real cost, and it keeps running until #1 is fixed.

---

## 5. Delta vs 2026-07-04 Audit

### Fixed since July 4 — verified live this session

| July 4 item | Commit | Live evidence |
|---|---|---|
| T2F-1 AI-SL RR-floor bypass (Exec #1) | `25dfcc7` | `enforce_live_rr_floor` wired at [tier2_fundamental.py:474-486](../agents/tier2_fundamental.py); percent-space check in [reward_risk.py:104-158](../utils/reward_risk.py); canary still UNFIRED (§4.1) |
| Money seams (Exec #2 a/b/c) | `e2715ea` + owner SQL | VOID guard `_void_failed_deploy` (:652-679); seam-c retry `_retry_failed_releases` ([update_paper_trades.py:328-377](../agents/update_paper_trades.py)); DB: `'VOID'` in status CHECK, `capital_release_failed` + `cost_rs` columns live |
| Fidelity trio (Exec #3) | `9a9969d` | P1-3 pessimistic `first_touch` (:75-98, :541-548); WAIT-boundary SL fills (:565-584); net-of-cost ledger release (:250-262). Untested by fire (0 closes) |
| Blanket-pytest live writes (Exec #4) | `13f585f` | (not re-tested this session; commit landed) |
| I-1 / P-1 / U-9 ops batch | `f7cbec4` | §2 item 6 |
| Guardian G-1 | `624bc0f` | §2 item 6 |
| tier2_signals hard-kill (audit §2.5) | `e227456` | §2 item 6 |
| Poller burst-eviction (post-audit discovery) | `884947a`+`a3f040b` | §1 #4 — production-validated |

### Still open — no change (do not re-propose as new)

Exec #5 learning loop (Phase 7 learning-half; pattern_insights frozen 2026-05-19) · statistical maturity (n=3, worsened in opportunity-cost terms by #1) · T0-4 evening hole / Phase 6 (fresh live evidence: 11 filings, §4.1) · P-3 30-min silent expiry (same 11) · P-2 at-most-once dispatch (superseded in mechanism by claim-model, residual risk now benign re-dispatch) · T2F-3 liquidity fail-open (bypass log exists since `8a223b9` Jun 13; no persistence) · T2F-5 no API retry on exceptions · U-4/U-5/U-6 (fabricated 0% on fetch-fail expiry, WAIT-zone semantics, calendar-day horizons) · F-1 pagination (§1 #5) · B1 unused · B7 zero · health-monitor/tier4 pagination time-bombs · I-4 no lockfile · I-7 Keys.txt · QuestDB dead writes.

### New findings this session

| # | Finding | Severity | Evidence |
|---|---|---|---|
| N-1 | Verifier `max_tokens=600` reasoning starvation — consensus mode structurally disabled; SOLO_DEEPSEEK fallback would starve identically | **HIGH** | §4.2 |
| N-2 | GH `schedule:` intraday under-firing (4-17%); Guardian/News have no cron-job.org primary → protection cadence ~4-5/day vs 30-min design | **MEDIUM** | §3.2 |
| N-3 | Post-market classification window (≈16:15-17:00 IST) produces dispatch candidates the poller never sees → silent expiry; 11 cases Jul 8-9 incl. score-10 KOTHARIPRO, score-8 ADVENZYMES/FORTIS/NILASPACES | **MEDIUM** (subset of T0-4/P-3, now with live counts) | §4.1 |
| N-4 | Portfolio snapshot: cancelled daily run = permanent equity-curve hole (no retry/backfill) | LOW | §2 item 2 |
| N-5 | `DEEPSEEK_BASE_URL` is dead config (hardcoded base_url) — harmless today, a trap during any endpoint migration | COSMETIC | [ai_consensus.py:25](../utils/ai_consensus.py) |
| N-6 | `.claude/settings.json` still allowlists unattended local execution of the live-writing updater | LOW (hygiene) | settings.json allow list |

---

## 6. Confidence & Limitations

- **Access:** all DB reads via `smb_audit_ro` (INSERT=false verified via `has_table_privilege`; `BYPASSRLS=true` so RLS hid nothing); Neon pooler rejects startup options, so read-only was enforced there via `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` + the role's own privileges. **Zero writes issued to any store.**
- **Secrets:** `gh secret list` → HTTP 403 (PAT lacks fine-grained secrets read). CI secret *values* therefore validated behaviorally (runs authenticate and respond), not by inspection.
- **Funnel completeness:** stage classification covers **all 365 successful runs** (one run initially mis-bucketed by a parse race was manually resolved to `illiquid` — counts in §4.1 include it). The 25 cancelled runs have no logs by nature; their impact is bounded exactly by the picked-vs-analyzed delta (22).
- **DeepSeek repro** used the local `.env` key with a synthetic-but-realistic context; production prompts vary in size, which is precisely what modulates the failure rate (observed 81% at the verifier).
- **No statistical claims:** resolved TIER2F sample is n=3 (expectancy −3.07%/trade, −0.61R per Tier-4's own run log) — reported for completeness, decision-useless at this n, matching the July 4 statistical-maturity stance.
- **Jul 11-12:** weekend; no trading-path activity expected and none observed beyond Saturday's NSE-500 sync (green).

---

*Investigation method note: 4-file parallel harvest of 390 Tier-2F run logs (deduped by run id) + 3 read-only DB passes (Supabase + Neon) + per-workflow `gh run list` aggregation + 2 controlled DeepSeek API probes (3 short-prompt, 3 verifier-sized). Every number in §4 cross-checks against at least one independent source (DB row counts vs log-derived counts vs run-conclusion counts). Report intentionally left uncommitted for owner review; working tree otherwise untouched.*

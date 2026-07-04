# StockMarket-Brain — Full System Deep Audit (Diagnosis Only)

**Date:** 2026-07-04 · **HEAD:** `7da30a9` (origin/main in sync) · **State:** FULLY PAUSED (sabhi 19 workflows `disabled_manually`, `gh workflow list` se live verify)
**Method:** Principal-engineer read-only audit — 4 parallel deep-read passes (ingestion / core-signal / lifecycle-money / infra-tests) + cross-cutting analysis. Har claim ke saath file:line evidence. **Koi code edit, git operation, DB write, ya DDL nahi hua.**
**Scope note:** Batch C reliability sprint (P2-7, P0-1, P3-11-iii, P2-13, P3-4, P3-8, P3-2, P3-9, P3-3, P1-8, P3-7, P3-10, P3-11 i/ii/iv, doc-debt) ke BAAD ka snapshot hai — jo fix ho chuka use dobara nahi ginwaya, sirf verify kiya.

---

## 1. Executive Summary

### Overall health grade: **B−**

| Dimension | Grade | Ek line mein |
|---|---|---|
| Architecture / design | A− | 5-tier separation, fail-open/fail-closed discipline, staged gates — genuinely well-designed |
| Batch-C reliability wins | B+ | Idempotent close (P2-7), atomic RPC (P0-1), mark-before-dispatch (P2-14), clean taxonomy (P3-4) — sab verified landed |
| Money-seam integrity | C | RPC ke andar atomic, lekin RPC ke *aas-paas* ke seams unguarded (§1 finding #2) |
| Paper-fidelity honesty | C+ | Teen independent optimistic biases ek hi direction mein (§1 finding #3) |
| Test / ops hygiene | D+ | Blanket pytest collection-time pe live capital writes karta hai (§1 finding #4) |
| Strategy validation maturity | D | Resolved TIER2F sample abhi bhi tiny; 55-65% win-rate target ka koi statistical evidence nahi — sirf wall-clock time isse fix karega |

### Top 5 findings

**#1 — AI-SL override RR-floor ko bypass karta hai (sabse material core bug).**
`validate_ai_signal` RR ko AI ke *shadow target* ke against check karta hai ([tier2_fundamental.py:157-161](../agents/tier2_fundamental.py)), lekin live trade ladder T1=6% pe exit karta hai jabki SL AI-blended (SL_CAP_PCT=10% tak, `:91`) ho jaata hai (`:446-449`). Concrete: blended SL 8% + blended target 14% → validator RR 1.75 PASS → live trade T1 6% / SL 8% → **effective live RR 0.75**, floor 1.5 ka aadha. `passes_rr_floor()` live TIER2F path mein kahin call nahi hota (callers sirf deprecated `tier2_signals.py:218` + tests). `USE_AI_SL="true"` prod mein ([tier2f.yml:40](../.github/workflows/tier2f.yml)). **Saving grace:** AI-SL canary ab tak UNFIRED hai (pause 06-13 se; aakhri TIER2F row id-162 pre-activation) — matlab abhi tak zero contaminated trades. Resume se pehle yeh band hona chahiye.

**#2 — Money-path RPC ke andar atomic hai, lekin seams unguarded hain (cash fabrication reachable).**
Teen linked holes:
- (a) Insert→deploy non-transactional: `paper_trades` insert (`tier2_fundamental.py:529`) commit hone ke baad `deploy_capital` (`:537`) bina try/except — RPC fail (insufficient cash / network) → **phantom OPEN trade jiska capital kabhi deduct nahi hua**.
- (b) `release_capital_atomic` mein **zero guards** ([p0-1_atomic_capital_rpc.sql:58-102](../sql/p0-1_atomic_capital_rpc.sql)): na `capital_deployed >= release` check, na matching-DEPLOY-ledger-row check, na `open_positions` floor. (a)+(b) milke: phantom trade close hote hi `release` **paisa mint karta hai** aur `capital_deployed` negative chala jaata hai.
- (c) Release-after-close failure = permanent leak: `_close_trade` status flip (`update_paper_trades.py:162-163`) ke baad `release_capital` (`:170`) bina try/except; `RuntimeError` ([capital_ledger.py:62](../utils/capital_ledger.py)) → trade ab non-OPEN hai toh koi future run release retry nahi karega, aur uncaught exception us run ke baaki trades bhi chhod deta hai.
Health checks 4+5 ([health_monitor.py:218-239](../agents/health_monitor.py)) yeh detect karte hain — lekin agli subah, aur repair manual hai. **Aaj ki taareekh mein identity rupee-tak holds** (2026-06-13 verified) — yeh corruption nahi, unguarded seams hain.

**#3 — Paper-fidelity mein teen optimistic biases, teeno ek hi taraf.**
- (i) **P1-3 target-before-SL abhi bhi open**: target pehle check hota hai (`update_paper_trades.py:336-339`), SL sirf `if not new_status` (`:342`). Gap-crash-then-rebound day = TARGET_HIT booked, jabki asli sequence pehle floor hit karta.
- (ii) **Optimistic SL fills**: wait-floor breach pe exit `active_sl` pe record hota hai (`:426`) jabki us din price demonstrably 4%-of-entry neeche trade hui.
- (iii) **Gross-of-cost equity**: `trade_costs.py` ka careful model **sirf reporting mein** lagta hai (sole consumer: `expectancy.py:14` → Tier-4 memory_text); portfolio equity, `pnl_rs`, ledger sab gross. Rs 25k position pe ~0.42-0.45% round-trip = winner edge ka ~7-11%.
Net effect: paper results live results ko systematically overstate karenge — validation-for-live ke goal ke against yeh sabse strategic risk hai.

**#4 — Blanket `pytest` collection time pe LIVE capital writes karta hai.**
`test_phase2.py` mein koi test function nahi — poora module-level code hai: collect karte hi `deploy_capital(None, ...)` (`:61`) aur `release_capital(...)` (`:98`) live portfolio pe chalte hain. Marker-gating kaafi nahi (import-time side effects). Upar se **naya bug**: [test_phase5_batchA.py:159](../tests/test_phase5_batchA.py) cleanup galat column `"deployed"` use karta hai (asli: `capital_deployed`) — live-insert test ke baad trade/ledger delete ho jaata hai par portfolio restore FAIL → **capital state inconsistent chhoot jaata hai**. `test_solo_clamp.py` bhi live `portfolio` read karta hai (`_mock_pipeline` mein `get_current_portfolio` unmocked; `load_dotenv(override=True)` at `tier2_fundamental.py:34` dummy env ko clobber kar deta hai).

**#5 — Learning loop structurally closed, operationally open.**
`trade_memory.memory_text` Tier-3 padhta hai ([tier3_position_manager.py:173-181](../agents/tier3_position_manager.py)) — lekin Tier-3 **advisory + post-hoc** hai: woh Tier-2F ke *complete hone ke baad* chalta hai (workflow_run), tab tak trade insert + capital deploy ho chuka hota hai; uske REJECT ka koi operational asar nahi (`tier3_decisions` ka ekmatra consumer Tier-4 hai — circular annotation loop). `trade_memory_v2` (Phase 7 capture) **strictly write-only** hai (writers: `tier2_fundamental.py:555`, `update_paper_trades.py:174`; readers: sirf seed scripts + tests). **Koi bhi rupee-moving decision memory नहीं padhta.** System har trade pe capture ka kharcha kar raha hai, consult zero.

---

## 2. Tier-by-Tier Findings

### 2.1 Tier-0 — Filing Ingestion (`agents/tier0_filings.py`)

**Purpose:** NSE announcements poll → DeepSeek classify → tradeable/liquidity/market gates → Telegram + Supabase `filings_log`.

**Current state:** 29-type enum `VALID_EVENT_TYPES` (`:33-40`) — prompt ([tier0_classify_v2.txt:11-13](../prompts/tier0_classify_v2.txt)) ke saath **exact sync**. Classify: `deepseek-v4-flash`, temp 0.3, max_tokens 400, 3 attempts, `extract_json` (P2-6) via `:135`, unknown types → OTHER coerce (`:137-139`), terminal failure → tombstone row (`:215-226`, infinite-retry prevention). Gates order: dedup (`:200`) → tradeable score ≥6 (`:228-233`) → liquidity ₹5Cr (`:236-240`) → market `size_multiplier==0` skip (`:243-246`). Dedup: dual-key (new `symbol|seq_id` `:79` vs legacy `:80`), `USE_NEW_DEDUP_KEY="true"` prod mein ([tier0-agent.yml:50](../.github/workflows/tier0-agent.yml)); 23505 race-tolerant insert (`:168-173`).

**Works well:** extract_json + retry + enum coercion + tombstone — robust classify path; Gate-B dual-hash canary logging (`:85-89`); 23505 tolerance.

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| T0-1 | Save-after-alert ordering: Telegram send (`:302`) ke baad save (`:328`) — non-23505 save failure → agle run pe **duplicate alert + re-classify** | `:302` vs `:328`, swallow `:329-330` | Medium |
| T0-2 | Legacy dedup key per-symbol collapse — `USE_NEW_DEDUP_KEY` env ke bina local run silently filings drop karega (code default `"false"`, `:20`) | `:80`, `:200` | Medium (latent) |
| T0-3 | Over-broad 23505 matcher: `"url_hash" in err` — NOT NULL violation bhi "benign duplicate" ban jaata hai, row silently lost | `:170` | Low |
| T0-4 | **Evening filings hole**: top-20 fetch (`:67`) + market-hours-only schedule — 17:00-21:00 IST earnings burst >20 filings top-20 se scroll-out → **permanently missed**. After-hours replacement (Phase 6) unbuilt | `:67`, tier0-agent.yml:10-11 | **High (strategic)** |
| T0-5 | emoji_map 13/29 keys — sirf **BULK_DEAL** reachable miss (score 8, gate paas karta hai); baaki 15 gate pe blocked; `📌` fallback cosmetic banata hai | `:185-190`, `:259` | Cosmetic |
| T0-6 | QuestDB writes CI mein dead — kisi workflow mein `QUESTDB_*` secrets nahi; `news_events` prod se kabhi populate nahi hua | [questdb_client.py:10-16](../utils/questdb_client.py), workflows grep | Low (silent) |

### 2.2 Tier-0F — Poller (`agents/tier0f_poller.py`)

**Purpose:** 2-min dispatcher — fresh material `filings_log` rows → per-filing `tier2f.yml` workflow_dispatch.

**Dispatch criteria chain (exact):** `is_material=true` AND `material_score>=6` AND `event_type!='OTHER'` (**P3-8 query-level, `:66`**) AND `picked_by_tier0f=false` AND `classified_at >= now−30min` [+ dormant B9 gate `trade_confidence>=60` sirf `USE_POLLER_CONFIDENCE_GATE=true` pe; prod `"false"` with shadow-logging `:74-84`] ORDER BY classified_at ASC LIMIT 10 (`BATCH_LIMIT`, `:29`). Phir per-row: **`_mark_picked` (`:173`) → `_dispatch_tier2f` (`:178`) → failure pe `_unmark_picked` rollback (`:185`)** — P2-14 ordering sahi laga hai (ek audit pass ne "mark after dispatch" kaha tha — woh function-definition lines ka misread tha; call-site order + runbook §3.4 dono mark-first confirm karte hain).

**Works well:** P2-14 failure mode ab "nothing dispatched, clean retry" hai; P3-8 tombstones ko Tier-2F se door rakhta hai; defense-in-depth (tier2f concurrency group + `uniq_paper_trades_ticker_date_source`).

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| P-1 | **Poller ka apna koi `concurrency:` group nahi** — 2-min cron-job.org + 10-min GH fallback overlap pe do concurrent runs same unpicked row dono padh sakte hain → double dispatch (downstream caps: duplicate trade impossible, wasted run possible) | workflows grep: groups sirf tier2f.yml:3 + update_paper_trades.yml:3 | Medium |
| P-2 | **At-most-once after 204**: dispatch accept hua par tier2f run fail (dep install / timeout 8-min) → row `picked=true` forever, koi retry nahi — **silent signal loss** | `:178-187` | Medium |
| P-3 | 30-min window = silent expiry: >30-min outage ke rows kabhi dispatch nahi honge aur backlog-check se bhi gayab | `:68` | Medium |
| P-4 | `_unmark_picked` khud fail ho jaaye → stuck row, log-only | `:142-144` | Low |
| P-5 | `GITHUB_PAT` missing → har cycle mark/unmark churn | `:91-93`, `:185` | Low |

### 2.3 Tier-1 — Guardian (`agents/tier1_guardian.py`)

**Purpose:** OPEN positions pe adverse/confirming news+filings scan (har 30 min, 08:30-19:00 IST), DeepSeek score −10…+10, EXIT ≤−7 / HOLD_STRONG ≥+7 alerts.

**Alert-only confirmed:** `paper_trades` pe sirf SELECT (`:149-152`); koi update/close/flag path nahi — trading path ke bahar hai. Batch-C fixes verified: P3-11-iv news window query-level `.gte("fetched_at", cutoff)` (`:168-173`); P2-11a `.NS` lookup (`:255-258`); P2-11b `_canonical_name` curated map + Neon fallback (`:102-132`); P2-11c NSE_FILING sirf filings hone pe (`:238-239`, `:461-464`).

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| G-1 | **Lone catastrophic filing kabhi alert nahi kar sakti** — filings ek hi source (`NSE_FILING`) mein collapse hoti hain aur `MIN_SOURCES_REQUIRED=2` (`:24`, `:426-429`); fraud/default filing bina same-4h news = 1 source → score se pehle skip. Protection layer ke liye **galat failure direction** | `:238-239`, `:426-429` | **High** |
| G-2 | Substring keyword filters: `"election"` ⊂ "selection", `"fire"` ⊂ "ceasefire" — genuine headline drop → suppressed EXIT alert | `:222-224`, `:28-34` | Medium |
| G-3 | Naive JSON handling (`json.loads` + fence-strip, `:304-306`) — P2-6 `extract_json` yahan apply nahi hua; prose-wrapped JSON → symbol skip for cycle | `:304-306` | Low |
| G-4 | Neon conn `close()` try ke andar, `finally` nahi — 4 call sites (`:119-129`, `:253-269`, `:327-341`, `:348-361`); gap_calculator ka P3-11-i standard yahan nahi laga | contrast [gap_calculator.py:60-65](../utils/gap_calculator.py) | Low |
| G-5 | Short-form names miss (L&T etc.) — curated 10 ke bahar weaker news recall | `:39-50`, `:99` | Low |

**Tier-1 News (`tier1_news.py`, brief):** blanket env-var strip sab env mutate karta hai (`:21-22`, multiline secret corrupt karega); duplicate-Telegram race (check-then-insert, no 23505 handler, `:47-63`); pre-P2-6 JSON parsing (`:119-129`); yml comment "offset 15 min from Tier-0" galat — cron set identical hai ([tier1_news.yml:6-9](../.github/workflows/tier1_news.yml)).

### 2.4 Tier-2F — Fundamental Agent (`agents/tier2_fundamental.py`) — CORE

**Pipeline (verified stage-by-stage):** filing load (`:180-184`) → F&O ban (`:187-190`) → liquidity HOTFIX-3 (`:193-196`) → Nifty500 via Neon (`:199-202`) → chart (`:205-211`) → NIFTY mood, BEARISH skip (`:214-233`) → price/volume dormant gates shadow-log (`:236-261`) → patterns + filing-memory brief (`:264-269`) → context (`:272-295`) → **Analyst Haiku 4.5** (`:305-316`; fail → `_run_deepseek_as_analyst` SOLO_DEEPSEEK; dono fail → clean skip) → **Verifier DeepSeek** (`:326-331`; fail → SOLO_HAIKU) → consensus / solo×0.9 vs floor 65 (`:337-356`) → disagreement log (`:360-362`) → clamp [50,85] HOTFIX-5 (`:394`) → conviction (`:640-649`) → **AI-SL blend** (`:401-436`; blend SL=max, target=conf-weighted) → ladder `generate_targets` (`:439-442`) → AI-SL override (`:445-449`) → sizing (`:454-462`) → insert `source='TIER2F'`, `raw_signal` **as dict** (`:490-534`) → `deploy_capital` RPC (`:537`) → memory capture (`:544-557`) → Telegram (`:560-572`).

**Flags:** `USE_AI_SL` def `:87` (default false) → **prod "true"** (tier2f.yml:40); `USE_PRICE_STRUCTURE_GATE` `:72` / `USE_VOLUME_GATE` `:77` → prod "false" (DORMANT, tier2f.yml:41-42); `TIER2F_TEST_MODE` `:67` unset ✓.

**HOTFIX-4 verified:** solo path pe koi KeyError risk nahi — `_safe_conf` (`ai_consensus.py:128-133`), None → SKIP. **HOTFIX-5 verified:** clamp `:394`; note — floor 50 practically dead hai (consensus/solo dono ≥65 maangte hain pehle), sirf ceiling 85 bind karta hai; side effect: Tier-3 ka `<50` reject TIER2F row pe kabhi fire nahi ho sakta. **P2-13 verified:** repo-wide sirf `:658` pe console print bacha hai; `raw_signal` (`:508-525`) + disagreement `full_context` (`:625-630`) plain dicts.

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| T2F-1 | **AI-SL RR-floor bypass** (Exec #1) — live (entry, AI-SL, ladder-T1) combo kabhi re-check nahi hota | `:157-161` vs `:445-449`, `:91` | **Critical (pre-resume)** |
| T2F-2 | **Insert→deploy non-atomic** (Exec #2a) — phantom OPEN trade possible | `:529` → `:537` | **High** |
| T2F-3 | Liquidity gate fail-OPEN on double network failure — yfinance outage pe HOTFIX-3 no-op, bypass persist nahi hota | [liquidity_check.py:42-44](../utils/liquidity_check.py) | High |
| T2F-4 | `determine_consensus` bracket-access KeyError: parsed-but-malformed analyst JSON (missing `directional_bias`) → uncaught crash at `:338` (fail-closed, lekin lost filing + red run) | [ai_consensus.py:144](../utils/ai_consensus.py) | Medium |
| T2F-5 | API-exception pe koi retry nahi — ek transient Anthropic 429 turant SOLO_DEEPSEEK + 0.9× haircut = trade economics badal jaate hain | ai_consensus.py:42 (`_retry_json` sirf empty/parse-fail retry karta hai) | Medium |
| T2F-6 | SELL trades unvalidated ladder pe — B2 validation long-only thi (RESULTS @5d), AI-SL BUY-only (`:407`) | [tiered_target_generator.py:4-8](../utils/tiered_target_generator.py) | Medium |
| T2F-7 | AI-SL eligibility truthiness: legit `stop_loss_pct: 0` silently AI-SL disable (benign-conservative, undocumented) | `:408-409` | Low |
| T2F-8 | Dead constant `AGREEMENT_THRESHOLD=70` (`:62`) — ai_consensus.py:141 ke literal se drift risk | `:62` | Cosmetic |

**Ladder note:** current ladder RR = 6/4 = **exactly 1.5 = floor, zero margin** — pass sirf inclusive-floor ki wajah se. Koi code path ladder ko floor ke against check nahi karta; future mein SL widen/T1 tighten silently floor ke neeche chala jayega. Conviction sirf T4 ke existence ko affect karta hai — HIGH/MEDIUM/LOW ko identical T1/T2/T3/SL milte hain.

### 2.5 Tier-2 — Signals Agent (`agents/tier2_signals.py`) — ORPHAN VERIFIED

- Deprecation notice module docstring `:1-12` mein — clear aur accurate (P1-8 scale gap documented).
- **Truly orphaned:** koi workflow reference nahi (`.github/` grep zero), koi prod import nahi (sirf `tests/test_tier2_questdb_write.py:14`).
- **Residual re-enable risk:** (a) live main guard `:239-247` — `python agents/tier2_signals.py` seedha production `paper_trades` insert karega (`:139-152`), 1-10 confidence (`:117`, `:145`), no source → default 'TIER2'; (b) **`.claude/settings.json:4-5,22` ab bhi ise allowlist karta hai** — bina prompt ke chal sakta hai. Blast radius: Tier-3 fail-closed reject (noise, not loss), lekin `paper_trades` pollute + updater OPEN scan mein aayega.
- **Recommendation:** main guard ko `sys.exit("DEPRECATED")` karo + settings.json allowlist entries hatao. (Deprecation notice akela kaafi nahi hai.)

### 2.6 Tier-3 — Position Manager (`agents/tier3_position_manager.py`)

**Trigger:** `workflow_run` on Tier-2F success + manual dispatch ([tier3_position_manager.yml:12-20](../.github/workflows/tier3_position_manager.yml)).

**Advisory + post-hoc confirmed:** capital Tier-3 ke fire hone se *pehle* deploy ho chuka hota hai; updater mein `tier3`/`approved` ka zero reference; `tier3_decisions` ka ekmatra consumer Tier-4 (`tier4_memory_manager.py:155`). REJECT = Telegram label + stats-scoping flag, aur kuch nahi.

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| T3-1 | **Source-blind fetch** (spotted #1 confirmed): `signal_date=today, status=OPEN`, koi source filter nahi. Old-date TIER2 rows date-filter se bach jaati hain, lekin same-day koi bhi source adjudicate ho jayega | `:139-147` | Medium |
| T3-2 | **Duplicate Telegram picks**: har Tier-2F completion pe din ke saare OPEN signals re-process; DB insert deduped (`:121-128`) lekin APPROVED pick message unconditional (`:246-247`) — multi-filing days pe guaranteed duplicate alerts + Claude re-billing | `:246-247` | Medium |
| T3-3 | **Hardcoded ₹25,000** pick message (`:99`), summary math (`:106`), `tier3_decisions.position_size` (`:240`) — asli `position_size_rs` row pe maujood hai, ignored | `:99,106,240` | Medium |
| T3-4 | Degraded prompt: TIER2F rows mein `reason`/`rsi`/`macd` NULL → "Reason: None | RSI: None"; verdict bias heavily-APPROVE (`:75-76`); prompt 1-10 maangta hai jabki display /100 (`:59` vs `:73`) | `:60-61` | Medium |

### 2.7 Tier-4 — Memory Manager (`agents/tier4_memory_manager.py`)

**P3-7 verified:** scope `["TARGET_HIT","SL_HIT","EXPIRED"]` (`:154-161`), EXPIRED apna bucket (`:22-28`), win% decisive W+L pe hi (`:54-58`), legend explicit (`:67`). Expectancy `source='TIER2F'`-scoped (`:183-190`), legacy 33 TIER2 rows excluded by design.

**Gaps / risks:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| T4-1 | **Selection bias**: breakdown `approved=True`-scoped (`:157`) — Tier-3-rejected trades (jo phir bhi execute hue, kyunki advisory) memory se gayab; LLM apne rejections ki correctness kabhi nahi seekh sakta | `:154-161` | Medium |
| T4-2 | Do disagreeing win-rates ek document mein: status-based (breakdown) vs pnl-sign-based (expectancy, [expectancy.py:6-9](../utils/expectancy.py)) — LLM consumer conflate kar sakta hai | `:52-59` vs `:98-144` | Low |
| T4-3 | `confidence_tier2` raw /100 integer granularity pe bucket — values spread hote hi perpetually "insufficient data"; banding chahiye | `:30-31` | Low |
| T4-4 | No pagination guard — PostgREST ~1000-row cap pe silent truncation (future) | `:154-161`, `:183-190` | Low (future) |

**Learning loop verdict:** Exec #5 dekho — memory → Tier-3 advisory → stats → memory ka circular annotation loop hai; **rupee-moving decisions tak koi current nahi pahunchta**. Phase 7 learning-half (trade_memory_v2 retrieval at Tier-2F signal time) is cluster ka single highest-leverage open item hai.

### 2.8 Updater — Trade Lifecycle (`agents/update_paper_trades.py`)

**Verified working:** HOTFIX-1 airtight (`must_expire` at `:250` fetch se pehle; WAIT holds `and not must_expire` `:349`, `:365`); HOTFIX-2 day-0 LTP-only guard `signal_generated_at` IST-based (`:317-329`); P2-7 idempotent close — `.eq("status","OPEN")` conditional UPDATE, loser `return None` before release (`:162-170`); `_close_trade` single funnel (`:131-175`); teen hi terminal statuses; DRY_RUN discipline consistent.

**Gaps / risks (Batch-C ke baad bhi):**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| U-1 | **P1-3 target-before-SL intrabar optimism OPEN** (Exec #3-i) | `:336-342` | **High (fidelity)** |
| U-2 | **Release-failure = permanent leak + aborted run** (Exec #2c) | `:162-170` + capital_ledger.py:62 | **High** |
| U-3 | **Release-without-deploy possible** (Exec #2b ke saath) — sirf `qty is not None` gate (`:169`) | `:169-172` | High |
| U-4 | Fabricated 0% P&L on fetch-fail expiry (Q11=a): genuinely −8% trade 0.0% record hota hai → BE bucket → expectancy se excluded ([expectancy.py:81-87](../utils/expectancy.py)) → **correlated upward bias** | `:260-261` | Medium |
| U-5 | WAIT zone gap-specific nahi hai — slow orderly drift bhi hold hota hai; effective stop = SL − 4%-of-entry; breach pe optimistic fill at `active_sl` | `:343-357`, `:426` | Medium |
| U-6 | **P2-12 calendar-day horizons OPEN**: `(now−signal_date).days` (`:245`) — Friday SHORT-horizon signal Monday ko ~1 trading day mein expire; weekend ke paas windows 30-60% compressed | `:245`, docstring `:66` | Medium |
| U-7 | Partial-API silent degradation: Yahoo hi/lo absent → LTP collapse (`:104-105`) — unplanned LTP-only mode, no log marker | `:104-105` | Low |
| U-8 | Ladder split-brain: generator `t2=1.08/t3=1.10` store karta hai, T1-upgrade unhe 1.10/1.15 se overwrite karta hai (`:202`, `:211`; intentional per efc2529, test-locked) — pre-T1 readers ko aise numbers dikhte hain jo engine kabhi honor nahi karega; dead `EQ_T1=1.05` (`:37`) | `:202,211,37` | Low |
| U-9 | **Koi Telegram close alerts nahi** — closes/upgrades/expiries silent; visibility sirf next-morning summary | file grep: zero telegram refs | Medium (ops) |
| U-10 | Import-order fragility: `capital_ledger` ka module-level `sb = get_client()` (`capital_ledger.py:7`) is module ke friendly FATAL handler se pehle chal jaata hai | `:24` vs `:72-76` | Low |

---

## 3. Infrastructure & Utilities

### 3.1 Capital & money (post-P0-1)

- **RPC path verified:** deploy/release dono ab pure RPC wrappers ([capital_ledger.py:39-46, :55-62](../utils/capital_ledger.py)) — Python RMW gone. RPC mein `FOR UPDATE` row lock, NUMERIC + ROUND (P3-11-iii), ledger row + portfolio update same transaction, `total_equity` dono paths pe derived (sql `:46`, `:90`) — **identity atomic by construction**.
- **Lekin:** deploy mein insufficient-cash guard hai (sql `:29-34`), **release mein zero guards** (Exec #2b). Idempotence poori tarah upstream P2-7 pe depend karti hai — direct double-call double-credits.
- `ORDER BY id DESC LIMIT 1 FOR UPDATE` "live row" ko convention se pin karta hai — stray manual `portfolio` insert saara future money movement retarget kar dega (sql `:23`, `:71`).

### 3.2 Calculation utilities

- **gap_calculator.py:** DEFAULT_GAPS 18 keys (P3-4 post); **SL sign bug**: `_calculate_levels` (`:76-85`) hamesha `stop_loss_pct = -abs(gap)` — LEGAL (−2.0, tradeable) ke liye stop == aggressive entry, same side as target. Tier-0 ka opposite-sign R:R check (`tier0_filings.py:290-293`) ise silently mask karta hai. Conn hygiene correct (`finally`, `:60-65` — P3-11-i standard).
- **tradeable_score.py:** 29/29 enum match, threshold 6, unknown → 3 fail-closed. Clean. Note: scores hand-set hain, B2-callibration pending.
- **trade_costs.py:** genuinely careful NSE delivery model (GST base sahi, DP no-double-GST, buy-only stamp); **sirf reporting mein applied** (Exec #3-iii). `SLIPPAGE_PCT=0.10%/side` uncalibrated — filing-driven mid/small-caps mein zyada hoga.
- **expectancy.py:** sign-based classification (P3-7 coherent); **BE-exclusion bias** — U-4 ke fabricated 0% rows denominator se gayab → |expectancy| overstated. R-multiple signal-time stop use karta hai (standard, documented rahe).
- **json_extract.py (P2-6):** greedy `\{.*\}` DOTALL + failed-path-only `{{}}` salvage — nested JSON kabhi corrupt nahi hota. Callers: tier0 + ai_consensus. Guardian/tier1_news/after-hours abhi bhi pre-P2-6 hand-rolled parsing pe hain.
- **position_sizer.py:** RISK_PCT=0.00125, MAX_TRADE_PCT=0.025, buffer 20% — pure math, no bug. Note: koi max-concurrent-positions cap nahi (sirf ~32-position cash ceiling); AI-SL wide stops = smaller-but-worse-RR trades (T2F-1 ke saath compounding).

### 3.3 Workflows (19) — trigger map

```
INGESTION:  cron-job.org 5-min → tier0-agent (GH fallback: merged 15-min crons)
TRADE:      cron-job.org 2-min → tier0f-poller (GH fallback */10) → GitHub API dispatch
            → tier2f (concurrency: tier2f-capital, dispatch-only, filing_id input)
            → (workflow_run) tier3_position_manager
LIFECYCLE:  cron-job.org 5-min 08:30-16:25 IST → update_paper_trades (concurrency: updater-run)
            ⚠ KOI GH FALLBACK NAHI — single point of failure
NIGHTLY:    tier4 21:00 IST · filings_log_backfill 20:00 → filing-memory-backfill 00:30
            · daily_summary 08:00 · health_monitor 09:00 + hourly 10-15 · snapshot 16:00 · sync_nse500 Sun
ZOMBIES ✓:  preopen_alert (P3-5 verified de-scheduled), nifty500_loader (P2-10 ✓),
            after_hours_watcher (deprecated ✓), historical_preloader (dispatch-only)
```

**Infra gaps:**
| # | Finding | Evidence | Severity |
|---|---|---|---|
| I-1 | **Updater ka koi GH `schedule:` fallback nahi** — trade-closing workflow cron-job.org pe SPOF; poller/tier0 dono ke paas fallback hai, isike paas nahi | update_paper_trades.yml:7-8 | **High (ops)** |
| I-2 | Poller no concurrency group (P-1 dekho) | tier0f-poller.yml | Medium |
| I-3 | Cron/comment drift ×4: tier4 comment "20:30 IST" vs actual 21:00 (`30 15 UTC`); tier1_news "offset" jhooth; tier0 "~30-min" stale; filing-memory-sync window comment galat | tier4_memory_manager.yml:8, tier1_news.yml:6-9, tier0-agent.yml:6, filing-memory-sync.yml:6 | Low |
| I-4 | requirements.txt floor-pinned (`>=`) only, no lockfile — evidence: floor `yfinance>=0.2.40` vs installed 1.3.0; `historical_preloader.yml:20` ad-hoc dep subset install karta hai; pytest requirements mein hi nahi | requirements.txt:1-28 | Medium |
| I-5 | 6 workflows bina `timeout-minutes` → hang pe 360-min default | tier0-agent, tier1_news, tier1_guardian, filing-memory ×3 | Low |
| I-6 | Supabase live tables ka koi in-repo DDL nahi; ulta `sql/schema_v1.sql` ek **legacy QuestDB** `paper_trades` define karta hai (naam-collision, alag shape) — documentation trap; `sql/fundamental_signals_schema.sql` orphaned (zero refs) | sql/schema_v1.sql:2-18 | Medium |
| I-7 | `agents/Keys.txt` disk pe (gitignored) — plaintext secrets file working tree mein; workflows secrets ko runner `.env` mein echo karte hain (standard, par artifact-upload se door rahe) | .gitignore:87 | Medium (hygiene) |

### 3.4 Tests — blanket pytest verdict: **UNSAFE**

| Class | Files |
|---|---|
| **LIVE-WRITE at collection** | test_phase2.py (deploy `:61`, release `:98`, portfolio update `:186-193`) |
| **LIVE at import** (reads/HTTP) | test_phase3_batchA (yfinance+NSE), test_phase3_batchB (Neon), test_phase4_batchA/B (Supabase) |
| **LIVE unmarked at run** | test_phase5_batchA (**real insert + capital deploy + real API spend** `:112`; **cleanup bug `:159` — `"deployed"` vs `capital_deployed` → portfolio restore fail**), test_phase5_batchB (real poller run) |
| **LIVE marked** | test_tier2f_insert_integration (`@pytest.mark.integration` ×3 — lekin koi pytest.ini nahi, toh yeh bhi default chalta hai) |
| **1 live read** | test_solo_clamp (`get_current_portfolio` unmocked; `load_dotenv(override=True)` dummy env clobber) |
| **PURE-UNIT (18 files)** | supabase/telegram/questdb-mocked ×4, price/volume/rr/costs/expectancy/json ×6, force_expire/pnl/close_expired/trailing ×4, daily_summary/health_monitor/trade_memory_writer ×3, tier3/tier4 (lazy clients) |

**Root cause:** phase2-4 files pytest tests nahi, **verification scripts** hain (`python tests/test_phase2.py` ke liye likhe gaye) — `test_` prefix collection-dangerous banata hai. Marker deselection unhe protect nahi kar sakta (import-time execution). **Single fix:** env-gated `collect_ignore` conftest mein + root `pytest.ini` with `addopts = -m "not integration"` + phase5A column bug + solo_clamp mock. (~30 min, highest-leverage safety fix in repo.)

### 3.5 Schema map (code-reference se)

- **Supabase (13 tables):** paper_trades, filings_log, portfolio, capital_ledger, filing_memory, trade_memory_v2, trade_memory (v1), pattern_insights, news_log, tier3_decisions, agent_disagreements, paper_trades_queue, portfolio_snapshots.
- **Neon:** company_profiles, research_cache, event_outcomes, pattern_library, tier1_guardian_alerts, after_hours_queue (dep.), nse500_watchlist, nse500_membership, (dep.) Neon-side filings_log — after_hours_watcher isi mismatch se mara tha.
- **QuestDB:** news_events, signals — **CI mein kabhi populate nahi hue** (T0-6): decide karo — provision karo ya 4 dead write paths strip karo.

---

## 4. Plan vs Reality (v3.1 master plan + backbone)

| Item | Plan | Reality @ 7da30a9 | Status |
|---|---|---|---|
| Phase 0-5 (Tier-0 v2 → real-time engine) | §3-§7 | Shipped + Batch A/B/C hardened; consensus §7.3 as designed; Tier-3 (ticker,source) dup-rule implemented (`tier3_position_manager.py:25-29`) | **DONE** |
| Position sizing | RISK 2% / MAX 12% (§5.2) | RISK 0.125% / MAX 2.5% ([position_sizer.py:38-40](../utils/position_sizer.py)) — deliberate conservative divergence, documented | DONE (diverged, fine) |
| Phase 6 — After-Hours engine | §8: after_hours_v2 + executor | **Koi file exist nahi karti**; old watcher deprecated; **evening ingestion hole open (T0-4)** — plan ka "core trading edge" abhi bhi unbuilt | **NOT STARTED** |
| Phase 7 — Tier-4F orchestrator | §9: capture + nightly extraction + injection | Capture-half SHIPPED (4eab182: trade_memory_writer + close backfill); **learning-half NOT built** — koi tier4f_nightly.py nahi, `pattern_insights` seed ke baad se **static** (koi nightly refresh nahi), disagreement backtest (§9.3.5) unbuilt | **HALF** |
| Phase 8 — Integration + monitoring | §10 | health_monitor 6-checks + hourly (P2-8 fixed ✓), daily_summary, snapshots shipped; E2E "tests" = dangerous phase-gate scripts (§3.4) | MOSTLY DONE |
| B1 Survivorship | membership table + filtered reseed | Sirf `scripts/backfill_membership.py` tracked (P3-10); `sync_nse500.py` mein membership append **nahi**, `memory_seed.py` mein filter **nahi**, exit-schema (Q6) undecided | **BARELY STARTED** |
| B2 Event-study backtest | scripts/event_study.py | SHIPPED (28f6270, scope 1+2) → HOTFIX-6 ladder isi se aaya | **DONE** |
| B6 Point-in-time alpha | — | DONE (e02c962) | DONE |
| B7 Regime thresholds | ±3% regime-conditional | **Zero code references** repo-wide | **NOT STARTED** |
| §15 pattern_library rebuild | filing_memory se rebuild after ~3mo matured | Not done — gap_calculator abhi bhi 17-row pattern_library + DEFAULT_GAPS pe | NOT STARTED |
| P2-12 trading-day horizons | Q8 decision | OPEN — calendar days (`update_paper_trades.py:245`) | OPEN |

**Sabse badi plan-vs-reality tension:** plan ka §8 after-hours ko "the core trading edge" kehta hai, aur woh + learning-half dono unbuilt hain — jabki reliability sprint (jo zaroori tha) poora ho chuka. Ab strategic backlog reliability backlog se bada hai.

---

## 5. Config Health & Skills/Automation Opportunities

### 5.1 CLAUDE.md & config

| Item | Issue | Action |
|---|---|---|
| Double-JSON GOTCHA | **STALE post-P2-13** — code mein sirf `:658` console print; nuance: **pre-P2-13 DB rows abhi bhi string-scalars hain** jab tak one-time decode migration na ho — GOTCHA ko "historical rows only" mein rewrite karo | Doc fix |
| "Where things live" line refs | "AI-SL blend :379-486", "USE_AI_SL :87" — P2-13 edits ke baad drift; "Verified 2026-06-01" ab month+ stale | Doc refresh |
| Memory file `tier2f_ai_sl_canary` | Double-encoding note stale (same nuance) | Memory update |
| `.claude/settings.json:4-5,22` | Deprecated `tier2_signals.py` ab bhi execution-allowlisted | Remove entries |
| **Missing rule #1** | "NEVER blanket `pytest` — sirf targeted files ya `pytest -m 'not integration'` after the conftest gate" — yeh rule aaj ke sabse khatarnaak footgun ko cover karta | Add to CLAUDE.md |
| **Missing rule #2** | "Updater ka trigger sirf cron-job.org hai — GH fallback NAHI hai" (resume sessions ke liye critical) | Add |
| Workflow comments | I-3 ke 4 drifts | Fix when touching |

### 5.2 Skills & automation candidates

| Candidate | Type | Verdict |
|---|---|---|
| **Staged-resume skill** — runbook ko interactive skill banao: layer-by-layer enable + canary queries + GO/NO-GO prompts + rollback commands | New skill | **HIGH value** — resume ek high-stakes, checklist-heavy, repeatable workflow hai; runbook already likha hua hai, skill sirf usse executable banayegi |
| **Bug-investigation skill** — pattern jo Batch C mein baar-baar chala: audit finding → graphify/Serena se callers map → fix propose → per-edit approval → targeted test → commit+push | New skill | HIGH value — 30+ P-items isi loop se nikle; formalize karne se har fix ki quality consistent hogi |
| **HOTFIX containment skill** — disable trigger → fix → unit test → canary → rollback-plan template | New skill (ya bug-investigation ka section) | Medium — kam frequent, but high-stakes |
| **gap-auditor weekly automation** | Automation (schedule cloud routine) | Paused state mein manual hi theek; **resume ke baad weekly schedule karo** — nightly zyada hai |
| **Doc-drift checker** — post-commit hook (graphify already rebuilds) se CLAUDE.md ke `file:line` refs validate karna | Automation | Medium — Batch C ke doc-debt ka root cause yahi tha |
| Telegram close alerts, pytest gate, emoji fill | Plain fixes | Skill nahi chahiye |

---

## 6. The 9 Spotted Issues — Re-graded

| # | Issue | Verdict | Severity | Action |
|---|---|---|---|---|
| 1 | Tier-3 source-blind fetch (`:139-147`) | **CONFIRMED** — plus duplicate-Telegram (T3-2) aur hardcoded ₹25k (T3-3) same file mein | Medium | **Fix** (3 small edits ek saath) |
| 2 | test_phase2 module-level live writes | **CONFIRMED — worse than spotted**: collection-time `deploy_capital` | **High** | **Fix now** (collect_ignore + rename to scripts/verify_*) |
| 3 | test_solo_clamp live portfolio read | **CONFIRMED** — `get_current_portfolio` (`tier2_fundamental.py:454`) dry-run exit (`:467`) se *pehle*; dotenv override dummies ko maar deta hai | Low-Med | **Fix** (ek mock add) |
| 4 | CLAUDE.md double-json GOTCHA stale | **CONFIRMED stale** — nuance: historical rows abhi bhi encoded | Low | **Doc fix** |
| 5 | after_hours_watcher LLM validation gap | **CONFIRMED** (`:123-139` bare loads; stale 13-type enum `:131`; string-confidence TypeError **DB-write ke baad** `:254-255`) | Low now (de-scheduled) / High if salvaged | **Nothing now**; Phase 6 = rebuild-not-salvage (mandate likh do) |
| 6 | CREDIT_RATING vs RATING_ACTION merge | Deliberate duplicate, 4 jagah sync, dono score 5 (<6) = **behavior-neutral** | Cosmetic | **Nothing** (classify-time consolidation kabhi future mein) |
| 7 | emoji_map missing types | 16 missing, **sirf BULK_DEAL reachable**; `📌` fallback covers | Cosmetic | Fix opportunistically (one line) |
| 8 | after_hours is_duplicate f-string SQL | **Not injectable as written** (md5 hex charset); asli problem: `neon_client.query()` mein param support hi nahi (`neon_client.py:48-55`) — pattern hazard | Low | **Nothing now**; Phase 6 start pe `query(sql, params)` add karo |
| 9 | pytest blanket-run unsafe | **CONFIRMED + naya bug** (phase5A `:159` wrong column → live portfolio inconsistent after test) | **High** | **Fix now** (spotted #2 ke saath ek package) |

---

## 7. Live-Trading Readiness Gap

Motive = paper-validation → live readiness. Us goal ke against dimension-wise:

| Dimension | State | Gap |
|---|---|---|
| **Cost honesty** | Weak | Model exists, sirf reporting mein; equity/pnl_rs/ledger gross. Fix: `cost_rs` per trade at close store karo (exact computable) |
| **Survivorship** | Weak | B1 barely started; memory seed unfiltered — historical patterns survivorship-biased ho sakte hain |
| **Look-ahead** | Moderate | Day-0 fixed (HOTFIX-2 ✓), B6 point-in-time ✓; lekin P1-3 intrabar optimism + optimistic SL fills open |
| **Liquidity reality** | Moderate-weak | ₹5Cr gate in path (HOTFIX-3 ✓) par fail-open on outage, bypass unlogged; slippage flat 0.10% uncalibrated |
| **Reward:risk** | Weak until T2F-1 fixed | Ladder exactly-at-floor (zero margin); AI-SL bypass hole live flag ke peeche |
| **Statistical maturity** | **Very weak (longest pole)** | Resolved TIER2F sample tiny (n<20 preliminary flag hamesha on); 55-65% target ke liye **≥100 resolved trades across regimes** chahiye — sirf calendar time isse fix karta hai, aur system 3+ hafte paused hai |
| **Execution fidelity** | Weak | 5-min polling, unauthenticated Yahoo single-source, no MTM (equity closes pe hi step karti hai — drawdown understated), no Telegram close visibility |
| **Ops robustness** | Moderate | Monitors achhe (6 checks, hourly); lekin updater SPOF (I-1), poller races (P-1/P-2), health-monitor pagination time-bomb ([health_monitor.py:302, :313-314](../agents/health_monitor.py)) |

**Real money se pehle MUST-TRUE list (minimum):**
1. RR floor live (entry, SL, T1) combo pe enforced — har trade, har path.
2. Money-seam invariants: deploy-fail compensation, release guards RPC mein, release-retry mechanism.
3. Pessimistic (ya at-least flagged) intrabar policy + realistic SL fills.
4. Net-of-cost equity + calibrated slippage.
5. ≥100 resolved trades, positive **net** expectancy, ≥2 market regimes.
6. Survivorship-clean memory (B1 complete).
7. Redundant updater trigger + kill-switch + auto-reconciliation repair.
8. Broker-grade data feed (Upstox live phase) + MTM.

Abhi ~2/8. Yeh theek hai — system ka current job paper-data generate karna hai, live jaana nahi. Lekin #1-#3 ke bina generate hua paper-data bhi biased hoga — isliye woh resume se *pehle* aane chahiye.

---

## 8. Prioritized Recommendations (leverage-ranked)

| Rank | Item | Type | Effort | Why this rank |
|---|---|---|---|---|
| 1 | **T2F-1: RR floor after AI-SL override** — ek `passes_rr_floor(entry, final_sl, t1, direction)` call `:451` se pehle; fail → ladder SL pe fallback (ya skip) | Fix | ~1h + test | Canary UNFIRED hai — abhi fix karo toh zero contaminated data; resume ke baad har din delay = potentially bad trades |
| 2 | **Test-safety package**: conftest `collect_ignore` (env-gated) + root pytest.ini + phase5A `"deployed"`→`capital_deployed` + solo_clamp mock + CLAUDE.md rule | Fix | ~30-45 min | Ek galat `pytest` LIVE portfolio corrupt kar sakta hai — paused state mein bhi |
| 3 | **Money-seam guards**: (a) `deploy_capital` try/except + VOID compensation (`tier2_fundamental.py:537`); (b) release RPC guards (deployed≥release, DEPLOY-row-exists, floors); (c) `_close_trade` release try/except + `RELEASE_FAILED` marker for retry | Fix | ~half day | Cash-fabrication + permanent-leak paths band; health checks detect→prevent upgrade |
| 4 | **Fidelity trio**: P1-3 pessimistic/flagged intrabar (1-min series already fetched hai — sirf meta use hota hai), SL-fill realism, `cost_rs` per close | Fix | ~1 day | Validation-quality data ke bina paper trading ka maksad hi adhura |
| 5 | **Ops small-batch**: updater GH cron fallback (I-1), poller concurrency group (P-1), Telegram close alerts (U-9), liquidity-bypass logging (T2F-3) | Fix | ~half day | Cheap insurance, resume-prerequisites |
| 6 | **Phase 7 learning-half** — trade_memory_v2 retrieval at Tier-2F signal time + nightly pattern refresh | Backbone | days | Sabse bada strategic unlock — but needs resolved-trade volume, so resume ke baad |
| 7 | **B1 completion** (membership append → exit schema Q6 → filtered reseed sequence) | Backbone | days | Memory-trust prerequisite; historical-learning se pehle zaroori |
| 8 | **Staged-resume skill** (runbook → interactive) + **bug-investigation skill** | New skill | ~half day each | Process leverage — har future fix/resume consistent |
| 9 | **gap-auditor weekly schedule** post-resume; doc-drift checker | Automation | small | Toil reduction |
| 10 | Guardian G-1 (single catastrophic filing bypass: material_score≥8 filing = own source) + G-2 word-boundary keywords | Fix | ~2h | Protection-layer correctness — resume ke baad jaldi |
| 11 | tier2_signals hard-kill (main guard sys.exit + settings.json allowlist removal), Keys.txt relocation, requirements lockfile, QuestDB decide-or-strip, SQL-file cleanup (I-6) | Hygiene | small each | Batch mein jab convenient |
| 12 | CREDIT_RATING merge, emoji fill beyond BULK_DEAL, f-string SQL param support | Nothing now | — | Behavior-neutral ya deprecated-path items |

---

## 9. Recommended Next Milestone

**Single highest-conviction call: "Batch D — Money-Integrity & Fidelity" (recos #1-#5, ~2-3 focused days) → phir staged resume per runbook → B1 parallel mein.**

Reasoning:
1. **Statistical maturity longest pole hai aur sirf wall-clock se fix hoti hai.** Har paused hafta n≥100 resolved-trades milestone ko ek hafta aage dhakelta hai. Isliye resume jaldi hona chahiye — B1/Phase-6 jaise multi-day backbone ke *peeche* nahi.
2. **Lekin aaj resume karna galat hoga.** USE_AI_SL live hai aur canary unfired — pehla hi post-resume TIER2F signal RR-0.75-class trade ho sakta hai (T2F-1). Aur P1-3 + optimistic fills + gross equity ka matlab: jo data aayega woh systematically flattering hoga — validation ke liye आधा-useless. 2-3 din ka Batch D yeh dono problems band karta hai.
3. **Test-safety Batch D ka hissa isliye hai** kyunki woh ek standing live-corruption risk hai jo kisi bhi din fire ho sakta hai — resume se unrelated.
4. B1 important hai par memory-*trust* issue hai, trade-*correctness* issue nahi — woh resume ke baad evenings mein ho sakta hai. Phase 7 learning-half ko resolved-trade volume chahiye — resume uska prerequisite hai, successor nahi.
5. Resume khud runbook ke §6 order se hi ho (monitors → memory → Tier-0 → updater → poller LAST), updater ke cron-job.org PRE-STEP ke saath — aur ideally staged-resume skill ke through, taaki canary discipline enforce ho.

Ek line mein: **pehle paise ka darwaza theek karo (Batch D), phir machine chalao (staged resume), phir use smart banao (B1 + Phase 7 learning-half).**

---

*Audit method note: 4 parallel read-only passes + primary-auditor cross-verification (Tier-3 fetch, P2-13 grep, pause state via `gh`, backbone greps, P2-14 order-conflict resolution). Ek sub-agent ka "mark-after-dispatch" claim call-site evidence (`tier0f_poller.py:173` vs `:178`) + runbook §3.4 se REJECT hua — report mein corrected version hai. Report file intentionally uncommitted (owner review first).*

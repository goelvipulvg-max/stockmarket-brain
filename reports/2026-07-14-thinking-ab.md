# O-3 Thinking A/B — Did the N-1 Config Choice Change the Verifier's Temperament?

**Date:** 2026-07-14 (evening session)
**Mode:** READ-ONLY, OFFLINE (no code/config/prompt changes, no DB writes, no dispatches; 20 DeepSeek probe calls)
**Continuity:** executes option **O-3** from [2026-07-14-consensus-calibration.md](2026-07-14-consensus-calibration.md) (verdict (b)); also references the [Jul-12](2026-07-12-current-scenario-report.md) N-1 root-cause report.
**Question:** does `thinking: enabled` + `max_tokens 4000` (the alternative N-1 remedy) produce a materially different verifier temperament than production's `thinking: disabled` + `max_tokens 2500` — on identical inputs?

---

## 0. Executive verdict — **(a): no material outcome difference. N-1 is exonerated as the cause of the drought — and the May→July temperament shift is real but was never ours to control.**

- **Zero decision changes.** All 9 archived post-resume cases end in SKIP under both arms. Arm B flipped one verdict (EMCURE → CONFIRM/80/BULLISH/65) — and it *still* skipped, on avg confidence 63.5 < 65. Re-enabling thinking would not have produced a single trade this month.
- **Arm B is not systematically more agreeable — it is more *dispersed*.** Mean agreement moves +6.7 points (41.7 → 48.3), but 4 of 9 cases moved *down*; the spread widens from 40–45 (σ≈2.4) to 30–80 (σ≈17). Thinking buys differentiated judgments, not friendlier ones.
- **The GILLETTE control killed yesterday's cleanest hypothesis.** The May-27 case that production CONFIRMed at agreement 85 (trade id 161) returns CHALLENGE under *both* arms today (Arm A: 40/40; Arm B: 40, 25). The thinking flag does not restore May behavior — so the config choice in commit 2e51d83 is **not** what moved the temperament.
- **What did move it: almost certainly server-side model drift.** Independent evidence already on record: in May, verifier calls succeeded inside a 600-token completion budget ([Jul-12 report §4.2](2026-07-12-current-scenario-report.md) — starvation began only in July); today, the same model burns 480–1,271 *reasoning* tokens on every thinking call (measured, §2). A May `deepseek-v4-flash` that fit in 600 tokens was not doing today's reasoning. The serving stack behind the alias changed somewhere between May 29 and Jul 7; our prompts, model string, and (in May) call parameters did not.
- **Arm B is technically viable** (0/11 starvations at max_tokens 4000; headroom 2,609+ tokens) — verdict (c) is ruled out — but it costs ~7× completion tokens and ~5× latency for zero decision benefit on this sample.

**Bottom line for the decision you asked me not to make:** there is no temperament argument *or* trade-production argument for switching to Arm B. The knob you were considering does not connect to the gate. The new, actionable fact is drift itself — the verifier's temperament changed once without any commit, and can change again silently (§5.3).

---

## 1. Part 1 — Rebuilding the 9 archived contexts

### 1.1 What was reproduced exactly vs approximately

**Exact (bit-for-bit with what production used):**
- **Analyst outputs:** the stored Haiku JSON from `agent_disagreements.full_context.haiku` (ids 31–39) — all 8 fields present for all 9 rows. The analyst never re-ran; the A/B isolates the verifier call as the only variable between arms.
- **Filing rows:** the full `filings_log` rows production loaded into `context["filing"]` ([tier2_fundamental.py:183-186, :313](../agents/tier2_fundamental.py#L183)).
- **Fundamentals:** Neon `company_profiles` (sector / market_cap_cr / business_summary) — `last_updated` 2026-05-09 for all 9 symbols, i.e. unchanged since before the eval dates.
- **Patterns:** `pattern_insights` is frozen (`max(extracted_at)` = 2026-05-19), so the retriever replica — including its multi-word-sector no-match quirk (`"basic materials"` never matches `"basic_materials"`; [pattern_insights_retriever.py:31-35](../utils/pattern_insights_retriever.py#L31-L35)) — returns exactly what production saw.
- **Gate logic:** `determine_consensus` imported from [utils/ai_consensus.py:148](../utils/ai_consensus.py#L148), not reimplemented. Production code untouched (throwaway harness in scratchpad: `ab_harness.py`).

**Approximate (disclosed):**
- **Charts:** rebuilt as-of the eval date by truncating a 2-year yfinance window at the last session production could have seen (id 33 ran 08:36 IST pre-open → truncated at Jul 8; others intraday same-day). Residual gap: production's last bar was the *live intraday* price at run time; mine is that day's *close*. Same bars otherwise, same RSI/MACD/SMA formulas ([yfinance_chart.py:28-72](../utils/yfinance_chart.py#L28-L72)).
- **NIFTY mood:** recomputed from truncated ^NSEI snapshots with the production rule ([tier2_fundamental.py:236-247](../agents/tier2_fundamental.py#L236-L247)) — NEUTRAL for all 9, consistent with production having proceeded past Stage 4 on each.
- **Memory briefs:** replicated with an as-of gate (a `filing_memory` row counts as FILLED only if its `updated_at` ≤ the eval timestamp) — close but not provably identical.
- **Dict key order** inside the prompt (JSONB re-orders keys) — cosmetic.

### 1.2 Fidelity check: Arm A vs archived production output

Arm A (identical config to production) is the reconstruction's own control: **verdict match 9/9 (all CHALLENGE), bias match 9/9 (all NEUTRAL), agreement exact 5/9 (max deviation 15), confidence exact 6/9 (deviations ±5)**. The contexts are faithful enough that the production distribution reproduces; per-case A/B deltas below are therefore attributable to the config arm, not reconstruction noise.

---

## 2. Part 2 — The A/B (18 calls, temperature 0.3 both arms, same prompt string per case)

**Arm A** = production config: `thinking: {"type": "disabled"}`, max_tokens 2500 ([ai_consensus.py:28-29](../utils/ai_consensus.py#L28-L29)).
**Arm B** = alternative N-1 remedy: thinking at API default (enabled — confirmed by nonzero reasoning tokens on all 9 calls), max_tokens 4000.

| id | Ticker | Haiku (stored) | Prod (Jul) | **Arm A** | **Arm B** | A→B shift | Decision A / B |
|---|---|---|---|---|---|---|---|
| 31 | AXISBANK | NEUTRAL/50 | CHG/45/NEU/55 | CHG/45/NEU/60 | CHG/**70**/NEU/60 | agr +25 | SKIP / SKIP (B died on avg 55 < 65) |
| 32 | TORNTPHARM | BULLISH/68 | CHG/40/NEU/55 | CHG/40/NEU/55 | CHG/50/**BULLISH**/70 | bias flip, conf +15 | SKIP / SKIP (agr 50 < 70) |
| 33 | SBIN | BULLISH/68 | CHG/30/NEU/60 | CHG/45/NEU/60 | CHG/35/NEU/60 | agr −10 | SKIP / SKIP |
| 34 | CHOICEIN | BULLISH/68 | CHG/30/NEU/55 | CHG/40/NEU/55 | CHG/30/NEU/60 | agr −10 | SKIP / SKIP |
| 35 | INTELLECT | BULLISH/68 | CHG/40/NEU/55 | CHG/40/NEU/55 | CHG/**60**/**BULLISH**/60 | bias flip, agr +20 | SKIP / SKIP (agr 60 < 70) |
| 36 | PIDILITIND | BULLISH/68 | CHG/40/NEU/60 | CHG/45/NEU/60 | CHG/35/NEU/55 | agr −10 | SKIP / SKIP |
| 37 | SAGILITY | BULLISH/68 | CHG/40/NEU/55 | CHG/40/NEU/60 | CHG/30/NEU/55 | agr −10 | SKIP / SKIP |
| 38 | ASTERDM | NEUTRAL/52 | CHG/40/NEU/60 | CHG/40/NEU/55 | CHG/45/NEU/55 | ≈same | SKIP / SKIP |
| 39 | EMCURE | BULLISH/62 | CHG/45/NEU/55 | CHG/40/NEU/55 | **CONFIRM/80/BULLISH/65** | verdict flip | SKIP / **SKIP (avg 63.5 < 65)** |

(CHG = CHALLENGE, NEU = NEUTRAL. Prod column = archived `agent_disagreements` values.)

**Aggregates:**

| Metric | Arm A | Arm B |
|---|---|---|
| Verdicts | CHALLENGE 9/9 | CHALLENGE 8, CONFIRM 1 |
| Bias | NEUTRAL 9/9 | NEUTRAL 6, BULLISH 3 |
| Agreement: mean / range / σ | 41.7 / 40–45 / 2.4 | 48.3 / 30–80 / 17.2 |
| Own confidence: mean | 57.2 | 60.0 |
| **PROCEED count** | **0** | **0** |
| finish_reason | stop 9/9 | stop 9/9 — **zero starvations** |
| Completion tokens: mean (range) | 148 (120–177) | 1,002 (610–1,391) |
| Reasoning tokens | 0 | 480–1,271 (mean ~872) |
| Latency: mean | 2.3 s | 12.0 s |

Three observations:

1. **No systematic direction.** Arm B raised agreement in 4 cases (+5 to +40) and lowered it in 4 (−10 each); one unchanged-ish. What thinking changes is *variance*, not *lean* — the reasoning process differentiates cases the no-thinking model treats as one undifferentiated "meh, 40."
2. **The gate still catches everything, and instructively so.** The EMCURE CONFIRM (80/BULLISH/65) died on the confidence floor: Haiku's 62 + DeepSeek's 65 average 63.5 < 65 ([ai_consensus.py:164-166](../utils/ai_consensus.py#L164-L166)). AXISBANK's agreement-70 CHALLENGE actually *cleared* the G2 challenge gate (70 is not < 70) and matched direction (NEUTRAL–NEUTRAL), then died on avg 55 < 65. TORNTPHARM Arm B agreed on direction with confidence 70 (avg 69 would have passed!) yet self-labeled CHALLENGE/50 — the prompt's magnitude-disagreement ambiguity ([calibration report §3.3](2026-07-14-consensus-calibration.md)) destroying an arithmetic near-pass. The multi-gate double-lock from yesterday's report is now demonstrated live in three variants.
3. **Arm B never starved** — max usage 1,391 of 4,000 tokens (2,609 headroom). Verdict (c) is ruled out: the alternative remedy *was* technically viable. It just doesn't change decisions.

---

## 3. Part 3 — The GILLETTE control

Same reconstructed context + verbatim May-27 Haiku output as yesterday's replay. Full lineage:

| Config | Result | Source |
|---|---|---|
| **Production, May 27** (thinking-era serving, max_tokens 600) | **CONFIRM / 85 / BULLISH / 70 → PROCEED** (trade id 161) | `paper_trades.raw_signal` |
| **Arm A today** (no thinking, 2500) | CHALLENGE / 40 / NEUTRAL / 60 — ×2 | yesterday's replay (`probe_gillette_results.json`) |
| **Arm B today** (thinking, 4000) | CHALLENGE / 40 / **BULLISH** / 60; CHALLENGE / 25 / NEUTRAL / 60 | this session (`ab_gillette_results.json`) |

**Arm B does not reproduce the May CONFIRM.** The loop yesterday's report hoped to close ("if Arm B returns CONFIRM/~85, the config change moved the temperament, definitively") closed the *other* way: the temperament shift is real relative to May, but **the thinking flag is not its mechanism**. Combined with the token-budget evidence (May: whole responses fit in 600 completion tokens; today: thinking alone consumes 480–1,271 before any output), the parsimonious explanation is that **DeepSeek's serving stack behind the `deepseek-v4-flash` alias changed between May 29 and Jul 7** — the same change that caused the N-1 starvation in the first place. Yesterday's "N-1 fix made the verifier harsher" framing was wrong in its attribution: N-1 and the harshness are two symptoms of the same upstream drift, not cause and effect. (Residual alternative: the GILLETTE reconstruction is unfaithful in some way that matters; it is approximate. But it cannot explain the 600-token May successes, which are from production logs, not reconstruction.)

---

## 4. Part 4 — Verdict

**(a) No material difference** — with precise scope:

- On **outcomes** (the thing that matters): identical. 0 PROCEEDs in 9/9 cases both arms; every skip reason lands in the same multi-gate lock. The July drought is **not** attributable to the N-1 remedy choice. N-1 is exonerated.
- On **texture**: Arm B differs measurably (1 verdict flip, 3 bias flips, agreement σ 2.4 → 17.2) but not directionally — it is *higher-variance*, not *more agreeable*.
- The **(b) hypothesis as originally framed is falsified** by the GILLETTE control: Arm B does not restore May behavior. The temperament shift vs May is real but exogenous (server-side drift), not a config regression we can revert.
- **(c) is ruled out**: Arm B never starved at 4,000 tokens.

One more live data point: a **10th post-resume CHALLENGE** arrived this morning — NBCC (CONTRACT_WIN), Jul 14, agreement 40, `agent_disagreements` id 40. The drought statistic is now 0/10.

---

## 5. Part 5 — The judgment call (framed for your decision; no recommendation to switch)

### 5.1 Is either temperament better *calibrated*? First real evidence — and it cuts against the gate's inputs, softly

All 20 May CHALLENGE'd filings now have FILLED 10-day outcomes in `filing_memory` (joined via `filings_log.url_hash`, read-only). Deduplicating repeat evaluations → 14 unique blocked theses. Scoring each against its NIFTY-adjusted alpha_10d in the analyst's direction (SAPPHIRE was a BEARISH call and the stock fell — counted as analyst-right):

| Blocked-by-verifier cohort (May, n=14 unique) | Count | Examples |
|---|---|---|
| Analyst direction right (\|alpha\| > 3%) | **7** | MINDACORP +11.7, DEEPAKFERT +14.8, RBLBANK +5.7, SAPPHIRE (bearish) −5.7 |
| Analyst direction wrong (> 3% against) | 4 | JUBLINGREA −8.7, ASAHIINDIA −6.0, CUMMINSIND −5.8, TCS −3.7 |
| Flat (\|alpha\| ≤ 3%) | 3 | JUBLPHARMA, JSWSTEEL, ALKEM |
| **Mean directional alpha of blocked theses** | **+1.6%** | median +2.1% |

Versus the cohort the May verifier **passed**: ASHOKLEY SL_HIT, GILLETTE EXPIRED, LUPIN EXPIRED — **0-for-3, zero targets hit**.

Honest reading: **n is far too small for confidence** (14 + 3, one May regime, overlapping dates) — but the direction of the evidence is that the verifier's CHALLENGE/CONFIRM distinction showed **no positive predictive value, and was mildly inverted**: what it blocked out-performed what it let through. Two weak sub-signals at the extremes (both agreement-20 cases lost; the single agreement-60 case won) are too thin to build on. Neither temperament has *any* demonstrated calibration; the tight gate is protecting the portfolio from a signal whose quality is unmeasured in both directions. "Insufficient data" is the verdict on which temperament is *better*; "no evidence of discrimination so far" is the verdict on the one we have.

### 5.2 The tradeoff, stated plainly

| | Arm A (current) | Arm B (thinking, 4000) |
|---|---|---|
| Trades from these 10 cases | 0 | 0 |
| Temperament | uniform, compressed (agr 40–45) | differentiated, dispersed (agr 25–80) |
| Cost per verifier call | ~148 completion tokens, ~2.3 s | ~1,002 completion tokens (~7×), ~12 s (~5×) |
| Starvation risk | none (no reasoning) | none observed at 4,000 (max 1,391) |
| Restores May behavior? | no | **no** |
| Learning-clock impact | none | none — the gate outcome is identical |

The premise of "Arm B = more trades, faster learning clock" **did not survive measurement** — Arm B produces zero additional trades on the real July stream. There is no quality-vs-volume tradeoff to weigh here; Arm B is strictly more expensive for the same decisions. The switch question answers itself, which is why I can state it without choosing for you.

### 5.3 What the session actually surfaced (new, for your awareness — proposals only)

1. **Silent model drift is now a documented, outcome-relevant risk.** The verifier's temperament changed materially between May and July with zero commits on our side — it altered the effective consensus bar and nobody chose it. A cheap countermeasure exists: a **drift canary** — a fixed set of frozen verifier contexts (e.g., the GILLETTE replay + 2–3 of these archived cases) re-run weekly/monthly offline, alerting when the verdict/agreement fingerprint moves. Read-only, ~4 calls per run, no production change. This is a new option (call it **O-6**) alongside the calibration report's O-1…O-5.
2. **The gate's double-lock is now demonstrated live, not just theorized:** EMCURE's CONFIRM/80 died on a 1.5-point confidence shortfall; TORNTPHARM's direction-matched conf-70 died on self-labeled CHALLENGE/50; AXISBANK's agreement-70 cleared G2 and died on G5. If any future recalibration is attempted (O-2), these three archived cases are ready-made unit tests for it.
3. **The calibration ledger (§5.1) should keep filling itself for free:** the 10 post-resume CHALLENGEs will have FILLED outcomes by late July — extending the blocked-cohort sample from 14 to ~24 with zero effort. Worth re-running the §5.1 join then before any decision on O-2.

**Decisions pending with you (unchanged from the calibration report, now better informed):** O-2 rubric repair (shadow-test first; the case *for* it is slightly strengthened — the score is provably noise-dominated and the gate's inputs show no calibration), O-1 wait (unchanged), O-6 drift canary (new, cheap, read-only). O-3 is now DONE — this report. O-4/O-5 remain not endorsed. **No config change follows from this session regardless — Arm B offers nothing to switch to.**

---

## 6. Methodology & compliance

- READ-ONLY honored: DB access exclusively via `smb_audit_ro` with `set_session(readonly=True)`; production code untouched (harness scripts: scratchpad `ab_harness.py`, `ab_gillette_armB.py`, `ab_pull_inputs.py`; raw outputs: `ab_results.json`, `ab_gillette_results.json`).
- **20 DeepSeek calls total** (18 A/B + 2 GILLETTE Arm B), within the ≤24 cap. Zero Anthropic calls (analyst outputs were archived — never re-run).
- `determine_consensus` imported from production ([utils/ai_consensus.py:148](../utils/ai_consensus.py#L148)); prompt template read from [prompts/tier2f_verifier_v1.txt](../prompts/tier2f_verifier_v1.txt) unmodified.
- Known limitations: single run per case per arm (temperature 0.3; Arm A's 9/9 match to production suggests low variance, and yesterday's 3× synthetic repeats were verbatim-stable, but single-shot deltas of ±5–10 agreement points are within noise); GILLETTE context approximate; May-cohort calibration n=14+3; drift attribution is inference from converging evidence (600-token May successes + both-arm CHALLENGE today), not a vendor changelog.

# Consensus Calibration Investigation — Can the PROCEED Gate Ever Open?

**Date:** 2026-07-14
**Mode:** READ-ONLY (no code/flag/prompt changes, no DB writes, no trades; LLM probe calls only)
**Continuity:** follows [2026-07-12-current-scenario-report.md](2026-07-12-current-scenario-report.md) (N-1 root cause + zero-trade funnel) and [2026-07-13-followup-investigation.md](2026-07-13-followup-investigation.md) (N-1 verified GREEN in prod, 5 clean verifier responses on Jul 13).
**Question:** with Haiku 4.5 as analyst and DeepSeek V4 Flash as verifier, as currently prompted and configured, is the consensus PROCEED path theoretically reachable — or do the two models have systematically incompatible temperaments such that the gate can essentially never open?

---

## 0. Executive verdict — **(b): reachable, but very tight — and measurably tighter than in May**

Four load-bearing facts, each established independently:

1. **The gate has opened before.** The three existing TIER2F paper trades (May 25–28) were genuine consensus PROCEEDs — `fallback_mode: null`, DeepSeek `CONFIRM` with agreement 75/85/85 and confidence 65/70/70 (`paper_trades` ids 160–162, raw_signal decode, §2.2). The investigation premise "zero PROCEED verdicts on record" is true only for the post-resume window.
2. **The gate opens today on an unambiguous case.** A controlled probe through the *actual production functions and prompts* (current no-thinking config) produced `CONFIRM / agreement 82 / confidence 75 / BULLISH` from DeepSeek **3 out of 3 times** on a deliberately blockbuster synthetic filing → `PROCEED` all three times (§4.3). Reachability is a proven yes.
3. **The post-resume drought (0 CONFIRMs in 9 verifier responses) is not yet statistical proof of anything.** May's observed CONFIRM base rate was ≥3/23 ≈ 13% of verifier-reached filings. P(0 confirms in 9 | p=0.13) = 0.87⁹ ≈ 0.29 — a 29% chance under unchanged behavior. The drought is consistent with "routine filings, working skeptic."
4. **But the bar has drifted upward since May.** An approximate replay of the May-27 GILLETTE case — the same filing profile and the *verbatim* original Haiku output that production confirmed at agreement 85 → PROCEED — now returns `CHALLENGE / 40 / NEUTRAL / 60` twice out of two through the current config (§4.4). The N-1 fix (thinking disabled, 2e51d83) or server-side model drift has made the verifier harsher on borderline cases. Caveat: reconstruction was approximate, so this is strong-indicative, not conclusive.

**Net:** the two models are not temperamentally incompatible — DeepSeek flips into a genuine CONFIRM mode (agreement 75–85, confidence 65–75) when the case is strong. But the flip currently requires a multi-catalyst, top-decile filing, and the routine dividend/results flow that dominates the stream will essentially never produce one. Under the current configuration the consensus trade arrival rate is plausibly ~0–2/month, which keeps the statistical-maturity clock (n=3 resolved TIER2F, the Jul-4 audit's "longest pole") effectively frozen. Whether that is *correct conservatism* or *a starvation problem* is a strategy decision, not a bug — the only 3 trades the more agreeable May verifier let through went 0-for-3 (1 SL_HIT, 2 EXPIRED). Options in §5; no changes made.

---

## 1. Part 1 — The PROCEED bar, exactly

### 1.1 Gate chain

`determine_consensus()` at [utils/ai_consensus.py:148-168](../utils/ai_consensus.py#L148-L168), invoked from [agents/tier2_fundamental.py:357](../agents/tier2_fundamental.py#L357). In evaluation order:

| # | Condition (must hold) | Source |
|---|---|---|
| G1 | `haiku["tradeable"]` truthy | ai_consensus.py:150-151 (early-skip duplicate at tier2_fundamental.py:341-342) |
| G2 | NOT (`verdict == "CHALLENGE"` AND `agreement_score < 70`) — missing score defaults to 0 | ai_consensus.py:153-154 |
| G3 | `haiku["directional_bias"] == flash["my_directional_bias"]` (exact string equality) | ai_consensus.py:156-157 |
| G4 | both confidences present and numeric | ai_consensus.py:159-162 |
| G5 | `(haiku_conf + flash_conf) / 2 >= 65` | ai_consensus.py:164-166; floor constant `AVG_CONFIDENCE_FLOOR = 65` at tier2_fundamental.py:65 |

Footnote: `AGREEMENT_THRESHOLD = 70` is defined at [tier2_fundamental.py:64](../agents/tier2_fundamental.py#L64) but `determine_consensus` hardcodes its own `70` at ai_consensus.py:153 — a defined-but-unused duplicate (cosmetic).

### 1.2 Post-PROCEED gates before a trade actually exists

- NEUTRAL-bias skip: a matched NEUTRAL–NEUTRAL pair passes G3 but is discarded at [tier2_fundamental.py:398-399](../agents/tier2_fundamental.py#L398-L399). Effective G3 is *matched AND directional*.
- Ladder RR floor: [tier2_fundamental.py:474-481](../agents/tier2_fundamental.py#L474-L481). With `T1_PCT = 6.0`, `SL_PCT = 4.0` ([utils/tiered_target_generator.py:6,10](../utils/tiered_target_generator.py#L6)) the ladder RR is exactly 1.50 = `RR_FLOOR` ([utils/reward_risk.py:18](../utils/reward_risk.py#L18)); the check is `rr < RR_FLOOR` so it passes as configured (canary unfired — consistent with the Jul-9 verification).
- Sizing + insert (Steps 9–10) impose no further confidence conditions.

### 1.3 Minimum clearing combinations (concrete numbers)

Both prompts clamp confidence to integers 50–85 ([prompts/tier2f_analyst_v1.txt:14](../prompts/tier2f_analyst_v1.txt#L14), [prompts/tier2f_verifier_v1.txt:18,28](../prompts/tier2f_verifier_v1.txt#L18)).

- **Canonical path:** DeepSeek `verdict = CONFIRM` (agreement score then irrelevant to G2), same directional bias, and `haiku_conf + flash_conf ≥ 130`. Minimum examples: 65+65, 68+62, 78+52. At Haiku's empirical 68-cluster, DeepSeek must supply ≥ 62.
- **Phantom path:** `CHALLENGE` with `agreement_score ≥ 70` + direction match + sum ≥ 130 clears G2 arithmetically, but is semantically near-unreachable: the verifier prompt *forces* agreement < 50 whenever directions mismatch ([tier2f_verifier_v1.txt:16](../prompts/tier2f_verifier_v1.txt#L16)), and defines direction+tradeability agreement as CONFIRM ([:12](../prompts/tier2f_verifier_v1.txt#L12)) — a CHALLENGE≥70 verifier would have to agree and disagree simultaneously. Observed: 0 of 29 CHALLENGEs ever reached 70 (max 60). Additionally, a CHALLENGE zeroes `my_stop_loss_pct`/`my_target_pct` (:19), which would silently disable AI-SL eligibility ([tier2_fundamental.py:423-428](../agents/tier2_fundamental.py#L423-L428)) even if this path ever fired.
- **SOLO path** (verifier transport failure only): raw solo confidence ≥ 73, because `int(conf * 0.9) ≥ 65` truncates — raw 72 → 64 fails, raw 73 → 65 passes ([tier2_fundamental.py:361-375](../agents/tier2_fundamental.py#L361-L375)).

**Plain statement of the bar:** *DeepSeek must say CONFIRM, name the same direction, and independently produce confidence ≥ (130 − Haiku's number). Nothing else clears.*

---

## 2. Part 2 — What the two models have actually produced

### 2.1 `agent_disagreements` — complete table (29 rows, not ~9)

The table holds **29 rows total**: 20 from the May 22–29 pre-pause window and **9 post-resume** (ids 31–39) — the 9 expected rows correspond 1:1 to the 4 pre-N-1-fix + 5 post-fix verifier responses. Post-resume rows:

| id | date | ticker | event | Haiku bias/conf | Flash verdict/agr/bias/conf | avg conf |
|---|---|---|---|---|---|---|
| 31 | Jul 07 | AXISBANK | RESULTS | NEUTRAL/50 | CHALLENGE/45/NEUTRAL/55 | 52.5 |
| 32 | Jul 08 | TORNTPHARM | MERGER_ACQUISITION | BULLISH/68 | CHALLENGE/40/NEUTRAL/55 | 61.5 |
| 33 | Jul 09 | SBIN | FUND_RAISE | BULLISH/68 | CHALLENGE/30/NEUTRAL/60 | 64.0 |
| 34 | Jul 09 | CHOICEIN | ACQUISITION | BULLISH/68 | CHALLENGE/30/NEUTRAL/55 | 61.5 |
| 35 | Jul 13 | INTELLECT | CONTRACT_WIN | BULLISH/68 | CHALLENGE/40/NEUTRAL/55 | 61.5 |
| 36 | Jul 13 | PIDILITIND | RESULTS | BULLISH/68 | CHALLENGE/40/NEUTRAL/60 | 64.0 |
| 37 | Jul 13 | SAGILITY | RESULTS | BULLISH/68 | CHALLENGE/40/NEUTRAL/55 | 61.5 |
| 38 | Jul 13 | ASTERDM | MERGER_ACQUISITION | NEUTRAL/52 | CHALLENGE/40/NEUTRAL/60 | 56.0 |
| 39 | Jul 13 | EMCURE | ACQUISITION | BULLISH/62 | CHALLENGE/45/NEUTRAL/55 | 58.5 |

Distributions (read-only decode via `smb_audit_ro`):

| Variable | All 29 rows | Post-resume 9 |
|---|---|---|
| Haiku confidence | 50×2, 52×1, 58×1, **62×7, 68×18** | 50, 52, 62, **68×6** |
| Haiku bias | BULLISH 25, NEUTRAL 3, BEARISH 1 | BULLISH 7, NEUTRAL 2 |
| Flash verdict | CHALLENGE 29/29 (by construction — see §2.1a) | CHALLENGE 9/9 |
| Flash agreement | 20×2, **30×13, 35×3, 40×8, 45×2**, 60×1 | 30×2, 40×5, 45×2 |
| Flash confidence | **55×13, 60×16** — never above 60 | 55×6, 60×3 |
| Flash bias | **NEUTRAL 27**, BULLISH 2 | NEUTRAL 9/9 |
| Max avg confidence | **64.0** (never ≥ 65) | 64.0 |

The report-noted "68-cluster and one 72" is confirmed and extended: 68 is Haiku's modal output (18/29); the single 72 appeared only in a SOLO context (Jul-12 report §4.3), never in a logged consensus pair.

**§2.1a Selection-bias correction (important):** `_insert_disagreement` fires only on `verdict == "CHALLENGE"` skips ([tier2_fundamental.py:380-381](../agents/tier2_fundamental.py#L380-L381)). The table therefore characterizes DeepSeek's *CHALLENGE mode only*. Its CONFIRM-mode statistics live in `paper_trades` (§2.2) and are dramatically different — treating the 55–60 confidence band as "DeepSeek's ceiling" would be wrong.

### 2.2 The three production PROCEEDs (May 25–28) — decoded from `paper_trades.raw_signal`

| trade id | ticker | date | Haiku | Flash | avg conf | outcome |
|---|---|---|---|---|---|---|
| 160 | ASHOKLEY | May 25 | BULLISH/68 | **CONFIRM/75**/BULLISH/**65** | 66.5 | SL_HIT |
| 161 | GILLETTE | May 27 | BULLISH/68 | **CONFIRM/85**/BULLISH/**70** | 69.0 | EXPIRED |
| 162 | LUPIN | May 28 | BULLISH/68 | **CONFIRM/85**/BULLISH/**70** | 69.0 | EXPIRED |

Two facts follow. First, **DeepSeek is bimodal, not uniformly skeptical**: CHALLENGE mode = agreement 20–45 / confidence 55–60 / bias NEUTRAL; CONFIRM mode = agreement 75–85 / confidence 65–70 / bias matched. There is no observed middle — no CHALLENGE above 60, no CONFIRM below 75 (§3.3 explains why). Second, **the agreeable verifier's track record is 0-for-3** (no target ever hit) — the skeptic is not self-evidently miscalibrated.

None of these were dividends-with-blemishes edge cases the current verifier would plausibly confirm: §4.4 replays GILLETTE (id 161) through today's config and gets CHALLENGE twice.

### 2.3 Run-log harvest, Jul 6 → Jul 14 (all 454 tier2f workflow runs)

All 454 tier2f workflow runs created 2026-07-06 → 2026-07-14 were fetched (429 success, 25 cancelled) and grepped for STAGE 6/7/8 lines. **131 runs reached the analyst stage** (per day: Jul 7 ×22, Jul 8 ×19, Jul 9 ×32, Jul 10 ×35, Jul 13 ×23; Jul 11–12 weekend; no analyst-stage runs yet on Jul 14 at harvest time). This independently cross-validates the Jul-12 report's funnel and extends it through Jul 13:

| Funnel stage | Count | Detail |
|---|---|---|
| Reached Stage 6 (analyst) | 131 | Haiku conf across all: 50×40, 52×12, 55×43, 58×9, 62×2, 65×1, **68×21, 72×2** (+1 anomalous `conf=0` — see footnote) |
| Analyst `tradeable=false` | **104 (79%)** | the dominant kill |
| Analyst `tradeable=true` | 27 | conf: **68×20**, 72×1, 62×2, 58×2, 52×1, 50×1; bias BULLISH 22 / NEUTRAL 4 / BEARISH 1 |
| Verifier responded | **9** | 4 pre-N-1-fix (Jul 7/8/9/9) + 5 post-fix (Jul 13) — **all 9 CHALLENGE**, agreement {30×2, 40×5, 45×2}, conf {55×6, 60×3}, bias **NEUTRAL 9/9**; matches `agent_disagreements` ids 31–39 exactly, 1:1 |
| Verifier transport-failed → SOLO | 18 | haircut confidences: 61×14 (raw 68), 64×1 (raw 72), 55×1, 52×2 — **all < 65, all refused** |
| Stage 8 `PROCEED` | **0** | all 27 tradeable cases ended SKIP (9 "Verifier challenged", 18 "Solo … < 65") |

Footnote: one Jul-10 run (29066157912) logged `tradeable=False, bias=BEARISH, conf=0` — a violation of the prompt's 50–85 confidence band on a non-tradeable output. Harmless (early-skip fires on `tradeable=false`), but it shows the band instruction is not perfectly enforced by the model.

Haiku's confidence never exceeded 72 in 131 real analyst calls. Its *tradeable* modal output is 68 — at which the consensus path needs DeepSeek to produce ≥ 62 **and** CONFIRM **and** a direction match, while the solo path needs raw ≥ 73, which occurred zero times in the window.

### 2.4 Closest approach to the bar — which variable binds?

- **All-time closest: RBLBANK, May 27** (disagreement id 20): directions matched (BULLISH–BULLISH), agreement 60, confidences 68+60 → avg **64.0**. It failed **two gates simultaneously**: G2 by 10 agreement points (60 < 70 on a CHALLENGE) and G5 by exactly **1 confidence point** (64 < 65). This is the only case in 29 where direction was not the upstream killer.
- **Post-resume closest: PIDILITIND, Jul 13** (id 36): agreement 40 (30 points short), avg 64.0 (1 point short), and bias NEUTRAL ≠ BULLISH (G3 dead too) — triple-locked.
- **Binding-variable structure:** in 27/29 rows the verifier's NEUTRAL bias kills G3, *and* the prompt's mismatch rule ([tier2f_verifier_v1.txt:16](../prompts/tier2f_verifier_v1.txt#L16)) mechanically drags agreement below 50, killing G2 in the same stroke. Independently, the confidence floor G5 would have killed **all 29** (max avg 64.0). No single-gate tweak rescues these rows: PROCEED is reached not by margin but by *mode-flip* — a CONFIRM lifts agreement, bias, and confidence together (§2.2).

---

## 3. Part 3 — Are the prompts pulling in opposite directions?

### 3.1 Yes — the asymmetry is explicit and by design

- Analyst: *"You are a sober Indian equity analyst … NOT a hype bot — err on the side of caution"* ([tier2f_analyst_v1.txt:1](../prompts/tier2f_analyst_v1.txt#L1)) — cautious, but its job is to *find* the tradeable opportunity.
- Verifier: *"You are an independent skeptic … **Your default stance is to CHALLENGE — CONFIRM is earned, not given.** The analyst could be wrong, and it is your job to find weaknesses in their thesis"* ([tier2f_verifier_v1.txt:1](../prompts/tier2f_verifier_v1.txt#L1)). This is a structural bias to challenge, verbatim.
- The burden is asymmetric in the schema too: a CHALLENGE must merely cite one weakness (:17); a CONFIRM must additionally produce independent SL and target numbers (:19). CHALLENGE is the cheaper well-formed output.

### 3.2 The NEUTRAL→agreement coupling is the single most consequential rule

*"If your my_directional_bias does not match the analyst's directional_bias → verdict MUST be CHALLENGE and agreement_score MUST be below 50"* ([tier2f_verifier_v1.txt:16](../prompts/tier2f_verifier_v1.txt#L16)). A skeptic's natural "not convinced" resting state is NEUTRAL (27/29 rows) — and NEUTRAL ≠ BULLISH is a mismatch, so the rule *mandates* sub-50 agreement. The G2 gate (< 70 on CHALLENGE) can then never pass. The observed 30–45 clustering is thus substantially **prompt-mandated, not measured disagreement**.

### 3.3 The agreement score is not a calibrated quantity

Only the endpoints are defined (0 = opposite, 100 = identical; :21, :26). The middle has no rubric — and the two worked examples pin **35** for CHALLENGE (:34) and **78** for CONFIRM (:37). Observed production outputs: CHALLENGEs cluster 20–45 around the 35 anchor; CONFIRMs land 75–85 around the 78 anchor. The score is behaving as an **example-anchored verdict echo**, not an independent measurement — which is why "raise/lower the 70 threshold" would not interact with a smooth distribution but with a bimodal one.

### 3.4 Anchoring/contrarian dynamics

The verifier receives the analyst's full output in the same prompt ([ai_consensus.py:110-111](../utils/ai_consensus.py#L110-L111)). It is instructed to form its own view first and to disregard the analyst's confidence (:10, :15, :20), but its persona is *defined* as the analyst's adversary (:1, :17) — the analyst output is the thing it exists to attack. True independence is not verifiable from outside; what is verifiable is that its CHALLENGE reasonings are consistently structured as rebuttals of the analyst's cited evidence (all 29 rows).

### 3.5 What the prompts do NOT explain: the May→July shift

Git history: the skeptic framing, the mismatch rule, and the 35-anchor CHALLENGE example have been in the prompt since the first commit (c7b7b1b, May 21). The May-28 edit (8f568ff) only added SL/target fields and the CONFIRM example. **The prompts did not change between May's 3 CONFIRMs and July's 0/9.** The model string (`deepseek-v4-flash`, [ai_consensus.py:19](../utils/ai_consensus.py#L19)) is also unchanged since May 19 (2b17ad7). What changed is the *call configuration*: N-1 (2e51d83, Jul 13) disabled thinking and raised max_tokens. §4.4 tests exactly this seam.

---

## 4. Part 4 — Controlled probe (11 primary LLM calls; no DB, no dispatch)

**Method:** the actual production functions (`run_analyst`, `run_verifier`, `determine_consensus`) with the actual Tier-2F prompt files and the live (post-N-1) client config. Contexts rebuilt to production shape: real `filings_log` rows + Neon fundamentals via read-only `smb_audit_ro`, live yfinance charts, pattern/memory blocks replicated with the same ranking logic as [utils/pattern_insights_retriever.py](../utils/pattern_insights_retriever.py) and [utils/filing_memory_brief.py](../utils/filing_memory_brief.py). Caveats: charts are Jul-14 (one day later than the originals); the GILLETTE replay context is an approximation reconstructed from the stored reasoning. Raw outputs archived in the session scratchpad (`probe_results.json`, `probe_gillette_results.json`).

### 4.1 Real filing replay — INTELLECT 7375 (CONTRACT_WIN, Jul 13)

Analyst: BULLISH/68 (matches prod exactly). Verifier: **CHALLENGE / 40 / NEUTRAL / 55** — *identical to the production result* (id 35). → SKIP. The production distribution reproduces deterministically at temperature 0.3.

### 4.2 Real filing replay — PIDILITIND 7480 (RESULTS, Jul 13)

Analyst: BULLISH/68. Verifier: **CHALLENGE / 45 / NEUTRAL / 60** (prod: 40/NEUTRAL/60). → SKIP. Same signature, ±5 agreement.

### 4.3 Synthetic maximum-bull case — the reachability test

Constructed to be unambiguous: liquid large-cap IT (₹4.5L Cr), PAT +42% YoY beating consensus by 18%, guidance raised, record TCV, large buyback, clean uptrend above both SMAs, RSI 58, 2.7× volume spike, +10% relative strength, HIGH-confidence 74%-win-rate pattern, 4/4 positive filing memory, BULLISH nifty mood.

- Analyst: BULLISH/**78** — Haiku's 68 ceiling is content-driven, not a clamp.
- Verifier, 3 independent runs: **CONFIRM / 82 / BULLISH / 75 — three out of three** (targets varied 7.0–8.0%, otherwise stable).
- `determine_consensus`: **PROCEED × 3** (avg conf 76.5).

**The PROCEED path is reachable under the current live configuration.** This is the probe's headline answer.

### 4.4 GILLETTE May-27 replay — the temperament-shift test

Same filing profile and the *verbatim* original May Haiku output (BULLISH/68) that production confirmed at CONFIRM/85/70 → PROCEED (trade id 161). Through today's no-thinking config: **CHALLENGE / 40 / NEUTRAL / 60, twice out of two.** The reasonings attack the analyst's own cited caveats ("the analyst's own reasoning undermines their directional bias") — textbook skeptic-mode behavior on a mixed setup. Subject to the approximate-context caveat, the effective CONFIRM threshold has **risen** since May: a borderline case that once passed now fails.

### 4.5 Isolating the skeptic wording

Same synthetic max-bull context and identical analyst output through the *generic Phase-3* verifier prompt ([prompts/ai_consensus_verifier.txt](../prompts/ai_consensus_verifier.txt) — "independent financial analyst," no skeptic framing, no mismatch rule): **CONFIRM / 90 / BULLISH / 85**. The Tier-2F skeptic wording costs ~8 agreement points and ~10 confidence points *on an identical unambiguous input* — a direct measurement of the prompt-temperament tax. On borderline inputs the tax is decisive (§4.4 vs May).

### 4.6 Budget

11 primary calls (2 analyst-replay + 2 verifier-replay + 1 synth analyst + 3 synth verifier + 1 generic verifier + 2 GILLETTE replay); zero retry WARNs observed; well under the 15-call budget. No DB connections in the probe path.

---

## 5. Part 5 — Verdict and options

### 5.1 Verdict: **(b)** — reachable but very tight

- **Not (c):** unreachability is disproven twice over — 3 production PROCEEDs exist (May), and the current config PROCEEDs 3/3 on an unambiguous case. The models are not temperamentally incompatible; DeepSeek has a genuine, stable CONFIRM mode.
- **Not fully (a):** "this week's filings were genuinely weak" is *most* of the story (9 routine dividends/results/small-M&A, all with chart blemishes), and 0/9 is within chance of May's base rate (p ≈ 0.29). But plain (a) would ignore two structural findings: (i) the bar is crossable only by mode-flip — every gate (G2, G3, G5) fails together in CHALLENGE mode (max avg conf 64.0 across all 29 real evaluations, vs floor 65) and passes together in CONFIRM mode; and (ii) the post-N-1 verifier is measurably harsher than the May verifier on borderline cases (§4.4) — the config change that fixed transport (N-1) also moved the temperament, unreviewed.
- **How tight, numerically:** CONFIRM-mode engagement required either a May-style borderline pass (apparently no longer granted) or a multi-catalyst blockbuster (probe-grade). At the observed stream quality (≈21 verifier-reached filings/week, ~0 blockbusters/week), expected consensus trades ≈ **0–2/month**. The n=30 resolved-trade sample that Phase 7 / B7 need would take *years* at this rate. That is the real cost of the current bar — not wrongness, slowness.

### 5.2 Options (proposals only — nothing changed; you decide)

| # | Option | What it does | Tradeoff / honest caveat |
|---|---|---|---|
| O-1 | **Wait (default)** | No change; gate opens on the next genuinely strong filing | Statistically safe, epistemically honest. Cost: sample-accrual near zero; Phase 7/B7 stay blocked indefinitely. If chosen, accept explicitly that consensus-TIER2F is a rare-event channel, not a learning engine. |
| O-2 | **Rubric repair (prompt engineering, not bar-lowering)** | Give `agreement_score` a worded anchor scale (e.g. 20/40/60/80 definitions), add a third worked example of a *borderline CONFIRM* (~70 with acknowledged flaws), and resolve the :12 vs :16 tension (magnitude-only disagreement currently has no sanctioned CONFIRM expression) | Targets the measured artifact (bimodal example-anchoring, §3.3) rather than the threshold. Still a behavioral change to a live prompt — needs offline shadow-testing against the 9 archived post-resume contexts before any deploy. Could shift the effective bar in either direction. |
| O-3 | **Thinking A/B (read-only next step)** | Offline probe: re-run the 9 post-resume contexts with `thinking` enabled + `max_tokens` ~4000 (the alternative N-1 remedy) vs current config, compare verdict/agreement distributions | Directly tests §4.4's hypothesis with zero production impact and ~18 LLM calls. If thinking-on restores May temperament, you get an *informed* choice between two working configs. Caveat: May temperament's track record is 0-for-3 — restoring it is not obviously good. |
| O-4 | **Threshold surgery (listed for completeness, NOT endorsed)** | e.g. floor 65→64 and/or G2 70→60 | Would have converted exactly one historical case (RBLBANK, §2.4) in 29. This is lowering the bar to manufacture trades — by your own stated rule, a system that trades because the bar was lowered is worse than one that doesn't trade. The bimodal score distribution (§3.3) also means threshold moves have near-zero leverage until O-2 makes the score continuous. |
| O-5 | **Accept SOLO as primary** | Treat verifier-down solo (raw ≥ 73) as the main path | Equivalently starved: Haiku's real-filing ceiling is 68 → haircut 61 < 65. Also single-model by design only as an outage fallback; making it primary abandons the two-AI premise rather than calibrating it. Not a fix. |

**Recommendation ordering if you want movement without compromising the bar:** O-3 first (pure information, read-only), then decide on O-2 with shadow-test evidence. O-1 remains defensible if you accept the frozen learning clock. O-4/O-5 are documented so they don't get re-proposed later without their caveats.

### 5.3 What needs your decision

1. Whether to run the O-3 thinking A/B (read-only, ~18 LLM calls, next session).
2. Whether O-2 rubric repair should be drafted for shadow-testing (no deploy without your explicit approval).
3. Whether the frozen sample-accrual rate is acceptable strategy-wise (pure judgment call — affects Phase 7 / B7 sequencing, not correctness).

---

## 6. Methodology & compliance

- **Read-only honored:** all DB access via `smb_audit_ro` connections with `set_session(readonly=True)`; zero writes, zero dispatches, zero flag/prompt/code changes. Report staged only (not committed).
- **Sources:** `agent_disagreements` (29 rows), `paper_trades` raw_signal decode (3 TIER2F trades), 454 tier2f GH workflow run logs (Jul 6–14), git history of prompts and `utils/ai_consensus.py`, live probe outputs (scratchpad `probe_results.json`, `probe_gillette_results.json`).
- **LLM probe budget:** 11 primary calls against the production Anthropic/DeepSeek keys (same as any single tier2f dispatch would consume; no retries were triggered).
- **Known limitations:** GILLETTE replay context approximate (§4.4 caveat); probe charts one day newer than originals; CONFIRM-mode statistics rest on n=3 (May) + n=4 probe runs; 0/9 post-resume is too small to bound the current CONFIRM rate tightly.

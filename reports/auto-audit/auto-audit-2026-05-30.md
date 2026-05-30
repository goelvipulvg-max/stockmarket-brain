# Auto-Audit — 2026-05-30

> **Run:** gap-auditor production run on the `auto-audit` branch (re-run — supersedes the earlier same-day local dry-run). Read-only via `smb_audit_ro` (Supabase + Neon poolers). Engine code / flags / trades / `main` untouched. Telegram digest sent to SMB Audit channel.
>
> **DB reachability:** both stores reachable — no DATA-UNAVAILABLE dimensions. **RLS check:** `paper_trades` and `filing_memory` have RLS enabled; the audit role read **36** and **805** rows respectively (not 0), so `BYPASSRLS`/policy is working — no zero-rows flag raised.

**Trades in scope:** 36 paper_trades (2026-05-03 → 2026-05-28; all 36 within last 30 days) · all-time used for maturity.
**Matured sample (filing_memory, 10d FILLED):** 35 of 805 → **below the ~50 soundness floor → report-wide LOW CONFIDENCE gate is ON.**
**Overall posture:** Slightly *more* real-world-honest than the 2026-05-29 hand audit (RR floor now on the classic path, price-structure + volume soft-context shipped, matured sample climbing 25→35). The three structural fidelity gaps — **cost honesty, survivorship, single-regime** — remain open, and the AI-SL canary is **not visible** in paper_trades. Net: trustworthy direction, conclusions still maturity-gated.

---

## Aasaan bhasha mein (real-world view)

**Bottom line (Hinglish):** System sahi raaste pe hai aur pehle se thoda zyada imaandaar ho gaya hai, par abhi itne kam "pakke" trades hue hain ki kisi bhi win-rate pe pakka bharosa karna jaldbaazi hogi — aur profit ka hisaab abhi cost-tax-slippage ke bina ho raha hai, isliye woh asli se accha dikhta hai.

- **Cost honesty (FAIL).** Matlab: Profit mein brokerage, STT, tax aur slippage minus nahi ho raha — paper profit asli se bada dikh raha hai. Jaise dukaan ka hisaab lagate waqt rent aur bijli ka bill bhul jaana.
- **Survivorship (FAIL).** Matlab: Purane outcomes mein 96.6% sirf dividend wale, aur sirf woh companies jo aaj bhi listed hain — doob/dropout wale nahi. Jaise coaching ko sirf toppers se judge karna, dropout students chhod kar.
- **AI-SL canary (WATCH).** Matlab: Jo "AI-driven stop-loss" wala naya feature ON hai, uska koi nishaan in 36 paper trades mein dikh hi nahi raha — ya to ye trades us feature wale raaste se aaye hi nahi, ya purane hain. Ghar mein naya CCTV laga diya par footage hi record nahi ho raha — check karna padega.
- **Statistical maturity (WARN).** Matlab: Abhi sirf 35 trades "pakke" (matured) hue hain — itne kam pe "strategy achhi hai" kehna 5 toss dekh kar coin ko lucky kehne jaisa hai.

---

## Scorecard

| # | Dimension | Score | Evidence (English) |
|---|---|---|---|
| 1 | Cost honesty | **FAIL** | No cost util in pipeline (B4 parked); `update_paper_trades.py` P&L is gross (no STT/brokerage/GST/slippage); expectancy computed on gross. |
| 2 | Survivorship integrity | **FAIL** | `event_outcomes` = 1382/1430 (**96.6%**) dividend; 585 distinct symbols, all current-listed; B1 verified 0/383 absent (survivors-only). |
| 3 | Look-ahead / point-in-time | **WARN** | Event-driven Tier-0F→Tier-2F flow point-in-time clean (credit). Suspect join: `filing_memory` alpha uses `auto_adjust=True` (B6) — outcome-only, not a decision input (`filing_memory_brief.py` read-only). |
| 4 | Liquidity reality | **WARN** | `USE_VOLUME_GATE=false` (dormant) + it is a *liquidity proxy*, not filing-reaction volume; size from fixed `RISK_PCT`/`MAX_TRADE_PCT`, not volume-relative. |
| 5 | Reward:risk discipline | **WARN** | `RR_FLOOR=1.5` enforced (`utils/reward_risk.py`, now classic path too `c584c35→a410656`) — but on **gross** targets; net R:R unverified. Sizer docstring vs code matches (drift fixed `9d0497c`) — no flag. |
| 6 | Statistical maturity | **WARN** *(gates report)* | `filing_memory` matured 10d = **35** (<50); 5d=213; total 805. Climbing from ~25 anchor but thin → LOW CONFIDENCE on outcome claims. |
| 7 | Overfitting / data-snooping | **PASS** | Both unvalidated gates correctly OFF pending B2: `USE_PRICE_STRUCTURE_GATE=false`, `USE_VOLUME_GATE=false`. No ON flag tuned in-sample. Discipline credited. |
| 8 | Regime robustness | **WARN** | Matured `filing_memory` window 2026-05-08→05-29 (~3 weeks) = single regime; no regime/volatility tag on outcomes; not claimed as general. |

### Operational health (WATCH block — not scored)

- **AI-SL distribution — WATCH (high value).** `USE_AI_SL=true`, but **0 of 36** paper_trades carry `raw_signal->>'ai_sl_used'` (all NULL). Either these trades come from a non-Tier-2F path (classic/after-hours watcher) or predate AI-SL activation (`103fdbd`). The canary Gaurav is watching has **no signal flowing into paper_trades** — confirm which path writes `paper_trades` and whether Tier-2F trades land here.
- **SL rejection reasons — WATCH.** `raw_signal->'ai_sl_validation'->>'rejection_reason'` = NULL for all 36 (consistent — no `ai_sl_validation` block present).
- **`quantity<=0` skip rate — OK.** 0 of 36 (0%). No sizing-skip problem.
- **Trade outcome mix — WATCH.** Of 33 closed: EXPIRED **19 (58%)**, SL_HIT 11, TARGET_HIT 3. Time-stop expiries dominate over target/SL hits — may hint targets sit too far for the holding window. Sample tiny (33) → low confidence.
- **Two-AI consensus — NOT MEASURED.** Needs `agent_disagreements`/consensus telemetry, outside this run's four tables. Flag for a future audit pass.

---

## Top gaps, ranked by leverage

**1. Gross-only P&L — costs not modelled  (FAIL · high impact × medium tractability)**
Why live: the single most common reason a profitable backtest goes flat live (literature: 20–50% haircut, much of it cost). On small NSE tickets STT + brokerage + GST + slippage are not negligible. Expectancy and every win-stat are inflated until netted.
Evidence: no cost util (B4 parked); `update_paper_trades.py` P&L gross.
**Matlab:** Profit ka hisaab bina kharcha kaate ho raha hai — asli haath mein kam aayega. Direction: build the parked B4 cost+slippage util and re-compute expectancy net. *(Proposal, not a code change.)*

**2. AI-SL canary invisible in paper_trades  (WATCH · high importance × high tractability)**
Why live: this is the Stage-2 feature currently ON; if its signal never reaches `paper_trades`, you are flying the canary blind and cannot tell whether AI-SL helps or hurts.
Evidence: 0/36 rows have `raw_signal.ai_sl_used`; flag `USE_AI_SL=true`.
**Matlab:** Naya CCTV ON hai par recording hi nahi aa rahi. Direction: confirm the write path / activation date; verify a Tier-2F-path trade lands the field.

**3. Survivors-and-dividends base rate  (FAIL · high impact × low tractability)**
Why live: the engine will meet delistings/suspensions the historical set never contained, and a 96.6%-dividend base rate has near-zero bearing on the RESULTS/M&A edge the system actually trades.
Evidence: `event_outcomes` 96.6% dividend, 100% survivors (B1).
**Matlab:** Sirf bache hue aur sirf dividend wale gin rahe hain — win-rate phula hua. Direction: parked B1 point-in-time membership + a RESULTS/M&A-focused outcome set (depends on `filing_memory` maturing).

**4. R:R floor enforced on gross targets  (WARN · medium × medium)**
Evidence: `RR_FLOOR=1.5` (`reward_risk.py`) on pre-cost targets.
**Matlab:** 1.5x ka rule hai, par woh tax-kharcha kaatne se pehle ka hai — cost ke baad asli ratio kam ho sakta hai. Direction: net-of-cost R:R once B4 lands.

**5. Maturity still thin → confidence gate  (WARN)**
Evidence: 35 matured (10d) < 50.
**Matlab:** Abhi itne kam pakke trades hain ki koi bhi nateeja "pakka" nahi — thoda aur rukna padega. Direction: re-check ~1–2 months out (B2 unblocks as samples mature).

*(Single-regime robustness, liquidity-proxy, and adjusted-close are real but lower-leverage WARNs — see scorecard.)*

---

## Still parked — no change

- **B2 filing-edge backtest** — unblock: ≥20–30 matured outcomes **per category**; now 35 matured (10d) total, climbing.
- **B1 point-in-time membership history** — unblock: create `nse500_membership_history` DDL + append on sync.
- **Gap #2 surprise magnitude/quality** — PAUSED; unblock: in-house quarterly store ≥5–8 quarters, or a source with ≥8 quarters quarterly revenue/PAT.
- **Price-structure & volume HARD gates** — dormant behind `USE_PRICE_STRUCTURE_GATE` / `USE_VOLUME_GATE`; unblock: B2 validation. *(Soft context already shipped.)*
- **QuestDB / Pinecone wiring**, **risk_factors/moat_analysis columns** — future-enhancement parked items.

---

## Confidence note

Matured 10d sample = **35 (<50)** → every outcome-statistics-dependent finding (survivorship strength, win/expectancy claims, regime) is **LOW CONFIDENCE** and should be re-checked, not acted on, until the sample matures (B2 horizon ≈ 1–2 months). Structural findings that do **not** depend on outcome stats — cost modelling (FAIL), the AI-SL canary visibility (WATCH), and gate discipline (PASS) — are **higher confidence** because they rest on code/flag state, not on trade counts.

*Generated by the `gap-auditor` skill (production run, `auto-audit` branch). Reports-only: it proposes; Gaurav decides.*

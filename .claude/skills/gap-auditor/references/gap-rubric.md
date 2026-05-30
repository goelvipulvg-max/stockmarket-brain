# Gap Rubric — stockmarket-brain real-world fidelity audit

This is the scoring guide the `gap-auditor` skill reads in Phase 2. Each dimension answers one question: *would this make the system behave worse in a live NSE market than it looks in paper trading?* Score **PASS / WARN / FAIL**, always with a one-line evidence string citing a real number or file. No evidence → **UNVERIFIED** (never default to PASS).

Rank order in the report is by leverage (impact × tractability), not by the order below.

---

## 1. Cost honesty
**Question:** Are real trading frictions modelled — brokerage, STT, exchange/SEBI charges, stamp duty, GST, *and* slippage + market impact?
**How to check here:** Look for a cost utility in the pipeline (the planned `B4 cost util`). Check whether `paper_trades` P&L is gross or net of costs, and whether expectancy (`#7`) is computed on net figures.
**Signals:** If P&L is gross, expectancy is dishonestly high. Costs on small NSE tickets are not negligible.
**Score:** PASS = full cost stack applied to every trade; WARN = partial (e.g. brokerage only, no slippage); FAIL = costs ignored.
**Why it matters live:** the single most common reason a profitable backtest goes flat live; literature reports 20–50% performance haircuts going live, much of it cost.

## 2. Survivorship integrity
**Question:** Does the universe / outcome set include names that were later delisted, suspended, or went to zero — or only survivors?
**How to check here:** Inspect `event_outcomes` for the share of still-listed names and the absence of delisted ones. Memory flag: outcomes have read ~100% survivors and ~96.6% dividend events.
**Signals:** ~100% survivors = survivorship bias is almost certainly present; headline returns are inflated.
**Score:** PASS = delisted/suspended names retained in the historical set; WARN = unknown / not verifiable; FAIL = survivors-only confirmed.
**Why it matters live:** the engine will meet the failures the backtest never saw.

## 3. Look-ahead / point-in-time
**Question:** Does any entry/exit decision use information not available at decision time?
**How to check here:** Two specific places — (a) `filing_memory` uses adjusted-close; confirm adjusted prices feed only *outcome measurement*, never an *entry/exit* decision (split/bonus adjustment embeds future info). (b) Confirm filing timestamp precedes the price bar used to act on it (no acting on a filing with same-bar or earlier price).
**Signals:** The engine is event-driven (Tier-0F poller → Tier-2F) which is the *correct*, look-ahead-resistant architecture — credit this. The risk is in the price-join, not the event flow.
**Score:** PASS = point-in-time clean, adjusted prices outcome-only; WARN = one suspect join; FAIL = decision uses future-derived data.
**Why it matters live:** look-ahead produces "god-like" paper performance that evaporates instantly live.

## 4. Liquidity reality
**Question:** Could the system actually fill the position size it assumes, at the price it assumes, given the name's real traded volume around the filing?
**How to check here:** Examine `USE_VOLUME_GATE`. **Known truth: it is a liquidity proxy, not filing-reaction volume.** Check whether position size is capped relative to a name's average traded value, and whether thin names are excluded or sized down.
**Signals:** If the gate is a static liquidity proxy and size is not volume-relative, fills/slippage will diverge from paper.
**Score:** PASS = position size constrained by real per-name liquidity; WARN = liquidity proxy only; FAIL = no liquidity constraint.
**Why it matters live:** illiquid names give the biggest backtest-to-live gaps. Never report this as "volume confirmation" — it is a proxy.

## 5. Reward:risk discipline
**Question:** Is a minimum reward:risk enforced before a trade is taken, and is it honest about costs?
**How to check here:** Verify `utils/reward_risk.py` (line ~18) enforces `RR_FLOOR` (= 1.5) and that the R:R is computed on net (post-cost) targets, not gross. Confirm the AI-SL blend rule holds: SL = max-of-SLs (conservative), target = confidence-weighted average, within `SL_FLOOR_PCT` (2%) / `SL_CAP_PCT` (10%) / `TARGET_FLOOR_PCT` (2%) / hallucination bounds (all in `agents/tier2_fundamental.py`). Position sizing lives in `utils/position_sizer.py` as `RISK_PCT` (0.00125 = 0.125%) and `MAX_TRADE_PCT` (0.025 = 2.5%).
**Signals:** R:R computed on gross targets quietly violates the real floor once costs are subtracted.
**Also check:** confirm `utils/position_sizer.py`'s docstring matches the live `RISK_PCT` / `MAX_TRADE_PCT` constants, and flag **only if they actually diverge** — the earlier 0.02 / 0.12 docstring drift was already fixed in `9d0497c`, so this should normally pass.
**Score:** PASS = RR_FLOOR enforced on net; WARN = enforced on gross; FAIL = not enforced.

## 6. Statistical maturity
**Question:** Are there enough *matured* outcomes to trust any performance claim?
**How to check here:** Read the `filing_memory` matured count. Memory anchor: ~25 matured. Treat < ~50 as low; < ~100 as still thin for regime-spanning claims.
**Signals:** Small samples manufacture false confidence — a handful of wins is noise, not edge.
**Score:** PASS = sample sound for the claims made; WARN = thin, claims must be hedged; FAIL = claims made on a handful of trades.
**Action:** this dimension drives the report-wide confidence gate (Phase 3). When low, every stats-dependent finding is labelled LOW CONFIDENCE and a re-check date is suggested (the B2 backtest unblocks roughly 1–2 months out as samples mature).

## 7. Overfitting / data-snooping
**Question:** Have thresholds/parameters been tuned on the same data used to judge them, or tuned enough times that the winner is luck?
**How to check here:** Count tunable parameters and flags. Check whether any flag was tuned-then-validated on the *same* window (no out-of-sample / walk-forward split). The two dormant gates (`USE_PRICE_STRUCTURE_GATE`, `USE_VOLUME_GATE`) are correctly OFF pending B2 validation — credit this discipline; FAIL only if a flag was turned ON and tuned without an out-of-sample check.
**Signals:** literature: 1,000 random no-edge strategies produced a top Sharpe of ~2.37 by chance alone. Many parameters + one validation window = likely overfit.
**Score:** PASS = out-of-sample / walk-forward used, parameter count modest; WARN = in-sample tuning with caveats; FAIL = ON flag tuned in-sample.

## 8. Regime robustness
**Question:** Has behaviour been checked across different market regimes (trending up, down, high-volatility), or only the recent calm one?
**How to check here:** Does the matured set span more than one regime? Is there any regime tag or volatility context on outcomes?
**Signals:** A strategy fit to one regime rarely survives the next; current samples likely span a single regime.
**Score:** PASS = multi-regime evidence; WARN = single-regime, acknowledged; FAIL = single-regime, treated as general.
**Why it matters live:** regime shift is a top structural cause of live divergence and is usually invisible in a short backtest.

---

## Operational health (short block, not scored on the fidelity scale)

Report these as a quick status, since they are the live Stage-2 AI-SL canary signals Gaurav is already watching:

- **AI-SL distribution** — share with `raw_signal->>'ai_sl_used' = true` vs false; is it in a sane band or collapsing to one side?
- **SL rejection reasons** — top values of `raw_signal->'ai_sl_validation'->>'rejection_reason'`; any single reason dominating unexpectedly?
- **`quantity <= 0` skip rate** — how often sizing produces a skipped trade (the column is `quantity`); a rising rate may indicate a sizing or liquidity problem.
- **Two-AI consensus** — any sign one model (Haiku vs DeepSeek) is consistently overridden or erroring, which would quietly make it a single-AI system.

Flag anything anomalous as a WATCH item; these inform whether the canary phase is healthy, not whether to change code.

---

## Plain-Hinglish "Matlab" library (for the report + Telegram explanation layer)

Every finding shown to Gaurav must carry a plain-language **"Matlab:"** line in **simple Hinglish (Roman script)** — beginner-friendly, no jargon, with a short real-world Indian analogy. Use these canonical lines for the eight dimensions (adapt the wording to the actual evidence; keep the analogy). For operational-health WATCH items or any novel gap, write a fresh "Matlab:" line in the same simple Hinglish style.

1. **Cost honesty** — Matlab: Profit mein brokerage, tax aur slippage poora minus nahi ho raha, isliye paper profit asli se bada dikhta hai. Jaise dukaan ka hisaab lagate waqt rent aur bijli ka bill bhul jaana.
2. **Survivorship integrity** — Matlab: Hum sirf un companies ko gin rahe hain jo bach gayi, jo doob gayi unhe chhod diya — isliye win-rate asli se accha dikhta hai. Jaise coaching ko sirf toppers se judge karna, dropout students ko ignore karke.
3. **Look-ahead / point-in-time** — Matlab: Decision lete waqt aisi jaankari use ho rahi hai jo us waqt available hi nahi thi — yaani "future jhaank kar" trade. Jaise match ka result pehle se dekh kar bet lagana — paper pe jeet, asli mein impossible.
4. **Liquidity reality** — Matlab: Jitna bada position hum maan rahe hain, asli market mein utne shares us price pe mil hi nahi sakte (kam volume). Jaise sasti property dekh kar khush hona, par bechne jaao to koi kharidaar hi nahi.
5. **Reward:Risk discipline** — Matlab: Har trade mein kam-se-kam itna profit-vs-risk hona chahiye (1.5x), aur woh cost ke baad sahi hona chahiye. Jaise ₹100 risk pe kam-se-kam ₹150 ki ummeed — warna khelna faydemand nahi.
6. **Statistical maturity** — Matlab: Abhi itne kam matured trades hain ki "win-rate accha hai" wali baat sirf ittefaq ho sakti hai, pakka nahi. Jaise 5 toss dekh kar coin ko "lucky" keh dena.
7. **Overfitting / data-snooping** — Matlab: Settings ko purane data pe itna fit kar diya ki woh sirf usi data pe achhi lagti hai, naye market mein fail. Jaise sirf ek hi question paper ratt kar board exam dene jaana.
8. **Regime robustness** — Matlab: Strategy sirf ek tarah ke market (jaise tezi) mein test hui hai; mandi ya volatile market mein chalegi ya nahi pata nahi. Jaise sirf garmi ke kapde dekh kar poore saal ka plan banana.

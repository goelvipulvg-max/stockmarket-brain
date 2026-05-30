---
name: gap-auditor
description: Audit the stockmarket-brain paper-trading engine for reliability and real-world (backtest-to-live) fidelity gaps, then produce a graded, leverage-ranked report — never changing code, flags, or trades. Use when the user asks to "run the gap audit", "audit gaps", "find reliability gaps", "reliability gap report", invokes /gap-auditor, or when the nightly auto-audit cloud routine fires. Scores eight fidelity dimensions (cost honesty, survivorship, look-ahead/point-in-time, liquidity reality, reward:risk, statistical maturity, overfitting/data-snooping, regime robustness) plus operational health (two-AI consensus, AI-SL distribution), cross-references already-deferred items so it does not re-propose them, gates low-maturity findings as low-confidence, writes a dated report to a reports branch, and sends a Telegram digest. Reports-only: it proposes, the user (Gaurav) decides.
license: MIT
metadata:
  author: Gaurav (stockmarket-brain)
  version: "1.0"
  surfaces: claude-code, api
---

# Gap Auditor

This skill is the **audit organ of the stockmarket-brain OS**. It does, on a schedule, what Gaurav has been doing by hand in the periodic reliability-gap sessions (e.g. `reports/reliability-gap-report-2026-05-29.md`): look at the engine and its recent paper-trading behaviour, find the places where the system is likely to underperform in a real NSE market, grade them, rank them by leverage, and hand back a report a human can act on.

It is a **control-plane** skill. The trading engine keeps running on its own GitHub Actions cadence; this skill only *observes and reports*. It sits above the engine, it does not become part of it.

## ⛔ Hard guardrails — read first, never violate

This is a trading system. The whole reason it is safe to run autonomously is that it cannot act. Hold this line absolutely:

- **NEVER edit engine code.** No fixes, no refactors, no "small" patches. Propose; do not apply.
- **NEVER flip a feature flag.** `USE_AI_SL`, `USE_PRICE_STRUCTURE_GATE`, `USE_VOLUME_GATE`, and any other constant stay exactly as they are. Flags are flipped by Gaurav after backtest validation, never by an audit run.
- **NEVER place, modify, or cancel a trade.** Not even a paper trade.
- **NEVER push to `main`.** Reports go to the `auto-audit` branch only (see Phase 4).
- **NEVER use a write-capable database credential.** Use the read-only key. If only a read-write key is available, read but issue zero writes, and flag in the report that a read-only key should be provisioned.

If a run ever feels like it "should just fix this one thing" — that feeling is the signal to write it as a recommendation, not to act. The bike still has training wheels on. Trust is earned one validated recommendation at a time.

## Phase 0 — Load context (narrow reads only)

The repo is large; do not read all of it. Read only what the audit needs, in this order:

1. `CONTEXT.md` (repo root) — the engine's own description of itself. This is the source of truth for architecture, tiers, and current state.
2. `reports/audit-history.md` — the consolidated memory of every past audit and hand-written reliability-gap session: what has been **shipped** (with commit refs), what is **parked** (with unblock conditions), what to **avoid**, and the **pending decisions**. Read this first — it is how you avoid re-proposing solved or knowingly-parked work. Then glance only at the single most recent dated report in `reports/` for anything not yet folded into the history file. (If `audit-history.md` does not exist yet, fall back to reading the two most recent files in `reports/`.)
3. The flag and risk-parameter sources. Flags are **defined** (with `false` defaults) in `agents/tier2_fundamental.py`, but their **effective runtime values** are set in `.github/workflows/tier2f.yml` — read the YAML to know the real state (currently `USE_AI_SL=true`, `USE_PRICE_STRUCTURE_GATE=false`, `USE_VOLUME_GATE=false`). Also record `SL_FLOOR_PCT`, `SL_CAP_PCT`, `TARGET_FLOOR_PCT` (in `tier2_fundamental.py`), `RR_FLOOR` (in `utils/reward_risk.py`), and `RISK_PCT` + `MAX_TRADE_PCT` (in `utils/position_sizer.py`). The audit reasons about what the flags imply, never about changing them.

Build a short in-memory "what is already known" list from steps 2–3 before scoring anything. A finding that duplicates a deferred item with no new evidence is noise, and noise erodes Gaurav's trust in the report.

## Phase 1 — Pull current engine state (read-only)

Query the live stores read-only. **Verify these source names against the actual schema on first run — they are best-known defaults, not confirmed:**

- **Supabase** — `paper_trades` (entries, exits, P&L, `quantity`, and a `raw_signal` JSONB blob that holds the AI-SL fields), `filings_log` (raw filing events, tiers, classification; Supabase-managed, no repo schema).
- **Neon** — the brain/analysis store, especially `filing_memory` (matured market-relative alpha outcomes) and `event_outcomes`.
- Optionally **QuestDB** for price/volume series if a dimension needs it.

Compute the inputs the rubric needs:
- Trade count and date range in scope (default: last 30 calendar days, plus all-time for maturity checks).
- `filing_memory` **matured** sample count (critical — see Statistical maturity).
- AI-SL canary signals — these live **inside the `raw_signal` JSONB** on `paper_trades`, not as top-level columns: `ai_sl_used` (via `raw_signal->>'ai_sl_used'`), rejection reasons (via `raw_signal->'ai_sl_validation'->>'rejection_reason'`), and the skip rate where `quantity <= 0` (the real top-level column is `quantity`; the code variable is `qty`).
- Outcome mix in `event_outcomes` (e.g. share of dividend events, share of names still listed) — the survivorship and base-rate signal.

If a store is unreachable, do not fail the whole run. Mark that dimension **DATA-UNAVAILABLE** and continue. A partial audit shipped is worth more than a perfect audit that errored out at 1 AM.

## Phase 2 — Score the eight dimensions + operational health

Read `references/gap-rubric.md` now. It defines, for each dimension, what it means, exactly how to check it in *this* system, the scoring scale, and the specific known signals to look for. Score every dimension PASS / WARN / FAIL with a one-line evidence string citing the concrete number or file you saw. No evidence → score is UNVERIFIED, not PASS.

The eight fidelity dimensions: cost honesty, survivorship integrity, look-ahead / point-in-time, liquidity reality, reward:risk discipline, statistical maturity, overfitting / data-snooping, regime robustness. Then a short operational-health block: two-AI consensus health and the AI-SL canary distribution.

## Phase 3 — Rank by leverage, gate by confidence

- **Rank** the WARN/FAIL findings by leverage = (real-world impact if unfixed) × (tractability of the fix). High-impact-and-easy goes to the top. This is what makes the report actionable instead of a flat checklist.
- **Confidence-gate.** If `filing_memory` matured samples are below a sound threshold (treat < ~50 as low), label any finding that depends on outcome statistics **LOW CONFIDENCE — insufficient maturity**, and say plainly that it should be re-checked once more samples mature rather than acted on now. Do not assert an edge or a defect from a handful of matured trades.
- **Cross-reference deferred work.** If a finding matches a known-deferred item (e.g. surprise-magnitude needing 5 quarters of fundamentals, or the B2 backtest waiting on maturity), do not list it as a fresh gap. Instead note one line under a "Still parked — no change" heading, with the unblock condition.

## Phase 4 — Write the report and send the digest

**Plain-language rule (applies to everything a human sees):** alongside the technical content, every top gap carries a **"Matlab:"** line in **simple Hinglish (Roman script)** — beginner-friendly, no jargon, with a short real-world Indian analogy. Pull these from the "Plain-Hinglish Matlab library" at the end of `references/gap-rubric.md` (adapt the wording to the actual evidence, keep the analogy); for novel or operational-health items, write a fresh one in the same style. The PASS/WARN/FAIL labels, evidence strings, and `file:line` references stay in English — those are facts; only the explanation layer is Hinglish.

Write a markdown report to `reports/auto-audit/auto-audit-YYYY-MM-DD.md`. Mirror the structure of Gaurav's hand-written gap reports so it reads familiar:

1. **Header** — date, trades-in-scope, matured-sample count, overall posture (one line: is the system getting more or less real-world-honest since the last audit?).
2. **Aasaan bhasha mein (real-world view)** — a plain-Hinglish summary placed high so it can be read first: one Hinglish "bottom line" sentence, then each top gap with its "Matlab:" line (the slightly longer real-world analogy version). This is the section a non-quant reader actually understands.
3. **Scorecard** — the eight dimensions + ops health, each PASS/WARN/FAIL with its evidence string (English).
4. **Top gaps, ranked by leverage** — for each: what it is, why it matters in a *live* NSE market (not in backtest), the concrete evidence, a one-line **Matlab:** (Hinglish), and a proposed direction (not a code change). Tie each to the relevant existing util/flag where one exists.
5. **Still parked — no change** — deferred items and their unblock conditions.
6. **Confidence note** — maturity status and what that means for trusting today's findings.

Commit it to the **`auto-audit` branch only** (create the branch if it does not exist; never commit to `main`). Then send a Telegram digest to the audit channel (`stockmarket_brain_bot` → chat `-1003901507651`): a one-line Hinglish posture line, then the top three ranked gaps, each with its PASS/WARN/FAIL label **and a short one-line "Matlab:" in Hinglish**, then the path to the full report. Keep each line short so it skims on a phone — Gaurav reads it in the morning and decides.

## Phase 5 — Update the history memory

Append a single dated line to `reports/audit-history.md` (on the `auto-audit` branch — never `main`, per Phase 4) capturing this run's headline: the date, the top gap, and any status change (e.g. a parked item that just unblocked, or a new gap first seen). This is what makes the audit *compound* — each night's finding informs the next, instead of starting blank. Keep the dated full reports too; together with this log they are the running history. This file is the lightweight first version of the future `os/wiki/` knowledge layer.

## Edge cases and failure modes

- **Sparse data.** Few trades or few matured samples → smaller, lower-confidence report, explicitly labelled. Never manufacture a finding to fill space.
- **Liquidity proxy ≠ volume confirmation.** `USE_VOLUME_GATE` is a *liquidity* proxy, not filing-reaction volume. Never claim the system has volume confirmation of a filing reaction when only the proxy exists. Calling this out correctly is itself a recurring high-value finding.
- **Adjusted-close subtlety.** `filing_memory` uses adjusted-close prices; adjustment uses information from after the trade date. Flag any place where adjusted prices feed an entry/exit decision (look-ahead), while noting adjusted close is fine for *outcome measurement*.
- **Dividend-heavy base rate.** If outcomes are dominated by dividend events and surviving names, treat headline win-rates as inflated and say so — this is the survivorship/base-rate trap.
- **Re-running same day.** Overwrite the same dated file rather than spawning duplicates; note "re-run" in the header.

## What this skill is NOT

It is not the research agent (that proposes improvements), not the fidelity analyzer (that quantifies the paper-to-live gap), and not an executor. It finds and ranks gaps and reports them. Keep its scope exactly that narrow — narrow scope is what keeps it trustworthy and cheap to run every night.

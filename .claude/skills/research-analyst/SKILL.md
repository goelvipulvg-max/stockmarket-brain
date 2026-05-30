---
name: research-analyst
description: Weekly, manual, reports-only "scout" for the stockmarket-brain OS — sibling to gap-auditor. Use this skill whenever Gaurav says "research-analyst chalao", "run research-analyst", "weekly research", "scout for improvements", "research the open gaps", or wants evidence-graded candidates to improve the trading system. It researches (1) SOLUTIONS to gap-auditor's OPEN gaps, (2) real-world-PROVEN share-market strategies, and (6) fills gap-auditor's deferred/blind-spot items — using only whitelisted sources, grading each finding's evidence, and writing a ranked Hinglish report to the auto-research branch. It NEVER changes engine code, flags, trades, or main; it proposes, Gaurav decides. NOT a trading agent, does NOT find gaps (that's gap-auditor), does NOT quantify paper-to-live fidelity (that's the future analyzer).
license: MIT
metadata:
  author: Gaurav (stockmarket-brain)
  version: "0.1"
  surfaces: claude-code, api
---

# Research Analyst

This skill is the **research scout of the stockmarket-brain OS** — the second control-plane organ, sibling to `gap-auditor`. Where `gap-auditor` looks *inward* and finds where the engine is likely to underperform, this skill looks *outward*: it researches **how to close** the gaps the auditor already found, and scouts **real-world-proven** ideas worth bringing in. It is a **scout, not an oracle** — it surfaces evidence-graded candidates and grades how trustworthy each is, so a human can decide.

It is a **control-plane** skill. The trading engine runs on its own GitHub Actions cadence; this skill only *observes, researches, and reports*. It sits above the engine; it never becomes part of it.

**Cadence:** weekly, run manually (Gaurav pastes a prompt; the Claude running this skill *is* the analyst — no model API wiring, no cost). v0 proves value over 2–3 runs; daily automation is a separate later phase.

## ⛔ Hard guardrails — read first, never violate

The whole reason this skill is safe to run is that it cannot act on the engine. Hold this line absolutely:

- **NEVER edit engine code, flip a flag, or place/modify/cancel a trade.** Not even a paper trade. Propose; do not apply.
- **NEVER commit to `main`.** Research output goes to the `auto-research` branch only (Phase 4). Always branch from `main`, commit only to `auto-research`, and return to `main`.
- **Reads are the entire power of this skill.** Reading public web pages (whitelisted sources) and the read-only databases via `smb_audit_ro` is all it may do. No writes to engine DBs; no engine-module import-and-run that could write.
- **Cite or drop.** A surfaced finding with no traceable, whitelisted source is a bug. If you can't cite it, don't surface it.
- **Quiet is a valid output.** If nothing clears the bar this week, say so in one line and stop. Manufacturing a finding to fill space erodes trust faster than silence.
- **Stay in your lane.** This is the OS **scout**. It does NOT find gaps (that's `gap-auditor`) and does NOT quantify paper-to-live fidelity (that's the future `realworld-fidelity-analyzer`). It is **NOT** the engine's dormant `tier1_news` agent and **NOT** the planned **Tier-1F** trading engine. No trading, ever.

If a run ever feels like it "should just wire this up" — that feeling is the signal to write a recommendation, not to act.

## The 3 lanes (v0 scope)

Research only these three — they compound directly with the auditor's output:

1. **System-improvement** — **solutions** to `gap-auditor`'s **OPEN** gaps (e.g. cost honesty, survivorship, the AI-SL canary).
2. **Proven strategies** — share-market approaches backed by **real evidence**, not theory or a single backtest.
3. **Auditor blind-spots** — fill what `gap-auditor` itself flagged as deferred / NOT MEASURED (e.g. how to *source analyst estimates* for surprise magnitude; how to *measure* two-AI consensus quality).

*(Daily market/regime, regulatory scanning, and other-traders lanes are deferred to a later phase. Keep the principle: market/regime info would only ever feed confidence interpretation, never a trade signal.)*

## Cross-branch reads & branch lifecycle (the engine tree is on `main`)

The auditor's latest report and its per-run log do **not** live on `main` — they live on the **`auto-audit`** branch (on `main`, `reports/auto-audit/` is empty and `audit-history.md` is the base ledger only). And this skill writes to its **own** branch, `auto-research`. So:

**Reading (no checkout needed):**
- The audit ledger — the superset (base sections + run-log), in **one** read:
  `git show auto-audit:reports/audit-history.md`
- The latest audit report: `git ls-tree --name-only auto-audit reports/auto-audit/` → pick the newest dated file → `git show auto-audit:reports/auto-audit/<latest>.md`
- This skill's own memory (if it exists): `git show auto-research:reports/research-history.md`

**Resilience:** if the `auto-audit` branch or its report is absent (early state / deleted), don't crash — fall back to `docs/stockmarket-brain-v3.1-master-plan.md` + the base `reports/audit-history.md` on `main`, and note "no prior audit report found" in the run. `auto-research`/`research-history.md` absent on the first run is expected.

**Writing (branch lifecycle):**
1. From `main`: `git checkout -b auto-research` (or `git checkout auto-research` if it exists).
2. Write the report and append the history line.
3. Stage **only** those two files. `reports/` is gitignored, so **`git add -f reports/auto-research/<report>.md`**. The history file **also needs `git add -f` on its first run**; after that it stages normally.
4. Commit **only** to `auto-research`. **Never** `main`. Push `auto-research`.
5. `git checkout main` to return the working tree to where Gaurav left it.

Before committing, verify the staged set is *exactly* the two research files — nothing from the engine or settings.

## Phase 0 — Load context (read-only)

Read only what the research needs, in this order:

1. **System-of-record** — `docs/stockmarket-brain-v3.1-master-plan.md` (the locked plan; the engine's description of itself). *(There is no `CONTEXT.md` in this repo — do not look for it. Side-note: `gap-auditor/SKILL.md:33` still references a non-existent `CONTEXT.md`; that's a known bug to fix separately — do not fix it from this skill.)*
2. **The audit ledger (cross-branch, one read)** — `git show auto-audit:reports/audit-history.md`. Four sections — **SHIPPED / PARKED / AVOID / PENDING DECISIONS** — plus the per-run audit log. Read it first; it is how you avoid re-proposing solved or parked work.
3. **The latest audit report (cross-branch)** — the newest `reports/auto-audit/<date>.md` on `auto-audit`: the dimension scorecard (PASS/WARN/FAIL) and ranked top gaps.
4. **Style + lens** — `.claude/skills/gap-auditor/SKILL.md` and `references/gap-rubric.md` for the Hinglish "Matlab:" discipline and the four skeptic lenses you'll reuse.
5. **This skill's own memory (cross-branch)** — `git show auto-research:reports/research-history.md` if it exists (so you don't re-surface dismissed ideas).
6. **Live grounding (read-only DB via `smb_audit_ro`)** — for *context only*, sample recent `paper_trades`, the `filing_memory` matured count, and the `event_outcomes` mix. Connect with `SMB_AUDIT_SUPABASE_URL` (Supabase: paper_trades, filing_memory) and `SMB_AUDIT_NEON_URL` (Neon: event_outcomes) from `.env`; parse the URL and connect via keyword args so an `@` in the password is safe. **Skip QuestDB** (localhost — unreachable). **RLS caveat:** `paper_trades` and `filing_memory` have RLS enabled; if a read returns **0 rows**, do **not** assume "empty" — **FLAG it** as a possible `BYPASSRLS`/policy regression.

Build a short "what's already known / already dismissed" list from steps 2–5 before researching anything.

## Phase 1 — Pick targets (define "OPEN" precisely)

An **OPEN** gap is one worth researching a solution for:

> **OPEN  =  (latest-audit FAIL/WARN gaps)  ∪  (audit-history "PENDING DECISIONS")  −  (SHIPPED ∪ PARKED ∪ AVOID)**

- **Lane 1:** pick **1–2 OPEN** gaps (good candidates from the latest audit: cost honesty, survivorship, the AI-SL canary).
- **Lane 6:** optionally one auditor blind-spot.
- **Lane 2:** open scouting for proven strategies relevant to the targets you picked.

Never target SHIPPED / PARKED / AVOID — re-proposing settled work is noise, and noise erodes Gaurav's trust.

## Phase 2 — Research (whitelisted + skeptical)

Use your own WebSearch / WebFetch tools, but only within the **source whitelist** (`references/research-rubric.md`). For each candidate finding, apply the research rubric: assign an **evidence grade**, run the **skeptic lenses** on the external claim, and check **fit-to-stack**. Recency-check (don't pass old work as new). Cite the real source or drop it.

**Bot-blocked official sources:** some official sources (e.g. NSE) block the basic fetch tool. Do NOT drop a legitimate official source just because the simple fetch times out — cite the known official methodology, and if exact figures matter, verify them with a READ-ONLY curl_cffi sidecar (the same cookie-spoofing the engine uses), never a write path.

## Phase 3 — Score, rank, and gate

- **Worth-it = Relevance × Evidence × Feasibility (fits the stack?) × Novelty (new-to-us).** Only items strong on *all four* surface — a brilliant idea we can't implement, or a proven one we already shipped, doesn't make the report.
- **Rank** survivors by **leverage = impact × tractability**, so the report leads with what's most worth doing.
- **Quiet-when-nothing:** if nothing clears the bar, write one honest line saying so and stop.

## Phase 4 — Write the report (`auto-research` branch, NEVER `main`)

Follow the branch lifecycle above. Write `reports/auto-research/research-YYYY-MM-DD.md`, mirroring the auditor's report shape so it reads familiar:

1. **Header** — date, which OPEN gaps / blind-spots were targeted, and a one-line posture (anything high-leverage this week, or a quiet week?).
2. **Aasaan bhasha mein** — a plain-Hinglish summary placed high: one bottom-line sentence, then each surfaced item's **"Matlab:"** line (beginner-friendly analogy).
3. **Findings, ranked by leverage** — for each: *What it is → Why it matters (which OPEN gap / blind-spot) → Evidence grade (Proven / Promising / Theory-only / Unverified) → What you'd consider or do (a direction, not a code change) → The catch / risk → Source(s) with links.*
4. **Nothing-worth-it note** — if applicable, state plainly that nothing cleared the bar and why.

Labels, evidence grades, and source links stay in English (facts); only the explanation layer is Hinglish. Reports-only — **"socho, karo mat."**

## Phase 5 — Update memory + hand off (no Telegram in v0)

- Append one dated line per outcome to `reports/research-history.md` (structure below) on `auto-research` (first run creates it with `git add -f`).
- **Output a short summary to the chat** (this replaces Telegram for v0): one Hinglish posture line, the top 1–3 surfaced items with evidence grade + a one-line Matlab, and a **full clickable GitHub URL** to the report:
  `https://github.com/goelvipulvg-max/stockmarket-brain/blob/auto-research/reports/auto-research/research-YYYY-MM-DD.md`
  (a bare repo-relative path won't be clickable).
- Return the working tree to `main`.

*(Telegram to an "SMB Research" channel is a later add — when it exists, send the same digest with a hardcoded chat-id, exactly as `gap-auditor` does with `-1003901507651`.)*

## research-history.md structure (compounding memory)

A four-section ledger, read every run so ideas don't repeat:

- **SURFACED** — date · finding · lane · evidence-grade · status
- **DISMISSED** — finding · **reason** (so it never re-surfaces)
- **EXPLORING** — Gaurav flagged this to dig into (may suggest new whitelist sources)
- **ADOPTED** — became a dev / backlog task (and which OPEN gap it closes)

This is what makes the scout *compound* — each week's research informs the next instead of starting blank. It is the lightweight first version of the future `os/wiki/` layer.

## What this skill is NOT

It is not `gap-auditor` (which *finds* gaps), not the future fidelity analyzer (which *quantifies* the paper-to-live gap), and not an executor or a trading agent. It researches solutions to known-open gaps and scouts proven external ideas, grades them, and reports. Keep its scope exactly that narrow — narrow scope is what keeps it trustworthy and cheap to run.

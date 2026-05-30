# Setup & Runbook — gap-auditor nightly OS

This is the human side. The skill itself is dropped into the repo; this file tells you how to wire it to run autonomously while you sleep, what to verify first, and how to read the output.

---

## 1. Where the files go (in your repo)

Drop the package into `C:\dev\stockmarket-brain\` so it lands at the repo root:

```
stockmarket-brain/
  .claude/
    skills/
      gap-auditor/
        SKILL.md
        references/
          gap-rubric.md
  reports/
    auto-audit/            <- created on first run (branch: auto-audit)
  SETUP-gap-auditor.md     <- this file (for your reference)
```

Skills at the repo-root `.claude/skills/` are auto-discovered by Claude Code, so the cloud routine will find it without extra config. The skill is self-scoping — it only reads `CONTEXT.md`, the latest `reports/`, the flags file, and the DBs — so even though the repo is large, each run stays narrow and cheap.

---

## 2. Pre-flight check — what's confirmed, what's left

The names were verified against the live code (read-only, 4 explore agents). Status:

- ✅ **Table names** — `paper_trades`, `filings_log`, `filing_memory`, `event_outcomes` all confirmed. (`filings_log` is Supabase-managed, no repo schema — fine.)
- ✅ **AI-SL fields** — confirmed these sit inside the `raw_signal` JSONB on `paper_trades` (not top-level columns); `quantity` is the real qty column. The skill now uses the correct JSONB paths.
- ✅ **Flags + risk params** — confirmed: flags defined in `agents/tier2_fundamental.py`, effective values in `.github/workflows/tier2f.yml` (`USE_AI_SL=true`, both gates `false`); `RR_FLOOR` in `utils/reward_risk.py`; sizing (`RISK_PCT` 0.00125, `MAX_TRADE_PCT` 0.025) in `utils/position_sizer.py`. Skill updated to read both flag locations.

Two small things still needed before the first run:

1. **Read-only DB key.** Provision a read-only Supabase + Neon credential just for the OS. The skill refuses to write, but a read-only key is the real guardrail (least privilege).
2. **Telegram channel.** Pick which of your 5 channels gets the morning digest, and have that channel's bot token + chat ID ready.

(Report branch stays `auto-audit` — no action needed unless you want a different name.)

---

## 3. Wire the nightly cloud routine (runs on Anthropic's cloud, machine can be off)

In claude.ai → Code → routines (or Claude desktop app → routines → **remote**), create a new routine:

- **Repo:** `goelvipulvg-max/stockmarket-brain`
- **Prompt:**
  > Run the gap-auditor skill. Read `.claude/skills/gap-auditor/SKILL.md` first, follow it exactly, and obey its hard guardrails (reports-only — no code, flag, trade, or `main` changes).
- **Model:** Opus 4.8 (extreme thinking) — this is a reasoning-heavy audit; give it the strongest model.
- **Schedule:** once daily, after the after-hours window closes. ~**23:30 IST** is good (results flow 3:30–11 PM IST, so this catches the full day). Cloud routines have a 1-hour minimum interval and ~15 runs/day on Max — one nightly run is well inside that.
- **Cloud environment → environment variables:** put the read-only DB URLs/keys + Telegram token + chat ID here. **Never** in the repo (the `.env` is git-ignored, so the cloud clone won't have it — env vars are how secrets reach the run).
- **Network access:** set to **full**. The run must reach Neon, Supabase, and Telegram, which aren't on the "trusted" allow-list. (Trade-off noted: full network is slightly less locked-down than trusted; acceptable here because the repo inputs are yours and the skill is read-only.)
- **Permissions:** the run only reads DBs and commits a report to the `auto-audit` branch. It will create a branch/commit, which persists; the rest of the clone is destroyed after the run.

---

## 4. The first 2–3 runs: watch them (don't nap yet)

This is the "bike method" — hold the handlebar before you let go.

- Hit **Run now** and watch the run end-to-end the first time. Check: did it read the right files? did it cite real numbers in the scorecard? did the report land on the `auto-audit` branch? did the Telegram digest arrive and read well on your phone?
- After each watched run, if something's off, tell me the exact symptom and I'll patch the SKILL.md / rubric — that's the feedback loop. Every fix makes the next run better, then you can let it run unattended.
- A failure is data: if a DB read errors, the skill marks that dimension DATA-UNAVAILABLE and continues, so you still get a partial report to learn from.

---

## 5. How to read the output each morning

Open the dated report on the `auto-audit` branch (or skim the Telegram digest):

- **Posture line** — is the system getting more or less real-world-honest since the last audit?
- **Aasaan bhasha mein** — har gap ka plain-Hinglish "Matlab:" + chhoti real-world misaal, taaki bina technical jhanjhat ke turant samajh aaye. Telegram digest mein bhi har top gap ke saath ek short Matlab line aayegi.
- **Scorecard** — eight fidelity dimensions + ops health, each PASS/WARN/FAIL with evidence.
- **Top gaps (ranked)** — act on these *you decide* — the OS only proposes. Tie each to the relevant util/flag.
- **Still parked** — deferred items + their unblock conditions (so they don't nag you).
- **Confidence note** — if maturity is low (we're at ~25 matured filing_memory rows), stats-based findings are flagged LOW CONFIDENCE with a re-check date. Don't over-act on a thin sample.

You then decide what becomes a real task in Antigravity. The OS never touches the engine.

---

## 6. Graduating autonomy later (optional, not now)

Once gap-auditor has earned trust over a few weeks — same way you flip a dormant flag only after B2 validates — you can let it open a *draft PR* with a proposed change for your review (the "Reports + auto-PR draft, you merge" tier). Until then: reports-only. Real-money trading is a separate, much higher bar and is out of scope for this OS.

---

## 7. (One-time) Build the audit memory from your past reports

The skill reads `reports/audit-history.md` each run as its memory — what's already shipped, parked, and decided — so it never re-proposes solved work. Create it **once, after the files are overwritten and before the first run**. In Antigravity, paste:

> Read every file in `reports/` (all reliability-gap reports, findings, and feasibility notes). Produce one compact file `reports/audit-history.md` with four sections — SHIPPED (with commit refs), PARKED (each with its unblock condition), AVOID, and PENDING DECISIONS — one line per item, no fluff. Don't change any other file, don't run anything, don't commit yet.

After this, every nightly audit appends its own one-line entry, so the memory compounds (the lightweight first version of the future `os/wiki/`). The exact branch this lives on — so the routine reads and updates the same copy — we'll finalize when wiring the routine.

## What's next in the OS (after this runs clean)

This is skill 1 of 3. Once the nightly plumbing is proven:
- **`research-analyst`** — reads recent performance + the latest audit, researches improvement candidates, proposes a prioritized list.
- **`realworld-fidelity-analyzer`** — quantifies the paper→live gap (cost-honest expectancy vs paper, survivorship-adjusted base rates, slippage estimate) so "best output in the real market" gets a number, not a vibe.
- **`os/wiki/`** — the compounding knowledge layer (Karpathy LLM-wiki style) that all three skills read and update, so deep analysis accumulates instead of resetting each night.

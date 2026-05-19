# Phase 3 — Shared Utilities — Execution Brief

**Date:** 2026-05-19
**Repo:** `goelvipulvg-max/stockmarket-brain`
**Local:** `C:\dev\stockmarket-brain\`
**Reference plan:** `docs/stockmarket-brain-v3.1-master-plan.md` §6 (on disk, commit `fca3e50`)
**Status:** Ready for Antigravity execution
**Precondition met:** Phase 1 (schema) + Phase 2 (capital ledger) complete & committed
(`fab2019`). Working tree clean.

---

## §0 What this brief is

This brief operationalizes **v3.1 §6 Phase 3 — Shared Utilities** into an
executable build plan. Phase 3 builds **7 utility modules in `utils/`** that both
trading engines (Tier-2F in Phase 5, after-hours in Phase 6) reuse. Building them
once as a shared layer is what prevents the v2 broken-dependency bug (engine code
depending on code defined in a later phase).

**Phase 3 writes no new DB objects** — all schema landed in Phase 1. These
utilities only *read* (yFinance, Neon, NSE, Supabase) and *compute*. No write-path
risk. Estimated ~2-3 hours across 2 batches.

All Phase 3 gates are **Layer-1 (Temp)** — verifiable immediately, no live market
data needed. Phase 3 does **not** wait on Monday's V0.1 / V0.7 result (per v3.1
§0.5).

---

## §1 Build approach

**2 batches, with a Layer-1 gate checkpoint between them.**

| Batch | Utilities | Why grouped |
|---|---|---|
| **A — data / lookup** | `trading_calendar`, `yfinance_chart`, `neon_fundamentals`, `fno_ban_list` | Independent fetchers/lookups; 3 have explicit Temp gates; no AI calls |
| **B — logic** | `filing_history`, `tiered_target_generator`, `ai_consensus` | Aggregation + decision logic; `ai_consensus` is the heaviest (API calls, JSON parsing, fallbacks) |

**Workflow rules (carried from Phase 2 — non-negotiable):**

1. **Recon first, read-only.** Run §2 recon *before* building any file. STOP and
   report findings. Recon never edits or overwrites anything.
2. **Never overwrite an existing file.** If recon finds any of the 7 files (or a
   client like `supabase_client.py`) already exists — STOP, report, do not
   replace. Reuse existing clients; never recreate them.
3. **One file at a time.** Build one utility → present the diff → wait for
   explicit approval → next. Never "allow all edits".
4. **Batch A fully done + gates green before Batch B starts.**
5. **No inline `python -c "..."`** — PowerShell ~965-byte limit + quote-escaping
   breaks it. Write all test/check logic into a `.py` file, run with
   `.venv\Scripts\python.exe`.
6. **Python always via `.venv\Scripts\python.exe`.** `load_dotenv(override=True)`
   where env vars are read.

---

## §2 Recon phase (read-only — run first, then STOP & report)

Recon answers these before any file is written. Report findings back before building.

1. **`utils/` contents** — does `trading_calendar.py`, `yfinance_chart.py`,
   `neon_fundamentals.py`, `filing_history.py`, `fno_ban_list.py`,
   `tiered_target_generator.py`, or `ai_consensus.py` already exist? If yes — do
   not overwrite; report.
2. **Existing RSI/MACD code** — `agents/tier2_signals.py` already computes RSI +
   MACD via Yahoo Finance (v3.1 §1.6). Read that indicator logic.
   `yfinance_chart.py` must **consolidate/reuse** it, not invent a divergent
   implementation.
3. **Existing `.NS` company_profiles lookup** — `utils/gap_calculator.py` and
   `agents/filing_memory_sync.py` already append `.NS` correctly when querying
   Neon `company_profiles` (v3.1 §3.4b). Read that pattern. `neon_fundamentals.py`
   must reuse it.
4. **Existing Neon client** — identify how `gap_calculator.py` connects to Neon.
   Reuse that client/connection. Do not create a second one.
5. **Existing Supabase client** — `utils/supabase_client.py` exists (Phase 2 used
   it). Reuse as-is.
6. **Existing DeepSeek call wrapper** — `agents/tier0_filings.py` calls DeepSeek
   and got retry logic in Phase 0 (`max_retries=2`, 2s backoff, retries on empty
   response + JSON-parse failure). Read it. `ai_consensus.py`'s DeepSeek path must
   reuse the same retry pattern.
7. **`research_cache` schema** — confirm column names (symbol, response_text,
   filing date, event/category). v3.1 §1.3: ~50% of rows have NULL
   `response_text` — `filing_history.py` must filter those out.
8. **Library availability** — check `requirements.txt` / `.venv` for: `yfinance`
   (system already uses Yahoo Finance, so likely present), and a market-calendar
   library such as `pandas-market-calendars` (relevant to §7 sub-decision 1).
9. **NSE F&O ban list source** — identify whether any existing code already
   fetches the NSE F&O ban list; if not, note the candidate source URL for
   `fno_ban_list.py` (see §7 sub-decision 2).

---

## §3 Batch A — Data / Lookup Utilities

### A1 — `utils/trading_calendar.py`  (Gate V3.4)

NSE trading-day calendar. Holiday + weekend aware. Needed by the Phase 4b
`filing_memory` outcome-window backfill, so it must be correct.

**Public functions:**
- `today()` — today's date (or most recent trading day).
- `next_trading_day(date)` — the next NSE trading day after `date`.
- `add_trading_days(date, n)` — `date` plus `n` trading days, skipping weekends
  and NSE holidays.
- `is_trading_day(date)` — bool.

**Design notes:**
- Weekends (Sat/Sun) are always non-trading.
- NSE holidays come from a published yearly list — see §7 sub-decision 1 for the
  library-vs-hardcoded choice. If hardcoded, cover **2026** at minimum and log a
  clear warning when asked about a date in an uncovered year.

**Gate V3.4:** `add_trading_days()` correctly skips weekends AND NSE holidays
(test across a known holiday, e.g. a 2026 NSE holiday, and across a weekend).

### A2 — `utils/yfinance_chart.py`  (Gate V3.1)

2-year daily chart for a ticker → technical snapshot.

**Public function:**
- `get_chart_snapshot(ticker)` → dict with: `rsi_14`, `macd` (line/signal/hist),
  `support`, `resistance`, `trend`, `last_close`, and the 2-year series the
  indicators were computed from.

**Design notes:**
- Ticker format `.NS` (e.g. `RELIANCE.NS`).
- **Reuse the RSI/MACD logic from `tier2_signals.py`** (recon step 2) — do not
  re-derive a different formula.
- Use yFinance **adjusted close** for indicators (split/bonus safe — same
  principle as `filing_memory`).
- On fetch failure: raise a clear exception (the engine decides whether to skip);
  do not return silent zeros.

**Gate V3.1:** `get_chart_snapshot("RELIANCE.NS")` returns RSI / MACD / support /
2-year data — values populated, not None/zero.

### A3 — `utils/neon_fundamentals.py`  (no Phase 3 gate — smoke-checked)

`company_profiles` lookup from Neon.

**Public function:**
- `get_fundamentals(symbol)` → dict: `sector`, `market_cap_cr`,
  `business_summary`. Returns `None` if the symbol is not in NIFTU500.

**Design notes:**
- **Append `.NS`** before querying `company_profiles` — reuse the gap_calculator
  pattern (recon step 3). A bare symbol returns nothing (this is the Guardian's
  100%-fail bug — do not repeat it).
- `risk_factors` and `moat_analysis` columns are **100% NULL** (v3.1 §1.3) — do
  not read or rely on them.

**Smoke check:** `get_fundamentals("RELIANCE")` returns a sector string and a
non-null market cap.

### A4 — `utils/fno_ban_list.py`  (Gate V3.3)

NSE F&O ban-list check.

**Public function:**
- `is_in_ban(symbol)` → bool.
- `get_ban_list()` → list of banned symbols.

**Design notes:**
- **Fail-open** — on any fetch/parse error, return "not banned" / empty list.
  Never block a trade because the ban list was unreachable.
- **2-hour cache** — do not re-fetch on every call.
- Source: see §7 sub-decision 2.

**Gate V3.3:** returns a list on success; on a simulated fetch error, fails open
(returns empty / "not banned"), does not raise.

### → Checkpoint after Batch A

Run a `tests/test_phase3_batchA.py` script (a real `.py` file, run with
`.venv\Scripts\python.exe`) covering **V3.1, V3.3, V3.4** + the A3 smoke check.
All green → STOP, report → then Batch B.

---

## §4 Batch B — Logic Utilities

### B1 — `utils/filing_history.py`  (Gate V3.2)

Per-company filing history aggregated from Neon `research_cache`. This is the
honest answer to Gap 1 — `research_cache` holds scattered per-filing summaries;
this utility groups them per company so an agent can see a company's 2-year
filing history.

**Public function:**
- `get_filing_history(symbol, limit=N)` → ordered list / compact brief of past
  filing summaries for that company.

**Design notes:**
- **Skip rows with NULL `response_text`** (~50% of `research_cache` — v3.1 §1.3).
- `research_cache` is a frozen cache (no new writes) — this is read-only and that
  is expected.
- Keep the output compact / AI-ready — a brief, not a raw dump (same philosophy
  as `get_filing_memory_brief`).

**Gate V3.2:** `get_filing_history("RELIANCE")` returns aggregated past filings
(non-empty for a well-covered symbol).

### B2 — `utils/tiered_target_generator.py`  (no Phase 3 gate — smoke-checked)

T1/T2/T3/T4 target levels from a consensus signal.

**Public function:**
- `generate_targets(entry_price, direction, conviction)` → dict with
  `t1`, `t2`, `t3`, `t4`, `stop_loss`.

**Design notes:**
- Reference levels (v3.1 §8.2): T1 ≈ 3%, T2 ≈ 5%, T3 ≈ 10%, T4 ≈ 20%+ only when
  `conviction == HIGH`.
- **Direction-aware** — for BUY, targets are above entry; for SELL/short, below.
  Reuse the `_dir_price` concept from Phase 0 (`BUY = entry*mult`,
  `SELL = entry*(2-mult)`) so short targets are priced correctly.

**Smoke check:** for a BUY, `t1 < t2 < t3 < t4` and all above entry; for a SELL,
inverted and all below entry; T4 only present when conviction is HIGH.

### B3 — `utils/ai_consensus.py`  (no Phase 3 gate — smoke-checked; verified live in Phase 5)

The 2-model brain: Haiku 4.5 analyst + DeepSeek V4 Flash verifier + consensus +
solo fallbacks. The heaviest utility — build last, review carefully.

**Public functions:**
- `run_analyst(context)` — Haiku 4.5: directional bias, expected move, horizon,
  confidence, reasoning.
- `run_verifier(context, analyst_output)` — DeepSeek V4 Flash: independent
  CONFIRM / CHALLENGE with agreement score.
- `determine_consensus(haiku, flash)` — consensus decision.
- `get_consensus(context)` — orchestrator: analyst → verifier → consensus, with
  fallback handling.

**Consensus logic (v3.1 §7.3):**
```
not haiku.tradeable                       -> SKIP ("not tradeable")
flash.verdict == CHALLENGE and
    flash.agreement_score < 70            -> SKIP ("verifier challenged")
haiku.directional_bias != flash bias      -> SKIP ("direction mismatch")
avg(haiku.confidence, flash.confidence)
    < 65                                  -> SKIP ("avg confidence < 65")
otherwise                                 -> PROCEED ("consensus reached")
```

**Solo fallback modes (v3.1 §7.4):**
- Anthropic down → `SOLO_DEEPSEEK`: DeepSeek does both analyst + verifier roles,
  apply a 10% confidence haircut.
- DeepSeek down → `SOLO_HAIKU`: Haiku alone, 10% confidence haircut.
- Both down → skip + log.

**Design notes:**
- **Reuse the DeepSeek retry wrapper from `tier0_filings.py`** (recon step 6) —
  same `max_retries`/backoff, retries on empty response + JSON-parse failure.
- Prompt templates: if any use `.format()`, double-brace escaping (`{{ }}`)
  belongs **only** in the `.txt`/string template, **never** in Python source
  (this caused a `TypeError` in Phase 0 — do not repeat).
- Confirm the exact Haiku model id available to the project (see §7 sub-decision 3).

**Smoke check:** feed mock `haiku` + `flash` dicts through `determine_consensus()`
for each branch (SKIP-not-tradeable, SKIP-challenge, SKIP-mismatch,
SKIP-low-confidence, PROCEED) and confirm the right outcome; confirm a solo
fallback path runs with one API toggled off.

### → Checkpoint after Batch B

Extend the test script (`tests/test_phase3_batchB.py`) covering **V3.2** + the B2
and B3 smoke checks. All green → STOP, report.

---

## §5 Verification gates — summary

| Gate | Utility | Check | Layer |
|---|---|---|---|
| V3.1 | yfinance_chart | RELIANCE.NS → RSI/MACD/support/2-year data | Temp |
| V3.2 | filing_history | RELIANCE → aggregated past filings | Temp |
| V3.3 | fno_ban_list | returns list; fail-open on error | Temp |
| V3.4 | trading_calendar | add_trading_days skips weekends + NSE holidays | Temp |
| (smoke) | neon_fundamentals | RELIANCE → sector + market cap | Temp |
| (smoke) | tiered_target_generator | BUY/SELL target ordering correct | Temp |
| (smoke) | ai_consensus | determine_consensus branches + solo fallback | Temp |

Gates state **PASS / FAIL / BLOCKED** honestly, each backed by actual test
output. No gate is called PASS without evidence.

---

## §6 Carry-forward pitfalls (Phase 0 / Phase 2 lessons — do not repeat)

- **`₹` symbol crashes on Windows cp1252.** Use `Rs.` in all strings/logs/notes.
- **No inline `python -c "..."`** — write logic into a `.py` file, run with
  `.venv\Scripts\python.exe`.
- **`{{ }}` double braces** belong only in `.txt` prompt templates for
  `.format()`, never in Python source.
- **Recon is read-only** — never overwrite an existing file or client
  (`supabase_client.py` overwrite was caught and stopped in Phase 2).
- **One git command at a time** on Windows.
- **`.venv\Scripts\python.exe`** for every Python run; `load_dotenv(override=True)`
  where env is read.

---

## §7 Build-time sub-decisions to confirm during recon

These are not blockers — surface them at the recon STOP and decide before the
relevant file is built.

1. **`trading_calendar` holiday source** — if `pandas-market-calendars` (or
   similar with an NSE calendar) is already available, prefer it (future years
   handled automatically). If not, hardcode the 2026 NSE holiday list and log a
   warning for uncovered years. Recon step 8 answers availability.
2. **`fno_ban_list` source** — confirm the NSE F&O ban-list source (existing code
   path, or NSE's published daily ban list). Whatever the source, fail-open is
   mandatory.
3. **`ai_consensus` Haiku model id** — confirm the exact Anthropic Haiku 4.5
   model string the project's API key has access to, before wiring `run_analyst`.

---

## §8 Execution sequence (recap)

1. **Recon** (§2) — read-only → STOP & report findings + §7 sub-decisions.
2. **Batch A** — build A1 → A2 → A3 → A4, one file at a time, approve each.
3. **Checkpoint A** — run `test_phase3_batchA.py`; V3.1/V3.3/V3.4 + A3 smoke green
   → STOP & report.
4. **Batch B** — build B1 → B2 → B3, one file at a time, approve each.
5. **Checkpoint B** — run `test_phase3_batchB.py`; V3.2 + B2/B3 smoke green
   → STOP & report.
6. **Git-commit Phase 3** (separate `feat(phase-3)` commit — message drafted at
   that point, file-based to avoid the PowerShell limit).
7. **Next:** Phase 4 — Memory Foundation + Seeding. *V0.7 (filing_memory sync)
   must be diagnosed before Phase 4 begins.*

---

*Brief prepared 2026-05-19. Operationalizes v3.1 §6. Recon-first, confirm-first,
one-file-at-a-time — same discipline as the verified Phase 2 build.*

# Phase 4 — Batch B Execution Brief — Outcome Backfill + Retrieval Brief

**For:** Antigravity (Claude Code) execution
**Repo:** `goelvipulvg-max/stockmarket-brain` · Working dir `C:\dev\stockmarket-brain\`
**Reference:** `docs/stockmarket-brain-v3.1-master-plan.md` §6 Phase 4b + §6 Phase 4c
**Scope:** Batch B only — `filing_memory` outcome backfill job (Phase 4b) + `get_filing_memory_brief()` retrieval utility (Phase 4c). Phase 5 (live engine) is the next brief — do NOT build it here.
**Precondition:** Batch A complete (commit `113703a`, 10/10 gates PASS). `filing_memory` has 146 rows, all with `base_price IS NULL` and outcome columns at schema defaults (`PENDING`).

---

## 0. READ THIS FIRST — Reality Corrections (recon required)

Master plan §6's Phase 4b/4c code is **pseudocode**, not runnable Python. Four
assumptions in it MUST be verified by recon (STEP 0) before STEP 1 — Batch A
proved that trusting §6's printed code without recon costs a full rebuild.

| # | Master plan assumed | Likely reality | Required handling |
|---|---|---|---|
| R1 | `yf_adjusted_open()` / `yf_adjusted_close()` helpers exist | These are pseudocode shorthand — almost certainly do NOT exist as named functions. `utils/yfinance_chart.py` (Phase 3) likely exposes 2-year chart fetch, not single-date OPEN/CLOSE | Recon: inspect `utils/yfinance_chart.py` exports. Either (a) reuse an existing primitive, or (b) build a small wrapper inside `agents/filing_memory_backfill.py` that calls `yf.Ticker(sym).history(start=, end=)` and returns adjusted OPEN/CLOSE for a date. Do NOT create a new `utils/` helper just for this — keep it local until a second consumer appears. |
| R2 | `trading_calendar.today()` and `next_trading_day()` exist | V3.4 only verified `add_trading_days()`. The other two may or may not exist | Recon: `grep` exports of `utils/trading_calendar.py`. If missing, add them — `today() = datetime.now(IST).date()`, `next_trading_day(d) = add_trading_days(d, 1)`. Commit those additions as part of Batch B (they belong in the calendar module, not the backfill agent). |
| R3 | Per-row yfinance fetch is acceptable | 146 rows × up to 4 dates × 2 tickers ≈ 1,168 yfinance calls. Yahoo unofficially rate-limits; per-row would be slow and brittle | **MIRROR `memory_seed.py`'s sector-lookup pattern** — one yfinance `Ticker(sym).history(start=earliest_filing_date, end=today)` call per UNIQUE symbol, store as a date-indexed dict, then look up each window date in memory. NIFTY (`^NSEI`) fetched ONCE across the full date range. |
| R4 | `filing_memory.symbol_base` works directly with yfinance | yfinance needs `.NS` suffix for NSE stocks. `symbol_base` in this table is bare (Batch A guarantee) | Append `.NS` at fetch time: `yf.Ticker(row["symbol_base"] + ".NS")`. Do NOT mutate `symbol_base` in the table. |

**Plus one Batch B-specific reality (V4.7 caveat):** Today is 20-May-2026.
`filing_memory`'s 146 rows are recent — the age distribution is unknown, but
many windows (especially 30d) will not have matured. **V4.7's test of
`get_filing_memory_brief()` must be structural-first, data-conditional-second:**
the function must run cleanly and return the correct *shape* even when no rows
have `outcome_10d_status='FILLED'`. If FILLED rows exist for a sample symbol,
also verify the brief's content. If none exist, that is not a failure — it is
the design intent ("No matured material filing history for this company.").

### Idempotency model — LOCKED

Three Batch A files used three different idempotency strategies. Batch B's
`filing_memory_backfill.py` uses a **fourth pattern: update-only, no inserts.**
Safety comes from filter predicates, not from upsert/conflict handling:

- Base-price pass: `WHERE base_price IS NULL` — already-priced rows are filtered out.
- Window pass: `WHERE outcome_Nd_status = 'PENDING'` — already-FILLED/FAILED rows are filtered out.

A re-run on the same day is therefore a no-op for rows already processed. A
re-run after new windows mature naturally fills them. **No `on_conflict` clause
is needed — Batch B never INSERTs into `filing_memory`, only UPDATEs.**

### Outcome semantics — reused from Batch A

`swing_verdict` uses the **same ±3% threshold** as `trade_memory_v2.outcome`'s
TARGET_HIT/SL_HIT rule (Batch A §0). One convention across the whole memory
system. The verdict is computed ONLY when `outcome_10d_status='FILLED'` —
earlier windows do not produce a verdict, and the rule is intentionally a hard
mechanical compute, never an AI guess.

```
alpha_10d > +3   → POSITIVE
alpha_10d < -3   → NEGATIVE
otherwise        → NEUTRAL
```

---

## Working agreements (carried verbatim from Batch A, do not deviate)

- **Confirm-first, one file at a time.** Build/edit ONE file, then STOP for an
  individual edit approval. Never "allow all edits" — always approve each edit.
- **Recon before assuming.** If anything diverges from this brief, STOP and
  report — do not silently self-correct.
- **DDL only via Supabase Dashboard SQL Editor.** No DDL through supabase-py.
  Batch B has NO new DDL — `filing_memory` schema already has all needed columns
  (verified V1.5b green in Batch A).
- **Throwaway scripts** (`scripts/recon_*`, `scripts/check_*`, `scripts/smoke_*`)
  are deleted after use, never committed. Real tests (`tests/test_phase4_*`) ARE
  committed.
- **Windows cp1252:** `₹` crashes — use `Rs.` in all printed/stored strings.
  `—` (em-dash) crashes too — use `--` in prints. Inline `python -c` hits
  PowerShell's ~965-byte limit — write logic to a `.py` file and run with
  `.venv\Scripts\python.exe` + `PYTHONPATH=C:/dev/stockmarket-brain`.
- **Git:** one command at a time. Add files explicitly (never `git add .`).
  Multi-line commit messages via heredoc. **After the commit, an explicit
  `git push`** — Antigravity does NOT auto-push. Verify with `git log --oneline -3`.
- Machine-local files (`.claude/settings.local.json`, `scheduled_tasks.lock`,
  `dumps/`) are never committed.
- **No gassing** — every gate backed by real output. State FAIL/BLOCKED honestly.

---

## STEP 0 — Recon (read-only, no commits)

Create a throwaway `scripts/recon_phase4b.py`. It must answer 5 questions and
print a clear report. Delete the script after STEP 0 completes.

**Questions to answer:**

1. **R1 — yfinance helper surface.** What does `utils/yfinance_chart.py` export?
   Specifically: is there any function that returns adjusted OPEN or adjusted
   CLOSE for a specific date (not a 2-year chart blob)? Print the module's
   public callables and a short note on whether single-date OPEN/CLOSE is
   already available or needs a small local wrapper in the backfill agent.
2. **R2 — trading_calendar surface.** Print the public callables of
   `utils/trading_calendar.py`. Confirm presence/absence of `today()` and
   `next_trading_day()`. If either is missing, note that STEP 1 must add it
   to that module.
3. **R3/R4 — filing_memory row state.** Run:
   - `SELECT count(*), count(*) FILTER (WHERE base_price IS NULL) FROM filing_memory;`
   - `SELECT symbol_base FROM filing_memory LIMIT 10;` — confirm symbols are
     bare (no `.NS` suffix), as Batch A guaranteed.
   - `SELECT min(filing_date), max(filing_date), count(DISTINCT symbol_base) FROM filing_memory;`
   - **Age histogram:** how many filings are aged ≥5 / ≥10 / ≥30 trading days
     today? Use simple calendar days as a rough proxy in the recon script
     (e.g. `filing_date <= today - 7 days`, `<= today - 14 days`, `<= today - 42 days`).
     This sets the expectation for STEP 4's FILLED counts.
4. **V4.7 readiness.** Pick one symbol from `filing_memory` that the histogram
   above shows is likely to have a ≥10 trading-day-old filing. Note it for
   STEP 7's smoke test. If NO symbol qualifies (all filings too recent), note
   that V4.7 will run in structural-only mode.
5. **yfinance install.** Run `python -c "import yfinance; print(yfinance.__version__)"` —
   confirm it is installed in the venv. (It must be — `utils/yfinance_chart.py`
   uses it. This is a safety check, not an expected failure.)

**Report format:** print each answer with a clear `[R1]`, `[R2]`, `[R3/R4]`,
`[V4.7]`, `[YF]` tag and a one-line conclusion. Then delete the script.

**→ STOP after running. Paste the full recon report. Do not proceed to STEP 1
until the user has reviewed it.**

---

## STEP 1 — `agents/filing_memory_backfill.py` — Pass 1 ONLY (base price)

Create `agents/filing_memory_backfill.py`. STEP 1 implements ONLY Pass 1 — the
base-price filler. Pass 2 (outcome windows) is added in STEP 3.

If STEP 0's `[R2]` showed that `utils/trading_calendar.py` is missing `today()`
and/or `next_trading_day()`, **add those functions to that module first** as a
separate edit (one edit, ask for approval, then move to `filing_memory_backfill.py`).
The calendar additions are tiny — `today()` returns `datetime.now(tz=IST).date()`;
`next_trading_day(d)` is `add_trading_days(d, 1)`. Match whatever existing
patterns/imports the module uses.

**Function `backfill_base_prices()`:**

1. **Read PENDING base-price rows from Supabase:**
   `SELECT id, symbol_base, filing_date FROM filing_memory WHERE base_price IS NULL`.
2. **Today's date** via `trading_calendar.today()`.
3. **Compute target base_date** for each row: `next_trading_day(filing_date)`.
   Skip rows where `base_date > today` (next session has not happened yet) —
   count them as `pending_future`.
4. **Group remaining rows by `symbol_base`.** Compute the per-symbol date range
   needed: `min(base_date)` to `max(base_date)` across that symbol's rows.
5. **Per-symbol yfinance fetch — ONE call per symbol** (R3):
   - `yf.Ticker(symbol_base + ".NS").history(start=range_start, end=range_end + 1d, auto_adjust=True)` —
     `auto_adjust=True` returns split/dividend-adjusted prices, which is the
     correct semantic for Phase 4 (master plan §4.4b: "adjusted close",
     "split/bonus safe").
   - Index the returned DataFrame by date string (`YYYY-MM-DD`) → dict of
     `{date_str: {"Open": ..., "Close": ...}}`. Handle empty DataFrame (delisted /
     bad symbol) by marking all that symbol's rows as `fetch_failed` and moving
     on — do NOT crash the whole job.
6. **Fetch NIFTY ONCE** for the full date range across all symbols:
   `yf.Ticker("^NSEI").history(start=overall_min, end=overall_max + 1d, auto_adjust=True)`,
   same date-indexed dict.
7. **Per row, look up the base_date in the dicts:**
   - `r_base = stock_dict[base_date_str]["Open"]`
   - `n_base = nifty_dict[base_date_str]["Open"]`
   - If either is missing (holiday gap, mid-fetch missing day): mark row as
     `lookup_failed` and skip the update. Do NOT raise.
8. **Update Supabase** in small batches:
   `sb.table("filing_memory").update({"base_price": float(r_base), "nifty_base": float(n_base), "updated_at": now_iso()}).eq("id", r["id"]).execute()`.
   Per-row update is fine here (Supabase REST does not support multi-row update
   by varying values in one call); the row count is small (≤146).
9. **Print summary:**
   - rows read with base_price NULL
   - pending_future (base_date > today)
   - per-symbol fetch count and failures
   - rows updated successfully
   - lookup_failed count
   - fetch_failed count

**Cost discipline:** if a symbol's yfinance call raises, log it as
`[WARN] yf fetch failed: <symbol>: <error>` and continue — one bad symbol must
NEVER abort the job. The whole point of update-only idempotency is that a
re-run picks up what failed.

Add `if __name__ == '__main__': backfill_base_prices()` so it can be run
directly. Pass 2 will add a second call below it in STEP 3.

**→ STOP after creating the file (and after the optional `trading_calendar.py`
edit if STEP 0 flagged it). Wait for edit approval. Do NOT run yet.**

---

## STEP 2 — Run Pass 1 + verify

1. Run: `$env:PYTHONPATH="C:/dev/stockmarket-brain"; .venv\Scripts\python.exe agents\filing_memory_backfill.py`
2. Paste the full summary output.
3. **Sanity-check before STEP 3:**
   - "rows updated" + "pending_future" + "lookup_failed" + "fetch_failed"
     should ≈ "rows read".
   - At least SOME rows should have updated successfully (if 0, recon was wrong
     — STOP and investigate). Acceptable range based on STEP 0's histogram.
4. **Spot-check Supabase:**
   `SELECT count(*) FILTER (WHERE base_price IS NOT NULL), count(*) FILTER (WHERE base_price IS NULL) FROM filing_memory;` —
   confirm the NOT-NULL count matches what STEP 2's summary reported.

**→ STOP. Report the output + spot-check numbers.**

---

## STEP 3 — Pass 2 (outcome windows + swing_verdict)

Add a second function `backfill_outcome_windows()` to the SAME file
`agents/filing_memory_backfill.py`.

1. **Read rows ready for outcome backfill:**
   `SELECT id, symbol_base, filing_date, base_price, nifty_base, outcome_5d_status, outcome_10d_status, outcome_30d_status FROM filing_memory WHERE base_price IS NOT NULL AND (outcome_5d_status='PENDING' OR outcome_10d_status='PENDING' OR outcome_30d_status='PENDING')`.
2. **Today** via `trading_calendar.today()`.
3. **Per row, determine which windows are ripe:**
   - For each window N ∈ {5, 10, 30} where the corresponding `outcome_Nd_status='PENDING'`:
     `target_date = trading_calendar.add_trading_days(filing_date, N)`.
     If `target_date > today`, leave PENDING (skip). Otherwise, mark as ripe.
4. **Group ripe windows by `symbol_base`.** For each symbol, compute the date
   range needed: from the earliest ripe target date to the latest, across all
   that symbol's ripe windows. ONE yfinance call per symbol (R3, same as Pass 1).
   Build a date-indexed dict.
5. **Fetch NIFTY ONCE** for the full overall range, same as Pass 1.
6. **Per row, per ripe window:** look up `stock_close` and `nifty_close` for the
   target date. If either is missing, set that window's `outcome_Nd_status` to
   `FAILED` (master plan §6 Phase 4b explicitly maps fetch failure to FAILED,
   not PENDING) and continue to the next window. Otherwise compute:
   ```
   raw_move = (stock_close - base_price) / base_price * 100
   nifty_move = (nifty_close - nifty_base) / nifty_base * 100
   alpha = raw_move - nifty_move
   ```
   Round to 2 decimals. Stage these into a `updates` dict for the row:
   `price_5d`, `nifty_5d`, `raw_move_5d`, `alpha_5d`, `outcome_5d_status='FILLED'`
   (same for 10d, 30d).
7. **Compute `swing_verdict` ONLY when this run fills the 10d window:**
   - If `updates.get("outcome_10d_status") == "FILLED"`:
     - `a = updates["alpha_10d"]`
     - `swing_verdict = "POSITIVE" if a > 3 else "NEGATIVE" if a < -3 else "NEUTRAL"`
     - Add to `updates`.
   - **Do NOT** set/overwrite `swing_verdict` for rows whose 10d was already
     FILLED in a previous run — they already have a verdict.
   - **Do NOT** compute verdict on FAILED 10d windows — only FILLED.
8. **Update Supabase** per row: `update(updates).eq("id", r["id"])`. Add
   `"updated_at": now_iso()` to every update.
9. **Print summary:**
   - rows read
   - ripe windows per N (5/10/30)
   - FILLED counts per N
   - FAILED counts per N
   - skipped-immature counts per N
   - swing_verdict distribution (POSITIVE / NEGATIVE / NEUTRAL) for verdicts
     written THIS RUN

Add a call to `backfill_outcome_windows()` to the `__main__` block AFTER
`backfill_base_prices()`, so a single run does both passes in order.

**→ STOP after editing the file. Wait for edit approval.**

---

## STEP 4 — Run Pass 2 + verify

1. Run `agents\filing_memory_backfill.py` again. Pass 1 will be a near-no-op
   (most rows already have `base_price`); Pass 2 runs in full.
2. Paste the full summary output (both passes).
3. **Sanity checks:**
   - FILLED counts should roughly match STEP 0's age histogram. If STEP 0 said
     "≥10 trading days old: 40 rows" and Pass 2 reports `FILLED_10d=3`, that is
     a red flag — STOP and investigate.
   - FAILED counts should be 0 or very small. A spike is a signal of bad
     symbols / delisted tickers.
   - swing_verdict should be non-degenerate (not all NEUTRAL) IF there are
     enough FILLED 10d rows. If FILLED_10d is 0, no verdicts will be written
     this run — that is correct, not a bug.
4. **Spot-check Supabase:**
   ```sql
   SELECT
     count(*) FILTER (WHERE outcome_5d_status='FILLED')  AS f5,
     count(*) FILTER (WHERE outcome_10d_status='FILLED') AS f10,
     count(*) FILTER (WHERE outcome_30d_status='FILLED') AS f30,
     count(*) FILTER (WHERE swing_verdict IS NOT NULL)   AS verdicts
   FROM filing_memory;
   ```
   Confirm `f10 == verdicts` (every FILLED 10d row got a verdict, no others did).
5. **Idempotency check:** run the script a SECOND time. Pass 1 should report 0
   updates; Pass 2 should report 0 FILLED additions (because all ripe windows
   are already FILLED). This proves the update-only-no-inserts idempotency model.

**→ STOP. Report both runs' output + spot-check numbers.**

---

## STEP 5 — GitHub Actions workflow

Create `.github/workflows/filing-memory-backfill.yml`. Cron `0 19 * * 1-5`
(weekdays 19:00 UTC = 00:30 IST next day = safely after market close + after
yfinance has updated). Model on the existing `filing-memory-sync.yml` from
Phase 0.7 — same secrets, same Python version, same setup pattern. The job
runs `python agents/filing_memory_backfill.py` and exits cleanly even if
some rows FAIL (the script handles that internally).

**Do NOT** add `workflow_dispatch` unless `filing-memory-sync.yml` has it —
match the sibling workflow's pattern exactly.

**→ STOP after creating the file. Wait for edit approval.**

---

## STEP 6 — `utils/filing_memory_brief.py` — retrieval brief utility

Create `utils/filing_memory_brief.py`. ONE pure function, no side effects, no
DB writes.

**`get_filing_memory_brief(symbol_base, current_event_type)`:**

1. Query Supabase:
   `SELECT event_type, filing_date, alpha_10d FROM filing_memory WHERE symbol_base = ? AND material_score >= 6 AND outcome_10d_status = 'FILLED' ORDER BY filing_date DESC LIMIT 30`.
2. **If no rows:** return the exact string
   `"No matured material filing history for this company."`
3. **Otherwise** build a compact brief:
   - Header: `f"{symbol_base} -- Filing Memory ({n} material filings, last 30):"`
     (use `--`, not em-dash; cp1252 safety.)
   - Per-event-type aggregate lines: group rows by `event_type`, compute count,
     average `alpha_10d` (rounded to 1 decimal), wins (`alpha_10d > 3`):
     `f"  {ev}: {n} events, avg {avg:+.1f}% alpha(10d), {wins}/{n} positive"`
   - If at least one row matches `current_event_type`, append a "Most recent"
     line for the latest matching row:
     `f"  Most recent {ev}: {date} -> {alpha:+.1f}% alpha in 10d"`
   - Join with `\n`.
4. Type the return as `str`. The function must NEVER raise on the no-rows case;
   it must NEVER raise on a missing column (defensive `.get()` style access on
   dict rows).

Add a small `if __name__ == '__main__':` block that takes `sys.argv[1]` and
`sys.argv[2]` and prints the brief — useful for smoke testing without a test
harness.

**→ STOP after creating the file. Wait for edit approval.**

---

## STEP 7 — Smoke-test the brief

1. Pick the symbol from STEP 0's `[V4.7]` answer (one likely to have FILLED
   10d rows). Run:
   `.venv\Scripts\python.exe utils\filing_memory_brief.py <SYMBOL> dividend`
   Paste the output.
2. Pick a symbol that almost certainly has NO FILLED rows (e.g. a recent-filing
   symbol from STEP 0). Run the same command. Confirm the no-rows fallback
   string is printed verbatim.
3. **If STEP 0 flagged V4.7-structural-only mode** (no symbol has 10d FILLED
   yet), skip part 1 — the no-rows path is the only path to verify, and that
   is acceptable for the current state.

**→ STOP. Report both outputs (or just the no-rows output if structural-only).**

---

## STEP 8 — `tests/test_phase4_batchB.py` — committed gate test

Create `tests/test_phase4_batchB.py`. Real assertions, clear PASS/FAIL prints,
non-zero exit on any failure. **All three gates must be structural-first** —
they must not fail purely because the data is too young.

- **V4.5 — Outcome backfill correctness.** Query `filing_memory`. Assert that:
  - For every row with `outcome_5d_status='FILLED'`, `price_5d`, `nifty_5d`,
    `raw_move_5d`, `alpha_5d` are all NOT NULL. (Same for 10d, 30d.)
  - For every row with `outcome_5d_status='PENDING'`, `price_5d`, `alpha_5d` etc.
    ARE NULL. (PENDING means "not yet filled" — data must reflect that.)
  - Cross-symbol math sanity: for one FILLED 10d row, recompute
    `alpha = raw_move - nifty_move` from raw numbers and assert it equals
    `alpha_10d` within 0.01 tolerance. (Pick the most-recent FILLED 10d row.)
  - If there are ZERO FILLED rows of any window, V4.5 PASSES with a
    `[V4.5 STRUCTURAL-ONLY]` note — there is nothing to verify yet, and that
    is correct for the current data age, not a test failure.
- **V4.6 — swing_verdict rule.** For every row with `outcome_10d_status='FILLED'`,
  assert `swing_verdict` is one of POSITIVE/NEGATIVE/NEUTRAL AND matches the
  ±3% rule applied to `alpha_10d`. If no FILLED 10d rows exist, PASS with
  `[V4.6 STRUCTURAL-ONLY]`.
- **V4.7 — `get_filing_memory_brief()` shape.** Import and call the function.
  - For a known-no-history symbol (use a clearly-fake string like
    `"NONEXISTENT_SYMBOL"`), assert the exact no-rows string is returned.
  - For a known-real symbol from `filing_memory` (pick the first row's
    symbol_base), call the function and assert the return is a `str` and
    contains either the no-rows string OR the header pattern
    `"<symbol> -- Filing Memory"`. Do NOT assert specific counts — that is
    data-dependent.

Print every gate's PASS/FAIL with actual numbers. Exit non-zero on any FAIL.

**→ STOP after creating the file. Wait for edit approval.**

---

## STEP 9 — Run the gate test

1. Run: `.venv\Scripts\python.exe tests\test_phase4_batchB.py`
2. Paste the full output.

**→ STOP. Report.**

---

## STEP 10 — Commit + push

Only after STEPs 1–9 are green. Add files **explicitly** (note: include the
`utils/trading_calendar.py` edit ONLY if STEP 1 modified it):

```
git add agents/filing_memory_backfill.py
git add .github/workflows/filing-memory-backfill.yml
git add utils/filing_memory_brief.py
git add tests/test_phase4_batchB.py
# AND if utils/trading_calendar.py was edited in STEP 1:
# git add utils/trading_calendar.py

git status        # confirm ONLY intended files staged -- no .claude/, no dumps/, no scripts/
git commit -m "$(cat <<'EOF'
feat(phase-4): Batch B -- filing_memory outcome backfill + retrieval brief

- agents/filing_memory_backfill.py: two-pass backfill. Pass 1 fills base_price
  + nifty_base from next-trading-day adjusted OPEN (yfinance, .NS appended).
  Pass 2 fills 5d/10d/30d windows as each matures (trading-calendar-accurate,
  market-relative alpha = stock_move - nifty_move, adjusted CLOSE). One
  yfinance call per symbol (range fetch + in-memory date dict), NIFTY fetched
  once. swing_verdict computed on 10d-FILLED rows via +/-3% rule. Update-only
  idempotency -- no inserts; re-run safe by base_price IS NULL / status PENDING
  filters.
- .github/workflows/filing-memory-backfill.yml: cron 0 19 * * 1-5 (post-close).
- utils/filing_memory_brief.py: get_filing_memory_brief(symbol, event_type)
  returns a compact ~50-word brief grouped by event_type from FILLED 10d
  outcomes; falls back to a fixed no-history string.
- tests/test_phase4_batchB.py: V4.5 (window FILLED/PENDING consistency +
  alpha math), V4.6 (swing_verdict rule), V4.7 (brief shape). Structural-only
  modes for windows that have not yet matured.
EOF
)"
git push
git log --oneline -3
git status
```

Confirm the push succeeded (commit appears, branch not ahead of origin).

**→ STOP. Report the commit hash and push confirmation.**

---

## Done criteria for Batch B

- [ ] STEP 0 recon done, R1–R4 + V4.7 readiness clarified, script deleted
- [ ] `filing_memory_backfill.py` created, two passes, idempotent on re-run
- [ ] `trading_calendar.py` extensions added IF STEP 0 required them
- [ ] Pass 1: `filing_memory.base_price` populated for all rows whose next
      trading day has passed
- [ ] Pass 2: matured windows FILLED with correct alpha; immature windows
      remain PENDING; FAILED count small
- [ ] `swing_verdict` populated only on FILLED 10d rows, matches +/-3% rule
- [ ] `.github/workflows/filing-memory-backfill.yml` created, cron set
- [ ] `utils/filing_memory_brief.py` returns correct no-history fallback +
      correct header pattern when data exists
- [ ] `test_phase4_batchB.py`: V4.5, V4.6, V4.7 all PASS (structural-only
      modes acceptable while data is young)
- [ ] One commit, pushed, only the 4 (or 5) intended files

Phase 5 (live engine: Tier-0F + Tier-2F + first live `ai_consensus` calls) is a
SEPARATE brief -- do not start it. After Batch B, STOP and report back. Also
note any rows that remain PENDING and will mature in coming sessions -- that
is the steady state of this job.

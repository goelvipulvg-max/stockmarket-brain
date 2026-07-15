# B1 Survivorship — Investigation Before Build (READ-ONLY)

**Date:** 2026-07-14 · **Repo:** stockmarket-brain @ d3ddb0c · **DB access:** `smb_audit_ro` (read-only, verified `current_user` = `smb_audit_ro`) · **Mode:** investigation only — zero code/config/DB changes.

---

## Executive summary

**Is B1 worth building? Yes — but not as designed, and it is three items, not one.**

The headline fear ("the universe gate has look-ahead bias and is killing filings wrongly") is **mostly not true today**: of the 107 universe-killed filings in the Jul 6–10 resume window, **at most 1 was wrongly killed (≤0.9%)**, and **0 filings wrongly passed**. The index has barely churned since the May-11 snapshot, so "today's universe" ≈ "filing-time universe" for now. That legitimately **downgrades the original B1** ("wire `nse500_membership` into the live gate").

What the investigation found instead is worse in a different way:

1. **A live `.NS`-suffix bug makes 8 current Nifty-500 members permanently invisible to the gate** (ULTRACEMCO, BAJAJFINSV, UNIONBANK, UBL, APARINDS, ANTHEM, ANANDRATHI, CIEINDIA). Over the full filings history this silently killed **9 material, dispatched candidates** — during a 0-trade drought.
2. **Index removals never reach the database.** GSPL left the index between May 11–17; all **6 weekly sync runs since May-17 flagged it REMOVED and every one silently no-op'd** (bare-symbol `UPDATE` vs `.NS`-stored rows). The DB still believes GSPL is a member.
3. **The September-2026 reconstitution is a cliff.** When ~25–30 names join and leave, the sync will insert the joiners as bare symbols (invisible to the gate) and no-op the leavers (they keep passing). The gate's universe then drifts monotonically wrong, in both directions, every cycle.
4. **`nse500_membership` cannot support a point-in-time gate as it stands**: join dates only, no exit dates, no leaver rows, 5 junk rows, no refresh mechanism. The refresh feed already exists (the weekly sync's diff) but is discarded.
5. The real, measured survivorship contamination is in the **learning corpus**: 56 of 1,430 `event_outcomes` rows (3.9%) are pre-join look-ahead, and leaver histories are absent entirely.

**One item or two?** Three: **B1-a** fix the `.NS` plumbing (tiny, drought-relevant, needed regardless), **B1-b** keep membership current with exits (small, must land before Sep-2026), **B1-c** point-in-time checks (live-path value ≈ nil; belongs in the learning/backtest layer). Proposals in Part 4. Nothing has been changed; Gaurav decides.

---

## Part 1 — What the live universe gate actually does today

### 1.1 Location and behaviour

The gate is **Stage 2 of Tier-2F**, after claim (Step 0), F&O-ban (Step 1) and liquidity (Step 1.5):

- [agents/tier2_fundamental.py:217-221](../agents/tier2_fundamental.py#L217-L221) — `fundamentals = get_fundamentals(symbol)`; if `None` → `return {"skip": "not_nifty500", ...}`.
- **On a miss: hard skip.** No shadow log, no DB record — the skip exists only in workflow stdout. (Side-finding: the Jul-12 funnel's "107" is reconstructable only via log archaeology; skips are not persisted anywhere.)

### 1.2 What it queries

- [utils/neon_fundamentals.py:12-31](../utils/neon_fundamentals.py#L12-L31) — `get_fundamentals` appends `.NS` and runs
  `SELECT sector, market_cap, business_summary FROM company_profiles WHERE symbol = '<SYM>.NS' LIMIT 1`.
- **Presence-only.** The `nifty500` boolean column is *not* consulted; any row that exists passes, even with `nifty500 = FALSE`.
- **No as-of logic anywhere.** Repo grep: `nse500_membership` is referenced only by [scripts/backfill_membership.py](../scripts/backfill_membership.py) (confirmed the prompt's premise); no live-path file touches `member_since` or any date-conditioned membership check. Purely present-tense.
- Note the gate is **dual-purpose**: the same call also supplies sector / market-cap / business-summary context for the downstream AI prompt. Any redesign must keep the fundamentals fetch even if the membership decision moves elsewhere.

### 1.3 Is `company_profiles` genuinely a current-universe snapshot?

No — it is a **May-2026 snapshot with two punctures** (all numbers queried live 2026-07-14):

| Fact | Value | Evidence |
|---|---|---|
| Rows | 505 | live query |
| Symbol format | 493 with `.NS`, **12 bare** (8 real members + 4 `DUMMYVEDL*`) | live query |
| `nifty500` flag | 501 TRUE / 4 FALSE (only the DUMMYs) — **GSPL still TRUE** | live query |
| Created | 2026-05-10 → 2026-05-17 (initial preloader load) | `created_at` min/max |
| Last update | 2026-07-05 (only the DUMMY flag-flips) — **zero rows created after 2026-06-01** | `updated_at` max |

So the gate's *effective* universe = "the index as loaded 11–17 May 2026, **minus** 8 members lost to the `.NS` mismatch, **plus** GSPL which left the index but was never removed." The Jul-12 report's claim (§4.1: killer = "candidate not in `company_profiles`") is confirmed literally.

### 1.4 The `.NS` bug, precisely

`get_fundamentals` queries `<SYM>.NS`; 8 real current members are stored **bare** in `company_profiles` (and in `nse500_watchlist`): **ANANDRATHI, ANTHEM, APARINDS, BAJAJFINSV, CIEINDIA, UBL, ULTRACEMCO, UNIONBANK** (all created 2026-05-12/17 in the initial load — a load quirk, not sync-created). Every filing from these 8 returns `None` → `not_nifty500`. This is the same `.NS` gap family as P2-11 (Guardian), previously fixed there but not here.

---

## Part 2 — Is the membership data actually usable?

### 2.1 What `nse500_membership` actually is

Schema (live): `id bigint, symbol text (bare), member_since date, source text, created_at timestamptz`. **505 rows, one per symbol, join-date only. No exit column. Not a time series.**

Granularity is **event-based** — exactly 5 distinct `member_since` values:

| member_since | source | rows |
|---|---|---|
| 2024-01-01 | floor | 410 |
| 2024-09-30 | circular | 19 |
| 2025-03-28 | circular | 28 |
| 2025-09-30 | wayback | 15 |
| 2026-03-28 | wayback | 33 |

Built 2026-06-04 (row `created_at`) by the one-shot [scripts/backfill_membership.py](../scripts/backfill_membership.py): current watchlist members floored at 2024-01-01, overridden by 4 hardcoded joiner cohorts. Two honesty notes:

- **The join data is itself survivor-filtered.** The script's cohorts contain 27/30/22/33 names but the DB holds 19/28/15/33 — cohort members no longer in the current watchlist were skipped ([backfill_membership.py:102-106](../scripts/backfill_membership.py#L102-L106)). Joiners who later left have no row.
- **5 junk/stale rows**: `DUMMYVEDL1-4` (NSE demerger placeholders, watchlist-INACTIVE since Jul-5) and GSPL — all carried as members since floor. Real current members = 500.

### 2.2 The "gap" to 2026-03-28 — mischaracterised

The table does **not** have a 3.5-month *data* gap in the daily sense: it is join-events, and 2026-03-28 was simply the **last index reconstitution before the build date**. The next scheduled one is ~Sep-2026. The genuine gaps are:

1. **No exits, ever** — the table cannot answer "was ex-member X in the index on date D"; ex-members have no rows at all.
2. **No refresh mechanism** — one-shot script, nothing in `.github/workflows/` references it (grep).
3. **Ad-hoc changes missed** — GSPL's exit (May-2026, between reconstitutions) exists nowhere.

Upstream sources remain available: the official NSE CSV is fetched successfully every Sunday (below), and the cohort sources (niftyindices circulars, Wayback CSV diffs) were usable as recently as Jun-4.

### 2.3 Weekly NSE 500 Sync — the live feed we're not connecting

[.github/workflows/sync_nse500.yml](../.github/workflows/sync_nse500.yml) (Sundays 02:30 UTC / 08:00 IST) → [scripts/sync_nse500.py](../scripts/sync_nse500.py). Running **weekly since 2026-05-17**, all green (run IDs 25986948425 May-17, 26357625867 May-24, 26710089239 May-31, 27085306146 Jun-7, 28740088022 Jul-5 dispatch, 29181521580 Jul-12; gap Jun-8→Jul-4 = the system pause). The Jul-12 report's "1 run" counted only its own window.

What it does: fetches the live NSE-500 CSV, diffs against `nse500_watchlist`, then writes watchlist status/dates, `company_profiles.nifty500` flags + minimal new-profile rows, and backfills `research_cache`/`event_outcomes` for new entrants. **It never touches `nse500_membership` — zero overlap today.** But its diff (New / Removed / Reactivated) *is* the membership event stream, currently computed weekly and thrown away.

**And its writes are partially broken.** It *compares* suffix-stripped ([sync_nse500.py:100-112](../scripts/sync_nse500.py#L100-L112)) but *writes* bare literals ([insert_new_watchlist:232-243](../scripts/sync_nse500.py#L232-L243), [ensure_company_profile:246-258](../scripts/sync_nse500.py#L246-L258), [mark_inactive:261-278](../scripts/sync_nse500.py#L261-L278), [mark_active:281-298](../scripts/sync_nse500.py#L281-L298)) against `.NS`-stored rows:

- **GSPL**: flagged `REMOVED` in **all six runs** May-17 → Jul-12; `UPDATE ... WHERE symbol='GSPL'` matches 0 rows against stored `GSPL.NS` → watchlist still `ACTIVE`, profile still `nifty500=TRUE` (verified live 2026-07-14). Exit window bounded: in the live CSV on the May-11 load, gone by May-17.
- `DUMMYVEDL1-4` removal *worked* on Jul-5 only because those rows happen to be stored bare.
- **Forward consequence (the Sep-2026 cliff):** joiners will be inserted **bare** → invisible to the `.NS`-querying gate; leavers will **no-op** → keep passing. Both error directions grow at every reconstitution, silently.

### 2.4 Verdict on usability

**As it stands: no — a point-in-time gate cannot be built from this data.** It answers only "when did a *current* member join", at 4-cohort resolution, with 5 junk rows. Missing for PIT: exit dates, leaver rows, a refresh path. **The needed work is small** because the weekly sync already computes the event stream; it just needs an exit schema and correct writes (Part 4, B1-b).

---

## Part 3 — Quantifying the actual bias

**Method.** Stage-2 skips aren't persisted, so I replayed the gate's exact semantics (`symbol + '.NS'` present in `company_profiles`) over `filings_log`. Validation: the Jul 6–10 IST window reproduces the Jul-12 funnel **exactly** — 1,537 classified / 385 material candidates / 365 picked. The liquidity stage (Step 1.5, runtime yfinance) is not replayable months later, so per-filing I bound rather than assert which gate-failers were among the 107 that *reached* Stage 2. "In the index at filing time" for the window uses: DB watchlist-ACTIVE minus GSPL (run-log evidence), which is exact here because **no symbol joined the index after the May-11 snapshot** (all `member_since` ≤ 2026-03-28; sync runs show New: 0 throughout).

### 3.1 Direction 1 — wrongly excluded (was in the index, gate killed it)

**Measured, Jul 6–10 window:** of 365 picked filings, 250 (188 symbols) fail today's gate. Of those, exactly **1 picked filing — ANTHEM — was from a symbol in the index at filing time**. So **at most 1 of the 107 universe kills was wrong (≤0.9%)** — and 0 if ANTHEM died at the liquidity stage first (not determinable from DB). Across all 1,537 window filings: 6 wrong-fails, from 3 symbols (ANANDRATHI, ANTHEM, BAJAJFINSV) — **all** `.NS`-bug members, **zero from index churn**.

**Measured, full history (2026-05-01 → 07-14, 7,806 filings):** the 8 bug members filed 38 times; **9 were material + picked** and therefore killed at Stage 2 (or earlier at liquidity): APARINDS ×4, ANTHEM ×2, UNIONBANK ×1, ANANDRATHI ×1, CIEINDIA ×1. These are the concrete lost candidates. (ULTRACEMCO/BAJAJFINSV/UBL filed only non-material items to date.)

### 3.2 Direction 2 — wrongly included (not in the index, gate passed it)

**Measured: 0 filings**, window *and* full history. The only known leaver, GSPL, has **zero rows in `filings_log`** since logging began 2026-05-01. The door is open (GSPL passes the gate today) but nothing has walked through it. No `paper_trades` contamination either — wrongly-*excluded* filings produce skips, not trades, and the wrongly-*includable* symbol never filed.

### 3.3 The corpus direction (silent backtest inflation)

- **`event_outcomes`** (pattern corpus: 1,430 rows, 2024-05-10 → 2026-05-07, feeds `pattern_library`/memory seeding): **56 rows across 31 symbols (3.9%) are pre-join** — the event predates the symbol's `member_since`. By cohort: Sep-24: 4, Mar-25: 17, Sep-25: 10, Mar-26: 25. These are look-ahead inclusions: the corpus "knew" these names would join. **Measured.**
- **The inverse — leaver histories — is absent entirely and unmeasurable** from our data (no leaver records exist anywhere). By churn symmetry (~25–30 names per half-yearly reconstitution, 4 reconstitutions in the corpus span) the missing-leaver side is plausibly the same order — tens of events. **Estimate, explicitly labelled.** GSPL sits in the corpus (1 row) as if a full member.
- **`filing_memory`** (learning corpus, 2,445 rows): **0 pre-join rows** — trivially, since the corpus starts 2026-05 and all joins are ≤ 2026-03-28. Separately: 1,809 rows (74%) from 1,024 symbols outside the membership table — the ingest is exchange-wide by design, fine for outcome math, but any future Tier-4 statistic that conditions on "universe" must handle this.

### 3.4 Magnitude verdict

The **live look-ahead bias is small today** — ~1% of universe kills wrong, 0 wrong inclusions — because the index has barely churned since May. Per the brief's own standard, this **downgrades the original B1** ("wire the table into the live gate") as a bias fix. What is *not* small:

1. **9 material dispatched candidates lost** to the `.NS` bug in ~10 weeks, during a stretch when the funnel produced 0 trades — recovering real candidates is the drought-relevant fix.
2. **The Sep-2026 cliff** (§2.3): both error directions start compounding at the next reconstitution unless the sync's writes are fixed and exits are recorded.
3. **3.9% pre-join contamination + total leaver absence** in the pattern corpus, which any future backtest or pattern statistic inherits silently.

---

## Part 4 — Integration design (proposals only — nothing built)

**Reframe.** For the **live** path, point-in-time and current-universe coincide: a filing is judged the moment it lands, so an *accurate, fresh* current universe is the correct gate — `member_since` adds nothing live. PIT semantics only bite in replay/backtest/corpus work. B1 therefore splits into three separable items:

### B1-a — Fix the plumbing (smallest; recommended first; needed under every option)

1. One-time normalization of the 8 bare `company_profiles` (and matching `nse500_watchlist`) rows to `.NS` — *or* make `get_fundamentals` suffix-tolerant (try `.NS`, then bare). Normalizing the data is cleaner: every other consumer assumes `.NS`.
2. Fix the sync's four write helpers ([sync_nse500.py:232-298](../scripts/sync_nse500.py#L232-L298)) to match `.NS`-stored rows.
3. Retro-mark GSPL: watchlist `INACTIVE`, `removed_date` bounded 2026-05-11..17 (source: run-log evidence), profile `nifty500=FALSE`.
4. Purge or ignore the 4 `DUMMYVEDL*` rows in `nse500_membership`.

Effect: the 8 members become visible immediately; removals start working before Sep-2026. **This changes gate outcomes → requires explicit approval under the no-behaviour-change rule.**

### B1-b — Keep the data current (prereq for any PIT use; must land before Sep-2026)

- Add exit tracking. Recommended shape: an **event table** `nse500_membership_events (symbol, event JOIN|LEAVE, effective_date, source)` rather than a `left_on` column — it preserves leave-rejoin histories (e.g. DCMSHRIRAM) and extends cleanly. (A nullable `left_on` column is the minimal alternative.)
- Wire the weekly sync's existing diff into it: New → JOIN (+ membership upsert), Removed → LEAVE. Retro-insert GSPL's LEAVE.
- Stamp a **freshness sentinel** on every green run (e.g. `universe_sync_log(run_date, live_count, n_changes)`) so any consumer can check staleness rather than trusting silently.
- Cost: small — the diff already exists and runs green weekly; this is plumbing, not new data acquisition.

### B1-c — Use the data in the live gate (optional; low value today)

If desired after B1-b: replace the presence check with `member_since <= filing_date AND no LEAVE ≤ filing_date` against membership. For live filings this equals current membership, but it makes replays honest and unifies live/backtest code paths. `get_fundamentals` must still run afterward for sector/mcap/summary context (§1.2) — so B1-a is required regardless.

**Gap/staleness handling (the crux the brief asked for) — tri-state, never silent:**

| Condition | Behaviour |
|---|---|
| filing_date within last green sync + 7d | normal universe decision |
| 7–14d since last green sync | decide normally, but WARN log + Telegram nudge |
| > 14d stale | **hard skip with dedicated reason `universe_data_stale` + Telegram alert** |

Rationale: fail-open recreates the GSPL drift silently; *silent* fail-closed would strangle the funnel invisibly (the Tier-0 poller would keep dispatching into a black hole); **loud** fail-closed surfaces the ops problem within one cycle and self-heals when the sync greens. The sentinel from B1-b is what makes this checkable.

### B1-d — Learning-layer honesty (whenever pattern/Tier-4 stats are next touched)

- Tag, don't delete: mark the 56 pre-join `event_outcomes` rows (`in_universe_at_event` boolean, or exclude via a membership join at read time) before any pattern statistic conditions on them.
- Document leaver-absence as a permanent corpus caveat (partially reconstructable from Wayback CSVs if ever justified).
- **No re-derivation needed** for `filing_memory` outcomes (price-vs-NIFTY math; universe is not an input) or `paper_trades` (zero historical trades from mis-gated symbols, §3.2).

### Priority recommendation

**B1-a + B1-b before the Sep-2026 reconstitution** (the only hard deadline in this area); B1-c cheap and optional after b; B1-d deferred until pattern stats are next in play. Against the wider backlog: B1-a is the only piece with immediate funnel impact (recovers real candidates during the drought); B1-b is cliff insurance; the originally-scoped B1 (a PIT live gate) is, on the measured evidence, the least urgent part of its own roadmap item.

---

## Appendix — Evidence trail

- **Role:** all DB reads via `smb_audit_ro` (`SELECT current_user` verified), sessions set read-only; zero writes to code, config, flags, DBs, or dispatches.
- **Repo evidence:** [agents/tier2_fundamental.py:205-221](../agents/tier2_fundamental.py#L205-L221) (gate order + hard skip); [utils/neon_fundamentals.py:12-31](../utils/neon_fundamentals.py#L12-L31) (presence-only `.NS` lookup); [scripts/backfill_membership.py](../scripts/backfill_membership.py) (one-shot cohorts, unknown-skip at :102-106); [scripts/sync_nse500.py:100-112, 232-298](../scripts/sync_nse500.py#L232-L298) (bare-write helpers); [.github/workflows/sync_nse500.yml](../.github/workflows/sync_nse500.yml) (Sunday schedule; no membership reference in any workflow).
- **Workflow runs (gh):** sync runs 25986948425 (May-17), 26357625867 (May-24), 26710089239 (May-31), 27085306146 (Jun-7), 28740088022 (Jul-5), 29181521580 (Jul-12) — GSPL `REMOVED` in every log; New: 0 in every log; live CSV counts 504→500.
- **Key live numbers (2026-07-14):** `company_profiles` 505 (493 `.NS`/12 bare; 501 TRUE incl. GSPL; created ≤ 2026-05-17); `nse500_watchlist` 501 ACTIVE (incl. GSPL.NS) + 4 INACTIVE (DUMMY, removed 2026-07-05); `nse500_membership` 505 (join-only, 5 junk rows, built 2026-06-04); `filings_log` 7,806 rows 2026-05-01→07-14, window reproduces 1,537/385/365; universe-fail among picked 250 filings/188 symbols, wrong-fails: 1 picked (ANTHEM)/6 all-level; `.NS`-bug members full history 38 filings/9 material+picked; `event_outcomes` 1,430 rows/56 pre-join (31 symbols); `filing_memory` 2,445 rows/0 pre-join/1,809 non-member.
- **Known limits:** liquidity stage not replayable (bounds used, stated inline); leaver-side corpus absence estimated by churn symmetry, not measured; GSPL exit date bounded May 11–17 from run logs, exact circular date not looked up.

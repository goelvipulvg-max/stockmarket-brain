# StockMarket-Brain — Follow-up Investigation: N-2, N-3, F-1, Telegram Silent-Swallow

**Date:** 2026-07-13 (Monday, trading day) · **HEAD:** `2e51d83` (origin/main in sync) · **Investigation-only — zero code/config/DB changes, zero trades**
**Baseline:** [2026-07-12 current-scenario report](2026-07-12-current-scenario-report.md) — this report continues its finding numbers (#3/N-2, N-3, #5/F-1, item 5).
**Method:** live `gh run list`/log harvest (all 64 Tier-2F runs today), read-only Supabase queries via the `smb_audit_ro` role (SELECT-only, transaction rolled back), file:line evidence throughout. Report intentionally uncommitted (staged for owner review).

---

## Part 0 — N-1 spot-check (verifier starvation fix)

**GREEN.** All 64 Tier-2F runs today (03:03–10:59 UTC) succeeded. Exactly one `[WARN] verifier attempt N` sequence exists — in run `29222982814` (created 04:02:33 UTC), which ran **before** the N-1 push (`2e51d83`, 2026-07-13 09:45:53 IST = 04:15:53 UTC) and shows the pre-fix signature (attempts 1–2 truncated-JSON, attempt 3 empty → `SOLO_HAIKU`, refused at 61 < 65). **Post-push: zero empty-response WARNs across all runs; 5 filings reached the verifier stage (INTELLECT, PIDILITIND, SAGILITY, ASTERDM, EMCURE) and all 5 returned parseable verdicts with `fallback_mode=None`** — all were challenges (agreement 40–45), logged as `agent_disagreements` ids 35–39 (DB-confirmed: 5 rows today, min 35 / max 39). Fix config live in [ai_consensus.py:28-29](../utils/ai_consensus.py) (`DEEPSEEK_MAX_TOKENS = 2500`, `thinking: disabled`, worst observed reasoning burn 1,146 tokens noted in-file). Consensus mode is functioning; still 0 trades (`paper_trades` max id 162, 0 rows today) — the verifier is simply conservative, which is its job. N-1 not re-litigated further.

---

## Part 1 — N-2: GH `schedule:` cadence gap (Guardian/News)

### 1.1 Cadence recount with one more trading day (Jul 13)

Weekend (Jul 11–12) adds nothing — all five intraday crons are Mon–Fri. Today's fired-vs-design counts, and the cumulative 6-trading-day window:

| Workflow | Design/day | Fired today (schedule) | Cumulative Jul 6→13 | % of design | Baseline % (Jul 12) |
|---|---|---|---|---|---|
| Updater fallback | 48 (`*/10 3-10`) | 3 | 14/288 | **4.9%** | 4.6% |
| Poller fallback | 42 (`*/10 3-9`) | 3 | 12/252¹ | **4.8%** | 4.3% |
| Tier-0 fallback | 26 (2 cron lines) | 4 | 24/156 | **15.4%** | 15% |
| **Guardian (no primary)** | 22 (`*/30 3-13`) | **3** | 22/132 | **16.7%** | 17% |
| **News (no primary)** | 26 (2 cron lines) | **4** | 26/156 | **16.7%** | 17% |

¹ Poller cumulative = baseline 9 + today's 3 (direct count; the full-window `gh` query saturates its result limit on this workflow).

**Verdict: no movement — this is steady-state GitHub throttling, not a transient.** The concrete protection picture today: Guardian ran at **11:55, 15:25, 18:06 IST** ([tier1_guardian.yml:8](../.github/workflows/tier1_guardian.yml) designs 30-min cadence from 08:30 IST). With an open position, there would have been **zero Guardian coverage from market open until 11:55 IST (2h40m)** and a single check in the entire afternoon session. The cron-job.org-backed workflows meanwhile ran at full design cadence today: poller 240 dispatches (08:31–16:28 IST, ~2-min), updater 96 (08:30–16:25 IST, ~5-min), tier0 96 (~5-min) — proving the primary-trigger pattern works when it exists.

### 1.2 Fix path: replicate the existing cron-job.org pattern for Guardian/News

Both workflows already accept `workflow_dispatch` ([tier1_guardian.yml:4](../.github/workflows/tier1_guardian.yml), [tier1_news.yml:4](../.github/workflows/tier1_news.yml)) — **zero repo changes needed; this is entirely a cron-job.org dashboard task** using the exact template already used by the poller/updater jobs (documented at [plans/2026-06-14-staged-resume-runbook.md:196-217](../plans/2026-06-14-staged-resume-runbook.md) and [docs/phase-5-batchB-execution-brief.md §3.9](../docs/phase-5-batchB-execution-brief.md)):

For each of the two jobs, in the cron-job.org dashboard → Create cronjob:

| Field | Guardian job | News job |
|---|---|---|
| URL | `https://api.github.com/repos/goelvipulvg-max/stockmarket-brain/actions/workflows/tier1_guardian.yml/dispatches` | same, `.../tier1_news.yml/dispatches` |
| Method | POST | POST |
| Headers | `Authorization: Bearer <WORKFLOW_DISPATCH_PAT>` · `Accept: application/vnd.github+json` · `X-GitHub-Api-Version: 2022-11-28` | same |
| Body | `{"ref": "main"}` | same |
| Schedule | every 30 min, Mon–Fri, 08:30–19:00 IST (matches the GH cron's design window) | every 30 min, Mon–Fri, 09:15–15:30 IST |

Then fire one manual test from the dashboard and confirm a green `workflow_dispatch` run in `gh run list --workflow=tier1_guardian.yml`. The PAT is the same `WORKFLOW_DISPATCH_PAT` the existing jobs use (it dispatches workflows in this repo already — poller/updater/tier0 jobs prove it works; note the token's expiry date is worth checking while in the dashboard). The existing GH `schedule:` blocks stay as fallback — same belt-and-suspenders as I-1/P-1.

### 1.3 Recommendation (owner decides)

**Do Guardian now; News can wait.** Reasons: (a) it is a 10-minute, zero-code, zero-risk dashboard task with a proven template; (b) N-1 is fixed as of today — the system can now actually produce a consensus trade, so "no open positions" can end any day, and Guardian's cadence should be correct *before* the first position exists, not scrambled after; (c) today's live numbers show the gap is real and steady (first coverage 2h40m after open). News is informational only (movers channel) — no protection role; add it in the same dashboard session if convenient, but it changes no risk posture. A Health-Monitor staleness check on Guardian's last-run timestamp remains a good *code* follow-up ([health_monitor.py](../agents/health_monitor.py) currently has no guardian/staleness check — grep confirmed) but is not a substitute for cadence.

---

## Part 2 — N-3: post-market window / Phase-6 evidence

### 2.1 Recount since baseline

Since Jul 11 (baseline covered through Jul 10): **exactly 1 new silently-expired dispatch candidate** — filings_log id **7557 POCL, SPLIT, score 6, trade_confidence 70, classified 16:27 IST today**; the weekend produced no candidates at all. Today's flow: 61 material candidates, 60 picked, 1 unpicked. Resume-window unpicked histogram by IST hour of classification (Jul 6→13): hour-12 → 5 (the Jul 6 pre-L5 rows), **hour-16 → 12, hour-17 → 4** — i.e. the evening tail now totals 16 across six trading days (the baseline's 11 Jul 8-9 cases + POCL + ~4 from Jul 6), ≈ **2–3/day**.

### 2.2 Mechanism refinement — today's miss was NOT a window miss

The poller's *actual* live window is wider than the baseline assumed: today it ran 08:31–16:28 IST (240 dispatches, first 03:01 / last 10:58 UTC) — **~1 hour past market close**. POCL at 16:27 IST was *inside* both the operating window and the 30-min lookback of the final 16:28 run. It expired because of **drain rate**: `BATCH_LIMIT = 1` ([tier0f_poller.py:29](../agents/tier0f_poller.py)) dispatches the *oldest* unpicked filing per 2-min cycle ([tier0f_poller.py:71](../agents/tier0f_poller.py)), and the last two cycles went to older siblings — filing 7553 (ASTERDM) and 7554 (EMCURE) (claim lines in runs `29244534624`/`29244649836`) — then the window ended. So N-3 has two sub-mechanisms: (a) end-of-window backlog > 1-per-2-min drain rate, and (b) filings classified after ~16:28 IST (tier0 classifies until ~16:5x on some days — the four hour-17 cases) that no poller cycle ever sees.

### 2.3 Interim options short of Phase 6

An important honesty note first: **Tier-2F has no market-hours guard** (grep of [tier2_fundamental.py](../agents/tier2_fundamental.py) for market-close/time gating: no matches) — it already analyzes and would enter paper trades up to ~16:30 IST at the last traded price (EMCURE was analyzed 16:30 IST today). Every option below *widens* the post-close stale-price entry surface that Phase 6 is designed to eliminate (analyze evening filings → enter at next day's open, honestly).

| Option | What | Effort | Risk |
|---|---|---|---|
| A. Extend poller/tier0 cron-job.org windows +45 min (to ~17:15 IST) | Dashboard-only; no code | ~5 min | Low operationally, **but adds more post-close entries at stale last-close prices** (paper-fidelity noise; the entry would be at a price unavailable in reality). Also: updater window ends 16:25 IST, so evening entries sit unmanaged until next 08:30 (existing condition, widened). |
| B. Morning catch-up: make `LOOKBACK_MINUTES` env-overridable ([tier0f_poller.py:28](../agents/tier0f_poller.py)) + one 09:20-IST dispatch (workflow or cron-job.org job) with `POLLER_LOOKBACK_MINUTES≈1100` | ~1-line py + small yml; bounded catch-up | ~1-2 h incl. test | Medium: entries at *fresh* prices (good fidelity), but the filing is ~17h stale — the market may have priced it overnight; this is Phase 6's core problem (gap analysis) done without Phase 6's gap logic. Also a **behavioural change to the trading path → needs explicit approval regardless**. Note `BATCH_LIMIT=1` means the backlog drains at 1/2-min across normal morning cycles, which works but delays the tail to ~09:50. |
| C. Raise `BATCH_LIMIT` near window close | — | — | **Rejected out of hand: BATCH_LIMIT=1 IS the burst-eviction fix (884947a).** |
| D. Wait for Phase 6 | nothing | 0 | Leak continues at ~2–3 candidates/day, mostly score 6–8 (one score-10, KOTHARIPRO, Jul 8). |

### 2.4 Recommendation (owner decides)

**Wait for Phase 6 (Option D).** The quantified leak is small (16 candidates over 6 days; at the observed funnel rates — 37% liquidity kill, 31% universe kill, then analyst + verifier — the expected *trades* lost round to ~0–1 for the whole window), and both interim patches push the system further into post-close stale-price entries, i.e. they buy candidates at the cost of paper-fidelity honesty, which the Jul-4 audit graded as a core dimension. If anything, Phase 6 should probably *shrink* the poller's live window back toward 15:30 IST and route the 15:30+ tail through the after-hours queue. One cheap orthogonal improvement worth doing whenever convenient: none of these 16 expiries was ever *logged* as an expiry — a poller log line for "candidate aged out unpicked" would make this leak self-reporting (tiny code change, no behaviour change; bundle with a future fix session).

---

## Part 3 — F-1: backfill pagination (and a bigger finding: it's a daily leak, not a frozen hole)

### 3.1 Diagnosis reconfirmed + today's numbers

[filings_log_backfill.py:20-23](../agents/filings_log_backfill.py) still selects with no `.order()` / `.range()` / pagination → the PostgREST/Supabase 1,000-row response cap silently truncates. Live numbers today (read-only):

| Metric | Jul 12 | Today (Jul 13) |
|---|---|---|
| Material candidates (`score>=6`, `!=OTHER`) | 2,307 | **2,368** (2,363 with non-NULL url_hash, all distinct) |
| `filing_memory` rows | 1,982 | **2,029** |
| **Candidate hashes missing from filing_memory** (anti-join, not subtraction) | −325 | **−336** |

A direct `LIMIT 1000` probe of the same filter returns ids 19→5505 — i.e. the sweep sees fewer than half the candidate set, in **unordered heap order** (unstable across runs as rows are updated), so its coverage is non-deterministic as well as capped.

### 3.2 New forensic finding — the gap grows every trading day, from the same clock-window as N-3

Missing rows by month: 2026-05 → 55, 2026-06 → 179, **2026-07 → 102**. The July misses bucket by IST classification hour as **15h → 27, 16h → 71, 17h → 4 (100% of them 15:00–17:59 IST)**, and by date they land on *every* trading day since resume (Jul 6/7/8/9/10/13 = 4/27/14/23/20/**14 today**). Mechanism, fully explained by three windows that don't line up:

1. **Tier-0 classifies until ~16:28 IST** (cron-job.org primary; last run 10:55 UTC today).
2. **filing_memory_sync stops at ~15:30 IST** (GH cron `*/10 3-9 * * 1-5`, [filing-memory-sync.yml:8](../.github/workflows/filing-memory-sync.yml); its 45-min lookback [filing_memory_sync.py:20](../agents/filing_memory_sync.py) covers backwards, not forwards) — so filings classified after ~15:30 IST are never seen by the sync.
3. **The nightly sweep at 20:00 IST is explicitly designed as the safety net for exactly these rows** ([filings_log_backfill.yml:6-10](../.github/workflows/filings_log_backfill.yml): "catching anything the real-time 10-min sync missed") — but the 1,000-row cap makes it read a stale, heap-ordered first-half of history that effectively never contains the newest rows.

So F-1 is not "a frozen historical hole with a working mitigant" (baseline framing) — **it is a ~15–25 rows/day permanent leak of exactly the late-afternoon filings**, and it will keep growing until the pagination fix lands. (Net growth since Jul 12 is +11 vs 14 leaked today — small reconciliation drift from rows the 45-min sync caught late; direction unambiguous.)

### 3.3 Proposed fix (draft — NOT applied)

Paginated, id-ordered fetch of candidates; paginated fetch of existing `filing_memory` hashes; **insert only the missing rows, in batches, with conflict-ignore** (rationale in §3.4):

```diff
--- a/agents/filings_log_backfill.py
+++ b/agents/filings_log_backfill.py
@@
 from utils.neon_client import get_neon_connection
 from utils.supabase_client import get_client

+PAGE_SIZE = 1000    # PostgREST max-rows cap; each .range() window stays at/below it
+INSERT_BATCH = 500
+
+
+def _fetch_all_candidates(sb) -> list[dict]:
+    """All material candidates, paginated in stable id order (F-1 fix)."""
+    rows, start = [], 0
+    while True:
+        page = sb.table("filings_log").select("*") \
+            .gte("material_score", 6) \
+            .neq("event_type", "OTHER") \
+            .order("id", desc=False) \
+            .range(start, start + PAGE_SIZE - 1) \
+            .execute().data or []
+        rows.extend(page)
+        if len(page) < PAGE_SIZE:
+            return rows
+        start += PAGE_SIZE
+
+
+def _fetch_existing_hashes(sb) -> set[str]:
+    """Every url_hash already in filing_memory, paginated (also >1000 rows now)."""
+    hashes, start = set(), 0
+    while True:
+        page = sb.table("filing_memory").select("url_hash") \
+            .order("url_hash", desc=False) \
+            .range(start, start + PAGE_SIZE - 1) \
+            .execute().data or []
+        hashes.update(r["url_hash"] for r in page if r.get("url_hash"))
+        if len(page) < PAGE_SIZE:
+            return hashes
+        start += PAGE_SIZE
+

 def backfill_filings_log():
     sb = get_client()

-    # Read material candidates from filings_log
-    candidates = sb.table("filings_log").select("*") \
-        .gte("material_score", 6) \
-        .neq("event_type", "OTHER") \
-        .execute()
+    # F-1: paginated read — the old single .execute() silently capped at the
+    # PostgREST 1000-row window in heap order, so late rows were never swept.
+    candidates = sb.table("filings_log").select("*")  # placeholder for type
+    candidate_rows = _fetch_all_candidates(sb)
+    existing_hashes = _fetch_existing_hashes(sb)

-    if not candidates.data:
+    if not candidate_rows:
         print("No material candidates found in filings_log.")
         return
@@
-    for filing in candidates.data:
+    already_present = 0
+    for filing in candidate_rows:
         url_hash_val = filing.get("url_hash")
         if not url_hash_val:
             skipped_null_hash += 1
             print(f"  [WARN] NULL url_hash for {filing.get('symbol','?')} "
                   f"({filing.get('event_type','?')}) — skipping")
             continue
+        if url_hash_val in existing_hashes:
+            already_present += 1
+            continue   # never rewrite existing rows (protects sync-written sector etc.)
@@
-    # Upsert with on_conflict='url_hash' — re-run inserts 0 duplicates
-    result = sb.table("filing_memory").upsert(insert_rows, on_conflict="url_hash").execute()
+    # Insert ONLY missing rows, in batches; ignore_duplicates=True renders the
+    # conflict path DO NOTHING (never clobbers existing filing_memory columns).
+    for i in range(0, len(insert_rows), INSERT_BATCH):
+        batch = insert_rows[i:i + INSERT_BATCH]
+        sb.table("filing_memory").upsert(
+            batch, on_conflict="url_hash", ignore_duplicates=True
+        ).execute()
+        print(f"  batch {i // INSERT_BATCH + 1}: {len(batch)} rows")
```

(Plus the matching summary-print updates. The `candidates = ...` placeholder line above is illustrative noise from diff minimization — a real patch would just delete the old query block.)

### 3.4 The risk you asked about: is a backfill-all-2,368-rows-now write safe?

Checked the conflict handling before proposing. Three findings:

1. **Duplicate rows: no risk.** `filing_memory.url_hash` is UNIQUE; both writers respect it (backfill via `on_conflict="url_hash"` [filings_log_backfill.py:92](../agents/filings_log_backfill.py); the 10-min sync via plain insert + `23505` skip [filing_memory_sync.py:110-117](../agents/filing_memory_sync.py)).
2. **Clobber risk: real — which is why the diff switches away from plain upsert.** The current upsert *updates* every supplied column on conflict. Outcome columns (`outcome_5d/10d/30d_status` etc.) are safe (not in the payload), but `sector` is: the backfill computes it from a one-shot Neon map ([filings_log_backfill.py:32-39](../agents/filings_log_backfill.py)) and writes `None` on a lookup miss — a naive re-run would NULL-overwrite sector on some of the **507 rows that currently have one** (1,522 are already NULL). `ignore_duplicates=True` (→ `ON CONFLICT DO NOTHING`) plus the local anti-join eliminates the entire class.
3. **Load: not a concern, but batch anyway.** The one-time catch-up inserts ~336 rows; steady-state nightly inserts ≈ the day's post-15:30 tail (~15–25). Batches of 500 keep any future catch-up payload well under PostgREST limits. Run it once via `workflow_dispatch` on the existing workflow, watch the printed counts, and the nightly cron then stays clean — no separate one-time script needed. One pre-existing fragility to note (not introduced by this fix): if the Neon connection fails, the whole backfill crashes ([filings_log_backfill.py:32](../agents/filings_log_backfill.py) has no try/except, unlike the sync's fail-open at [filing_memory_sync.py:70-74](../agents/filing_memory_sync.py)) — worth folding into the same fix session.

**Downstream note:** after the catch-up, ~336 rows will join the nightly outcome-backfill's PENDING pool (currently 397 PENDING / 1,632 FILLED) — expected, harmless, but the first post-fix Filing Memory Backfill run will be busier than usual.

---

## Part 4 — telegram_client silent-swallow

### 4.1 Current behaviour confirmed — with one nuance the baseline under-stated

[telegram_client.py:10-12](../utils/telegram_client.py): config missing → print + return. [telegram_client.py:18-19](../utils/telegram_client.py): HTTP non-OK → print + return. No retry, no raise, returns `None`. **The nuance: transport-level failures (timeout, DNS, connection reset) are NOT swallowed** — `requests.post` raises through `send_message` today. So the current contract is *inconsistent*: HTTP 4xx/5xx are silent, but a 10-second timeout is a live exception.

### 4.2 Call-site census (repo-wide)

| Caller | Wrapped? | If send_message raised |
|---|---|---|
| [update_paper_trades.py:187-203](../agents/update_paper_trades.py) `_tg_send` | ✅ try/except | safe (fail-open by design, U-9) |
| [tier2_fundamental.py:636-649](../agents/tier2_fundamental.py) `_tg_send` | ✅ try/except | safe ("never blocks trade") |
| [tier1_guardian.py:422-427](../agents/tier1_guardian.py) | ✅ try/except → returns False | safe |
| [tier1_news.py:204-208](../agents/tier1_news.py) | ✅ try/except around `send_telegram` | safe |
| [tier0_filings.py:302](../agents/tier0_filings.py) | ❌ **naked, inside the per-filing loop** | crash kills the rest of the classification batch; the in-flight filing is not yet saved → re-classified next cycle (wasted DeepSeek call) |
| [tier3_position_manager.py:152, 247, 253](../agents/tier3_position_manager.py) | ❌ naked ×3 | crash mid-adjudication skips remaining signals |
| [health_monitor.py:360](../agents/health_monitor.py) | ❌ naked | run goes red (ironically the most *visible* failure mode) |
| [daily_summary.py:161](../agents/daily_summary.py) | ❌ naked | run goes red; that day's summary lost (no retry) |
| scripts/ (preopen_alert, after_hours_watcher, test_telegram) + tier2_signals | ❌ | non-live paths (deprecated/manual) |

Tests that pin the contract: [tests/test_telegram_client.py:29-36](../tests/test_telegram_client.py) explicitly asserts **print-and-continue on HTTP error**, and [tests/test_close_alerts.py:154](../tests/test_close_alerts.py) asserts the updater's `_tg_send` swallows a raising `send_message`.

### 4.3 Fix direction (proposal): keep the no-raise contract — make it *complete* and observable, don't invert it

Switching to raise-on-failure would require touching 4 naked production call sites + 1 pinned test file, and the failure it creates at [tier0_filings.py:302](../agents/tier0_filings.py) (batch-killing crash for a *notification* failure) is strictly worse than a lost alert. The updater's fail-open wrapper pattern is the right philosophy — the client should honour it uniformly. Proposed contract: **never raises (now including transport errors), one retry on transient failures (5xx/429/transport), logs loudly, returns `bool`** so callers that *want* visibility (health_monitor, daily_summary — where a red run is arguably desirable) can check the return and exit non-zero in a later caller-side follow-up, without forcing anything on the other seven sites.

```diff
--- a/utils/telegram_client.py
+++ b/utils/telegram_client.py
@@
+import time
+
 import requests


 def send_message(
     bot_token: str,
     chat_id: str,
     text: str,
     parse_mode: str = "HTML",
-) -> None:
+    retries: int = 1,
+) -> bool:
+    """Fail-open by contract: NEVER raises (callers are alert paths that must
+    not break trades/batches). Returns True only on confirmed delivery.
+    Transient failures (transport, 429, 5xx) get one retry; permanent HTTP
+    errors (bad chat id, parse error) return False immediately."""
     if not bot_token or not chat_id:
         print("  Telegram config missing -- skipping")
-        return
-    r = requests.post(
-        f"https://api.telegram.org/bot{bot_token}/sendMessage",
-        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
-        timeout=10,
-    )
-    if not r.ok:
-        print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")
+        return False
+    for attempt in range(retries + 1):
+        try:
+            r = requests.post(
+                f"https://api.telegram.org/bot{bot_token}/sendMessage",
+                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
+                timeout=10,
+            )
+            if r.ok:
+                return True
+            print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")
+            if r.status_code != 429 and r.status_code < 500:
+                return False  # permanent -- retry cannot help
+        except requests.RequestException as e:
+            print(f"  Telegram transport error: {type(e).__name__}: {e}")
+        if attempt < retries:
+            time.sleep(2)
+    return False
```

Compatibility check: all existing callers ignore the return value (None→bool is invisible to them); all four `test_telegram_client.py` tests still pass as written (config-skip prints preserved, HTTP-error print preserved — a 400 returns after one attempt with no retry; the payload test's mocked 200 returns True); `test_close_alerts.py` still passes (its stub raises, `_tg_send` still catches). The behavioural *additions* are: transport errors no longer crash the 4 naked callers, and transient failures get one 2-second retry. Follow-up candidates for the same fix session (not required): have `daily_summary`/`health_monitor` check the return and `sys.exit(1)` on failure so a lost proof-of-life alert turns the run red.

---

## Decisions needed from owner (nothing proceeds without them)

1. **N-2:** Create the Guardian cron-job.org job now (recommended; 10-min dashboard task, template in §1.2)? News same-session or skip?
2. **N-3:** Accept "wait for Phase 6" (recommended), or pick interim Option A/B (§2.3) knowing both widen stale-price entry exposure?
3. **F-1:** Approve the pagination + insert-missing-only fix (§3.3) for a fix session — now upgraded in urgency: it stops a **daily** ~15–25-row leak, not just a frozen 336-row hole.
4. **Telegram:** Approve the fail-open-complete + retry + `bool`-return direction (§4.3), explicitly *keeping* the no-raise contract?

## Confidence & limitations

- DB access: `smb_audit_ro` via direct Postgres connection; every statement this session was `SELECT`/`SHOW`, transaction rolled back, **zero writes**. (The role's INSERT=false was verified in the Jul-12 session; not re-verified today.)
- Cadence percentages assume the cron *design* slot counts as denominator (48/42/26/22/26 per day); GH's own throttling behaviour is the known cause (baseline §3.2), not re-derived here.
- The poller/updater/tier0 cron-job.org *windows* quoted (08:30–16:28 IST etc.) are observed from today's run timestamps, not read from the dashboard (no API access to cron-job.org) — they differ from the 9:15–15:30 window in the older docs, so the dashboard is the source of truth when Gaurav is in there.
- F-1 heap-order probe: the `LIMIT 1000 → ids 19–5505` sample is from psycopg2; PostgREST's unordered read may pick a different (equally unstable) subset — the claim that matters (cap + no order = non-deterministic half-coverage) holds either way.
- No statistical claims: 0 trades, n=3 resolved sample unchanged.

*Continuity: Part 0 closes the loop on baseline #1/N-1 (fix verified in production). Parts 1/2/3/4 correspond to baseline findings #3 (N-2), N-3, #5 (F-1), and Part-1-item-5 (telegram_client) respectively. Report left uncommitted-but-staged for owner review; working tree otherwise untouched.*

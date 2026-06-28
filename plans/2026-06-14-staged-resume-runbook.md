# Staged-Resume Runbook — 2026-06-14

**Status:** PLAN ONLY. Do NOT execute during review. Execute in a separate deliberate
session on a watched NSE trading day.

## Confirmed Ground State (2026-06-14)

| Item | State | Source |
|------|-------|--------|
| GitHub Actions — all 17 workflows | `disabled_manually` | `gh workflow list --repo goelvipulvg-max/stockmarket-brain --all` |
| cron-job.org | OFF (all jobs disabled ~06-10) | plan §STEP-2 + handoff |
| `uniq_filings_log_url_hash` unique index | **DEPLOYED** on Supabase — **partial index** (`WHERE url_hash IS NOT NULL`). Duplicate-count for non-NULL hashes returns zero rows. **46 legacy NULL-hash rows are outside the index** — dedup is NOT covered for those. See §3.6. | verified live via `pg_indexes` + dup-count query |
| HOTFIX-6 ladder | Live in code: T1=6%, SL=4%, EQ_SL_T1=1.03, EQ_SL_T2=1.06 | `agents/update_paper_trades.py:39-41` |
| `update_paper_trades.yml` trigger | `workflow_dispatch` ONLY — no `schedule:`, no `workflow_run:` | `.github/workflows/update_paper_trades.yml:2-3` |
| Open positions | 0 trades open per handoff (GILLETTE id-161 EXPIRED 2026-06-13, LUPIN id-162 closed 06-08). **⚠️ VERIFY at execution time** — see Layer 4 pre-enable check. If any lingering OPEN trade exists that the handoff missed, the updater WILL manage it on first run under the new 6/4 ladder. | per handoff — cross-check with `SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'` at Layer 4 |
| Tier-3 auto-trigger; Tier-4 nightly | Tier-3 fires `on.workflow_run: ["Tier-2F Fundamental Signal"]`; Tier-4 runs nightly `on.schedule` `'30 15 * * 1-5'` (20:30 IST Mon-Fri — P3-6, was `workflow_run: ["Update Paper Trades"]`) | `.github/workflows/tier3_position_manager.yml:13-15` + `tier4_memory_manager.yml:7-8` |

---

## 1. Pre-Conditions Checklist

- [x] **P2 — `filings_log` unique index** — DEPLOYED (partial: `WHERE url_hash IS NOT NULL`).
  Non-NULL url_hash dedup is covered; zero duplicates confirmed. **46 legacy NULL-hash rows
  are outside the index** — dedup is NOT covered for those. If NULL-hash rows grow beyond 46
  after resume, investigate the insert path. Monitor via §3.6 query. No blocking action.
- [x] **GH-pause** — All 17 workflows `disabled_manually`. Trading switch is OFF.
- [ ] **P1 — Updater trigger** — `update_paper_trades.yml` has NO schedule. cron-job.org job for the
  updater must be re-enabled as a PRE-STEP of the Updater layer (Layer 4). See §2.4.
- [ ] **Trading-day guard** — Execute ONLY on a Mon–Fri NSE trading day with at least 4 hours
  of market remaining. Never enable the Tier-0F Poller before a weekend or holiday. Check
  `utils/trading_calendar.py` or NSE holiday list before starting.

---

## 2. Staged Resume — §6 Order

The plan order (from `plans/2026-06-13-bug-fix-implementation-plan.md:217`):

> monitors → memory plumbing → Tier-0 → updater → **Tier-0F Poller LAST**

Each layer has: enable commands, pre-enable verification, the canary signal to watch,
a GO / NO-GO gate, and a rollback step.

---

### 2.1 LAYER 1 — Monitors (6 workflows)

**Purpose:** Confirm observability stack is alive BEFORE any trading component runs.

#### Workflows to enable

```powershell
gh workflow enable "Health Monitor"               --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Daily Summary"                --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-1 Guardian"              --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-1 News Researcher"       --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-3 Position Manager"      --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Pre-Open Alert"               --repo goelvipulvg-max/stockmarket-brain
```

#### Before enabling

- Nothing — these are read-only. No trade impact.

#### Canary signals

| Workflow | What to watch | Where | How to confirm |
|----------|--------------|-------|----------------|
| `daily_summary.yml` | Morning digest | Telegram `TELEGRAM_TIER3_CHANNEL` | **Always sends** at ~8:00 AM IST. Contains: filings count, signals, trades, cash/deployed/equity, realized PnL, win-rate line. This is the **primary proof-of-life** — if you don't get this, the monitoring layer is down. |
| `health_monitor.yml` | Alert (problem only) | Telegram `TELEGRAM_TIER3_CHANNEL` | **Silence = green.** Fires at 9:00 AM IST. Sends ONLY if ≥1 check fails. Known caveat (P2-8): Check-1 (Tier-0 stall) is gated to 9:15–15:30 IST → always False at 9:00 AM cron time. Checks 2–6 can still fire. |
| `tier1_guardian.yml` | EXIT advisories | Telegram `TELEGRAM_GUARDIAN_CHANNEL` | Symbol-level risk posts every ~30 min during market hours |
| `tier1_news.yml` | News research | Telegram `TELEGRAM_MOVERS_CHANNEL` | News digests every ~15 min during market hours |
| `tier3_position_manager.yml` | Position-sizing recs | Telegram `TELEGRAM_TIER3_CHANNEL` | **Must be enabled to respond to `workflow_run`** — a disabled workflow ignores ALL triggers including upstream completions (per GitHub docs). Fires automatically when Tier-2F completes, but won't until Layer 5. Enabled here so it's ready; expect zero runs until then. |
| `preopen_alert.yml` | Pre-open alert | Telegram `TELEGRAM_TRADES_CHANNEL_ID` | Fires at 9:00 AM IST. P3-5 zombie — may produce nothing useful. |

#### GO / NO-GO gate

- **GO:** `daily_summary` Telegram received with non-zero numbers in the digest fields.
- **NO-GO:** No digest within 15 minutes of expected 8:00 AM IST firing. Check `gh run list --workflow="Daily Summary"` for failure. Rollback below.

#### Rollback

```powershell
gh workflow disable "Health Monitor"               --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Daily Summary"                --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Tier-1 Guardian"              --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Tier-1 News Researcher"       --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Tier-3 Position Manager"      --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Pre-Open Alert"               --repo goelvipulvg-max/stockmarket-brain
```

---

### 2.2 LAYER 2 — Memory Plumbing (3 workflows)

**Purpose:** Confirm filing-memory sync + backfill + Tier-4 operational before Tier-0
starts writing new `filings_log` rows.

#### Workflows to enable

```powershell
gh workflow enable "Filing Memory Sync"            --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Filing Memory Backfill"        --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-4 Memory Manager"         --repo goelvipulvg-max/stockmarket-brain
```

> **Note on `workflow_run` mechanics:** A `disabled_manually` workflow ignores ALL
> triggers, including `workflow_run` upstream completions (GitHub docs: disabling
> "stops a workflow from being triggered"). This applies to Tier-3 (enabled in Layer 1,
> fires when Tier-2F completes in Layer 5) — it MUST be enabled to auto-fire. Tier-4 is
> now nightly-scheduled (P3-6, not `workflow_run`); enabling it here is harmless — it
> only recomputes the `trade_memory` aggregate at the next 20:30 IST slot (no trading),
> independent of the updater.

#### Before enabling

- Monitors layer confirmed green (Layer 1 GO).

#### Canary signals

| Workflow | What to watch | Where | How to confirm |
|----------|--------------|-------|----------------|
| `filing-memory-sync.yml` | Sync run log | GH Actions log (`gh run list --workflow="Filing Memory Sync"`) | "Found N material filings" or "No material filings in window." Runs every 10 min. Silence → check GH for failures. |
| `filing-memory-backfill.yml` | Backfill run log | GH Actions log (`gh run list --workflow="Filing Memory Backfill"`) | Runs once daily at 00:30 IST. Won't fire during daytime resume. |
| `tier4_memory_manager.yml` | `trade_memory` upsert | GH Actions log (`gh run list --workflow="Tier-4 Memory Manager"`) | Runs nightly 20:30 IST Mon-Fri (P3-6) — once enabled, fires on the next 20:30 slot, independent of the updater. Verify workflow is `active` in listing. |

#### GO / NO-GO gate

- **GO:** `filing-memory-sync` completes successfully (green check in GH Actions) on its
  first scheduled run.
- **NO-GO:** Sync run fails. Check log for DB connection errors, missing env vars.

#### Rollback

```powershell
gh workflow disable "Filing Memory Sync"            --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Filing Memory Backfill"        --repo goelvipulvg-max/stockmarket-brain
gh workflow disable "Tier-4 Memory Manager"         --repo goelvipulvg-max/stockmarket-brain
```

---

### 2.3 LAYER 3 — Tier-0 (Filing Agent)

**Purpose:** Restart NSE filings ingestion. New rows flow into `filings_log`.
Tier-0 is read-only on the trading path — it writes observations, not positions.

#### Workflow to enable

```powershell
gh workflow enable "Tier-0 Filing Agent"           --repo goelvipulvg-max/stockmarket-brain
```

#### Before enabling

- **P2 confirmed:** `uniq_filings_log_url_hash` index deployed and zero duplicates
  (verified live). Without this index, overlapping Tier-0 + poller schedules could
  create duplicate filings → duplicate Tier-2F dispatches → duplicate trades.
- Memory plumbing green (Layer 2 GO).
- Monitors green (Layer 1 GO).

#### Canary signals

| Signal | Where | How to confirm |
|--------|-------|----------------|
| New `filings_log` rows | Supabase | `SELECT COUNT(*) FROM filings_log WHERE classified_at > NOW() - INTERVAL '30 minutes';` — should grow after Tier-0 fires |
| "Duplicate url_hash (23505)" | GH Actions log | `gh run list --workflow="Tier-0 Filing Agent"` → view latest run log. Should show "⏭️ Duplicate url_hash" ONLY if a genuine race occurs (benign — the unique index catches it). If this fires >0 times per run, investigate the race path. |
| Tier-0 stall check | `health_monitor` Telegram (if it fires) | If Tier-0 stalls for >30 min during market hours, health_monitor sends an alert to `TELEGRAM_TIER3_CHANNEL` |

#### GO / NO-GO gate

- **GO:** At least one new `filings_log` row appears with `classified_at` within the
  current trading window, and the Tier-0 run log shows clean execution (no crash).
- **NO-GO:** Tier-0 crashes or produces zero rows after two scheduled windows.
  Check `gh run list --workflow="Tier-0 Filing Agent"` for failures.

#### Rollback

```powershell
gh workflow disable "Tier-0 Filing Agent"           --repo goelvipulvg-max/stockmarket-brain
```

> Fixtures ingested during the Layer 3 window remain in `filings_log` — they are
> harmless observations. The poller (Layer 5) is still disabled so no dispatches fire.

---

### 2.4 LAYER 4 — Updater (Position Manager)

**Purpose:** The sole position manager. Without this, every trade opened by Tier-2F
becomes a zombie — no trailing SL upgrades, no target/SL hit detection, no force-expiry,
capital permanently locked.

**⚠️ This layer requires P1 resolution as a PRE-STEP.**

#### PRE-STEP: Re-enable cron-job.org trigger for the updater

The updater has NO GitHub `schedule:` and NO `workflow_run:`. It was triggered
exclusively by cron-job.org. Re-enable it:

1. **Log into** [cron-job.org](https://cron-job.org) dashboard
2. **Locate** the job named "Update Paper Trades" (or similar — the display name set at creation time)
3. **Verify** the job configuration:
   - **URL:** `https://api.github.com/repos/goelvipulvg-max/stockmarket-brain/actions/workflows/update_paper_trades.yml/dispatches`
   - **Method:** POST
   - **Headers:**
     - `Authorization: Bearer <WORKFLOW_DISPATCH_PAT>`
     - `Accept: application/vnd.github+json`
     - `X-GitHub-Api-Version: 2022-11-28`
   - **Body:** `{"ref": "main"}`
   - **Schedule:** Every 5 minutes, Mon–Fri, 9:15 AM–3:30 PM IST (3:45–10:00 UTC)
4. **Re-enable** the job
5. **Fire one manual test** from the cron-job.org dashboard → confirm a run appears in
   `gh run list --workflow="Update Paper Trades"` with green status
6. If the job was **deleted** (not just paused), create a new one following the template
   above, using the existing "Tier-0F Poller" or "Filing Memory Sync" cron-job.org jobs
   as reference templates (see `docs/phase-5-batchB-execution-brief.md:1163-1179`)

#### Workflow to enable (after cron-job.org test-fire succeeds)

```powershell
gh workflow enable "Update Paper Trades"            --repo goelvipulvg-max/stockmarket-brain
```

#### Before enabling

- **P1 resolved:** cron-job.org test-fire confirmed green run in GH Actions.
- Tier-0 green (Layer 3 GO).
- Memory plumbing green (Layer 2 GO).
- Monitors green (Layer 1 GO).
- **Zero open positions** confirmed (the handoff says 0 OPEN trades).
  Verify manually:
  ```sql
  SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN';
  ```
  If >0, note the trade IDs — the updater will immediately manage them on first run.

#### Canary signals

**Telegram:** The updater sends trade-close alerts when a position exits. With 0 open
trades, expect **silence** (no close alerts). If there are pre-existing OPEN trades,
watch for `TARGET_HIT` / `SL_HIT` / `EXPIRED` alerts.

**GH Actions log — the critical first-run check:**
```bash
gh run list --workflow="Update Paper Trades" --limit 5
```
View the first run's log. Confirm:
- "Fetched N OPEN trades" (N=0 expected today; could be >0 if there are lingering OPEN rows)
- "No open trades to process" (expected if N=0)
- No fetch failures, no crash

**Supabase — ladder verification query (when trades exist):**
```sql
SELECT symbol, entry_price, direction, segment,
       current_target_level, t1_hit, t2_hit,
       trailing_sl, status, signal_date
FROM paper_trades
WHERE source = 'TIER2F' AND status = 'OPEN'
ORDER BY signal_date DESC;
```
With the HOTFIX-6 ladder (T1=6%, SL=4%), after the updater runs against an open BUY EQUITY trade, verify transitions:

| Column | Entry state | After T1 hit |
|--------|------------|--------------|
| `t1_hit` | `false` | `true` (`agents/update_paper_trades.py:184`) |
| `current_target_level` | `"T1"` | `"T2"` (`:185`) |
| `trailing_sl` | entry × 0.96 | entry × 1.03 (`:187` — `EQ_SL_T1=1.03`) |

After T2 hit (BUY EQUITY):
| Column | After T1 | After T2 hit |
|--------|----------|--------------|
| `t2_hit` | `false` | `true` (`:201`) |
| `current_target_level` | `"T2"` | `"T3"` (`:202`) |
| `trailing_sl` | entry × 1.03 | entry × 1.06 (`:203` — `EQ_SL_T2=1.06`) |

**If `trailing_sl` stays at entry × 0.96 for days while price rises:** the updater
isn't managing positions. Check the GH run log for errors.

#### GO / NO-GO gate

- **GO:** Updater runs clean (no crash, no fetch failure) on its first cron-job.org
  trigger. If there are OPEN trades, ladder transitions (above) confirm T1/SL tracking.
- **NO-GO:** Crash, fetch failure, or `trailing_sl` stuck at initial values despite
  price movement past T1. **Do NOT proceed to Layer 5.** Investigate the GH run log.

#### Rollback

```powershell
gh workflow disable "Update Paper Trades"            --repo goelvipulvg-max/stockmarket-brain
```
Then disable the cron-job.org job in the dashboard.

---

### 2.5 LAYER 5 — Tier-0F Poller (THE TRADING SWITCH) ⚠️ LAST

**⚠️ WARNING: This is the LIVE TRADING SWITCH. Enabling the poller means the
system WILL open real paper trades when a material filing lands. Do this early
in a market session you can actively watch.**

#### Workflow to enable

```powershell
gh workflow enable "Tier-0F Poller"                 --repo goelvipulvg-max/stockmarket-brain
```

> **Note:** `tier2f.yml` ("Tier-2F Fundamental Signal") is `workflow_dispatch`-only —
> NO schedule. It fires ONLY when the poller dispatches it. Enabling the poller IS
> enabling Tier-2F. Tier-3 auto-fires on Tier-2F completion.

#### Before enabling

- **ALL previous layers GO** (Layers 1–4 confirmed green).
- **At least 4 hours of NSE market remaining** in the current session.
- **You are actively watching** these Telegram channels:
  - `TELEGRAM_TIER3_CHANNEL` — trade alerts + Tier-3 position recs
  - `TELEGRAM_GUARDIAN_CHANNEL` — EXIT advisories
  - `TELEGRAM_MOVERS_CHANNEL` — news
- **cron-job.org Tier-0F Poller job** reconfirmed disabled — the poller should run
  on its GH fallback schedule (`*/10 3-9 * * 1-5`) first, giving you a 10-min
  observation window before potentially enabling the 2-min cron-job.org primary.

#### Canary signals — the first poller run

**GH Actions log:**
```bash
gh run list --workflow="Tier-0F Poller" --limit 5
```
View the first run's log. Expected output:
```
[N] material filings in last 30min
```
- If 0: no material filing in the window. Wait for the next run (10 min).
  The poller is alive but idle — expected during quiet market periods.
- If >0: look for `"Dispatched Tier-2F for filing_id=N"` (`agents/tier0f_poller.py:106`).

**If a dispatch fires, the cascade is:**
1. Poller log: "Dispatched Tier-2F for filing_id=N"
2. `gh run list --workflow="Tier-2F Fundamental Signal"` — a new run appears (dispatched, not scheduled)
3. Tier-2F completes → Tier-3 auto-fires (`workflow_run`)
4. If Tier-2F opens a trade → `paper_trades` gets a new OPEN row with `source='TIER2F'`
5. Updater (Layer 4, running every 5 min) picks up the new trade and manages it

**Supabase — confirm no double-dispatches:**
```sql
SELECT filing_id, COUNT(*) AS dispatches
FROM paper_trades WHERE source = 'TIER2F'
AND signal_date = CURRENT_DATE
GROUP BY filing_id HAVING COUNT(*) > 1;
```
Zero rows = no duplicate dispatches. The `uniq_filings_log_url_hash` index prevents
duplicate `filings_log` rows; the poller's `_mark_picked` + `picked_by_tier0f` flag
prevents re-dispatch. If this returns >0, something raced — investigate immediately.

**Telegram — the ultimate canary:**
After a poller dispatch → Tier-2F completion, expect:
- Tier-2F sends a signal Telegram (channel depends on the agent's send path)
- Tier-3 sends a position-sizing recommendation to `TELEGRAM_TIER3_CHANNEL`
- If either is silent after a dispatch, check GH run logs

#### GO / NO-GO gate (the final gate)

- **GO (trading live):** Poller dispatches work correctly — one dispatch per filing,
  Tier-2F runs, Tier-3 runs, updater manages any opened trade. Paper P&L tracking
  confirms ladder transitions are correct.
- **NO-GO (abort):** Any of these fire:
  - Duplicate dispatches (same filing_id dispatched twice)
  - Tier-2F crash on dispatch
  - Updater fails to track a new trade (verify ladder query after ~30 min)
  - Capital ledger identity breaks (run the health_monitor reconciliation query
    or wait for the next health_monitor Telegram)
  
  **If NO-GO:** disable the poller immediately AND disable cron-job.org poller job
  if it was enabled:
  ```powershell
  gh workflow disable "Tier-0F Poller"               --repo goelvipulvg-max/stockmarket-brain
  ```

#### Post-GO: re-enable cron-job.org 2-min poller (optional latency improvement)

Once the GH fallback (10-min) poller has run clean for ≥2 cycles, re-enable the
cron-job.org Tier-0F Poller job for the original 2-min cadence:
1. Log into cron-job.org dashboard
2. Locate "Tier-0F Poller" job
3. Verify config: endpoint `.../tier0f-poller.yml/dispatches`, POST, PAT auth
4. Re-enable
5. Confirm GH Actions shows runs arriving at 2-min intervals

---

## 3. What Could Go Wrong

### 3.1 Updater without Poller = zombie positions

If you enable the poller (Layer 5) BEFORE the updater (Layer 4): Tier-2F opens a
trade → it sits OPEN forever. No trailing SL, no target detection, no expiry.
Capital locked. **The §6 order exists for this reason. Don't skip it.**

### 3.2 Poller without cron-job.org updater = silent drift

If cron-job.org updater job fails to re-enable (P1 not resolved) but you proceed to
Layer 5 anyway: same failure as §3.1. The updater has no GH schedule fallback — it
requires cron-job.org or an alternative trigger.

### 3.3 Known-untested paths in the updater (unchanged by HOTFIX-6)

The following code paths have zero test coverage. They are unchanged by HOTFIX-6
but remain in the updater's main loop:

| Path | Location | Risk |
|------|----------|------|
| Hit-detection triggers | `update_paper_trades.py:201-232` (T1-hit, T2-hit, T3-hit detection comparing `day_high/day_low`) | Untested. Logic is straightforward (price > target → hit) but no automated verification |
| Day-0 LTP-only guard | `update_paper_trades.py:83` fetches `range=1d` — on signal day, the full day's OHLC is available retroactively (P0-2 look-ahead) | Known bug, not fixed. First-run after signal may use future intraday knowledge |
| Idempotency guards | `t1_hit` / `t2_hit` boolean columns prevent duplicate upgrades (`:252-254`) | Works by design (simple bool check), but no test confirms a double-upgrade can't happen |

**Watch for:** multiple Tier-2F signals hitting the same stock on the same day
(spotted via `paper_trades` query). If the day-0 guard bug causes an optimistic
target hit, it would close a trade on day 0 at T1 — visible in `status='TARGET_HIT'`
with `holding_days=0`.

### 3.4 Duplicate-trade race (MITIGATED, not eliminated)

The deployed `uniq_filings_log_url_hash` index prevents duplicate `filings_log`
rows → prevents the Tier-0F Poller from dispatching Tier-2F twice for the same
filing. **But:** the poller's `_dispatch_tier2f` → `_mark_picked` sequence
(`agents/tier0f_poller.py:153`) dispatches BEFORE marking. If `_mark_picked` fails
(network blip, DB timeout), the filing stays `picked_by_tier0f=false` and gets
re-dispatched on the next poller cycle.

**Mitigation check:** The canary query in §2.5 (GROUP BY filing_id HAVING COUNT>1)
will catch this. If it fires, the Tier-2F `concurrency: group: tier2f-capital`
(YAML line 3–5) means the second dispatch queues behind the first — it won't
parallel-race capital. And the poller's `BATCH_LIMIT=10` (`tier0f_poller.py:29`)
caps exposure to 10 filings per cycle.

### 3.5 Capital-ledger race (P0-1, unmitigated)

The `capital_ledger.py` read-modify-write on the single `portfolio` row has no
lock/transaction. If two Tier-2F runs complete simultaneously and both call
`deploy_capital`, they can both read the same `cash_available` and over-allocate.

**Status:** The `concurrency: group: tier2f-capital` on `tier2f.yml` serializes
concurrent dispatches (Batch 0-A, A1 — deployed). This closes the realistic
exposure (poller-burst of 2+ filings). But the underlying `capital_ledger` RMW
is still unguarded — a DB-side atomic decrement is tracked as Batch C (C2) and
not yet implemented.

**Watch for:** the health_monitor capital reconciliation check (Check-4). If
`cash_available + capital_deployed ≠ total_equity`, the health monitor will
fire an alert to `TELEGRAM_TIER3_CHANNEL`.

### 3.6 Tier-0 + Poller overlapping on GH fallback schedules

Both Tier-0 and the poller have GH fallback schedules active:
- Tier-0: `15,45 3-9 * * 1-5` + `0,30 4-9 * * 1-5` (every ~15 min during market)
- Poller: `*/10 3-9 * * 1-5` (every 10 min)

These can overlap — Tier-0 could be inserting a `filings_log` row while the poller
is querying. Without the unique index, this was a duplicate-risk window. With the
index deployed, Tier-0's insert would get a `23505` unique-violation on duplicate
`url_hash`, caught by the `tier0_filings.py:169` handler. **No new duplicates
should form.** If they do (e.g. NULL `url_hash` rows bypassing the partial index),
the 46 legacy NULL-hash rows are the only known gap — the partial index
(`WHERE url_hash IS NOT NULL`) deliberately allows them through. Monitor via:
```sql
SELECT COUNT(*) FROM filings_log WHERE url_hash IS NULL;
```
If this number grows beyond 46, investigate the NULL-hash insert path.

---

## Quick-Reference: All Enable Commands

> ⚠️ **REFERENCE ONLY — DO NOT RUN AS A BLOCK.**
>
> This is a convenient per-layer copy-paste reference for the execution session.
> Running all of these at once defeats the entire staged-resume design: each layer
> requires its GO gate to pass before proceeding to the next. The §6 order
> (monitors → memory plumbing → Tier-0 → updater → Tier-0F Poller LAST) exists
> to contain blast radius. Skipping it means discovering a failure with the
> trading switch already live.
>
> **Execute one layer at a time. Verify the canary. Confirm GO. Then proceed.**

Execute in order, one layer at a time. Wait for GO gate before proceeding.

```powershell
# === LAYER 1: Monitors ===
gh workflow enable "Health Monitor"               --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Daily Summary"                --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-1 Guardian"              --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-1 News Researcher"       --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-3 Position Manager"      --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Pre-Open Alert"               --repo goelvipulvg-max/stockmarket-brain

# === LAYER 2: Memory Plumbing ===
gh workflow enable "Filing Memory Sync"            --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Filing Memory Backfill"        --repo goelvipulvg-max/stockmarket-brain
gh workflow enable "Tier-4 Memory Manager"         --repo goelvipulvg-max/stockmarket-brain

# === LAYER 3: Tier-0 ===
gh workflow enable "Tier-0 Filing Agent"           --repo goelvipulvg-max/stockmarket-brain

# === LAYER 4: Updater (after P1 cron-job.org re-enable) ===
gh workflow enable "Update Paper Trades"            --repo goelvipulvg-max/stockmarket-brain

# === LAYER 5: Tier-0F Poller — THE TRADING SWITCH ===
gh workflow enable "Tier-0F Poller"                 --repo goelvipulvg-max/stockmarket-brain
```

---

## Reference: Telegram Channels

| Env Var | Used By |
|---------|---------|
| `TELEGRAM_TIER3_CHANNEL` | `health_monitor`, `daily_summary`, `tier3_position_manager`, `tier2f` |
| `TELEGRAM_GUARDIAN_CHANNEL` | `tier1_guardian` |
| `TELEGRAM_MOVERS_CHANNEL` | `tier1_news` |
| `TELEGRAM_TRADES_CHANNEL_ID` | `preopen_alert`, `tier0_filings` |
| `TELEGRAM_LT_CHANNEL` | `tier0_filings` (LT-specific alerts) |
| `TELEGRAM_SWING_CHANNEL` | `tier0_filings` (swing alerts) |

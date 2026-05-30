# Audit History — StockMarket-Brain

_Compact ledger synthesized from all reports/ docs (reliability-gap report, gap1 design+plan, gap2 surprise findings, b2 backtest feasibility, pipeline blueprint, audit_report_1_30). Status reconciled against `git log` as of 2026-05-30. Reports-only: items propose; Gaurav decides._

---

## SHIPPED (commit refs)

- **Gap #1 price-structure (soft)** — SMA-50/200 + RS-vs-NIFTY fed to Tier-2F LLM context + soft analyst guidance; hard gate wired but dormant — `6c2f47e→8e81878→ea23da9`
- **Gap #3 volume/confirmation (soft)** — volume + volume_series fed to Tier-2F context + soft guidance; dormant gate wired — `67ab0c1→ae69e41→d580ff3→f4c5533`
- **Gap #5 R-multiple** — RR≥1.5 floor enforced on classic Tier-2 path via shared `reward_risk` util — `c584c35→a410656`; sizer docstring corrected to 0.125%/2.5% — `9d0497c`
- **Gap #7 expectancy** — portfolio expectancy metric (win%×avg-win − loss%×avg-loss) added to Tier-4 memory manager — `e9a567a`
- **AI-SL Stage 2** — `validate_ai_signal` + SL/target prompt schema built dormant, then activated `USE_AI_SL=true` — `cad14c0→8f568ff→34ffe35→103fdbd`
- **Position-sizer caps** — tightened to user-intended 2.5%/trade — `66a1c00`
- **Gap #2 / B2 read-only diagnostics** — Upstox fundamentals income-statement spot-check `8ea685e`; event-study data-inventory diagnostic (`event_study_inventory.py`) `7d96abd`
- **Insufficient-data policy (locked)** — price_structure None-metric always = no-opinion-pass; gate never skips on missing data — (within `6c2f47e`)
- **Infra preload (blueprint, May 9–11)** — Nifty500 493/493 profiles `37e7ecd`, research_cache ~101k rows, parallel preloader 19/19 batches, deep_audit source-of-truth, duplicate/.NS cleanup, SMA backtester — _(blueprint-reported; only 37e7ecd carries a ref)_

## PARKED (with unblock condition)

- **Gap #1 hard price-structure skip gate** — dormant behind `USE_PRICE_STRUCTURE_GATE=false` → unblock: B2 backtest validates rule (look-ahead-free, survivorship-adjusted; ~1–2 mo)
- **Gap #1 threshold tuning** — above_sma50 / −25% from 52wk-high / RS≥0 are dormant constants → unblock: B2 results inform optimal thresholds
- **Gap #3 hard volume/breakout gate** — dormant behind `USE_VOLUME_GATE=false` → unblock: B2 backtest validates rule
- **Gap #2 surprise magnitude/quality** — PAUSED → unblock: in-house quarterly store reaches ≥5–8 quarters, OR a source with ≥8 quarters of quarterly revenue/PAT (ideally EPS) is found
- **B2 filing-edge backtest code** — not built → unblock: `filing_memory` matures to ≥20–30 matured outcomes per category (RESULTS/M&A/CONTRACT_WIN); currently 25 total matured
- **B2 event-study harness** (`scripts/event_study.py`: t-test/Wilcoxon/placebo/Benjamini-Hochberg/OOS split) → unblock: n≥20–30 per category
- **B1 point-in-time membership history** — `nse500_membership_history` absent; sync overwrites → unblock: create DDL via Supabase + extend `sync_nse500.py` to append (approved as separate chunk)
- **B1 historical RESULTS/M&A/CONTRACT_WIN backfill** → unblock: B1 point-in-time membership sourced first
- **B3 live scaling** — V0.1 OTHER-rate gate deferred → unblock: V0.1 gate verification passes AND monitoring doc in place
- **risk_factors / moat_analysis columns** — NULL for all 493 profiles → unblock: Tier-2 agent implementation
- **9 uncommitted preloader scripts** — `?? ` status → unblock: user decision to integrate + code review
- **QuestDB wiring** — `questdb_client.py` configured, inactive → unblock: prioritization + server setup + ingestion
- **Pinecone integration** — configured, not wired → unblock: embedding pipeline + index creation
- **Windows scheduled task** (`StockMarketBrain_OneTimeAudit`) — ineffective (no stdout) → unblock: user decision to remove/reimplement with logging

## AVOID

- **Untested hard rules** — PEAD/Minervini-SEPA/Weinstein methods are methods, not guarantees; never trust a hard gate without look-ahead-free, survivorship-adjusted backtest (root reason price-structure + volume gates stay dormant)
- **yfinance quarterly fundamentals (NSE)** — REJECTED, unreliable for quarterly surprise
- **Upstox Company Fundamentals for quarterly-YoY surprise** — INSUFFICIENT: only 4 quarters, no quarterly EPS (annual only), daily token-expiry blocker
- **Dividend-only alpha backtest** — survivorship-biased upward + answers wrong question; do not build as a proxy edge test
- **Legacy `load_nifty500.py`** — old schema, no AI summaries; use parallel preloader
- **Single-threaded `historical_preloader.py`** — impractical (4–8h/504 cos); use `run_parallel_preloader.py`
- **Thread-based `audit_20.py`** — fragile, hardcoded 20; `deep_audit_20.py` is source of truth
- **Windows Task Scheduler for preloader/audit** — no stdout capture; silently fails

## PENDING DECISIONS (awaiting Gaurav)

- **Checklist #1 hard gate** — promote above-MA / 52wk-high / RS to a binding skip rule? (soft version already shipped)
- **Checklist #2 surprise approach** — choose QoQ vs annual-YoY vs accumulate in-house quarterly snapshots (unblocks Gap #2)
- **Checklist #4 tradability** — build ASM/GSM/T2T + circuit-band + min-price filters? (have F&O-ban, Nifty500, ₹5Cr liquidity, score≥6)
- **Checklist #6 regime multiplier** — apply graded 0.75/0.50 to confidence/sizing (currently only 0.0 skip used) and add FII/DII?
- **B1 survivorship** — source external delisted-universe data, or proceed with forward-fix only?
- **B4 frictionless P&L** — add STT+brokerage+GST+slippage cost model / net-of-cost column to `update_paper_trades.py`?
- **B5 learning loop** — build `tier4f_nightly.py` + record live-trade outcomes + before/after A/B?
- **B6 look-ahead (adjusted close)** — implement as-of / unadjusted alpha in `filing_memory_backfill.py` (`auto_adjust=True` today)?
- **B7 fixed alpha thresholds** — make ±3% alpha thresholds regime-conditional via market_context?
- **B8 confidence calibration** — recalibrate the arbitrary 65 threshold from win-rate-by-confidence stats?
- **B9 poller gates** — add `trade_confidence≥60` + `event_type≠OTHER` to `tier0f_poller.py` query?
- **B10 weak-inference n≥5** — raise min-n threshold + add statistical-adequacy labeling in `memory_seed.py`?
- **RELIANCE EPS adjustment** — verify split/bonus adjustment (Mar23 98.59 vs Mar24 51.45) before trusting Upstox EPS
- **Event-type edge gate** — per event_type keep/up-weight vs drop/down-weight, pending event-study results

## Audit run log

- **2026-05-30** — auto-audit (production, `auto-audit` branch). Top gap: **Cost honesty FAIL** (gross-only P&L). New WATCH: AI-SL canary invisible — 0/36 paper_trades carry `raw_signal.ai_sl_used` despite `USE_AI_SL=true`. Status change: matured `filing_memory` (10d) 25→**35** (still <50, confidence gate ON); RLS now readable (paper_trades 36, filing_memory 805). Report: `reports/auto-audit/auto-audit-2026-05-30.md`.

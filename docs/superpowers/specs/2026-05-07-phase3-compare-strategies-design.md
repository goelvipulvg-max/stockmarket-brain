# Phase 3.1 — Strategy Comparison Script Design

**Date:** 2026-05-07
**Status:** Approved

## Goal

A single terminal script that prints two clearly-labeled sections — the SMA 50/200 backtest baseline and the Tier-2 AI signal stats from Supabase — so both strategies can be reviewed side by side in one run.

## Context

- `scripts/backtest_sma.py` established the SMA 50/200 baseline in Phase 3.0: +1.3% total, +0.4% CAGR, Sharpe 0.18, 26 trades across 10 NSE stocks over 3 years.
- Tier-2 AI signals live in Supabase `paper_trades`. As of 2026-05-07, only ~3 days of data exist (~16 trades). Not enough for CAGR or Sharpe computation.
- The comparison is intentionally asymmetric: each strategy shows only the metrics its data supports. This is made explicit in the output.

## Decisions Locked

| Question | Decision |
|---|---|
| Output format | Two labeled terminal sections, no forced metric alignment |
| SMA data source | Re-run vectorbt live (fresh, authoritative) |
| HTML report | None — terminal only (`backtest_sma.py` handles HTML) |
| Script location | `scripts/compare_strategies.py` — new standalone |
| Changes to existing scripts | None |

## Script: `scripts/compare_strategies.py`

### Section 1 — SMA 50/200 Baseline

Fetches 3Y of OHLCV data via yfinance for the same 10 tickers as `backtest_sma.py`. Computes SMA 50/200 golden/death cross signals via vectorbt. Prints per-ticker table + portfolio row.

```
============================================================
  STRATEGY 1: SMA 50/200 Baseline
  Period : 2022-01-01 → 2026-05-07
  Tickers: 10  |  Rs 25k/ticker  |  0.1% fees
============================================================
  Ticker           Total Ret     CAGR   Sharpe   Max DD  # Trades
  ------------------------------------------------------------------
  RELIANCE.NS        +4.2%     +1.1%     0.45   -12.3%         3
  ...
  PORTFOLIO          +1.3%     +0.4%     0.18   -15.6%        26
```

### Section 2 — Tier-2 AI Signals

Queries all rows from Supabase `paper_trades`. Computes metrics on closed trades only (status = TARGET_HIT, SL_HIT, EXPIRED with pnl_pct set). Prints a summary block, not a per-ticker table (sample size too small for per-ticker to be meaningful).

```
============================================================
  STRATEGY 2: Tier-2 AI Signals (Supabase paper_trades)
  Period : 2026-05-05 → 2026-05-07  (3 days)
  NOTE   : Early data — CAGR / Sharpe not computed
============================================================
  Metric                          Value
  ----------------------------------
  Total signals                      16
  Open trades                         0
  Closed trades                      16
    TARGET_HIT (wins)                 2
    SL_HIT (losses)                   2
    EXPIRED (no PnL)                 12
  Win rate (excl. expired)        50.0%
  Avg PnL % (closed w/ PnL)      +0.27%
  Avg confidence score              7.4
  Data maturity                   3 days  ← illustrative; actual values from live query
```

### Error Handling

- Missing `.env` keys → print error and exit.
- yfinance fetch failure → print error and exit.
- Supabase fetch returns empty → print "No paper trades found" and skip Section 2.
- vectorbt stats failure → fall back to `N/A` per cell, continue.

## What This Script Does NOT Do

- No HTML report (that's `backtest_sma.py`'s job).
- No per-ticker AI signal breakdown (sample size too small).
- No forced metric alignment between strategies (data maturity is incompatible).
- No writing to Supabase or QuestDB.

## Files Changed

| File | Change |
|---|---|
| `scripts/compare_strategies.py` | New file — ~120 lines |

No other files are modified.

## Success Criteria

1. `python scripts/compare_strategies.py` prints both sections cleanly in one run.
2. Section 1 matches `backtest_sma.py` numbers (same logic, same tickers).
3. Section 2 reflects current `paper_trades` row count and closed-trade stats.
4. If Supabase has no closed trades, script exits gracefully with a note.
